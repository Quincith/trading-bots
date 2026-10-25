"""Bot 2's second job - the News radar: watch the news all the time to catch a trend while it is forming.

The News bot used to read headlines only for coins Scout had already flagged, which means it only
ever heard about a story after the price had started moving. The radar reads the news for every
coin, every scan, before Scout looks at prices:

  - Alpaca's news feed (Benzinga headlines; the same free feed News already used)
  - CoinDesk, Cointelegraph and Decrypt headlines (free public RSS feeds, no key)
  - CoinGecko's "trending" list: the coins people searched for most in the last 24 hours (free, no key).
    A rush of people looking up a coin often comes before a rush of people buying it.

For each coin it counts "buzz": how many headlines in the last few hours compared with the usual
pace before that. Once an hour Claude reads all the headlines together and names the themes that
are forming (for example "ETF hopes for Solana") and which coins they could lift or hurt. The
counting is free; only the hourly Claude read costs money (see `radar:` in the config files).

What the radar changes:
  - Always: News and Decision see the radar's notes, and the run report and bot world show them.
  - Only if `radar.early_watch` is on: Scout lets coins with strong news buzz through with looser
    volume and price-move rules, so the team can look at them earlier. This is off until it has
    been tested in the strategy lab.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path

import requests

from ..ai import AI
from ..alpaca import norm
from .news import BAD, GOOD

log = logging.getLogger(__name__)
UA = {"User-Agent": "trading-bots/1.0 (paper trading research)"}

FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
}
TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"

# Names used in headlines, for coins Alpaca can trade. Coins outside our list are reported, not traded.
NAMES = {
    "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"], "AVAX": ["avalanche"],
    "LINK": ["chainlink"], "DOGE": ["dogecoin"], "LTC": ["litecoin"], "XRP": ["xrp", "ripple"],
    "AAVE": ["aave"], "BCH": ["bitcoin cash"], "DOT": ["polkadot"], "UNI": ["uniswap"], "SHIB": ["shiba inu"],
    "PEPE": ["pepe"], "CRV": ["curve dao"], "GRT": ["the graph"], "MKR": ["maker", "makerdao"],
    "SUSHI": ["sushiswap"], "XTZ": ["tezos"], "YFI": ["yearn"], "BAT": ["basic attention token"],
}

SYSTEM = (
    "You are the News radar on a small crypto trading team. Your job is to spot trends while they are "
    "still forming, before the price has moved much. You get the last day of crypto headlines, the coins "
    "people are searching for most, and a buzz count per coin (headlines in the last few hours versus the "
    "usual pace). Name up to 3 themes that are building right now and which of the listed coins they "
    "could lift or hurt. Then score each listed coin from -1 (bad news building) to +1 (strong good news "
    "building); 0 means nothing new. Be skeptical: recycled stories, price-recap articles ('BTC rises 2%') "
    "and paid promotions are not catalysts. Keep notes under 20 words and plain enough for a beginner."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "note": {"type": "string"},
                           "coins": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "note", "coins"], "additionalProperties": False}},
        "coins": {"type": "array", "items": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}, "score": {"type": "number"}, "note": {"type": "string"}},
            "required": ["ticker", "score", "note"], "additionalProperties": False}},
    },
    "required": ["themes", "coins"], "additionalProperties": False,
}


@dataclass
class Radar:
    time: str = ""
    coins: dict[str, dict] = field(default_factory=dict)   # ticker -> buzz, score, note, trending rank
    themes: list[dict] = field(default_factory=list)
    trending_elsewhere: list[str] = field(default_factory=list)   # trending coins we don't trade
    headlines: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    ai_time: str | None = None                             # when Claude last read the headlines

    def watch(self, min_score: float) -> list[str]:
        """Coins whose news looks strong enough to look at early."""
        return [t for t, c in self.coins.items() if c["score"] >= min_score]

    def to_dict(self) -> dict:
        return {"time": self.time, "coins": self.coins, "themes": self.themes,
                "trending_elsewhere": self.trending_elsewhere, "headlines": self.headlines,
                "sources": self.sources, "ai_time": self.ai_time}


def ticker(symbol: str) -> str:
    return symbol.split("/")[0].upper() if "/" in symbol else norm(symbol).removesuffix("USD")


# ---- free sources --------------------------------------------------------------------------------

def _get(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        return r
    except Exception as e:
        log.info("Radar source unavailable (%s): %s", url.split("/")[2], e)
        return None


def parse_rss(xml_text: str, source: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if title:
            desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
            out.append({"headline": title, "summary": " ".join(desc.split())[:200], "symbols": [],
                        "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": source})
    return out


def rss_headlines() -> list[dict]:
    out = []
    for source, url in FEEDS.items():
        r = _get(url)
        if r is not None:
            out += parse_rss(r.text, source)
    return out


def trending() -> list[str]:
    """Tickers of CoinGecko's most-searched coins right now, most searched first."""
    r = _get(TRENDING_URL)
    try:
        return [c["item"]["symbol"].upper() for c in r.json()["coins"]]
    except Exception:
        return []


