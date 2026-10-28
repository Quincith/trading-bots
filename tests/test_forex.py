from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

from tradebots import forex, fxdata, lab, runlog, weekly, world
from tradebots.__main__ import ROOT
from tradebots.store import Store

FX = yaml.safe_load((ROOT / "config/forex.yaml").read_text())
COPY = yaml.safe_load((ROOT / "config/fxcopy.yaml").read_text())


def daily(n=600, drift=0.0, seed=0, start=1.10, vol=0.005, end="2026-10-26"):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start * np.cumprod(1 + rets)
    idx = pd.date_range(end=end, periods=n, freq="D", tz="UTC")
    opn = np.r_[start, close[:-1]]
    return pd.DataFrame({"open": opn, "high": np.maximum(opn, close) * 1.002, "low": np.minimum(opn, close) * 0.998,
                         "close": close, "spread": 0.00008, "volume": 1000}, index=idx)


def test_sizing_risks_about_one_percent_and_respects_limits():
    units, note = forex.size("EUR_USD", 1, 1.10, 0.006, 100.0, [], FX["forex"], FX["risk"])
    # 1% of $100 = $1 at risk; stop 2 x 0.006 = 0.012 away -> about 83 units
    assert units == 83 and "risking $1.00" in note
    # USD/JPY: profit is in yen, so the size is converted with the price
    u2, _ = forex.size("USD_JPY", -1, 150.0, 0.9, 100.0, [], FX["forex"], FX["risk"])
    assert abs(u2 * 1.8 / 150 - 1) < 0.05
    # three trades all betting the dollar falls: a fourth one is the same bet again
    held = [{"pair": p, "direction": 1, "notional": 50} for p in ("EUR_USD", "GBP_USD", "AUD_USD")]
    assert forex.size("NZD_USD", 1, 0.6, 0.004, 100.0, held, FX["forex"], FX["risk"])[0] == 0
    # but betting the dollar rises is fine
    assert forex.size("USD_CAD", 1, 1.36, 0.006, 100.0, held, FX["forex"], FX["risk"])[0] > 0
    # the leverage cap: a tiny stop can't make a trade bigger than the whole account
    u3, n3 = forex.size("EUR_USD", 1, 1.10, 0.0001, 100.0, [], FX["forex"], FX["risk"])
    assert forex.notional_usd("EUR_USD", u3, 1.10) <= 100.0 and "capped" in n3


def test_trend_rule_buys_breakouts_and_sells_breakdowns():
    up = forex.trend_table(daily(drift=0.002, seed=1), FX["forex"])
    s = forex.trend_signal("EUR_USD", up.iloc[-1], FX["forex"])
    assert s.direction in (0, 1) and not s.exit_long
    down = forex.trend_table(daily(drift=-0.002, seed=1), FX["forex"])
    s2 = forex.trend_signal("EUR_USD", down.iloc[-1], FX["forex"])
    assert s2.direction in (0, -1) and not s2.exit_short
    # a fresh 55-day high in an uptrend is a buy
    df = daily(drift=0.0, seed=3)
    df.iloc[-1, df.columns.get_loc("close")] = df["high"].iloc[-60:-1].max() * 1.01
    df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1]
    t = forex.trend_table(df, dict(FX["forex"], trend_ema_days=0))
    assert forex.trend_signal("EUR_USD", t.iloc[-1], dict(FX["forex"], trend_ema_days=0)).direction == 1


def cot_rows(ccy_net: dict[str, list[float]], start="2026-01-06"):
    rows = []
    for ccy, nets in ccy_net.items():
        for i, n in enumerate(nets):
            day = pd.Timestamp(start) + pd.Timedelta(weeks=i)
            rows.append({"cftc_contract_market_code": fxdata.COT_CODES[ccy], "report_date_as_yyyy_mm_dd": f"{day:%Y-%m-%d}T00:00:00.000",
                         "open_interest_all": "1000", "lev_money_positions_long": str(500 + n * 5),
                         "lev_money_positions_short": str(500 - n * 5), "asset_mgr_positions_long": "0",
                         "asset_mgr_positions_short": "0"})
    return fxdata.cot_frame(rows)


def test_cot_copy_rule_and_release_delay():
    cot = cot_rows({"JPY": [5, 20], "EUR": [-15, -15]})
    tue = pd.Timestamp("2026-01-13", tz="UTC")
    # Tuesday's report isn't public until Friday evening: on Thursday we still see the week before
    assert fxdata.cot_as_of(cot, (tue + pd.Timedelta(days=2)).to_pydatetime())["JPY"]["leveraged"] == 5
    now = fxdata.cot_as_of(cot, (tue + pd.Timedelta(days=4)).to_pydatetime())
    assert now["JPY"]["leveraged"] == 20 and now["JPY"]["leveraged_prev"] == 5
    # funds long yen = betting USD/JPY falls, so Copycat FX sells USD/JPY
    s = forex.cot_signal("USD_JPY", 150.0, 0.9, now, COPY["forex"])
    assert s.direction == -1 and "Copy: sell USD/JPY" in s.note and s.exit_long and not s.exit_short
    assert forex.cot_signal("EUR_USD", 1.1, 0.006, now, COPY["forex"]).direction == -1


def test_simulation_charges_costs_and_respects_stops():
    bars = {p: daily(n=900, drift=0.0015 if i % 2 else -0.0015, seed=i, start=150 if "JPY" in p else 1.1)
            for i, p in enumerate(forex.PAIRS)}
    start, end = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    r = forex.simulate(FX, bars, None, start, end)
    assert r.trades and r.fees > 0
    # trending markets: the trend rule should make money here, and paying double costs should earn less
    r2 = forex.simulate(FX, bars, None, start, end, cost=2.0)
    assert r.equity[-1][1] > 100 and r2.equity[-1][1] < r.equity[-1][1]
    # no trade ever loses much more than the 1% it risked (gaps aside, these test prices have none)
    assert min(t["pnl"] / t["equity_at_open"] for t in r.trades) > -0.02
    flat = forex.FxEngine(bars, None, start, end)
    assert lab.pct(flat.benchmark(start, end)) == 0


