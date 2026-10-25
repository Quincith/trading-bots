"""Past insider buys and stock prices, so the strategy lab can replay Copycat over the last year.

The SEC publishes every Form 4 as a free download, one zip file per quarter ("Insider Transactions
Data Sets"). Each zip has tab-separated tables; we read three of them:
  SUBMISSION.tsv      one row per filing: filing date, company, ticker
  REPORTINGOWNER.tsv  who filed: name, officer/director, job title
  NONDERIV_TRANS.tsv  each stock trade in the filing: code (P = bought on the open market), shares, price
A quarter's zip appears a few weeks after the quarter ends, so the replay stops at the newest one.

The replay itself goes one trading day at a time with daily candles from Alpaca:
  - buys filed by the evening before are added to the watchlist with Copycat's own rules,
  - at the open we buy the best picks (same ranking, chase limit and Risk sizing as the live bot),
  - stops, profit goals and the time limit are checked against each day's low, high and close.
The live bot checks every 30 minutes during the day, so its exact prices will differ a little.
"""
from __future__ import annotations

import io
import logging
import os
import pickle
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from . import backtest as bt
from . import copycat, sec
from .alpaca import AlpacaPaper
from .bots import risk
from .models import Candidate, Plan

log = logging.getLogger(__name__)

ZIP_URL = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{q}_form345.zip"
FEE = 0.0               # Alpaca charges no commission on stocks
SLIPPAGE = 0.001        # assume each order fills 0.1% worse than the quoted price (small companies trade thinly)
OPEN_UTC = (14, 30)     # 9:30 New York time (close enough for daily replay)


@dataclass
class InsiderHistory:
    buys: list[sec.InsiderBuy]               # every qualifying purchase, oldest filing first
    bars: dict[str, pd.DataFrame]            # daily candles per ticker, indexed by date
    spy: pd.DataFrame                        # daily candles for the S&P 500 fund
    last_data_day: date                      # newest filing day in the SEC files


# ---- reading the SEC files -------------------------------------------------------------------------

