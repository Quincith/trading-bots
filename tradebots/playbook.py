"""Playbook: the five textbook kinds of crypto trading, replayed on past prices for Aggressive and Medium.

  Trend following ("trend"): buy when the 50-day average price crosses above the 200-day average (the
      "golden cross"); sell when it crosses back below. After a safety stop, buy back only on a new 20-day high
      while the 50-day is still above the 200-day.
  Breakout ("breakout"): buy when a coin closes above its highest price of the last 20 days on 1.5x normal
      volume (the Turtle traders' rule plus a volume check); sell when it closes below its 10-day low.
  Swing ("swing"): on 4-hour candles, buy a bullish RSI divergence: the price makes a lower low, but the
      momentum score (RSI) makes a higher low, the first of them in the oversold zone (RSI under 30).
      Sell when RSI gets back above 70 (overbought) or after 14 days.
  Day trading ("daytrade"): an opening range breakout on 15-minute candles. Crypto never closes, so the "open"
      is midnight UTC. Buy when a candle closes above the first 30 minutes' high within 3 hours; the stop is the
      range's low; everything is sold by the end of the day.
  Scalping ("scalp"): on 5-minute candles, buy when the 9-candle average crosses above the 21-candle average
      while the price is above its 200-candle average. Take profit at 1.5x the typical candle swing (ATR), stop at
      1x, and get out after an hour regardless.

Arbitrage (buying a coin on one exchange and selling it on another for a tiny gap) can't be tested here: the
bots have one Alpaca paper account, and a paper account fills at Alpaca's own prices. See README.

Alpaca can't "short" crypto (bet on a fall), so every rule only buys, and a break down is a reason to sell.
The settings above were fixed before any test ran, from the textbook version of each rule, not tuned on these
years. Sizing follows each account's Risk settings (the % risked per trade, the biggest position, open
positions and the daily loss limit), so the same rule bets bigger in Aggressive than in Medium.

`simulate` is the lab replay; this is a test bench only (no live trading code yet).
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import backtest as bt
from .indicators import atr, ema, rsi

log = logging.getLogger(__name__)

# The textbook settings, fixed before testing (see the module notes).
STYLES = {
    "trend": {"style": "trend", "timeframe": "1Day", "fast_days": 50, "slow_days": 200, "reentry_days": 20,
              "atr_bars": 20, "stop_atr_mult": 3.0},
    "breakout": {"style": "breakout", "timeframe": "1Day", "entry_days": 20, "exit_days": 10,
                 "volume_days": 20, "min_volume_ratio": 1.5, "atr_bars": 20, "stop_atr_mult": 2.0},
    "swing": {"style": "swing", "timeframe": "4Hour", "rsi_bars": 14, "pivot_bars": 3, "oversold": 30,
              "lookback_bars": 60, "exit_rsi": 70, "max_hold_bars": 84, "atr_bars": 14, "stop_atr_mult": 0.5},
    "daytrade": {"style": "daytrade", "timeframe": "15Min", "range_minutes": 30, "entry_hours": 3},
    "scalp": {"style": "scalp", "timeframe": "5Min", "fast_bars": 9, "slow_bars": 21, "trend_bars": 200,
              "atr_bars": 14, "stop_atr_mult": 1.0, "target_atr_mult": 1.5, "max_hold_bars": 12},
}
TITLES = {"trend": "Trend following (50/200-day golden cross)", "breakout": "Breakout (20-day high on 1.5x volume)",
          "swing": "Swing (RSI bullish divergence, 4-hour candles)",
          "daytrade": "Day trading (midnight UTC opening range breakout)",
          "scalp": "Scalping (9/21 average cross on 5-minute candles)"}
MIN_TRADES = {"trend": 8, "breakout": 20, "swing": 20, "daytrade": 50, "scalp": 50}
MINUTES = {"5Min": 5, "15Min": 15, "1Hour": 60, "4Hour": 240, "1Day": 1440}


def config_for(strategy: str, style: str) -> dict:
    """The account's own config (risk sizing and loss limits) with a playbook rule in place of Scout & co."""
    cfg = copy.deepcopy(bt.load_config(strategy))
    cfg["playbook"] = dict(STYLES[style])
    cfg["title"] = f"{strategy.title()}: {TITLES[style]}"
    return cfg


# ---- the rules: when to buy and when to sell ----------------------------------------------------------------

