"""Free data for the Forex wing: past currency prices (for the lab) and the CFTC's weekly report on who
holds which currency bets (for Copycat FX, live and in the lab). Neither needs a key.

Past prices come from Dukascopy, a Swiss bank that publishes years of bid and ask prices for free. Bid and
ask let the lab charge the real gap between buying and selling (the "spread"). The live bots use OANDA's
own prices instead.

The CFTC (the US futures regulator) publishes the "Commitments of Traders" report every Friday at 3:30pm
New York time. It shows, as of the Tuesday before, how many currency futures contracts each type of big
trader holds, bets up (long) and down (short). Copycat FX copies the "leveraged funds" group: hedge funds
and the big trading firms that manage money for them.
"""
from __future__ import annotations

import logging
import lzma
import struct
from datetime import date, datetime, timedelta, timezone

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


def _get(http: requests.Session, url: str) -> bytes:
    for attempt in range(4):
        try:
            r = http.get(url, timeout=60)
        except requests.RequestException:
            r = None
        if r is not None and r.status_code == 200:
            return r.content
        if r is not None and r.status_code == 404:
            return b""
    raise RuntimeError(f"couldn't download {url}")


def daily_history(pair: str, start: date, end: date, session: requests.Session | None = None) -> pd.DataFrame:
    """Daily mid-price candles with the bid/ask spread, from Dukascopy. Whole past years come as one
    file each; this year's finished months are built from hourly files. The month in progress is left
    out. Days start at 00:00 UTC."""
    http = session or requests.Session()
    sym = pair.replace("_", "")
    sides = {}
    today = datetime.now(timezone.utc).date()
    for side in ("BID", "ASK"):
        parts = []
        for y in range(start.year, end.year + 1):
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
        sides[side] = df[~df.index.duplicated()].sort_index() if len(df) else df
    bid, ask = sides["BID"], sides["ASK"]
    if bid.empty or ask.empty:
        raise RuntimeError(f"no Dukascopy prices for {pair}")
    j = bid.join(ask, lsuffix="_b", rsuffix="_a", how="inner")
    out = pd.DataFrame({c: (j[f"{c}_b"] + j[f"{c}_a"]) / 2 for c in ("open", "high", "low", "close")})
    out["spread"] = (j["close_a"] - j["close_b"]).clip(lower=0)
    out["volume"] = j["volume_b"]
    s, e = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    return out[(out.index >= s) & (out.index < e)]
