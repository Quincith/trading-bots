from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from tradebots import backtest as bt
from tradebots.ai import AI
from tradebots.models import Plan

COINS = ["BTC/USD", "ETH/USD", "SOL/USD", "AVAX/USD", "LINK/USD", "DOGE/USD", "LTC/USD", "XRP/USD"]


def synth_history(days=25, seed=0):
    """Random-walk candles for the 8 coins, with a few volume-backed rallies for Scout to find."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-07-01", periods=days * 96, freq="15min", tz="UTC")
    b15, b1h = {}, {}
    for s in COINS:
        r, v = rng.normal(0.0001, 0.004, len(idx)), rng.uniform(900, 1100, len(idx))
        for j in rng.integers(100, len(idx) - 10, 25):
            r[j:j + 4], v[j:j + 2] = 0.006, 4000
        c = 100 * np.cumprod(1 + r)
        df = pd.DataFrame({"open": c / (1 + r), "high": c * 1.002, "low": c / (1 + r) * 0.998, "close": c,
                           "volume": v}, index=idx)
        b15[s] = df
        b1h[s] = df.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    news_items = [{"headline": "SOL ETF approval sparks record inflow", "summary": "", "symbols": ["SOLUSD"],
                   "created_at": "2026-07-10T12:00:00Z", "source": "test"}]
    return bt.History({"15Min": b15, "1Hour": b1h}, news_items, {"2026-07-10": 70})


@pytest.fixture(scope="module")
def hist():
    return synth_history()


START = datetime(2026, 7, 16, tzinfo=timezone.utc)
END = datetime(2026, 7, 24, tzinfo=timezone.utc)


def test_window_never_shows_future_candles(hist):
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    w = hist.window("15Min", "BTC/USD", now, 50)
    assert len(w) == 50 and w.index[-1] == pd.Timestamp("2026-07-10 11:45", tz="UTC")   # closed at 12:00
    w = hist.window("1Hour", "BTC/USD", now + timedelta(minutes=30), 10)
    assert w.index[-1] == pd.Timestamp("2026-07-10 11:00", tz="UTC")                     # 12:00 bar still open
    assert hist.price("BTC/USD", now) == w["close"].iloc[-1]


def test_news_and_fear_greed_by_time(hist):
    b = bt.SimBroker(hist, 100)
    b.now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    assert len(b.get_news(["SOL/USD"])) == 1 and b.get_news(["BTC/USD"]) == []
    b.now = datetime(2026, 7, 10, 11, tzinfo=timezone.utc)
    assert b.get_news(["SOL/USD"]) == []        # not published yet
    assert hist.fear_greed(datetime(2026, 7, 10, 5, tzinfo=timezone.utc)) == 70


def test_sim_broker_charges_fees_both_ways(hist):
    b = bt.SimBroker(hist, 100)
    b.now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    b.buy_notional("BTC/USD", 50, "crypto", "x")
    assert b.cash == 50 and b.equity() < 100
    b.close_position("BTCUSD")
    assert b.cash < 100 and b.round_trips[0]["pnl"] < 0          # same price, so fees + slippage are the loss
    assert abs(b.fees_paid - (50 * bt.FEE + (b.cash - 50) / (1 - bt.FEE) * bt.FEE)) < 1e-9


def test_simulate_and_benchmarks(hist):
    cfg = bt.load_config("aggressive")
    r = bt.simulate(cfg, hist, START, END)
    s = bt.stats(r, 100)
    assert len(r.equity) == (END - START) // bt.TICK + 1
    assert r.trades and r.events and s["fees"] > 0
    assert all(e.claude_calls >= 1 for e in r.events)
    hold = bt.stats(bt.buy_and_hold("hold_btc", hist, ["BTC/USD"], START, END), 100)
    p0, p1 = hist.price("BTC/USD", START), hist.price("BTC/USD", END)
    assert abs(hold["end_value"] - 100 * (1 - bt.FEE) / (1 + bt.SLIPPAGE) * p1 / p0) < 1e-6


def test_trade_outcome_stop_and_target(hist):
    cfg = bt.load_config("medium")
    t = datetime(2026, 7, 12, tzinfo=timezone.utc)
    px = hist.price("ETH/USD", t)
    stopped = bt.trade_outcome(hist, "ETH/USD", Plan("up", 0, 0, px, px * 0.9999, px * 10), t, cfg)
    assert stopped["exit"] in ("stop", "time limit") and stopped["return_pct"] < 1
    won = bt.trade_outcome(hist, "ETH/USD", Plan("up", 0, 0, px, px * 0.01, px * 1.0001), t, cfg)
    assert won["exit"] in ("target", "time limit")


class FakeAI(AI):
    """Answers like Claude would, so the model comparison can be tested offline."""

    def __init__(self, model, effort="low", api_key=None):
        super().__init__(model, effort, api_key="")
        self.model, self.live = model, api_key is None

    @property
    def enabled(self):
        return self.live

    def ask(self, system, prompt, schema):
        if not self.live:
            return None
        self.calls += 1
        self.input_tokens += 1000
        self.output_tokens += 200
        if "calls" in schema["properties"]:
            import json
            syms = [x["symbol"] for x in json.loads(prompt)]
            buy = self.model == "claude-opus-5-5"
            return {"calls": [{"symbol": s, "decision": "BUY" if buy else "SKIP", "confidence": 0.9, "reason": "t"}
                              for s in syms]}
        return None


def test_model_check_respects_budget_and_summarizes(hist, monkeypatch):
    monkeypatch.setattr(bt, "AI", FakeAI)
    cfgs = {s: bt.load_config(s) for s in ("aggressive", "medium")}
    events = bt.simulate(cfgs["aggressive"], hist, START, END).events + bt.simulate(cfgs["medium"], hist, START, END).events
    check = bt.compare_models(cfgs, hist, events, n=6, budget=1.0, ai_from=START)
    assert check["rows"] and check["spent"] <= 1.0
    m = bt.summarize_models(check)
    assert m["claude-haiku-5-5"]["trades_taken"] == 0 and m["claude-opus-5-5"]["trades_taken"] > 0
    per_call = bt.cost_usd("claude-opus-5-5", 1000, 200)
    assert abs(m["claude-opus-5-5"]["cost_per_call"] - per_call) < 1e-12
    assert 0 <= m["agreement_pct"] <= 100
    tiny = bt.compare_models(cfgs, hist, events, n=6, budget=0.0, ai_from=START)
    assert tiny["rows"] == [] and tiny["spent"] == 0


def test_cli_end_to_end(tmp_path, hist, monkeypatch):
    import pickle
    cache = tmp_path / "h.pkl"
    cache.write_bytes(pickle.dumps(hist))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "out"
    assert bt.main(["--days", "5", "--end", "2026-07-22", "--cache", str(cache), "--out", str(out)]) == 0
    text = (out / "summary.md").read_text()
    assert "Just hold Bitcoin" in text and "Did not run" in text
    assert (out / "daily_values.csv").exists() and (out / "results.json").exists()


def test_halted_strategy_also_runs_without_the_limit(tmp_path, hist, monkeypatch):
    import pickle
    real = bt.load_config

    def touchy(name):            # a "loss" limit that trips at once (any total below +1%)
        cfg = real(name)
        cfg["risk"]["max_total_loss_pct"] = -1
        return cfg

    monkeypatch.setattr(bt, "load_config", touchy)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cache = tmp_path / "h.pkl"
    cache.write_bytes(pickle.dumps(hist))
    bt.main(["--days", "5", "--end", "2026-07-22", "--cache", str(cache), "--out", str(tmp_path / "o")])
    text = (tmp_path / "o" / "summary.md").read_text()
    assert "hit its total loss limit" in text and "Aggressive, never stopped" in text
