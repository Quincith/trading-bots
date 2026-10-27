"""Free data for the Forex wing: past currency prices (for the lab) and the CFTC's weekly report on who
holds which currency bets (for Copycat FX, live and in the lab). Neither needs a key.

Past prices come from OANDA itself once its practice key is set up (the same prices the bots trade on), and
until then from Dukascopy, a Swiss bank that publishes years of prices for free. Dukascopy only allows a few
downloads at a time from one place, so each file is saved once in FX_CACHE_DIR and never fetched again. The
lab charges at least OANDA's usual gap between the buy and sell price (see forex.MIN_SPREAD_PIPS), which is
bigger than Dukascopy's real one, so downloading only the "bid" side loses nothing.

The CFTC (the US futures regulator) publishes the "Commitments of Traders" report every Friday at 3:30pm
New York time. It shows, as of the Tuesday before, how many currency futures contracts each type of big
trader holds, bets up (long) and down (short). Copycat FX copies the "leveraged funds" group: hedge funds
and the big trading firms that manage money for them.
"""
from __future__ import annotations

import logging
import lzma
import os
import struct
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

# ---- Commitments of Traders (CFTC) -------------------------------------------------------------------

COT_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"   # Traders in Financial Futures, futures only
# CFTC code for each currency's futures contract (all priced in US dollars, so "long" = betting the currency
# rises against the dollar)
COT_CODES = {"EUR": "099741", "GBP": "096742", "JPY": "097741", "AUD": "232741", "CAD": "090741",
             "CHF": "092741", "NZD": "112741"}
GROUPS = {"leveraged": ("lev_money_positions_long", "lev_money_positions_short"),
          "asset_managers": ("asset_mgr_positions_long", "asset_mgr_positions_short")}
RELEASE_DELAY = timedelta(days=3, hours=21)   # Tuesday's numbers are public on Friday by ~21:00 UTC


def fetch_cot(since: date, session: requests.Session | None = None) -> pd.DataFrame:
    """One row per currency per week: report date, when it became public, and each group's net bet
    as a % of all open contracts (positive = betting the currency rises against the dollar)."""
    http = session or requests.Session()
    codes = ",".join(f"'{c}'" for c in COT_CODES.values())
    params = {"$where": f"cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd >= '{since:%Y-%m-%d}'",
              "$order": "report_date_as_yyyy_mm_dd", "$limit": 50000}
    r = http.get(COT_URL, params=params, timeout=60)
    r.raise_for_status()
    return cot_frame(r.json())


def cot_frame(rows: list[dict]) -> pd.DataFrame:
    by_code = {v: k for k, v in COT_CODES.items()}
    out = []
    for x in rows:
        ccy = by_code.get(str(x.get("cftc_contract_market_code", "")).strip())
        oi = float(x.get("open_interest_all") or 0)
        if not ccy or oi <= 0:
            continue
        day = pd.Timestamp(str(x["report_date_as_yyyy_mm_dd"])[:10], tz="UTC")
        rec = {"ccy": ccy, "report": day, "public": day + RELEASE_DELAY, "oi": oi}
        for g, (lo, sh) in GROUPS.items():
            rec[g] = (float(x.get(lo) or 0) - float(x.get(sh) or 0)) / oi * 100
        out.append(rec)
    df = pd.DataFrame(out, columns=["ccy", "report", "public", "oi", *GROUPS])
    return df.sort_values(["report", "ccy"]).reset_index(drop=True)


def cot_as_of(cot: pd.DataFrame, when: datetime) -> dict[str, dict]:
    """The newest public report for each currency at `when`, plus the one before it (to see the change)."""
    seen = cot[cot["public"] <= pd.Timestamp(when)]
    out = {}
    for ccy, g in seen.groupby("ccy"):
        last = g.iloc[-1]
        prev = g.iloc[-2] if len(g) > 1 else last
        out[ccy] = {"report": last["report"].date().isoformat(), **{k: float(last[k]) for k in GROUPS},
                    **{f"{k}_prev": float(prev[k]) for k in GROUPS}}
    return out


# ---- past prices (Dukascopy) ---------------------------------------------------------------------------

DUKA = "https://datafeed.dukascopy.com/datafeed"


def _point(pair: str) -> float:
    return 1e3 if pair.endswith("JPY") else 1e5


