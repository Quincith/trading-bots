"""Gold bounce: buy gold (XAU/USD) when it bounces after a sharp selloff, on 30-minute candles.

This is the trade from legendarydrec's gold screenshots, written as a fixed rule so it can be tested:
gold falls hard, makes a low, and the bounce is bought with the safety stop under that low; once the trade
is well ahead, the stop moves up to the entry price ("breakeven"), so a winner can't turn into a loser.

The rule, checked at the close of every 30-minute candle:
1. Selloff: over the last `lookback_bars` candles (8 hours), gold fell from its high to its low by at least
   `selloff_atr` typical candle swings (ATR, the average size of a 30-minute candle).
2. Fresh low: that low was made in the last 3 candles.
3. Bounce: this candle closed up (close above open) and above the previous candle's high.
4. Optional trend check (`trend_days`, 0 = off): yesterday's close was above the N-day average price.
Then buy at the next candle's open. The safety stop sits a quarter of a candle swing under the selloff's low.
The profit goal is `target_r` times what the trade risks. Once gold is up `breakeven_r` times the risk, the stop
moves to the entry price. A trade still open after `max_hold_bars` candles (24 hours), or when the market is
about to close for the weekend, is sold at the candle's close.

Sizing is the Forex wing's: about 1% of the account at risk, at most 1x the account in one trade, and the 3%
daily loss limit. Costs: at least OANDA's usual gold spread (35 cents an ounce, or 0.01% of the price if
bigger) plus 10 cents of slip on every fill, and 4% a year of the trade's size to hold it overnight.

The settings in `RULES` were fixed before any test ran, not tuned on these years. `simulate` is the lab
replay only: there is no live gold trading code.

Result (2026-10-28, OANDA 30-minute prices Oct 2018 to Oct 2026, $100 start): both versions FAILED the lab.
The plain bounce ended at $74.98 (unseen months -7.5%) and the uptrend version at $79.32 (unseen -1.2%), with
worst drops of 28% and 26%. Before costs they made +75% and +27%: the spread and slip on ~300 trades a year ate
it. Holding gold made +249%. Also, OANDA's US practice accounts don't offer gold at all (no metals in the FX
COPY account's 68 instruments), so this couldn't run there even if it had passed.
Run it again with `python -m tradebots.gold --cache gold.pkl` (needs OANDA_API_TOKEN).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import backtest as bt
from .indicators import atr

log = logging.getLogger(__name__)

PAIR = "XAU_USD"
MIN_SPREAD = 0.35        # dollars per ounce: about OANDA's usual gold spread...
MIN_SPREAD_PCT = 0.01    # ...or this % of the price, whichever is bigger (gold costs more as its price rises)
SLIP = 0.10              # dollars per ounce lost on every fill
FINANCING_PCT = 4.0      # a year, of the trade's size, for holding it past the daily 5pm New York roll

# The two versions, fixed before testing: the plain bounce, and the bounce only when gold is in an uptrend.
RULES = {
    "bounce": {"style": "bounce", "lookback_bars": 16, "fresh_bars": 3, "selloff_atr": 3.0, "atr_bars": 14,
               "stop_buffer_atr": 0.25, "target_r": 2.0, "breakeven_r": 1.0, "max_hold_bars": 48, "trend_days": 0},
}
RULES["bounce_trend"] = {**RULES["bounce"], "trend_days": 50}
TITLES = {"bounce": "Gold bounce (buy after a selloff)",
          "bounce_trend": "Gold bounce, only in an uptrend (above the 50-day average)"}
RISK = {"risk_per_trade_pct": 1, "max_position_pct": 100, "max_total_exposure_pct": 300, "max_open_positions": 1,
        "max_same_usd_side": 1, "max_daily_loss_pct": 3, "max_total_loss_pct": 15}


def config(rule: str = "bounce", **risk) -> dict:
    return {"name": "gold", "title": TITLES.get(rule, "Gold bounce"), "markets": {"pairs": [PAIR]},
            "forex": dict(RULES[rule]), "risk": {**RISK, **risk}}


def half_cost(price: float, cost: float = 1.0) -> float:
    return (max(MIN_SPREAD, price * MIN_SPREAD_PCT / 100) / 2 + SLIP) * cost


def signals(df: pd.DataFrame, fx: dict) -> np.ndarray:
    """True on each candle whose close completes a bounce (the buy is at the next candle's open)."""
    n, fresh = int(fx["lookback_bars"]), int(fx["fresh_bars"])
    a = atr(df, int(fx["atr_bars"])).to_numpy()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    # the window is the n candles before this one
    hi = pd.Series(h).rolling(n).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(n).min().shift(1).to_numpy()
    recent_lo = pd.Series(l).rolling(fresh).min().shift(1).to_numpy()
    low = np.minimum(lo, l)            # the bounce candle itself may dip to a new low first
    ok = ((hi - low >= float(fx["selloff_atr"]) * a) & (np.minimum(recent_lo, l) <= lo) & (c > o)
          & (c > np.r_[np.nan, h[:-1]]))
    if int(fx.get("trend_days") or 0):
        day = df["close"].resample("1D").last().dropna()
        avg = day.rolling(int(fx["trend_days"])).mean()
        up = (day > avg).shift(1)      # yesterday's close vs its average: known before today starts
        ok &= up.reindex(df.index.normalize()).fillna(False).to_numpy(dtype=bool)
    return np.nan_to_num(ok, nan=0).astype(bool)


def simulate(cfg: dict, df: pd.DataFrame, start: datetime, end: datetime, cash: float = 100.0,
             cost: float = 1.0, sig: np.ndarray | None = None) -> bt.SimResult:
    fx, rk = cfg["forex"], cfg["risk"]
    sig = signals(df, fx) if sig is None else sig
    a = atr(df, int(fx["atr_bars"])).to_numpy()
    t = df.index
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    gap_after = np.r_[np.diff(t.asi8) / 6e10, 1e9]          # minutes to the next candle
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    first, last = int(t.searchsorted(s)), int(t.searchsorted(e))
    equity, fees = cash, 0.0
    res = bt.SimResult(cfg["name"], [(start, cash)])
    day, day_start, day_pl = None, cash, 0.0
    lo_n = pd.Series(l).rolling(int(fx["lookback_bars"])).min().shift(1).to_numpy()
    i = first
    while i < last - 1:
        if not sig[i] or gap_after[i] > 120:   # the next candle is after a market close: no entry
            i += 1
            continue
        today = t[i + 1].date()
        if today != day:
            day, day_start, day_pl = today, equity, 0.0
        if day_pl <= -day_start * rk["max_daily_loss_pct"] / 100:
            i += 1
            continue
        hc = half_cost(o[i + 1], cost)
        entry = o[i + 1] + hc
        stop = min(lo_n[i], l[i]) - float(fx["stop_buffer_atr"]) * a[i]
        risk = entry - stop
        if not risk > 0:
            i += 1
            continue
        units = equity * rk["risk_per_trade_pct"] / 100 / risk
        units = min(units, equity * rk["max_position_pct"] / 100 / entry)
        target = entry + float(fx["target_r"]) * risk
        be_at = entry + float(fx["breakeven_r"]) * risk
        j, why, px = i + 1, "", 0.0
        end_j = min(i + int(fx["max_hold_bars"]), last - 1)
        moved = False
        while True:
            if l[j] - hc <= stop:                      # the stop (a gap past it fills at the worse price)
                px = min(o[j] - hc, stop - SLIP * cost) if j > i + 1 else stop - SLIP * cost
                why = "breakeven stop" if moved else "stop hit"
                break
            if h[j] - hc >= target:
                px, why = target, "profit goal"
                break
            if not moved and h[j] - hc >= be_at:       # from the next candle on, the stop is the entry price
                stop, moved = max(stop, entry), True
            if j >= end_j or gap_after[j] > 120:
                px, why = c[j] - hc, "time limit" if j >= end_j else "market closing"
                break
            j += 1
        held_days = (t[j] - t[i + 1]).total_seconds() / 86400
        rolls = int(held_days) + (1 if t[j].hour >= 21 > t[i + 1].hour else 0)
        fin = units * entry * FINANCING_PCT / 100 / 365 * rolls * cost
        pl = units * (px - entry) - fin
        fees += units * 2 * hc + fin
        day_pl += pl
        equity += pl
        res.trades.append({"symbol": PAIR, "direction": 1, "opened": t[i + 1].isoformat(), "closed": t[j].isoformat(),
                           "pnl": pl, "cost": units * entry, "equity_at_open": equity - pl, "exit": why,
                           "ctx": {"units": units, "risk_usd": units * risk}})
        res.equity.append((t[j].to_pydatetime(), equity))
        i = j + 1
    res.equity.append((end, equity))
    res.fees = fees
    return res


class GoldEngine:
    """Lab engine: 30-minute XAU/USD candles. The lab's checks compare it with doing nothing."""
    benchmark_label = "Do nothing (keep the cash)"

    def __init__(self, bars: pd.DataFrame, start: datetime, end: datetime, cash: float = 100.0, min_trades: int = 30):
        self.bars, self.start, self.end, self.cash, self.min_trades = bars, start, end, cash, min_trades
        self._sig: dict[str, np.ndarray] = {}

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        key = repr(sorted(cfg["forex"].items()))
        if key not in self._sig:
            self._sig[key] = signals(self.bars, cfg["forex"])
        return simulate(cfg, self.bars, start, end, self.cash, cost, self._sig[key])

    def benchmark(self, start: datetime, end: datetime) -> bt.SimResult:
        return bt.SimResult("benchmark", [(start, self.cash), (end, self.cash)])

    def hold_gold_pct(self, start: datetime, end: datetime) -> float:
        p = self.bars["close"]
        p = p[(p.index >= pd.Timestamp(start)) & (p.index < pd.Timestamp(end))]
        return (p.iloc[-1] / p.iloc[0] - 1) * 100 if len(p) > 1 else 0.0

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        return [{"opened": t["opened"][:16], "pair": "XAU/USD", "side": "buy",
                 "result_pct": round(t["pnl"] / max(t["equity_at_open"], 1e-9) * 100, 2), "exit": t["exit"]}
                for t in res.trades]


def load_engine(years: int = 8, cache: str | None = None, end: datetime | None = None) -> GoldEngine:
    import os
    import pickle
    from pathlib import Path

    from .oanda import OandaPractice
    now = datetime.now(timezone.utc)
    end = end or datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = end.replace(year=end.year - years)
    if cache and Path(cache).exists():
        bars = pickle.loads(Path(cache).read_bytes())
    else:
        token = os.environ.get("OANDA_API_TOKEN")
        if not token:
            raise RuntimeError("The gold test needs OANDA's 30-minute gold prices: set OANDA_API_TOKEN")
        api = OandaPractice(token, os.environ.get("OANDA_FXCOPY_ACCOUNT_ID") or "-")
        bars = api.history(PAIR, "M30", start - timedelta(days=90), end)
        if cache:
            Path(cache).write_bytes(pickle.dumps(bars))
    return GoldEngine(bars, start, end)


def report(eng: GoldEngine, rules=tuple(RULES)) -> str:
    """Each version through the lab's whole-strategy check, plus what it made before costs and how the
    trades ended."""
    from . import lab
    runner = lab.Runner(eng)
    split = lab.make_split(eng.start, eng.end)
    rows, details = [], []
    for rule in rules:
        cfg = config(rule)
        v, text = lab.validate("fxcopy", eng, runner, cfg)
        full = runner.run_many([(cfg, eng.start, eng.end, 1.0)])[0]
        free = eng.run(cfg, eng.start, eng.end, cost=0.0)
        passed = sum(c["passed"] for c in v.checks)
        rows.append(f"| {TITLES[rule]} | {lab.pct(full):+.1f}% ({bt.money(full.equity[-1][1])}) | {lab.pct(free):+.1f}% | "
                    f"{v.numbers['unseen']:+.1f}% | {v.numbers['drawdown']:.1f}% | {len(full.trades)} | "
                    f"{bt.money(full.fees)} | {'✅ pass' if v.kept else f'❌ {passed}/{len(v.checks)}'} |")
        exits: dict[str, list[float]] = {}
        years: dict[int, list[float]] = {}
        for t in full.trades:
            r = t["pnl"] / max(t["equity_at_open"], 1e-9) * 100
            exits.setdefault(t["exit"], []).append(r)
            years.setdefault(int(t["opened"][:4]), []).append(r)
        units = [t["ctx"]["units"] for t in full.trades]
        extra = ["", f"Before costs the whole period would have been {lab.pct(free):+.1f}%.", "",
                 "How the trades ended:", "", "| Exit | Trades | Total % |", "|---|---|---|"]
        extra += [f"| {k} | {len(x)} | {sum(x):+.1f}% |" for k, x in sorted(exits.items())]
        extra += ["", "Trades per year: " + ", ".join(f"{y}: {len(x)} ({sum(x):+.1f}%)" for y, x in sorted(years.items()))]
        if units:
            extra += ["", f"Trade size: {min(units):.3f} to {max(units):.3f} ounces (median {np.median(units):.3f})."]
        details.append(text + "\n".join(extra) + "\n")
    head = ["# Gold bounce: lab check", "",
            f"Prices: OANDA 30-minute XAU/USD candles, {eng.start:%b %Y} to {eng.end:%b %Y}. $100 start, about 1% "
            "risked per trade, at most 1x the account per trade, 3% daily loss limit. Settings fixed before testing.",
            "",
            f"Holding gold over the same time: whole period {eng.hold_gold_pct(eng.start, eng.end):+.1f}%, unseen months "
            f"({split.study_end:%b %Y} to {split.end:%b %Y}) {eng.hold_gold_pct(split.study_end, split.end):+.1f}%.", "",
            "| Rule | Whole period | Before costs | Unseen months | Worst drop | Trades | Costs paid | Lab check |",
            "|---|---|---|---|---|---|---|---|"]
    return "\n".join(head + rows) + "\n\n" + "\n---\n\n".join(details)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--years", type=int, default=8)
    p.add_argument("--cache", default=None, help="save/load the downloaded prices here")
    p.add_argument("--end", default=None, help="last day, YYYY-MM-DD (default: the start of this month)")
    p.add_argument("--out", default=None, help="also write the report to this file")
    a = p.parse_args(argv)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else None
    text = report(load_engine(a.years, a.cache, end))
    print(text)
    if a.out:
        from pathlib import Path
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
