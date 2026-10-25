from datetime import datetime, timedelta, timezone

import yaml
from conftest import FakeBroker, make_bars

from tradebots import pipeline, recap, runlog, world
from tradebots.__main__ import ROOT
from tradebots.ai import AI
from tradebots.store import Store

AGG = yaml.safe_load((ROOT / "config/aggressive.yaml").read_text())
MED = yaml.safe_load((ROOT / "config/medium.yaml").read_text())
NO_AI = AI("claude-opus-5-5", api_key="")


def _run_and_log(tmp_path, cfg, broker, now, dry=False):
    store = Store(tmp_path, cfg["name"])
    res = pipeline.run(cfg, broker, NO_AI, store, now=now, dry_run=dry)
    runlog.save(res, store, dry)
    return store, res


def test_run_log_records_what_each_bot_saw(tmp_path):
    broker = FakeBroker(equity=100, bars={"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1),
                                          "BTC/USD": make_bars(seed=2)})
    t0 = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    store, _ = _run_and_log(tmp_path, AGG, broker, t0)
    [rec] = runlog.load_day(store, "2026-10-24")
    assert rec["scanned"] and set(rec["scan"]) == {"SOL/USD", "BTC/USD"}
    assert rec["scan"]["SOL/USD"]["passed"] is True and rec["scan"]["BTC/USD"]["passed"] is False
    assert rec["candidates"][0]["symbol"] == "SOL/USD" and rec["candidates"][0]["decision"]
    assert rec["equity"] == 100 and rec["net_deposits"] == 100


def test_daily_recap_and_world_page(tmp_path):
    t0 = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    bars = {"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1), "BTC/USD": make_bars(seed=2)}
    store, res = _run_and_log(tmp_path, AGG, FakeBroker(equity=100, bars=bars), t0)
    _run_and_log(tmp_path, MED, FakeBroker(equity=100, bars={"BTC/USD": make_bars(seed=2)}), t0)
    # a quiet second run for aggressive where the account grew a little
    _run_and_log(tmp_path, AGG, FakeBroker(equity=101, bars={"BTC/USD": make_bars(seed=2)}), t0 + timedelta(minutes=30))

    r = recap.build(store, "2026-10-24")
    assert r["headline"].startswith("Aggressive: up $1.00")
    assert r["summary"] and r["bullets"] and all(t in recap.GLOSSARY for t in r["terms"])
    quiet = recap.build(Store(tmp_path, "medium"), "2026-10-24")
    assert quiet["summary"].startswith("Quiet day")

    page = world.build(tmp_path, tmp_path / "site", now=t0 + timedelta(hours=1))
    html = page.read_text()
    assert "/*__DATA__*/" not in html and '"aggressive"' in html and '"medium"' in html
    assert "/*__THREE__*/" not in html and "World3D" in html and "WebGLRenderer" in html
    assert (tmp_path / "recaps" / "2026-10-24.md").read_text().count("Key takeaways") == 2


def test_world_page_before_any_runs(tmp_path):
    html = world.build(tmp_path, tmp_path / "site").read_text()
    assert "Awaiting first run." in html


def test_recap_matches_sell_to_buy(tmp_path):
    s = Store(tmp_path, "t")
    s.append("trades.csv", {"time": "2026-10-24T01:00:00+00:00", "symbol": "SOL/USD", "side": "buy", "usd": "40",
                            "price": 100, "reason": "x"})
    s.append("trades.csv", {"time": "2026-10-24T05:00:00+00:00", "symbol": "SOLUSD", "side": "sell", "usd": "44",
                            "price": 110, "reason": "target hit (110 >= 110)"})
    [t] = recap.closed_trades(s)
    assert t["symbol"] == "SOL" and abs(t["pl"] - 4) < 1e-9