def _decode(raw: bytes, start: datetime, pair: str) -> pd.DataFrame:
    """A .bi5 candle file: LZMA-packed 24-byte records (seconds from the file's start, four prices as whole
    numbers of 'points', volume). The four prices are open, close, low, high."""
    if not raw:
        return pd.DataFrame()
    data = lzma.decompress(raw)
    n = len(data) // 24
    rec = np.array(struct.unpack(">" + "iiiiif" * n, data[: n * 24]), dtype=float).reshape(n, 6)
    p = _point(pair)
    df = pd.DataFrame({"open": rec[:, 1] / p, "close": rec[:, 2] / p, "low": rec[:, 3] / p, "high": rec[:, 4] / p,
                       "volume": rec[:, 5]},
                      index=pd.DatetimeIndex([start + timedelta(seconds=int(s)) for s in rec[:, 0]]))
    bad = ((df["low"] > df[["open", "close"]].min(axis=1) + 1e-9) | (df["high"] < df[["open", "close"]].max(axis=1) - 1e-9))
    if len(df) and bad.mean() > 0.05:
        raise RuntimeError(f"Dukascopy {pair} candles don't look right ({bad.mean():.0%} have low/high outside open/close)")
    return df[df["volume"] > 0]


PAUSE = 1.5   # seconds between downloads: Dukascopy limits how fast one visitor may download (HTTP 429)


class SlowDown(RuntimeError):
    """Dukascopy asked us to stop downloading for a while."""


def daily_prices(pair: str, start: date, end: date) -> pd.DataFrame:
    """Daily candles for the lab: from OANDA when OANDA_API_TOKEN is set, otherwise Dukascopy's bid prices."""
    token = os.environ.get("OANDA_API_TOKEN")
    if token:
        from .oanda import OandaPractice
        df = OandaPractice(token, os.environ.get("OANDA_FOREX_ACCOUNT_ID") or "-").daily_bars(pair, 5000)
        s, e = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        return df[(df.index >= s) & (df.index < e)]
    return daily_history(pair, start, end, sides=("BID",))


def _cached(url: str) -> Path | None:
    root = os.environ.get("FX_CACHE_DIR")
    return Path(root) / url.removeprefix(DUKA + "/") if root else None


def _get(http: requests.Session, url: str) -> bytes:
    path = _cached(url)
    if path and path.exists():
        return path.read_bytes()
    why = ""
    for attempt in range(3):
        time.sleep(PAUSE)
        try:
            r = http.get(url, timeout=60)
        except requests.RequestException as e:
            r, why = None, str(e)
        if r is not None and r.status_code in (200, 404):
            data = r.content if r.status_code == 200 else b""
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            return data
        if r is not None and r.status_code == 429 and attempt == 2:
            raise SlowDown(f"Dukascopy says slow down (HTTP 429) at {url}; files so far are saved, try again later")
        if r is not None:
            why = f"HTTP {r.status_code}"
        wait = r.headers.get("Retry-After") if r is not None else None
        time.sleep(float(wait) if wait and wait.isdigit() else 10 * 2 ** attempt)   # slow down as asked
    raise RuntimeError(f"couldn't download {url} ({why})")


def daily_history(pair: str, start: date, end: date, session: requests.Session | None = None,
                  sides: tuple[str, ...] = ("BID", "ASK")) -> pd.DataFrame:
    """Daily mid-price candles with the bid/ask spread, from Dukascopy. Whole past years come as one
    file each; this year's finished months are built from hourly files. The month in progress is left
    out. Days start at 00:00 UTC."""
    http = session or requests.Session()
    sym = pair.replace("_", "")
    got = {}
    today = datetime.now(timezone.utc).date()
    for side in sides:
        parts = []
        for y in range(start.year, (end - timedelta(days=1)).year + 1):   # `end` itself is left out
            if y < today.year:
                t0 = datetime(y, 1, 1, tzinfo=timezone.utc)
                parts.append(_decode(_get(http, f"{DUKA}/{sym}/{y}/{side}_candles_day_1.bi5"), t0, pair))
            else:
                for m in range(1, today.month):
                    t0 = datetime(y, m, 1, tzinfo=timezone.utc)
                    h = _decode(_get(http, f"{DUKA}/{sym}/{y}/{m - 1:02d}/{side}_candles_hour_1.bi5"), t0, pair)
                    if len(h):
                        parts.append(h.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                                           "close": "last", "volume": "sum"}).dropna())
        df = pd.concat([p for p in parts if len(p)]) if any(len(p) for p in parts) else pd.DataFrame()
        got[side] = df[~df.index.duplicated()].sort_index() if len(df) else df
    bid, ask = got["BID"], got.get("ASK", got["BID"])
    if bid.empty or ask.empty:
        raise RuntimeError(f"no Dukascopy prices for {pair}")
    j = bid.join(ask, lsuffix="_b", rsuffix="_a", how="inner")
    out = pd.DataFrame({c: (j[f"{c}_b"] + j[f"{c}_a"]) / 2 for c in ("open", "high", "low", "close")})
    out["spread"] = (j["close_a"] - j["close_b"]).clip(lower=0)
    out["volume"] = j["volume_b"]
    s, e = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    return out[(out.index >= s) & (out.index < e)]
