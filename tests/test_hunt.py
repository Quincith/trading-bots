from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tradebots import hunt, lab


def walk(n, seed=0, vol=0.01, drift=0.0005, freq="B", end="2026-10-01"):
    idx = pd.date_range(end=end, periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, vol, n))
    o = np.r_[100, c[:-1]] * (1 + rng.normal(0, vol / 5, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c,
                         "volume": 1.0}, index=idx)


def stocks(n=1500):
    return {s: walk(n, seed=i) for i, s in enumerate(hunt.STOCKS)}


def test_targets_never_look_ahead():
    d = stocks()
    close = pd.DataFrame({s: d[s]["close"] for s in d})
    coins = {c: walk(900, seed=10 + i, freq="D", vol=0.04) for i, c in enumerate(hunt.STYLES["crypto_rotation"]["coins"])}
    cclose = pd.DataFrame({c: coins[c]["close"] for c in coins})
    for style, h in hunt.STYLES.items():
        cl = cclose if style in hunt.CRYPTO_STYLES else close
        cut = len(cl) - 200
        later = cl.copy()
        later.iloc[cut:] *= 1.7
        a, b = hunt.targets(cl, h), hunt.targets(later, h)
        pd.testing.assert_frame_equal(a.iloc[:cut], b.iloc[:cut], obj=style)


def test_every_rule_runs_through_the_lab_and_costs_cost_money():
    d = stocks()
    coins = {c: walk(1100, seed=10 + i, freq="D", vol=0.04) for i, c in enumerate(hunt.STYLES["crypto_rotation"]["coins"])}
    start, end = datetime(2022, 1, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    for style, eng in hunt.engines({"stocks": d, "crypto": coins}, start, end).items():
        cfg = hunt.check_config(style) if style in hunt.CHECKS else hunt.config_for(style)
        free, paid = eng.run(cfg, eng.start, eng.end, 0.0), eng.run(cfg, eng.start, eng.end, 1.0)
        assert free.trades, style
        assert paid.equity[-1][1] < free.equity[-1][1], style
        assert paid.fees > 0
        v, text = lab.validate("aggressive", eng, lab.Runner(eng, workers=1), cfg)
        assert len(v.checks) == 7 and "Strategy check" in text


def test_trend_is_all_in_above_the_average_and_cash_below():
    d = stocks(600)
    q = d["QQQ"]
    q.loc[q.index[-100]:, ["open", "close"]] *= 0.5     # a crash puts QQQ far below its 200-day average
    close = pd.DataFrame({s: d[s]["close"] for s in d})
    w = hunt.targets(close, hunt.STYLES["lev_trend"])
    assert w["TQQQ"].iloc[-1] == 0 and set(w["TQQQ"].dropna().unique()) <= {0.0, 1.0}
    assert w.drop(columns="TQQQ").abs().sum().sum() == 0


class TrendBroker:
    """A paper account for the live trend rule: QQQ's daily closes and whatever the account holds."""

    def __init__(self, closes, positions=(), market_open=True, equity=100.0):
        self.closes, self.open, self.equity = closes, market_open, equity
        self.positions = list(positions)
        self.orders, self.closed = [], []

    def _data(self, path, params):
        days = pd.bdate_range(end="2026-10-27", periods=len(self.closes))
        return {"bars": {"QQQ": [{"t": f"{d:%Y-%m-%d}T04:00:00Z", "c": c} for d, c in zip(days, self.closes)]}}

    def get_account(self):
        return {"equity": self.equity, "buying_power": self.equity}

    def get_positions(self):
        return [p for p in self.positions if p["symbol"] not in self.closed]

    def is_market_open(self):
        return self.open

    def can_buy_fractional(self, symbol):
        return True

    def latest_price(self, symbol):
        return 50.0

    def buy_notional(self, symbol, usd, asset_class, client_order_id):
        self.orders.append((symbol, usd))

    def close_position(self, symbol):
        self.closed.append(symbol)


def pos(symbol, asset_class="stocks", value=90.0):
    return {"symbol": symbol, "asset_class": asset_class, "market_value": value, "current_price": 10.0,
            "avg_entry_price": 10.0, "qty": value / 10}


def live(broker, tmp_path, strategy="aggressive", **kw):
    from tradebots.store import Store
    cfg = hunt.bt.load_config(strategy)
    now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
    return cfg, hunt.run_live(cfg, broker, Store(tmp_path, strategy), now=now, **kw)


def test_live_rule_buys_the_fund_in_an_uptrend_and_sells_leftover_coins(tmp_path):
    b = TrendBroker(list(np.linspace(100, 200, 260)), [pos("BTCUSD", "crypto", 40.0)])
    cfg, res = live(b, tmp_path)
    assert b.closed == ["BTCUSD"]
    assert b.orders == [("TQQQ", 98.0)] and res.buys
    assert cfg["trend"]["hold"] == "TQQQ" and hunt.bt.load_config("medium")["trend"]["hold"] == "QLD"


def test_live_rule_sells_the_fund_below_the_average_and_waits_while_closed(tmp_path):
    down = list(np.linspace(200, 100, 260))
    b = TrendBroker(down, [pos("TQQQ")])
    live(b, tmp_path)
    assert b.closed == ["TQQQ"] and not b.orders
    b = TrendBroker(down, [pos("TQQQ")], market_open=False)
    _, res = live(b, tmp_path)
    assert not b.closed and any("when the stock market opens" in n for n in res.notes)


def test_live_rule_respects_the_kill_switch_and_dry_run(tmp_path):
    up = list(np.linspace(100, 200, 260))
    b = TrendBroker(up)
    live(b, tmp_path, kill_switch=True)
    assert not b.orders
    b = TrendBroker(up)
    _, res = live(b, tmp_path, dry_run=True)
    assert not b.orders and res.buys


def test_a_live_trend_run_shows_in_the_report_and_bot_world(tmp_path):
    from tradebots import report, runlog, world
    from tradebots.store import Store
    b = TrendBroker(list(np.linspace(100, 200, 260)))
    cfg, res = live(b, tmp_path)
    store = Store(tmp_path, "aggressive")
    runlog.save(res, store, False)
    assert "BUY TQQQ" in report.render(res, store, False)
    d = world.strategy_data(store, cfg)
    assert d["title"].startswith("Leveraged Nasdaq trend") and "TQQQ" in d["rules"]
    assert d["stations"]["scout"]["status"] == "found" and d["stations"]["decision"]["status"] == "buy"
