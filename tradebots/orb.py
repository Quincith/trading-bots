"""Opening Range Breakout (ORB) for the Forex wing, as a day trade.

Each trading day, once a big market opens (London or New York):
1. The "opening range" is the highest and lowest price of the first `range_minutes` after the open.
2. If the price then breaks above the range, buy; if it breaks below, sell (only the first break counts).
   OANDA can hold these as "buy if it gets here" orders, so the bot doesn't have to watch every minute.
3. The safety stop sits on the other side of the range. Sizing risks about 1% of the account, so a wide
   range means a small trade.
4. Every trade still open at `exit_hour` (local time) is closed: nothing is held overnight, so there is
   no overnight interest.

This module is the lab replay, on 5-minute candles. Same costs as the rest of the wing: at least OANDA's
usual spread plus half a pip of slip on every fill, and a gap past a price fills at the worse price.
When the entry and the stop are both touched inside one 5-minute candle, the replay assumes the loss.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import backtest as bt
from .forex import (FxEngine, half_cost, label, notional_usd, pnl_usd, size, usd_per_unit_move)
from .pipeline import _iso

log = logging.getLogger(__name__)

SESSIONS = {"london": ("Europe/London", 8, 0), "newyork": ("America/New_York", 8, 0)}


def sessions(bars: pd.DataFrame, fx: dict) -> dict:
    """Each trading day's 5-minute candles from the open to `exit_hour`, in that market's local time.
    Returns {day: (times, open, high, low, close)} with times as UTC timestamps."""
    tz, h, m = SESSIONS[fx["session"]]
    local = bars.index.tz_convert(tz)
    mins = local.hour * 60 + local.minute
    start, stop = h * 60 + m, int(fx["exit_hour"]) * 60
    keep = (mins >= start) & (mins < stop) & (local.dayofweek < 5)
    sub = bars[keep]
    days = pd.Index(local[keep].date)
    out = {}
    for day, idx in sub.groupby(days).indices.items():
        g = sub.iloc[idx]
        out[day] = (g.index, g["open"].to_numpy(), g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy())
    return out


def day_trade(pair: str, sess: tuple, fx: dict, cost: float) -> dict | None:
    """The day's one trade for a pair, before sizing: entry time and price, direction, stop and exit."""
    times, o, h, l, c = sess
    n_rng = int(fx["range_minutes"]) // 5
    if len(times) <= n_rng:
        return None
    if (times[n_rng - 1] - times[0]) > pd.Timedelta(minutes=int(fx["range_minutes"]) - 5):
        return None    # gaps in the opening minutes (a holiday or a quiet day): skip
    hi, lo = float(h[:n_rng].max()), float(l[:n_rng].min())
    if hi <= lo:
        return None
    hc = half_cost(pair, 0.0, cost)
    last_entry = times[0] + pd.Timedelta(minutes=int(fx["range_minutes"])) + pd.Timedelta(hours=float(fx["entry_hours"]))
    for i in range(n_rng, len(times)):
        if times[i] >= last_entry:
            return None
        up, down = h[i] > hi, l[i] < lo
        if not (up or down):
            continue
        if up and down:          # broke both ways inside one candle: count it as a losing buy
            d = 1
        else:
            d = 1 if up else -1
        level, stop = (hi, lo) if d > 0 else (lo, hi)
        entry = (max(o[i], level) if d > 0 else min(o[i], level)) + d * hc
        # the rest of the day: the stop, else close at the exit time. Inside the entry candle we can't tell
        # which came first, so a candle that broke both ways counts as entry-then-stop.
        for j in range(i, len(times)):
            hit = (up and down) if j == i else ((l[j] <= stop) if d > 0 else (h[j] >= stop))
            if hit:
                px = stop if j == i else (min(o[j], stop) if d > 0 else max(o[j], stop))
                return {"pair": pair, "d": d, "t_in": times[i], "entry": entry, "stop": stop, "t_out": times[j],
                        "exit": px - d * hc, "why": "stop hit", "hi": hi, "lo": lo}
        return {"pair": pair, "d": d, "t_in": times[i], "entry": entry, "stop": stop, "t_out": times[-1],
                "exit": float(c[-1]) - d * hc, "why": "end of session", "hi": hi, "lo": lo}
    return None


