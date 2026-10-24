"""Bot 6 - Decision: reads the other five bots and makes the final BUY, WAIT or SKIP call."""
from __future__ import annotations

import json

from ..ai import AI
from ..models import Candidate

SYSTEM = (
    "You are the Decision maker on a six-bot crypto/stock trading team. Scout found unusual volume and "
    "price moves, News looked for catalysts, Sentiment read social chatter, Charts set entry/stop/target, "
    "and Risk sized the position (Risk has already rejected anything unsafe). For each asset, make the "
    "final call: BUY (signals agree, setup is clean), WAIT (promising but mixed or overextended - check "
    "again next run) or SKIP (not worth it). Give a confidence from 0 to 1 and a reason under 30 words. "
    "Protecting capital matters more than catching every move. Strategy style: {style}"
)

SCHEMA = {
    "type": "object",
    "properties": {"calls": {"type": "array", "items": {
        "type": "object",
        "properties": {"symbol": {"type": "string"}, "decision": {"type": "string", "enum": ["BUY", "WAIT", "SKIP"]},
                       "confidence": {"type": "number"}, "reason": {"type": "string"}},
        "required": ["symbol", "decision", "confidence", "reason"], "additionalProperties": False}}},
    "required": ["calls"], "additionalProperties": False,
}

STYLES = {
    "aggressive": "AGGRESSIVE - short holds of a few hours, willing to act on momentum with decent confirmation.",
    "medium": "MEDIUM - holds for days, only buys when trend, news and sentiment clearly line up.",
}


def rule_call(c: Candidate) -> tuple[str, float, str]:
    """Fallback when Claude is unavailable: a weighted vote of the other bots."""
    score = 0.35 * min(c.scout_score / 6, 1) + 0.2 * (c.news_score + 1) / 2 + 0.2 * (c.sentiment_score + 1) / 2 \
        + 0.25 * (1 if c.plan and c.plan.trend == "up" else 0.4)
    score -= 0.15 * max(0.0, c.hype - 0.6)
    if c.news_score < -0.3 or c.sentiment_score < -0.4:
        return "SKIP", round(score, 2), "Negative news or sentiment (rule-based)."
    if score >= 0.65:
        return "BUY", round(score, 2), "Signals mostly agree (rule-based)."
    if score >= 0.5:
        return "WAIT", round(score, 2), "Signals mixed (rule-based)."
    return "SKIP", round(score, 2), "Weak setup (rule-based)."


def decide(cands: list[Candidate], ai: AI, strategy: str) -> None:
    live = [c for c in cands if c.risk_verdict in ("APPROVE", "REDUCE")]
    for c in cands:
        if c not in live:
            c.decision, c.confidence, c.decision_note = "SKIP", 0.0, f"Risk: {c.risk_note}"
    if not live:
        return
    prompt = json.dumps([c.summary() for c in live], indent=1)
    result = ai.ask(SYSTEM.format(style=STYLES.get(strategy, strategy)), prompt, SCHEMA)
    calls = {x["symbol"]: x for x in (result or {}).get("calls", [])}
    for c in live:
        if c.symbol in calls:
            x = calls[c.symbol]
            c.decision, c.confidence, c.decision_note = x["decision"], float(x["confidence"]), x["reason"]
        else:
            c.decision, c.confidence, c.decision_note = rule_call(c)
