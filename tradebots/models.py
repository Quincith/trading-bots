"""Shared data passed from bot to bot."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Plan:
    trend: str            # "up", "down" or "sideways"
    support: float
    resistance: float
    entry: float
    stop: float
    target: float

    @property
    def risk_pct(self) -> float:
        return (self.entry - self.stop) / self.entry * 100

    @property
    def reward_risk(self) -> float:
        return (self.target - self.entry) / max(self.entry - self.stop, 1e-12)


@dataclass
class Candidate:
    symbol: str                      # as Alpaca takes orders, e.g. BTC/USD or NVDA
    asset_class: str                 # "crypto" or "stocks"
    bars: pd.DataFrame = field(repr=False)
    price: float = 0.0
    # Scout
    volume_ratio: float = 0.0
    move_pct: float = 0.0
    rsi: float = 50.0
    scout_score: float = 0.0
    # News / Sentiment: -1 (very bad) .. +1 (very good)
    news_score: float = 0.0
    news_note: str = ""
    sentiment_score: float = 0.0
    hype: float = 0.0               # 0..1, how much of the buzz looks like pure hype
    sentiment_note: str = ""
    # Charts
    plan: Plan | None = None
    # Risk
    risk_verdict: str = ""           # APPROVE, REDUCE or REJECT
    risk_note: str = ""
    size_usd: float = 0.0
    # Decision
    decision: str = ""               # BUY, WAIT or SKIP
    confidence: float = 0.0
    decision_note: str = ""

    def summary(self) -> dict:
        p = self.plan
        return {
            "symbol": self.symbol, "price": round(self.price, 6),
            "volume_ratio": round(self.volume_ratio, 2), "move_pct": round(self.move_pct, 2),
            "rsi": round(self.rsi, 1),
            "news_score": round(self.news_score, 2), "news": self.news_note,
            "sentiment_score": round(self.sentiment_score, 2), "hype": round(self.hype, 2),
            "sentiment": self.sentiment_note,
            "trend": p.trend if p else None,
            "entry": round(p.entry, 6) if p else None, "stop": round(p.stop, 6) if p else None,
            "target": round(p.target, 6) if p else None,
            "reward_risk": round(p.reward_risk, 2) if p else None,
            "risk": self.risk_verdict, "risk_note": self.risk_note, "size_usd": round(self.size_usd, 2),
        }