def simulate(cfg: dict, sess_by_pair: dict[str, dict], start: datetime, end: datetime, cash: float = 100.0,
             cost: float = 1.0) -> bt.SimResult:
    fx, rk = cfg["forex"], cfg["risk"]
    s, e = start.date(), end.date()
    days = sorted({d for ss in sess_by_pair.values() for d in ss if s <= d < e})
    equity, fees = cash, 0.0
    res = bt.SimResult(cfg["name"], [(start, cash)])
    for day in days:
        cands = [t for p, ss in sess_by_pair.items() if day in ss
                 for t in [day_trade(p, ss[day], fx, cost)] if t]
        held, day_pl, day_start = [], 0.0, equity
        for t in sorted(cands, key=lambda x: x["t_in"]):
            if day_pl <= -day_start * rk["max_daily_loss_pct"] / 100:
                break    # the daily loss limit: no new trades today
            held = [h for h in held if h["t_out"] > t["t_in"]]
            gap = abs(t["entry"] - t["stop"])
            # the stop is the far edge of the range: size so that hitting it loses about risk_per_trade_pct
            units, _ = size(t["pair"], t["d"], t["entry"], gap, day_start, held, {**fx, "stop_atr_mult": 1.0}, rk)
            if not units:
                continue
            pl = pnl_usd(t["pair"], t["d"], units, t["entry"], t["exit"])
            fee = units * half_cost(t["pair"], 0.0, cost) * usd_per_unit_move(t["pair"], t["entry"]) * 2
            fees += fee
            day_pl += pl
            held.append({"pair": t["pair"], "direction": t["d"], "notional": notional_usd(t["pair"], units, t["entry"]),
                         "t_out": t["t_out"]})
            res.trades.append({"symbol": t["pair"], "direction": t["d"], "opened": _iso(t["t_in"].to_pydatetime()),
                               "closed": _iso(t["t_out"].to_pydatetime()), "pnl": pl,
                               "cost": notional_usd(t["pair"], units, t["entry"]), "equity_at_open": day_start,
                               "exit": t["why"], "ctx": {"range": f"{t['lo']:.5g}-{t['hi']:.5g}"}})
        equity += day_pl
        res.equity.append((datetime(day.year, day.month, day.day, 23, tzinfo=timezone.utc), equity))
    res.fees = fees
    return res


class OrbEngine(FxEngine):
    """Lab engine for the ORB rule: 5-minute candles, cut into each day's session once per session choice."""

    def __init__(self, intraday: dict[str, pd.DataFrame], start: datetime, end: datetime, cash: float = 100.0):
        super().__init__({}, None, start, end, cash, min_trades=50)
        self.intraday, self._sess = intraday, {}

    def sessions_for(self, fx: dict) -> dict[str, dict]:
        key = (fx["session"], int(fx["exit_hour"]))
        if key not in self._sess:
            self._sess[key] = {p: sessions(df, fx) for p, df in self.intraday.items()}
        return self._sess[key]

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        return simulate(cfg, self.sessions_for(cfg["forex"]), start, end, self.cash, cost)

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        return [{"opened": t["opened"][:16], "pair": label(t["symbol"]), "side": "buy" if t["direction"] > 0 else "sell",
                 "result_pct": round(t["pnl"] / max(t["equity_at_open"], 1e-9) * 100, 2), "exit": t["exit"]}
                for t in res.trades]


def load_engine(cfg: dict, years: int = 8, cache: str | None = None, end: datetime | None = None) -> OrbEngine:
    import os
    import pickle
    from pathlib import Path

    from .oanda import OandaPractice
    now = datetime.now(timezone.utc)
    end = end or datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = end.replace(year=end.year - years)
    if cache and Path(cache).exists():
        intraday = pickle.loads(Path(cache).read_bytes())
    else:
        token = os.environ.get("OANDA_API_TOKEN")
        if not token:
            raise RuntimeError("The ORB test needs OANDA's 5-minute prices: set OANDA_API_TOKEN")
        api = OandaPractice(token, os.environ.get("OANDA_FOREX_ACCOUNT_ID") or "-")
        intraday = {p: api.history(p, "M5", start - timedelta(days=3), end) for p in cfg["markets"]["pairs"]}
        if cache:
            Path(cache).write_bytes(pickle.dumps(intraday))
    return OrbEngine(intraday, start, end)