# ---- counting buzz -------------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _patterns(tick: str) -> tuple[re.Pattern, re.Pattern | None]:
    """Ticker in capitals (so "link" the word isn't LINK), or the coin's name in any case."""
    names = NAMES.get(tick, [])
    return (re.compile(rf"\b{re.escape(tick)}\b"),
            re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b", re.I) if names else None)


def mentions(item: dict, tick: str) -> bool:
    if tick in {ticker(s) for s in item.get("symbols", [])}:
        return True
    text = item["headline"] + " " + item.get("summary", "")
    caps, name = _patterns(tick)
    return bool(caps.search(text) or (name and name.search(text)))


def buzz(items: list[dict], tick: str, now: datetime, recent_hours: float, window_hours: float) -> dict:
    """Headlines about a coin in the last `recent_hours`, against its usual pace over the window."""
    cut = (now - timedelta(hours=recent_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mine = [n for n in items if mentions(n, tick)]
    recent = [n for n in mine if n["created_at"] >= cut]
    before = len(mine) - len(recent)
    usual_rate = max(before, 1) / max(window_hours - recent_hours, 1)   # at least 1 story, so 1 headline isn't "infinite"
    ratio = (len(recent) / recent_hours) / usual_rate
    tone = 0
    for n in recent:
        text = (n["headline"] + " " + n.get("summary", "")).lower()
        tone += sum(w in text for w in GOOD) - sum(w in text for w in BAD)
    return {"recent": len(recent), "before": before, "buzz": round(ratio, 2), "tone": tone,
            "headlines": [n["headline"][:140] for n in recent[:3]]}


def rule_score(b: dict, trend_rank: int | None) -> float:
    """Free score from the counts: more buzz than usual, good-sounding words, people searching for it."""
    s = 0.0
    if b["recent"] >= 2:
        s += 0.2 * min(b["buzz"] - 1, 2.5)
    s += max(-0.6, min(0.4, 0.1 * b["tone"]))
    if trend_rank is not None:
        s += 0.3 if trend_rank < 5 else 0.15
    return round(max(-1.0, min(1.0, s)), 2)


# ---- one radar sweep -----------------------------------------------------------------------------

def _cache(data_dir: Path) -> Path:
    return data_dir / "radar" / "latest.json"


def load(data_dir: Path) -> dict | None:
    p = _cache(data_dir)
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, json.JSONDecodeError):
        return None


def _ask_claude(r: Radar, items: list[dict], ai: AI) -> dict | None:
    newest = sorted(items, key=lambda n: n["created_at"], reverse=True)[:60]
    ours = sorted((c["trending"], t) for t, c in r.coins.items() if c["trending"] is not None)
    lines = [f"Coins we trade: {', '.join(r.coins)}",
             "Our coins on CoinGecko's most-searched list: " + (", ".join(f"{t} (#{i + 1})" for i, t in ours) or "none")
             + (f". Also trending, not traded by us: {', '.join(r.trending_elsewhere)}" if r.trending_elsewhere else ""),
             "", "Buzz per coin (headlines in the recent hours vs. the usual pace, 1.0 = normal):"]
    lines += [f"- {t}: {c['recent']} recent headlines, buzz {c['buzz']}x" for t, c in r.coins.items()]
    lines += ["", "Headlines, newest first:"]
    lines += [f"- [{n['created_at'][5:16]} {n['source']}] {n['headline']}" for n in newest]
    return ai.ask(SYSTEM, "\n".join(lines), SCHEMA)


def scan(symbols: list[str], broker, ai: AI, rcfg: dict, data_dir: Path, now: datetime) -> Radar:
    """Read every source, count buzz per coin, and (about once an hour) ask Claude what's forming.

    Both strategies run within a minute of each other, so a fresh sweep is saved and reused, and
    Claude's read is reused until `claude_every_minutes` has passed.
    """
    data_dir = Path(data_dir)
    ticks = list(dict.fromkeys(ticker(s) for s in symbols))
    cached = load(data_dir)
    if cached and cached.get("time") and set(ticks) <= set(cached["coins"]) and \
            0 <= (now - datetime.fromisoformat(cached["time"])).total_seconds() < 20 * 60:
        r = Radar(**cached)
        r.coins = {t: r.coins[t] for t in ticks}
        return r

    window = rcfg["window_hours"]
    items = []
    try:
        items += broker.get_news(symbols, hours=window, limit=50)
    except Exception as e:  # news helps, never required
        log.warning("Alpaca news unavailable for the radar: %s", e)
    alpaca_count = len(items)
    rss = [n for n in rss_headlines()
           if n["created_at"] >= (now - timedelta(hours=window)).strftime("%Y-%m-%dT%H:%M:%SZ")
           and n["created_at"] <= now.strftime("%Y-%m-%dT%H:%M:%SZ")]
    items += rss
    hot = trending()

    r = Radar(time=now.isoformat(timespec="seconds"), headlines=len(items),
              sources={"Alpaca/Benzinga": alpaca_count, "crypto news sites": len(rss), "CoinGecko trending": len(hot)})
    r.trending_elsewhere = [t for t in hot if t not in ticks and t in NAMES][:5]
    for t in ticks:
        b = buzz(items, t, now, rcfg["recent_hours"], window)
        rank = hot.index(t) if t in hot else None
        b.update(trending=rank, rule_score=rule_score(b, rank), score=rule_score(b, rank), note="")
        r.coins[t] = b

    # Claude's read: reuse the last one until it's due again
    last_ai = cached.get("ai_time") if cached else None
    due = not last_ai or (now - datetime.fromisoformat(last_ai)).total_seconds() >= rcfg["claude_every_minutes"] * 60 - 120
    if not due and cached:
        r.ai_time, r.themes = last_ai, cached.get("themes", [])
        for t, c in r.coins.items():
            old = cached["coins"].get(t)
            if old and old.get("note"):
                c["score"], c["note"] = old["score"], old["note"]
    elif items and ai.enabled:
        result = _ask_claude(r, items, ai)
        if result:
            r.ai_time = r.time
            r.themes = [{"title": th["title"][:80], "note": th["note"][:200],
                         "coins": [c.upper() for c in th["coins"] if c.upper() in r.coins]}
                        for th in result.get("themes", [])[:3]]
            for x in result.get("coins", []):
                t = x["ticker"].upper()
                if t in r.coins:
                    r.coins[t]["score"] = round(max(-1.0, min(1.0, float(x["score"]))), 2)
                    r.coins[t]["note"] = x["note"][:160]
            _log_read(data_dir, r)
    for c in r.coins.values():
        if not c["note"]:
            c["note"] = (f"{c['recent']} headlines lately ({c['buzz']}x usual)" if c["recent"] else "quiet")
            if c["trending"] is not None:
                c["note"] += f", #{c['trending'] + 1} most searched"

    _cache(data_dir).parent.mkdir(parents=True, exist_ok=True)
    _cache(data_dir).write_text(json.dumps(r.to_dict(), indent=1))
    return r


def _log_read(data_dir: Path, r: Radar) -> None:
    """Keep every Claude read, so we can later check whether its early calls came true."""
    p = data_dir / "radar" / f"{r.time[:10]}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps({"time": r.time, "themes": r.themes,
                            "coins": {t: {k: c[k] for k in ("score", "note", "recent", "buzz", "trending")}
                                      for t, c in r.coins.items()}}) + "\n")