def quarters(start: date, end: date) -> list[str]:
    out, y, q = [], start.year, (start.month - 1) // 3 + 1
    while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
        out.append(f"{y}q{q}")
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def _table(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    member = next((n for n in z.namelist() if n.upper().endswith(name)), None)
    if member is None:
        raise ValueError(f"{name} missing from the SEC file")
    with z.open(member) as f:
        df = pd.read_csv(f, sep="\t", dtype=str, quoting=3, on_bad_lines="skip", encoding="latin-1",
                         keep_default_na=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def _day(s: str) -> str:
    """The SEC writes dates like 31-MAR-2026; some rows use 2026-03-31."""
    s = (s or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:11] if fmt == "%d-%b-%Y" else s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def parse_quarter(raw: bytes) -> list[sec.InsiderBuy]:
    """Open-market purchases (code P, acquired) from one quarter's zip, built the same way as the live feed."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    subs, owners, trades = _table(z, "SUBMISSION.TSV"), _table(z, "REPORTINGOWNER.TSV"), _table(z, "NONDERIV_TRANS.TSV")
    trades = trades[(trades["TRANS_CODE"].str.strip() == "P") & (trades["TRANS_ACQUIRED_DISP_CD"].str.strip() == "A")]
    subs = subs[subs["DOCUMENT_TYPE"].str.strip().isin(["4", "4/A"])].set_index("ACCESSION_NUMBER")
    who: dict[str, dict] = {}
    for r in owners.itertuples(index=False):
        rel = (getattr(r, "RPTOWNER_RELATIONSHIP", "") or "").lower()
        title = (getattr(r, "RPTOWNER_TITLE", "") or "").strip()
        w = who.setdefault(r.ACCESSION_NUMBER, {"names": [], "roles": [], "officer": False, "director": False})
        w["names"].append((r.RPTOWNERNAME or "").strip())
        if "officer" in rel:
            w["officer"] = True
            w["roles"].append(title or "Officer")
        if "director" in rel:
            w["director"] = True
            w["roles"].append("Director")
        if "tenpercent" in rel.replace(" ", "").replace("%", "percent"):
            w["roles"].append("10% owner")
    out = []
    for r in trades.itertuples(index=False):
        acc = r.ACCESSION_NUMBER
        if acc not in subs.index or acc not in who:
            continue
        s = subs.loc[acc]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[0]
        ticker = (s["ISSUERTRADINGSYMBOL"] or "").strip().upper()
        if not ticker or not ticker.replace(".", "").isalpha() or len(ticker) > 7:
            continue
        try:
            shares, price = float(r.TRANS_SHARES), float(r.TRANS_PRICEPERSHARE)
        except (TypeError, ValueError):
            continue
        filed = _day(s["FILING_DATE"])
        if shares <= 0 or price <= 0 or not filed:
            continue
        w = who[acc]
        out.append(sec.InsiderBuy(
            accession=acc, ticker=ticker, company=(s["ISSUERNAME"] or "").strip(),
            who=" & ".join(n for n in w["names"] if n) or "unknown",
            role=", ".join(dict.fromkeys(w["roles"])) or "Insider", is_officer=w["officer"],
            is_director=w["director"], shares=shares, price=price, date=_day(r.TRANS_DATE) or filed,
            # Filed some time that day; we treat it as seen after the close and act the next morning.
            filed=f"{filed}T21:00:00+00:00"))
    return out


def fetch_buys(start: date, end: date, session: requests.Session | None = None) -> list[sec.InsiderBuy]:
    email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
    if "@" not in email:
        raise RuntimeError(sec.NEEDS_EMAIL)
    http = session or requests.Session()
    http.headers.update({"User-Agent": f"Paper trading research bot {email}"})
    buys = []
    for q in quarters(start, end):
        r = http.get(ZIP_URL.format(q=q), timeout=120)
        if r.status_code == 404:
            log.warning("SEC file for %s is not out yet", q)
            continue
        r.raise_for_status()
        got = parse_quarter(r.content)
        log.warning("%s: %d insider purchases", q, len(got))
        buys += got
    buys = [b for b in buys if start.isoformat() <= b.filed[:10] <= end.isoformat()]
    return sorted(buys, key=lambda b: b.filed)


def worth_fetching(buys: list[sec.InsiderBuy], cc: dict) -> list[str]:
    """Tickers that could ever be copied under any setting the lab may try (keeps the price download small)."""
    roles = set(cc["insider_roles"])
    total: dict[str, float] = {}
    for b in buys:
        if b.price >= 2 and (("officer" in roles and b.is_officer) or ("director" in roles and b.is_director)):
            total[b.ticker] = total.get(b.ticker, 0.0) + b.usd
    return sorted(t for t, usd in total.items() if usd >= 25000)


def _daily(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index).tz_convert(None).normalize()
    return df[~df.index.duplicated(keep="last")]


def fetch_history(cfg: dict, start: date, end: date, key: str, secret: str) -> InsiderHistory:
    buys = fetch_buys(start, end)
    if not buys:
        raise RuntimeError("no insider purchases found in the SEC files")
    last = max(date.fromisoformat(b.filed[:10]) for b in buys)
    tickers = worth_fetching(buys, cfg["copycat"])
    broker = AlpacaPaper(key, secret)
    t0 = datetime.combine(start - timedelta(days=100), datetime.min.time(), timezone.utc)
    t1 = datetime.combine(min(end, date.today()), datetime.min.time(), timezone.utc)
    bars = {}
    log.warning("Downloading daily prices for %d stocks...", len(tickers))
    for i in range(0, len(tickers), 200):
        for s, df in broker.get_bars_range(tickers[i:i + 200], "1Day", t0, t1, "stocks").items():
            bars[s] = _daily(df)
    spy = _daily(broker.get_bars_range(["SPY"], "1Day", t0, t1, "stocks")["SPY"])
    log.warning("Got %d insider buys, prices for %d of %d stocks, SEC data up to %s.", len(buys), len(bars),
                len(tickers), last)
    return InsiderHistory(buys, bars, spy, last)


# ---- the day-by-day replay -------------------------------------------------------------------------

class CopycatEngine:
    benchmark_label = "Just hold the S&P 500"
    min_trades = 8

    def __init__(self, hist: InsiderHistory, start: datetime, end: datetime, cash: float = 100.0):
        self.hist, self.start, self.end, self.cash = hist, start, end, cash

    def days(self, start: datetime, end: datetime) -> list[pd.Timestamp]:
        idx = self.hist.spy.index
        return list(idx[(idx >= pd.Timestamp(start.date())) & (idx <= pd.Timestamp(end.date()))])

    def _bar(self, ticker: str, day: pd.Timestamp):
        df = self.hist.bars.get(ticker)
        if df is None or day not in df.index:
            return None
        return df.loc[day]

    def _before(self, ticker: str, day: pd.Timestamp, n: int) -> pd.DataFrame:
        df = self.hist.bars.get(ticker)
        if df is None:
            return pd.DataFrame()
        return df[df.index < day].tail(n)

    def benchmark(self, start: datetime, end: datetime) -> bt.SimResult:
        days = self.days(start, end)
        res = bt.SimResult("benchmark", [])
        if not days:
            return res
        p0 = float(self.hist.spy.loc[days[0], "open"]) * (1 + SLIPPAGE)
        for d in days:
            res.equity.append((_at_close(d), self.cash * float(self.hist.spy.loc[d, "close"]) / p0))
        return res

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        # Without the total loss limit, like the crypto lab: we measure the rules, not the safety brake.
        cc, rk, ex = cfg["copycat"], bt.without_total_limit(cfg)["risk"], cfg["exits"]
        fee, slip = FEE * cost, SLIPPAGE * cost
        lookback = cfg["scout"]["lookback_bars"]
        cash, pos, st = self.cash, {}, {}
        res = bt.SimResult(cfg["name"], [])
        buys, i = self.hist.buys, 0
        prev_close_equity = cash

        def value(day, field="close"):
            total = cash
            for t, p in pos.items():
                b = self._bar(t, day)
                total += p["qty"] * (float(b[field]) if b is not None else p["last"])
            return total

        for day in self.days(start, end):
            now = _at_open(day)
            # 1. Filings published by last night join the watchlist (Copycat's own rules).
            new = []
            while i < len(buys) and sec.filed_time(buys[i]) < now:
                if sec.filed_time(buys[i]) >= now - timedelta(days=cc["max_signal_age_days"] + 3):
                    new.append(buys[i])
                i += 1
            copycat.update_watchlist(st, new, cc, now)

            # 2. Exits: gap through the stop at the open, then the day's low, high, and the time limit.
            for t in list(pos):
                p, b = pos[t], self._bar(t, day)
                if b is None:
                    continue
                o, lo, hi, cl = (float(b[k]) for k in ("open", "low", "high", "close"))
                held_h = (now - p["opened"]).total_seconds() / 3600
                exit_px, why = None, None
                if o <= p["stop"]:
                    exit_px, why = o, "stop"
                elif lo <= p["stop"]:
                    exit_px, why = p["stop"], "stop"
                elif hi >= p["target"]:
                    exit_px, why = max(o, p["target"]), "target"
                elif held_h + 6.5 >= ex["max_hold_hours"]:
                    exit_px, why = cl, "time limit"
                if exit_px is not None:
                    gross = p["qty"] * exit_px * (1 - slip)
                    cash += gross * (1 - fee)
                    res.fees += gross * fee
                    res.trades.append({"symbol": t, "opened": p["opened"].isoformat(), "closed": _at_close(day).isoformat(),
                                       "cost": p["cost"], "pnl": gross * (1 - fee) - p["cost"], "exit": why,
                                       "insiders": p["insiders"], "insider_usd": p["insider_usd"], "score": p["score"],
                                       "chase_pct": p["chase_pct"]})
                    pos.pop(t)
                    continue
                p["last"] = cl
                r_unit = p["entry"] - p["initial_stop"]
                if p["stop"] < p["entry"] and hi >= p["entry"] + ex["move_stop_to_breakeven_at_r"] * r_unit:
                    p["stop"] = p["entry"]

            # 3. Entries at the open, same gate, ranking, chase limit and Risk sizing as the live bot.
            equity = value(day, "open")
            gate = risk.account_gate(equity, prev_close_equity, self.cash, False, None, rk)
            if gate.allowed and len(pos) < rk["max_open_positions"]:
                planned, virtual, held_bars = 0.0, [], {}
                for t, p in pos.items():
                    virtual.append({"symbol": t, "market_value": p["qty"] * p["last"], "asset_class": "stocks"})
                    held_bars[t] = self._before(t, day, lookback)
                for e in copycat.ranked(st, cc, set(pos), now):
                    if len(pos) >= rk["max_open_positions"]:
                        break
                    t, b = e["ticker"], self._bar(e["ticker"], day)
                    if b is None:
                        continue
                    price = float(b["open"])
                    chase = (price / copycat.avg_price(e) - 1) * 100
                    if chase > cc["max_chase_pct"]:
                        continue
                    stop, target = price * (1 - cc["stop_pct"] / 100), price * (1 + cc["target_pct"] / 100)
                    bars = self._before(t, day, lookback)
                    c = Candidate(symbol=t, asset_class="stocks", bars=bars, price=price,
                                  plan=Plan(trend="copy", support=stop, resistance=target, entry=price, stop=stop,
                                            target=target))
                    risk.review(c, equity, cash - planned, virtual, held_bars, rk, already_planned_usd=planned)
                    if c.risk_verdict == "REJECT":
                        continue
                    usd = min(c.size_usd, cash)
                    fill = price * (1 + slip)
                    cash -= usd
                    res.fees += usd * fee
                    pos[t] = {"qty": usd * (1 - fee) / fill, "entry": price, "stop": stop, "initial_stop": stop,
                              "target": target, "opened": now, "cost": usd, "last": price,
                              "insiders": len({x["who"] for x in e["buys"]}),
                              "insider_usd": round(sum(x["usd"] for x in e["buys"])), "score": e["score"],
                              "chase_pct": round(chase, 1)}
                    st.setdefault("copied", {})[t] = now.isoformat()
                    st["watchlist"].pop(t, None)
                    planned += usd
                    virtual.append({"symbol": t, "market_value": usd, "asset_class": "stocks"})
                    if len(bars):
                        held_bars[t] = bars
            prev_close_equity = value(day)
            res.equity.append((_at_close(day), prev_close_equity))
        return res

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        rows = []
        spy = self.hist.spy["close"]
        for t in res.trades:
            opened = datetime.fromisoformat(t["opened"])
            before = spy[spy.index < pd.Timestamp(opened.date())]
            trend = (float(before.iloc[-1]) / float(before.tail(200).mean()) - 1) * 100 if len(before) >= 50 else None
            rows.append({"opened": opened.strftime("%Y-%m-%d"), "stock": t["symbol"],
                         "result_pct": round(t["pnl"] / t["cost"] * 100, 2), "exit": t.get("exit", "?"),
                         "days_held": (datetime.fromisoformat(t["closed"]) - opened).days,
                         "insiders": t.get("insiders"), "insider_usd": t.get("insider_usd"),
                         "score": t.get("score"), "chase_pct": t.get("chase_pct"),
                         "sp500_vs_200day_avg_pct": round(trend, 1) if trend is not None else None})
        return rows


def _at_open(day: pd.Timestamp) -> datetime:
    return datetime(day.year, day.month, day.day, *OPEN_UTC, tzinfo=timezone.utc)


def _at_close(day: pd.Timestamp) -> datetime:
    return datetime(day.year, day.month, day.day, 21, 0, tzinfo=timezone.utc)


def load_engine(cfg: dict, days: int = 365, cache: str | None = None, end: datetime | None = None) -> CopycatEngine:
    if cache and Path(cache).exists():
        hist = pickle.loads(Path(cache).read_bytes())
    else:
        today = (end or datetime.now(timezone.utc)).date()
        # Ask for a bit more than a year: the newest quarter usually isn't published yet.
        hist = fetch_history(cfg, today - timedelta(days=days + 120), today,
                             os.environ.get(cfg["alpaca_key_secret"], ""), os.environ.get(cfg["alpaca_secret_secret"], ""))
        if cache:
            Path(cache).write_bytes(pickle.dumps(hist))
    last = datetime.combine(hist.last_data_day, datetime.min.time(), timezone.utc) + timedelta(hours=23)
    return CopycatEngine(hist, last - timedelta(days=days), last)
