"""Bot 1 - Scout: finds unusual volume and price moves, then checks momentum."""
from __future__ import annotations

import pandas as pd

from ..indicators import ema, rsi
from ..models import Candidate


def measure(df: pd.DataFrame, cfg: dict) -> dict | None:
    """How unusual this market looks right now. None when there isn't enough history."""
    vw, mb = cfg["volume_window"], cfg["move_bars"]
    if len(df) < max(vw + 1, mb + 1, 60):
        return None
    close, vol = df["close"], df["volume"]
    # 1. Volume: latest few bars vs the normal level before them
    recent_vol = vol.iloc[-2:].mean()
    normal_vol = vol.iloc[-vw - 2:-2].mean()
    volume_ratio = recent_vol / normal_vol if normal_vol > 0 else 0.0
    # 2. Movement: price change over the last `move_bars` bars
    move_pct = (close.iloc[-1] / close.iloc[-mb - 1] - 1) * 100
    # 3. Momentum: above the 20 EMA, 20 EMA rising, RSI strong but not exhausted
    e20 = ema(close, 20)
    r = float(rsi(close).iloc[-1])
    momentum_ok = bool(close.iloc[-1] > e20.iloc[-1] and e20.iloc[-1] > e20.iloc[-4]
                       and cfg.get("min_rsi", 50) <= r <= cfg.get("max_rsi", 78))
    passed = volume_ratio >= cfg["min_volume_ratio"] and move_pct >= cfg["min_move_pct"] and momentum_ok
    return {"price": float(close.iloc[-1]), "volume_ratio": float(volume_ratio), "move_pct": float(move_pct),
            "rsi": r, "momentum_ok": momentum_ok, "passed": bool(passed)}


def scan(bars: dict[str, pd.DataFrame], asset_class: str, cfg: dict) -> list[Candidate]:
    found = []
    for symbol, df in bars.items():
        m = measure(df, cfg)
        if m is None or not m["passed"]:
            continue
        score = min(m["volume_ratio"], 5) + min(m["move_pct"], 10) / 2 + (m["rsi"] - 50) / 20
        found.append(Candidate(symbol=symbol, asset_class=asset_class, bars=df, price=m["price"],
                               volume_ratio=m["volume_ratio"], move_pct=m["move_pct"], rsi=m["rsi"],
                               scout_score=score))
    found.sort(key=lambda c: c.scout_score, reverse=True)
    return found