def test_validate_and_knobs(tmp_path):
    bars = {p: daily(n=1200, drift=0.001 if i % 2 else -0.001, seed=i, start=150 if "JPY" in p else 1.1)
            for i, p in enumerate(forex.PAIRS)}
    eng = forex.FxEngine(bars, None, datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc))
    v, text = lab.validate("forex", eng, lab.Runner(eng, 1), FX)
    assert "Strategy check: Forex" in text and len(v.checks) == 7 and len(v.numbers["nudges"]) == 8
    changes, problems = lab.clean_changes("forex", FX, {"forex.entry_days": 41})
    assert changes == {"forex.entry_days": 40} and not problems


class FakeOanda:
    def __init__(self, bars, nav=100000.0):
        self.bars, self.nav, self.orders, self.trades, self.closed = bars, nav, [], [], []

    def get_account(self):
        return {"nav": self.nav, "balance": self.nav, "unrealized": 0.0, "currency": "USD"}

    def open_trades(self):
        return [t for t in self.trades if t["id"] not in self.closed]

    def daily_bars(self, pair, count):
        return self.bars.get(pair, pd.DataFrame()).tail(count)

    def market_order(self, pair, units, stop, tag):
        self.orders.append((pair, units, stop))
        tid = str(len(self.orders))
        self.trades.append({"id": tid, "pair": pair, "units": units, "price": 1.0, "unrealized": 0.0, "opened": "", "stop": stop})
        return {"filled": True, "price": float(self.bars[pair]["close"].iloc[-1]), "trade_id": tid, "reason": ""}

    def close_trade(self, tid):
        self.closed.append(tid)
        return {"price": 1.0, "pl": 0.5}

    def closed_trade(self, tid):
        return {"price": 1.0, "pl": -1.0, "closed": ""}


def breakout_bars():
    out = {}
    for i, p in enumerate(forex.PAIRS):
        df = daily(n=300, drift=0.001, seed=i, start=150 if "JPY" in p else 1.1)
        df.iloc[-1, df.columns.get_loc("close")] = df["high"].iloc[-60:-1].max() * 1.01
        df.iloc[-1, df.columns.get_loc("high")] = df["close"].iloc[-1]
        out[p] = df
    return out


def test_live_run_trades_once_a_day_with_a_virtual_100(tmp_path):
    broker = FakeOanda(breakout_bars())
    store = Store(tmp_path, "forex")
    now = datetime(2026, 10, 27, 21, 30, tzinfo=timezone.utc)
    res = forex.run(FX, broker, store, now=now)
    assert store.net_deposits() == 100 and res.equity == 100     # $100,000 practice account, counted as $100
    assert res.scanned and broker.orders and len(broker.orders) <= FX["risk"]["max_open_positions"]
    assert all(abs(u) < 1000 for _, u, _ in broker.orders)      # micro-sized for $100, not for $100,000
    runlog.save(res, store, False)
    # 30 minutes later: same finished day, so nothing new
    n = len(broker.orders)
    res2 = forex.run(FX, broker, store, now=now + timedelta(minutes=30))
    assert not res2.scanned and len(broker.orders) == n and res2.forex["pairs"]
    # OANDA's stop closes a trade by itself: the next run notices and logs it
    broker.closed.append(broker.trades[0]["id"])
    broker.nav -= 1
    res3 = forex.run(FX, broker, store, now=now + timedelta(hours=1))
    assert res3.exits and res3.exits[0].startswith("SOLD") and abs(res3.equity - 99) < 1e-9
    assert "Today's read on each pair" in forex.render(res, store, FX, False)


def test_world_and_weekly_include_the_forex_wing(tmp_path):
    broker = FakeOanda(breakout_bars())
    now = datetime(2026, 10, 27, 21, 30, tzinfo=timezone.utc)
    for cfg in (FX, COPY):
        store = Store(tmp_path, cfg["name"])
        cot = lambda since: cot_rows({"EUR": [12, 15], "JPY": [-20, -25]}, start="2026-10-13")
        res = forex.run(cfg, broker, store, now=now, cot_source=cot)
        runlog.save(res, store, False)
    html = world.build(tmp_path, tmp_path / "site", now=now).read_text()
    assert '"fxcopy"' in html and "FOREX WING" in html
    data = world.strategy_data(Store(tmp_path, "fxcopy"), COPY)
    assert [c["id"] for c in data["crew"]] == ["scout", "risk", "decision"]
    assert "hedge funds" in data["stations"]["scout"]["say"].lower()
    stats = {n: weekly.strategy_stats(Store(tmp_path, n), now, lambda t: 1.0) for n in ("forex", "fxcopy")}
    text = weekly.render(stats, now, titles={"forex": "Forex", "fxcopy": "Copycat FX"})
    assert "## Copycat FX" in text and "Doing nothing" in text


def test_switched_off_office_does_not_trade(tmp_path, monkeypatch):
    from tradebots import __main__ as cli
    broker = FakeOanda(breakout_bars())
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr(cli, "broker_for", lambda cfg: broker)
    assert FX["enabled"] is False and COPY["enabled"] is False
    assert cli.main(["run", "--strategy", "forex"]) == 0
    assert not broker.orders and not (tmp_path / "forex" / "summary.md").exists()
