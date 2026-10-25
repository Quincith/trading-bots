"""Bot 2 - News: picks up catalysts from Alpaca's free news feed (Benzinga headlines).

News also runs the radar (radar.py), which watches all the news before Scout looks at prices.
Its themes and per-coin notes are added here as background."""
from __future__ import annotations

import logging

from ..ai import AI
from ..alpaca import norm
from ..models import Candidate

log = logging.getLogger(__name__)

SYSTEM = (
    "You are the News analyst on a small trading team. For each asset, read the recent headlines and "
    "judge whether there is a real catalyst that supports a short-term price rise. Score from -1 "
    "(clearly bad news) to +1 (strong positive catalyst); 0 means no meaningful news. Be skeptical of "
    "recycled or promotional headlines. Keep each note under 25 words."
)

SCHEMA = {
    "type": "object",
    "properties": {"assets": {"type": "array", "items": {
        "type": "object",
        "properties": {"symbol": {"type": "string"}, "score": {"type": "number"}, "note": {"type": "string"}},
        "required": ["symbol", "score", "note"], "additionalProperties": False}}},
    "required": ["assets"], "additionalProperties": False,
}

GOOD = ("approval", "etf", "partnership", "upgrade", "beats", "record", "surge", "launch", "adopt", "inflow")
BAD = ("hack", "exploit", "lawsuit", "sec sues", "downgrade", "misses", "outflow", "ban", "fraud", "delist")


def headlines_for(c: Candidate, news: list[dict]) -> list[dict]:
    key = norm(c.symbol)
    return [n for n in news if key in {norm(s) for s in n["symbols"]}][:8]


def rule_score(items: list[dict]) -> float:
    s = 0.0
    for n in items:
        text = (n["headline"] + " " + n["summary"]).lower()
        s += 0.2 * sum(w in text for w in GOOD) - 0.3 * sum(w in text for w in BAD)
    return max(-1.0, min(1.0, s))


def analyze(cands: list[Candidate], broker, ai: AI, themes: list[dict] | None = None) -> None:
    if not cands:
        return
    try:
        news = broker.get_news([c.symbol for c in cands])
    except Exception as e:  # news is helpful, never required
        log.warning("News feed unavailable: %s", e)
        news = []
    per = {c.symbol: headlines_for(c, news) for c in cands}

    radar_notes = {c.symbol: c.radar_note for c in cands if c.radar_note}
    prompt = "\n\n".join(
        f"## {sym}\n" + ("\n".join(f"- [{n['created_at'][:16]}] {n['headline']} — {n['summary']}" for n in items)
                         or "(no headlines in the last 48 hours)")
        + (f"\nRadar (all crypto news): {radar_notes[sym]}" if sym in radar_notes else "")
        for sym, items in per.items())
    if themes:
        prompt = "Themes the radar sees forming across crypto news:\n" + "\n".join(
            f"- {t['title']}: {t['note']}" for t in themes) + "\n\n" + prompt
    result = ai.ask(SYSTEM, prompt, SCHEMA) if any(per.values()) else None
    scored = {a["symbol"]: a for a in (result or {}).get("assets", [])}

    for c in cands:
        if c.symbol in scored:
            c.news_score = max(-1.0, min(1.0, float(scored[c.symbol]["score"])))
            c.news_note = scored[c.symbol]["note"]
        else:
            c.news_score = rule_score(per[c.symbol])
            c.news_note = f"{len(per[c.symbol])} headlines (rule-based)" if per[c.symbol] else "no recent news"
