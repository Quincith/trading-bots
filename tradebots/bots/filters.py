"""Optional entry filters: extra "don't buy when..." rules a strategy can switch on in its config.

They all start switched off (0), so a strategy trades exactly as before until one is set in its
config file (normally by merging a strategy lab pull request). Each one is a plain rule, no AI:

  filters:
    max_atr_pct: 3          # skip when the coin swings more than 3% per candle on average (too wild)
    trend_ema_bars: 200     # only buy when the price is above its 200-candle average (an uptrend)
    btc_ema_bars: 200       # only buy when Bitcoin is above its 200-candle average (the market is healthy)
    min_fear_greed: 20      # skip when the crypto Fear & Greed index is below 20 (panic)
    max_fear_greed: 80      # skip when it is above 80 (greed, often near a top)

Charts runs first, then these filters, then the bots that cost money (News, Sentiment, Decision).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..indicators import atr, ema
from ..models import Candidate

KEYS = ("max_atr_pct", "trend_ema_bars", "btc_ema_bars", "min_fear_greed", "max_fear_greed")


@dataclass
class Context:
    btc: pd.DataFrame | None = None   # Bitcoin candles on the strategy's timeframe
    fng: int | None = None            # today's Fear & Greed index, 0..100


def active(cfg: dict | None) -> dict:
    """The filters that are switched on (missing, 0 and null all mean off)."""
    return {k: v for k, v in (cfg or {}).items() if k in KEYS and v}


def needs_fear_greed(cfg: dict | None) -> bool:
    return any(k in active(cfg) for k in ("min_fear_greed", "max_fear_greed"))


def above_average(df: pd.DataFrame | None, bars: int) -> bool | None:
    """Is the last close above its `bars`-candle average? None when there is too little history."""
    if df is None or len(df) < min(bars, 50):
        return None
    close = df["close"]
    return bool(close.iloc[-1] > ema(close, int(bars)).iloc[-1])


def check(c: Candidate, cfg: dict | None, ctx: Context) -> str | None:
    """Why this setup is filtered out, or None when it passes every filter that is on."""
    f = active(cfg)
    price = float(c.bars["close"].iloc[-1])
    if "max_atr_pct" in f:
        swing = float(atr(c.bars).iloc[-1]) / price * 100
        if swing > f["max_atr_pct"]:
            return f"too wild: swings {swing:.1f}% per candle (limit {f['max_atr_pct']}%)"
    if "trend_ema_bars" in f and above_average(c.bars, f["trend_ema_bars"]) is False:
        return f"not in an uptrend: below its {f['trend_ema_bars']}-candle average"
    if "btc_ema_bars" in f and above_average(ctx.btc, f["btc_ema_bars"]) is False:
        return f"Bitcoin is below its {f['btc_ema_bars']}-candle average (weak market)"
    if ctx.fng is not None:
        if "min_fear_greed" in f and ctx.fng < f["min_fear_greed"]:
            return f"Fear & Greed is {ctx.fng}, under {f['min_fear_greed']} (panic)"
        if "max_fear_greed" in f and ctx.fng > f["max_fear_greed"]:
            return f"Fear & Greed is {ctx.fng}, over {f['max_fear_greed']} (greed)"
    return None


def apply(cands: list[Candidate], cfg: dict | None, btc: pd.DataFrame | None, fear_greed) -> tuple[list, dict]:
    """Splits setups into (kept, {symbol: reason filtered}). `fear_greed` is only called when needed."""
    if not active(cfg) or not cands:
        return cands, {}
    ctx = Context(btc=btc, fng=fear_greed() if needs_fear_greed(cfg) else None)
    out = {c.symbol: why for c in cands if (why := check(c, cfg, ctx))}
    return [c for c in cands if c.symbol not in out], out
