import copy
from datetime import datetime, timedelta, timezone

import yaml
from conftest import FakeBroker, make_bars

from tradebots import pipeline, report
from tradebots.__main__ import ROOT
from tradebots.ai import AI
from tradebots.bots import radar
from tradebots.store import Store

AGG = yaml.safe_load((ROOT / "config/aggressive.yaml").read_text())
NO_AI = AI("claude-opus-5-5", api_key="")
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Solana ETF filing draws record interest</title><pubDate>Sun, 25 Oct 2026 11:00:00 +0000</pubDate>
<description>&lt;p&gt;Asset managers &lt;b&gt;line up&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>No date here</title></item>
<item><title>Click this link to win</title><pubDate>Sun, 25 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def item(headline, hours_ago, symbols=()):
    t = NOW - timedelta(hours=hours_ago)
    return {"headline": headline, "summary": "", "symbols": list(symbols),
            "created_at": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "test"}


class NewsBroker(FakeBroker):
    def __init__(self, news, **kw):
        super().__init__(**kw)
        self.news = news

    def get_news(self, symbols, hours=48, limit=50):
        return self.news


class FakeAI:
    enabled = True

    def __init__(self, answer):
        self.answer, self.calls, self.prompts = answer, 0, []

    def ask(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        return self.answer


def test_parse_rss_reads_titles_and_times():
    got = radar.parse_rss(RSS, "CoinDesk")
    assert [n["headline"] for n in got] == ["Solana ETF filing draws record interest", "Click this link to win"]
    assert got[0]["created_at"] == "2026-10-25T11:00:00Z" and got[0]["summary"] == "Asset managers line up"
    assert radar.parse_rss("not xml", "x") == []


def test_mentions_match_names_and_capital_tickers_only():
    assert radar.mentions(item("Solana hits new high", 1), "SOL")
    assert radar.mentions(item("Whales buy LINK", 1), "LINK")
    assert radar.mentions(item("Big day", 1, ["SOLUSD"]), "SOL")
    assert not radar.mentions(item("Click this link to win", 1), "LINK")
    assert not radar.mentions(item("Solar power stocks rise", 1), "SOL")


def test_buzz_compares_recent_headlines_with_the_usual_pace():
    news = [item("Solana ETF approval", h) for h in (0.5, 1, 2, 3)] + [item("Solana update", 20)]
    b = radar.buzz(news, "SOL", NOW, recent_hours=4, window_hours=24)
    assert b["recent"] == 4 and b["before"] == 1
    assert b["buzz"] == 20.0          # 1 per hour lately vs 1 per 20 hours before
    assert b["tone"] > 0
    assert radar.rule_score(b, trend_rank=0) > radar.rule_score(b, trend_rank=None) > 0
    quiet = radar.buzz(news, "BTC", NOW, 4, 24)
    assert quiet["recent"] == 0 and radar.rule_score(quiet, None) == 0


def test_scan_counts_every_coin_and_saves_a_shared_sweep(tmp_path, monkeypatch):
    monkeypatch.setattr(radar, "rss_headlines", lambda: radar.parse_rss(RSS, "CoinDesk"))
    monkeypatch.setattr(radar, "trending", lambda: ["SOL", "PEPE", "FAKECOIN"])
    news = [item("Solana ETF approval nears", h, ["SOLUSD"]) for h in (1, 2)]
    r = radar.scan(["BTC/USD", "SOL/USD"], NewsBroker(news), NO_AI, AGG["radar"], tmp_path, NOW)
    assert set(r.coins) == {"BTC", "SOL"}
    assert r.coins["SOL"]["recent"] == 3 and r.coins["SOL"]["trending"] == 0
    assert r.coins["SOL"]["score"] > 0.5 and r.coins["BTC"]["score"] == 0
    assert r.trending_elsewhere == ["PEPE"]           # tradable on Alpaca, not in our list; FAKECOIN isn't
    assert "most searched" in r.coins["SOL"]["note"]
    # The second strategy a minute later reuses the sweep instead of reading everything again
    monkeypatch.setattr(radar, "rss_headlines", lambda: 1 / 0)
    again = radar.scan(["SOL/USD"], NewsBroker([]), NO_AI, AGG["radar"], tmp_path, NOW + timedelta(minutes=1))
    assert again.coins["SOL"] == r.coins["SOL"] and list(again.coins) == ["SOL"]


def test_claude_reads_hourly_and_its_notes_carry_over(tmp_path):
    answer = {"themes": [{"title": "Solana ETF hopes", "note": "Several funds filed.", "coins": ["sol", "ZZZ"]}],
              "coins": [{"ticker": "SOL", "score": 0.8, "note": "ETF news is building."},
                        {"ticker": "ZZZ", "score": 1, "note": "not ours"}]}
    ai = FakeAI(answer)
    news = [item("Solana ETF filing", 1, ["SOLUSD"])]
    r = radar.scan(["SOL/USD"], NewsBroker(news), ai, AGG["radar"], tmp_path, NOW)
    assert ai.calls == 1 and "Solana ETF filing" in ai.prompts[0]
    assert r.themes == [{"title": "Solana ETF hopes", "note": "Several funds filed.", "coins": ["SOL"]}]
    assert r.coins["SOL"]["score"] == 0.8 and set(r.coins) == {"SOL"}
    assert (tmp_path / "radar" / "2026-10-25.jsonl").exists()
    # 30 minutes later the counts refresh for free, and Claude's read is reused
    r2 = radar.scan(["SOL/USD"], NewsBroker(news), ai, AGG["radar"], tmp_path, NOW + timedelta(minutes=30))
    assert ai.calls == 1 and r2.coins["SOL"]["note"] == "ETF news is building." and r2.themes == r.themes
    # An hour later Claude reads again
    radar.scan(["SOL/USD"], NewsBroker(news), ai, AGG["radar"], tmp_path, NOW + timedelta(minutes=60))
    assert ai.calls == 2


def _hot_sol(tmp_path, early_watch):
    """SOL rises with momentum but not enough volume for Scout's normal rules, while its news is hot."""
    cfg = copy.deepcopy(AGG)
    cfg["radar"]["early_watch"] = early_watch
    bars = make_bars(drift=0.0008, surge=True, seed=1)
    bars.loc[bars.index[-2:], "volume"] = 1300          # about 1.3x normal: below Scout's 1.5x
    news = [item("Solana ETF approval nears, record inflow", h, ["SOLUSD"]) for h in (0.5, 1, 1.5, 2)]
    broker = NewsBroker(news, bars={"SOL/USD": bars, "BTC/USD": make_bars(seed=2)})
    return pipeline.run(cfg, broker, NO_AI, Store(tmp_path, "aggressive"), now=NOW, dry_run=True)


def test_early_watch_off_changes_nothing_but_the_radar_still_reports(tmp_path):
    res = _hot_sol(tmp_path, early_watch=False)
    assert res.candidates == []
    assert res.radar["coins"]["SOL"]["recent"] == 4
    text = report.render(res, Store(tmp_path, "aggressive"), True)
    assert "News radar (trends forming)" in text and "| SOL |" in text


def test_early_watch_lets_a_coin_with_hot_news_in_early(tmp_path):
    res = _hot_sol(tmp_path, early_watch=True)
    assert [c.symbol for c in res.candidates] == ["SOL/USD"]
    c = res.candidates[0]
    assert c.early and c.radar_score >= AGG["radar"]["early_min_score"]
    assert any("early watch" in n for n in res.notes)
