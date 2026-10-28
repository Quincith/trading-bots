from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tradebots import gold, lab


def bars(n=6000, seed=1, start=2000.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-06", periods=n, freq="30min", tz="UTC")
    idx = idx[idx.dayofweek < 5]
    close = start + np.cumsum(rng.normal(0, 3, len(idx)))
    opn = np.r_[start, close[:-1]]
    return pd.DataFrame({"open": opn, "high": np.maximum(opn, close) + 1, "low": np.minimum(opn, close) - 1,
                         "close": close, "spread": 0.0}, index=idx)


def selloff_then_bounce():
    """Flat, then a sharp 8-candle selloff, a bounce candle, and a rally."""
    idx = pd.date_range("2026-03-02 00:00", periods=80, freq="30min", tz="UTC")
    c = [2000.0] * 30 + [2000 - 6 * k for k in range(1, 9)] + [1955.0] + [1955 + 3 * k for k in range(1, 42)]
    o = [2000.0] + c[:-1]
    o[38] = 1950.0          # a hammer-like candle, then the next one closes above its high: the bounce
    df = pd.DataFrame({"open": o, "close": c}, index=idx)
    df["high"] = df[["open", "close"]].max(axis=1) + 0.5
    df["low"] = df[["open", "close"]].min(axis=1) - 0.5
    return df


def test_bounce_signal_buys_after_a_selloff_and_risks_about_one_percent():
    df = selloff_then_bounce()
    cfg = gold.config("bounce")
    sig = gold.signals(df, cfg["forex"])
    assert sig.sum() >= 1 and sig[39]
    assert not sig[:30].any()           # nothing while the price is flat
    r = gold.simulate(cfg, df, df.index[0].to_pydatetime(), df.index[-1].to_pydatetime())
    t = r.trades[0]
    assert t["opened"].startswith("2026-03-02T20:00")
    # about 1% of $100 at risk, and never more than 1x the account
    assert t["ctx"]["risk_usd"] <= 1.0001 and t["cost"] <= 100.0001
    assert t["exit"] in ("profit goal", "breakeven stop") and t["pnl"] > -0.01


def test_costs_only_make_it_worse_and_lab_check_runs():
    df = bars()
    eng = gold.GoldEngine(df, df.index[300].to_pydatetime(), df.index[-1].to_pydatetime())
    cfg = gold.config("bounce")
    free = lab.pct(eng.run(cfg, eng.start, eng.end, cost=0.0))
    paid = lab.pct(eng.run(cfg, eng.start, eng.end, cost=1.0))
    assert paid <= free
    v, text = lab.validate("fxcopy", eng, lab.Runner(eng, 1), cfg)
    assert len(v.checks) == 7 and "Strategy check" in text
    assert "Gold bounce: lab check" in gold.report(eng)


def test_trend_version_only_trades_in_uptrends():
    df = bars(seed=3)
    down = df.copy()
    for k in ("open", "high", "low", "close"):
        down[k] = down[k] - np.linspace(0, 1500, len(down))   # a steady fall: no day is above its average
    eng = gold.GoldEngine(down, down.index[0].to_pydatetime(), down.index[-1].to_pydatetime())
    assert eng.run(gold.config("bounce_trend"), eng.start, eng.end).trades == []
