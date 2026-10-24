"""Bot 4 - Charts: sets the trend, support and resistance, and an entry, stop and target."""
from __future__ import annotations

from ..indicators import atr, ema, swing_levels
from ..models import Candidate, Plan


def make_plan(c: Candidate, cfg: dict) -> Plan | None:
    """Returns a trade plan, or None when the chart doesn't offer a good long setup."""
    df = c.bars
    close = df["close"]
    price = float(close.iloc[-1])
    fast, slow = ema(close, cfg["ema_fast"]).iloc[-1], ema(close, cfg["ema_slow"]).iloc[-1]
    trend = "up" if price > fast > slow else "down" if price < fast < slow else "sideways"

    lows, highs = swing_levels(df.iloc[:-1], cfg["swing_window"])
    supports = [x for x in lows if x < price]
    resistances = [x for x in highs if x > price]
    a = float(atr(df, cfg["atr_period"]).iloc[-1])
    support = max(supports[-10:]) if supports else price - 2 * a
    resistance = min(resistances[-10:]) if resistances else price + 3 * a

    entry = price
    # Stop: the tighter of "just under support" and "N x ATR below entry", but never closer than 0.5 ATR.
    stop = max(support - 0.25 * a, entry - cfg["stop_atr_mult"] * a)
    stop = min(stop, entry - 0.5 * a)
    risk = entry - stop
    # Target: the nearest resistance if it pays enough, otherwise the minimum reward:risk.
    target = max(resistance, entry + cfg["min_reward_risk"] * risk)
    plan = Plan(trend=trend, support=support, resistance=resistance, entry=entry, stop=stop, target=target)

    if trend == "down" or stop <= 0:
        return None
    # If the target had to be pushed past a nearby wall of resistance, the setup is cramped.
    if resistance < entry + risk:
        return None
    return plan
