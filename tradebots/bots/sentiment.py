"""Bot 3 - Sentiment: what people are saying. Bullish, bearish or pure hype.

Free sources (X/Twitter has no realistic free API):
  - ApeWisdom: Reddit mention counts and 24h change for crypto and stocks
  - Reddit search: recent post titles (best effort; Reddit sometimes blocks cloud servers)
  - alternative.me Crypto Fear & Greed index
"""
from __future__ import annotations

import logging

import requests

from ..ai import AI
from ..models import Candidate

log = logging.getLogger(__name__)
UA = {"User-Agent": "trading-bots/1.0 (paper trading research)"}

SYSTEM = (
    "You are the Sentiment analyst on a small trading team. For each asset you get Reddit mention stats "
    "and recent post titles, plus the overall market mood. Score sentiment from -1 (bearish) to +1 "
    "(bullish), and separately rate hype from 0 to 1: how much of the buzz looks like empty hype or "
    "pump talk rather than real conviction. Keep each note under 25 words."
)

SCHEMA = {
    "type": "object",
    "properties": {"assets": {"type": "array", "items": {
        "type": "object",
        "properties": {"symbol": {"type": "string"}, "score": {"type": "number"},
                       "hype": {"type": "number"}, "note": {"type": "string"}},
        "required": ["symbol", "score", "hype", "note"], "additionalProperties": False}}},
    "required": ["assets"], "additionalProperties": False,
}

SUBREDDITS = {"crypto": "CryptoCurrency", "stocks": "stocks+wallstreetbets"}


def _get(url: str, **params):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.info("Sentiment source unavailable (%s): %s", url.split("/")[2], e)
        return None


def ticker(symbol: str) -> str:
    return symbol.split("/")[0].upper()


def fear_greed() -> int | None:
    data = _get("https://api.alternative.me/fng/", limit=1)
    try:
        return int(data["data"][0]["value"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def mentions(asset_class: str) -> dict[str, dict]:
    path = "all-crypto" if asset_class == "crypto" else "all-stocks"
    data = _get(f"https://apewisdom.io/api/v1.0/filter/{path}")
    return {r["ticker"].upper(): r for r in (data or {}).get("results", [])}


def reddit_titles(c: Candidate) -> list[str]:
    data = _get(f"https://www.reddit.com/r/{SUBREDDITS[c.asset_class]}/search.json",
                q=ticker(c.symbol), restrict_sr=1, sort="new", t="day", limit=15)
    try:
        return [p["data"]["title"][:140] for p in data["data"]["children"]]
    except (TypeError, KeyError):
        return []


def rule_score(m: dict | None, fng: int | None) -> tuple[float, float]:
    score, hype = 0.0, 0.3
    if m:
        now, before = float(m.get("mentions") or 0), float(m.get("mentions_24h_ago") or 0)
        change = (now - before) / before if before else 0.0
        score += max(-0.5, min(0.5, change / 2))
        hype = min(1.0, 0.3 + max(0.0, change) / 4)   # sudden mention spikes look more like hype
    if fng is not None:
        score += (fng - 50) / 100
    return max(-1.0, min(1.0, score)), hype


def analyze(cands: list[Candidate], ai: AI) -> None:
    if not cands:
        return
    fng = fear_greed() if any(c.asset_class == "crypto" for c in cands) else None
    mention_maps = {ac: mentions(ac) for ac in {c.asset_class for c in cands}}
    info = {}
    for c in cands:
        m = mention_maps[c.asset_class].get(ticker(c.symbol))
        info[c.symbol] = (m, reddit_titles(c))

    lines = [f"Crypto Fear & Greed index: {fng}/100" if fng is not None else "Fear & Greed: unavailable"]
    for sym, (m, titles) in info.items():
        stats = (f"mentions 24h: {m.get('mentions')} (24h before: {m.get('mentions_24h_ago')}), "
                 f"upvotes: {m.get('upvotes')}, rank: {m.get('rank')}") if m else "no mention data"
        lines.append(f"## {sym}\n{stats}\n" + ("\n".join(f"- {t}" for t in titles) or "(no recent posts found)"))
    has_data = any(m or t for m, t in info.values())
    result = ai.ask(SYSTEM, "\n\n".join(lines), SCHEMA) if has_data else None
    scored = {a["symbol"]: a for a in (result or {}).get("assets", [])}

    for c in cands:
        if c.symbol in scored:
            a = scored[c.symbol]
            c.sentiment_score = max(-1.0, min(1.0, float(a["score"])))
            c.hype = max(0.0, min(1.0, float(a["hype"])))
            c.sentiment_note = a["note"]
        else:
            m, _ = info[c.symbol]
            c.sentiment_score, c.hype = rule_score(m, fng)
            c.sentiment_note = "rule-based from mention counts" + (f", fear/greed {fng}" if fng is not None else "")
