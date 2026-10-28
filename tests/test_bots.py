from datetime import datetime, timedelta, timezone

import yaml
from conftest import FakeBroker, make_bars

from tradebots import pipeline
from tradebots.__main__ import ROOT
from tradebots.ai import AI
from tradebots.bots import charts, risk, scout
from tradebots.models import Plan
from tradebots.store import Store

AGG = yaml.safe_load((ROOT / "config/aggressive.yaml").read_text())
MED = yaml.safe_load((ROOT / "config/medium.yaml").read_text())
NO_AI = AI("claude-opus-5-5", api_key="")


def test_configs_have_same_shape():
    def keys(d, p=""):
        return {p + k for k, v in d.items()} | {x for k, v in d.items() if isinstance(v, dict) for x in keys(v, p + k + ".")}
    assert keys(AGG) == keys(MED)


def test_scout_finds_only_the_surging_coin():
    bars = {"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1), "BTC/USD": make_bars(seed=2)}
    found = scout.scan(bars, "crypto", AGG["scout"])
    assert [c.symbol for c in found] == ["SOL/USD"]
    assert found[0].volume_ratio > 1.5


def test_chart_plan_is_sane():
    c = scout.scan({"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1)}, "crypto", AGG["scout"])[0]
    plan = charts.make_plan(c, AGG["charts"])
    assert plan and plan.stop < plan.entry < plan.target
    assert plan.reward_risk >= AGG["charts"]["min_reward_risk"] - 1e-9


def _cand(stop_pct=5.0):
    c = scout.Candidate(symbol="SOL/USD", asset_class="crypto", bars=make_bars(seed=3), price=100)
    c.plan = Plan("up", 95, 115, 100, 100 - stop_pct, 110)
    return c


def test_risk_sizes_from_stop_distance():
    c = _cand(stop_pct=10)      # 10% stop, 2% risk -> 20% position on $1000
    risk.review(c, 1000, 1000, [], {}, MED["risk"])
    assert c.risk_verdict == "APPROVE" and abs(c.size_usd - 200) < 0.01


def test_risk_caps_position_size():
    c = _cand(stop_pct=2)       # 7.5% risk / 2% stop = 375% -> capped at 40%
    risk.review(c, 100, 100, [], {}, AGG["risk"])
    assert c.risk_verdict == "REDUCE" and abs(c.size_usd - 40) < 0.01


def test_risk_shrinks_or_rejects_correlated():
    c = _cand(stop_pct=10)
    held = [{"symbol": "ETHUSD", "market_value": 10, "asset_class": "crypto"}]
    twin = c.bars.copy()
    risk.review(c, 1000, 1000, held, {"ETHUSD": twin}, AGG["risk"])
    assert c.risk_verdict == "REDUCE" and "moves with ETHUSD" in c.risk_note
    risk.review(c, 1000, 1000, held, {"ETHUSD": twin}, MED["risk"])   # medium allows 0 correlated
    assert c.risk_verdict == "REJECT"


def test_account_gate_limits():
    cfg = MED["risk"]
    assert risk.account_gate(100, 100, 100, True, None, cfg).allowed is False
    assert risk.account_gate(96, 100, 100, False, None, cfg).allowed is False          # -4% today
    g = risk.account_gate(49, 49, 100, False, None, cfg)                                # -51% total (limit 50%)
    assert not g.allowed and g.halt_strategy
    assert risk.account_gate(99, 100, 100, False, None, cfg).allowed


def test_deposits_do_not_count_as_profit(tmp_path):
    s = Store(tmp_path, "t")
    t = datetime(2026, 10, 24, tzinfo=timezone.utc)
    s.add_deposit(100, "start", t)
    s.append("equity.csv", {"time": "1", "equity": "100", "net_deposits": "100"})
    s.append("equity.csv", {"time": "2", "equity": "110", "net_deposits": "100"})   # +10% from trading
    s.add_deposit(100, "top up", t)
    s.append("equity.csv", {"time": "3", "equity": "210", "net_deposits": "200"})   # deposit, flat trading
    p = s.performance()
    assert abs(p["profit"] - 10) < 1e-9
    assert abs(p["twr_pct"] - 10) < 1e-9


def test_full_run_buys_then_exits(tmp_path):
    broker = FakeBroker(equity=100, bars={"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1),
                                          "BTC/USD": make_bars(seed=2)})
    store = Store(tmp_path, "aggressive")
    t0 = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    res = pipeline.run(AGG, broker, NO_AI, store, now=t0)
    assert store.net_deposits() == 100            # starting balance auto-recorded
    assert [c.symbol for c in res.candidates] == ["SOL/USD"]
    c = res.candidates[0]
    assert c.news_score > 0                       # rule-based news picked up the ETF headline
    if c.decision == "BUY":
        assert broker.orders and broker.orders[0][0] == "SOL/USD"
        plan = store.state["plans"]["SOLUSD"]
        broker.positions = [{"symbol": "SOLUSD", "qty": 1, "market_value": 30, "avg_entry_price": plan["entry"],
                             "current_price": plan["stop"] * 0.99, "asset_class": "crypto"}]
        res2 = pipeline.run(AGG, broker, NO_AI, store, now=t0 + timedelta(hours=1))
        assert broker.closed == ["SOLUSD"] and "stop hit" in res2.exits[0]


def test_kill_switch_blocks_buys(tmp_path):
    broker = FakeBroker(equity=100, bars={"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1)})
    res = pipeline.run(AGG, broker, NO_AI, Store(tmp_path, "aggressive"), kill_switch=True)
    assert not broker.orders and "Kill switch" in res.gate


def test_time_limit_exit(tmp_path):
    store = Store(tmp_path, "medium")
    t0 = datetime(2026, 10, 24, tzinfo=timezone.utc)
    store.state["plans"]["ETHUSD"] = {"symbol": "ETHUSD", "asset_class": "crypto", "entry": 100, "stop": 90,
                                      "target": 130, "opened_at": t0.isoformat()}
    broker = FakeBroker(positions=[{"symbol": "ETHUSD", "qty": 1, "market_value": 101, "avg_entry_price": 100,
                                    "current_price": 101, "asset_class": "crypto"}])
    res = pipeline.run(MED, broker, NO_AI, store, now=t0 + timedelta(hours=121))
    assert broker.closed == ["ETHUSD"] and "limit" in res.exits[0]


def test_alpaca_parses_bars_and_positions():
    from tradebots.alpaca import AlpacaPaper

    class Resp:
        def __init__(self, data):
            self.status_code, self._d, self.content = 200, data, b"x"

        def json(self):
            return self._d

    class Session:
        headers = {}

        def request(self, method, url, **kw):
            if "bars" in url:
                bar = {"t": "2026-10-24T00:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}
                return Resp({"bars": {"BTC/USD": [bar, bar]}, "next_page_token": None})
            return Resp([{"symbol": "BTCUSD", "qty": "0.001", "market_value": "60", "avg_entry_price": "59000",
                          "current_price": "60000", "asset_class": "crypto"}])

    a = AlpacaPaper("k", "s", session=Session())
    df = a.get_bars(["BTC/USD"], "15Min", 100, "crypto")["BTC/USD"]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"] and df["close"].iloc[-1] == 1.5
    assert a.get_positions()[0]["symbol"] == "BTCUSD"


def test_ai_check_without_key():
    assert "not set" in NO_AI.check()


def test_weekly_report_nets_out_deposits_and_compares_to_bitcoin(tmp_path):
    from tradebots import weekly
    s = Store(tmp_path, "medium")
    t0 = datetime(2026, 10, 18, tzinfo=timezone.utc)
    s.add_deposit(100, "start", t0)
    s.append("equity.csv", {"time": t0.isoformat(), "equity": "100.00", "net_deposits": "100.00"})
    s.add_deposit(50, "top up", t0 + timedelta(days=3))
    s.append("equity.csv", {"time": (t0 + timedelta(days=3)).isoformat(), "equity": "160.00", "net_deposits": "150.00"})
    s.append("equity.csv", {"time": (t0 + timedelta(days=7)).isoformat(), "equity": "160.00", "net_deposits": "150.00"})
    btc = lambda when: 100.0 if when < t0 + timedelta(days=3) else 120.0   # Bitcoin up 20% mid-week
    st = weekly.strategy_stats(s, t0 + timedelta(days=7), btc)
    assert abs(st["week_profit"] - 10) < 1e-9          # the $50 deposit is not profit
    assert abs(st["week_pct"] - 10) < 1e-9             # 100 -> 110 before the deposit, flat after
    assert abs(st["btc_week_pct"] - 20) < 1e-9
    assert abs(st["btc_value"] - 170) < 1e-9           # $100 bought at 100, $50 bought at 120
    text = weekly.render({"medium": st, "aggressive": None}, t0 + timedelta(days=7))
    assert "trailed Bitcoin by 10.0 points" in text and "No runs recorded yet" in text


def test_bitcoin_price_lookup_uses_last_close_before_the_time():
    from tradebots import weekly
    bars = make_bars(seed=4)
    at = weekly.btc_prices(FakeBroker(bars={"BTC/USD": bars}), bars.index[0])
    assert at(bars.index[10] + timedelta(minutes=5)) == bars["close"].iloc[10]
    assert at(bars.index[0] - timedelta(days=1)) == bars["close"].iloc[0]
