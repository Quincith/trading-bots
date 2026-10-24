"""Small set of chart math used by Scout and Charts."""
from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def swing_levels(df: pd.DataFrame, window: int) -> tuple[list[float], list[float]]:
    """Swing lows (support) and swing highs (resistance): bars that are the extreme of +/- window bars."""
    lows, highs = df["low"], df["high"]
    span = 2 * window + 1
    is_low = lows == lows.rolling(span, center=True).min()
    is_high = highs == highs.rolling(span, center=True).max()
    return lows[is_low].tolist(), highs[is_high].tolist()