def signals(df: pd.DataFrame, pb: dict) -> pd.DataFrame:
    """For one coin, decided at each candle's close: `enter` (buy at the next open), `exit` (sell at the next
    open), `stop_dist` (how far below the entry the stop goes), `target_dist` (profit goal, NaN = none),
    `flat` (sell at this candle's close: the day trade's end of day) and `strength` (to rank coins)."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    out = pd.DataFrame(index=df.index)
    out["target_dist"] = np.nan
    out["flat"] = False
    s = pb["style"]
    if s == "trend":
        fast, slow = c.rolling(pb["fast_days"]).mean(), c.rolling(pb["slow_days"]).mean()
        up = fast > slow
        cross = up & ~up.shift(1, fill_value=False)
        new_high = c > h.shift(1).rolling(pb["reentry_days"]).max()
        out["enter"] = cross | (up & new_high)
        out["exit"] = ~up
        out["stop_dist"] = atr(df, pb["atr_bars"]) * pb["stop_atr_mult"]
        out["strength"] = c / slow - 1
    elif s == "breakout":
        hi = h.shift(1).rolling(pb["entry_days"]).max()
        lo = l.shift(1).rolling(pb["exit_days"]).min()
        vol_x = v / v.shift(1).rolling(pb["volume_days"]).mean()
        out["enter"] = (c > hi) & (vol_x >= pb["min_volume_ratio"])
        out["exit"] = c < lo
        out["stop_dist"] = atr(df, pb["atr_bars"]) * pb["stop_atr_mult"]
        out["strength"] = vol_x
    elif s == "swing":
        r = rsi(c, pb["rsi_bars"])
        k = pb["pivot_bars"]
        span = 2 * k + 1
        # a pivot low is the lowest low of k candles either side; it is only known k candles later
        is_piv = (l == l.rolling(span, center=True).min()).to_numpy()
        lows, rs, a = l.to_numpy(), r.to_numpy(), atr(df, pb["atr_bars"]).to_numpy()
        n = len(df)
        enter = np.zeros(n, bool)
        stop = np.full(n, np.nan)
        prev = None   # (index, low, rsi) of the last pivot low
        for t in range(k, n):
            p = t - k   # the candle that becomes a confirmed pivot at t
            if not is_piv[p] or np.isnan(rs[p]):
                continue
            if (prev is not None and p - prev[0] <= pb["lookback_bars"] and lows[p] < prev[1]
                    and rs[p] > prev[2] and prev[2] < pb["oversold"]):
                enter[t] = True
                stop[t] = c.iat[t] - (lows[p] - pb["stop_atr_mult"] * a[t])
            prev = (p, lows[p], rs[p])
        out["enter"] = enter
        out["exit"] = (r > pb["exit_rsi"]).to_numpy()
        out["stop_dist"] = stop
        out["strength"] = -r
    elif s == "daytrade":
        tf = MINUTES[pb["timeframe"]]
        mins = df.index.hour * 60 + df.index.minute
        n_rng = pb["range_minutes"] // tf
        day = df.index.normalize()
        first = pd.Series(mins < pb["range_minutes"], index=df.index)
        rng_hi = h.where(first).groupby(day).transform("max")
        rng_lo = l.where(first).groupby(day).transform("min")
        window = (mins >= pb["range_minutes"]) & (mins < pb["range_minutes"] + pb["entry_hours"] * 60)
        brk = window & (c > rng_hi)
        # only the day's first break counts
        first_brk = brk & (brk.astype(int).groupby(day).cumsum() == 1)
        # the bar after the break must be the same day (no buying at the last candle)
        out["enter"] = first_brk & (mins < 24 * 60 - 2 * tf)
        out["exit"] = False
        out["stop_dist"] = c - rng_lo
        out["flat"] = mins == 24 * 60 - tf
        out["strength"] = (c - rng_hi) / (rng_hi - rng_lo)
        out.loc[first.groupby(day).transform("sum") < n_rng, "enter"] = False   # a missing range: skip the day
    elif s == "scalp":
        f, sl, tr = ema(c, pb["fast_bars"]), ema(c, pb["slow_bars"]), ema(c, pb["trend_bars"])
        up = f > sl
        out["enter"] = up & ~up.shift(1, fill_value=False) & (c > tr)
        out["exit"] = False
        a = atr(df, pb["atr_bars"])
        out["stop_dist"] = a * pb["stop_atr_mult"]
        out["target_dist"] = a * pb["target_atr_mult"]
        out["strength"] = (c - tr) / tr
    else:
        raise ValueError(f"unknown style {s}")
    out["enter"] = out["enter"].fillna(False).astype(bool) & (out["stop_dist"] > 0)
    out["exit"] = out["exit"].fillna(False).astype(bool)
    return out


# ---- the replay ---------------------------------------------------------------------------------------------

def grid(bars: dict[str, pd.DataFrame], tf: str) -> dict[str, pd.DataFrame]:
    """All coins on one regular candle grid. A candle with no trades repeats the last price with no volume."""
    step = pd.Timedelta(minutes=MINUTES[tf])
    lo = min(df.index[0] for df in bars.values())
    hi = max(df.index[-1] for df in bars.values())
    idx = pd.date_range(lo.floor(step), hi, freq=step)
    out = {}
    for s, df in bars.items():
        df = df[~df.index.duplicated()].reindex(idx)
        start = df["close"].first_valid_index()
        cl = df["close"].ffill()
        df["volume"] = df["volume"].fillna(0)
        for col in ("open", "high", "low"):
            df[col] = df[col].fillna(cl)
        df["close"] = cl
        out[s] = df.loc[start:]
    return out


def simulate(cfg: dict, bars: dict[str, pd.DataFrame], start: datetime, end: datetime, cash: float = 100.0,
             cost: float = 1.0) -> bt.SimResult:
    """Candle-by-candle replay. Buys and rule sells decided at a candle's close fill at the next candle's open;
    the stop and the profit goal can fill inside a candle (if both are touched, the replay assumes the stop).
    Every buy and sell pays Alpaca's 0.25% fee plus 0.05% slip (times `cost`). The total loss limit is left off
    so the replay shows what the rule itself does (the lab checks the worst drop against it separately);
    the daily loss limit stays on."""
    pb, rk = cfg["playbook"], cfg["risk"]
    fee, slip = bt.FEE * cost, bt.SLIPPAGE * cost
    coins = [s for s in cfg["markets"]["crypto"] if s in bars]
    sig = {s: signals(bars[s], pb) for s in coins}
    s0, e0 = pd.Timestamp(start), pd.Timestamp(end)
    idx = bars[coins[0]].index
    for s in coins[1:]:
        idx = idx.union(bars[s].index)
    idx = idx[(idx >= s0) & (idx < e0)]
    step = pd.Timedelta(minutes=MINUTES[pb["timeframe"]])
    # numpy columns on the shared index (NaN before a coin starts trading)
    col = {}
    for s in coins:
        d = bars[s].reindex(idx)
        g = sig[s].reindex(idx)
        col[s] = {k: d[k].to_numpy(float) for k in ("open", "high", "low", "close")}
        col[s].update({k: g[k].fillna(False).astype(bool).to_numpy() for k in ("enter", "exit", "flat")})
        col[s].update({k: g[k].to_numpy(float) for k in ("stop_dist", "target_dist", "strength")})
    risk_pct, max_pos = rk["risk_per_trade_pct"] / 100, rk["max_position_pct"] / 100
    max_total, max_open = rk["max_total_exposure_pct"] / 100, rk["max_open_positions"]
    daily_limit = rk["max_daily_loss_pct"] / 100
    max_hold = pb.get("max_hold_bars")

    money, fees = cash, 0.0
    pos: dict[str, dict] = {}
    pend_in: list[tuple] = []
    pend_out: set[str] = set()
    res = bt.SimResult(cfg["name"], [(start, cash)])
    last = {}
    day, day_start_eq, day_blocked = None, cash, False
    eq = cash
    record_every = max(1, int(pd.Timedelta(hours=1) / step))

    def sell(s, px, when, why):
        nonlocal money, fees
        p = pos.pop(s)
        fill = px * (1 - slip)
        gross = p["qty"] * fill
        f = gross * fee
        money += gross - f
        fees += f
        res.trades.append({"symbol": s, "opened": p["opened"], "closed": when.isoformat(), "cost": p["cost"],
                           "pnl": gross - f - p["cost"], "exit": why, "equity_at_open": p["equity"]})

    for i, t in enumerate(idx):
        # a new UTC day resets the daily loss limit
        if t.normalize() != day:
            day, day_start_eq, day_blocked = t.normalize(), eq, False
        # 1. orders decided at the last close fill at this open
        for s in list(pend_out):
            o = col[s]["open"][i]
            if s in pos and not np.isnan(o):
                sell(s, o, t, "rule exit")
        pend_out = set()
        for s, usd, dist, tgt, e_at in pend_in:
            o = col[s]["open"][i]
            if s in pos or np.isnan(o) or usd > money:
                continue
            fill = o * (1 + slip)
            f = usd * fee
            qty = (usd - f) / fill
            money -= usd
            fees += f
            pos[s] = {"qty": qty, "cost": usd, "stop": fill - dist, "target": fill + tgt if tgt == tgt else np.nan,
                      "opened": t.isoformat(), "bar": i, "equity": e_at}
        pend_in = []
        # 2. the stop and the profit goal can fill any time inside the candle
        for s in list(pos):
            c = col[s]
            o, h, lo = c["open"][i], c["high"][i], c["low"][i]
            if np.isnan(o):
                continue
            p = pos[s]
            if lo <= p["stop"]:
                sell(s, min(o, p["stop"]), t, "stop hit")
            elif p["target"] == p["target"] and h >= p["target"]:
                sell(s, max(o, p["target"]), t, "profit goal")
        # 3. at the close
        for s in coins:
            px = col[s]["close"][i]
            if not np.isnan(px):
                last[s] = px
        eq = money + sum(p["qty"] * last[s] for s, p in pos.items())
        if eq < day_start_eq * (1 - daily_limit):
            day_blocked = True
        for s in list(pos):
            c = col[s]
            if np.isnan(c["close"][i]):
                continue
            if c["flat"][i]:
                sell(s, c["close"][i], t, "end of day")
            elif c["exit"][i] or (max_hold and i - pos[s]["bar"] >= max_hold):
                pend_out.add(s)
        eq = money + sum(p["qty"] * last[s] for s, p in pos.items())
        if i % record_every == 0 or i == len(idx) - 1:
            res.equity.append((t + step, eq))
        if day_blocked:
            continue
        held = {s: p["qty"] * last[s] for s, p in pos.items() if s not in pend_out}
        exposure, free = sum(held.values()), money
        cands = [s for s in coins if s not in pos and col[s]["enter"][i]]
        for s in sorted(cands, key=lambda s: -np.nan_to_num(col[s]["strength"][i])):
            if len(held) >= max_open:
                break
            px, dist = col[s]["close"][i], float(col[s]["stop_dist"][i])
            if np.isnan(px) or not dist > 0:
                continue
            usd = min(eq * risk_pct / (dist / px), eq * max_pos, eq * max_total - exposure, free)
            if usd < rk.get("min_order_usd", 2):
                continue
            tgt = col[s]["target_dist"][i]
            pend_in.append((s, usd, dist, float(tgt) if tgt == tgt else np.nan, eq))
            held[s], exposure, free = usd, exposure + usd, free - usd
    res.fees = fees
    return res


# ---- the lab engine -----------------------------------------------------------------------------------------

class PlaybookEngine:
    """Lab engine for the playbook rules: past candles for the 8 coins at every candle size a rule needs."""
    benchmark_label = "Just hold Bitcoin"

    def __init__(self, bars: dict[str, dict[str, pd.DataFrame]], start: datetime, end: datetime,
                 cash: float = 100.0, min_trades: int = 20):
        self.bars, self.start, self.end, self.cash, self.min_trades = bars, start, end, cash, min_trades

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        return simulate(cfg, self.bars[cfg["playbook"]["timeframe"]], start, end, self.cash, cost)

    def benchmark(self, start: datetime, end: datetime) -> bt.SimResult:
        """Buy Bitcoin with all the money at the start (paying the fee and slip) and never sell."""
        btc = self.bars["1Day"]["BTC/USD"]
        c = btc["close"][(btc.index >= pd.Timestamp(start)) & (btc.index < pd.Timestamp(end))]
        if c.empty:
            return bt.SimResult("benchmark", [(start, self.cash), (end, self.cash)])
        qty = self.cash * (1 - bt.FEE) / (float(btc["open"][btc.index >= pd.Timestamp(start)].iloc[0]) * (1 + bt.SLIPPAGE))
        return bt.SimResult("benchmark", [(start, self.cash)] + [(t + timedelta(days=1), qty * v) for t, v in c.items()])

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        return [{"opened": t["opened"][:16], "coin": t["symbol"], "exit": t["exit"],
                 "result_pct": round(t["pnl"] / t["cost"] * 100, 2)} for t in res.trades]


def fetch(symbols: list[str], start: datetime, end: datetime, key: str, secret: str,
          scalp_from: datetime | None = None) -> dict[str, dict[str, pd.DataFrame]]:
    """Daily candles (plus a year to warm up the 200-day average), hourly candles turned into 4-hour ones,
    15-minute candles, and 5-minute candles from `scalp_from` (there are a lot of them)."""
    from .alpaca import AlpacaPaper
    broker = AlpacaPaper(key, secret)
    out = {}
    plan = [("1Day", start - timedelta(days=400)), ("1Hour", start - timedelta(days=40)),
            ("15Min", start - timedelta(days=2)), ("5Min", (scalp_from or start) - timedelta(days=2))]
    for tf, a in plan:
        log.warning("Downloading %s candles from %s...", tf, a.date())
        out[tf] = broker.get_bars_range(symbols, tf, a, end, "crypto")
        for s, df in out[tf].items():
            log.warning("  %s %s: %d candles from %s", tf, s, len(df), df.index[0].date())
    out["4Hour"] = {s: df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last",
                                              "volume": "sum"}).dropna(subset=["close"])
                    for s, df in out.pop("1Hour").items()}
    return {tf: grid(d, tf) for tf, d in out.items()}


def load_engine(years: int = 5, cache: str | None = None, end: datetime | None = None,
                scalp_years: int = 1) -> PlaybookEngine:
    import os
    import pickle
    from pathlib import Path
    now = datetime.now(timezone.utc)
    end = end or datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = end.replace(year=end.year - years)
    if cache and Path(cache).exists():
        bars = pickle.loads(Path(cache).read_bytes())
    else:
        symbols = bt.load_config("aggressive")["markets"]["crypto"]
        key = os.environ.get("ALPACA_MEDIUM_KEY_ID") or os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", "")
        sec = os.environ.get("ALPACA_MEDIUM_SECRET_KEY") or os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", "")
        bars = fetch(symbols, start, end, key, sec, end.replace(year=end.year - scalp_years))
        if cache:
            Path(cache).write_bytes(pickle.dumps(bars))
    return PlaybookEngine(bars, start, end)


def engine_for(base: PlaybookEngine, style: str, scalp_years: int = 1) -> PlaybookEngine:
    """The same prices, judged over the period a rule has data for (scalping only has the last year of 5-minute
    candles), with the number of trades it needs."""
    start = base.start
    if STYLES[style]["timeframe"] == "5Min":
        start = base.end.replace(year=base.end.year - scalp_years)
    return PlaybookEngine(base.bars, start, base.end, base.cash, MIN_TRADES[style])


# ---- the full comparison ------------------------------------------------------------------------------------

def compare(base: PlaybookEngine, strategies=("aggressive", "medium"), styles=tuple(STYLES)) -> str:
    """Every rule for every account through the lab's whole-strategy check, plus what it made before fees."""
    from . import lab
    rows, details = [], []
    for style in styles:
        eng = engine_for(base, style)
        runner = lab.Runner(eng)
        bench = lab.pct(eng.benchmark(eng.start, eng.end))
        for strategy in strategies:
            cfg = config_for(strategy, style)
            v, text = lab.validate(strategy, eng, runner, cfg)
            free = eng.run(cfg, eng.start, eng.end, cost=0.0)
            full = runner.run_many([(cfg, eng.start, eng.end, 1.0)])[0]
            passed = sum(c["passed"] for c in v.checks)
            rows.append(f"| {TITLES[style]} | {strategy.title()} | {lab.pct(full):+.1f}% | {lab.pct(free):+.1f}% | "
                        f"{v.numbers['unseen']:+.1f}% | {bench:+.1f}% | {v.numbers['drawdown']:.1f}% | {len(full.trades)} | "
                        f"{bt.money(full.fees)} | {'✅ pass' if v.kept else f'❌ {passed}/{len(v.checks)}'} |")
            details.append(text.replace("Fees, the buy/sell gap (spread), slip and overnight interest included.",
                                        "Alpaca's 0.25% fee and 0.05% slip on every buy and sell included.")
                           + f"\nBefore fees and slip, the whole period would have been {lab.pct(free):+.1f}%.\n")
            log.warning("%s %s: %+.1f%% (before fees %+.1f%%), %s", style, strategy, lab.pct(full), lab.pct(free),
                        "PASS" if v.kept else "fail")
    head = ["# Playbook: the five kinds of trading on crypto, for Aggressive and Medium", "",
            f"Prices: Alpaca, {base.start:%b %Y} to {base.end:%b %Y} (scalping: the last year of 5-minute candles). "
            "$100 start, each account's own bet sizes and daily loss limit. Settings fixed before testing.", "",
            "| Rule | Account | Whole period | Before fees | Unseen months | Hold BTC (same period) | Worst drop | Trades | Fees paid | Lab check |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    return "\n".join(head + rows) + "\n\n" + "\n---\n\n".join(details)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--cache", default=None, help="save/load the downloaded prices here")
    p.add_argument("--end", default=None, help="last day, YYYY-MM-DD (default: the start of this month)")
    p.add_argument("--style", action="append", choices=list(STYLES), help="only these rules (default: all)")
    p.add_argument("--out", default=None, help="also write the report to this file")
    a = p.parse_args(argv)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else None
    base = load_engine(a.years, a.cache, end)
    text = compare(base, styles=tuple(a.style or STYLES))
    print(text)
    if a.out:
        from pathlib import Path
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
