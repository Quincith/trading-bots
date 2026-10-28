from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tradebots import lab, playbook as pbk


def walk(freq, n, seed=0, vol=0.01, drift=0.0, end="2026-10-01"):
    idx = pd.date_range(end=end, periods=n, freq=freq, tz="UTC")
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, vol, n))
    o = np.r_[100, c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * (1 + vol / 2), "low": np.minimum(o, c) * (1 - vol / 2),
                         "close": c, "volume": rng.lognormal(0, 0.6, n)}, index=idx)


def test_signals_never_look_ahead():
    """Changing the future must not change any signal decided before it."""
    for style, freq, n in (("trend", "1D", 700), ("breakout", "1D", 400), ("swing", "4h", 1500),
                           ("daytrade", "15min", 2000), ("scalp", "5min", 3000)):
        df = walk(freq, n, seed=1, vol=0.02 if freq == "1D" else 0.004)
        cut = n - 200
        later = df.copy()
        later.iloc[cut:, :4] *= 1.5
        a, b = pbk.signals(df, pbk.STYLES[style]), pbk.signals(later, pbk.STYLES[style])
        pd.testing.assert_frame_equal(a.iloc[:cut], b.iloc[:cut], check_exact=False, obj=style)


def test_breakout_buys_a_new_high_on_volume_and_sells_a_new_low():
    df = walk("1D", 60, vol=0.001)
    df.iloc[40, df.columns.get_loc("close")] = 120
    df.iloc[40, df.columns.get_loc("high")] = 121
    df.iloc[40, df.columns.get_loc("volume")] = 50
    df.iloc[50, df.columns.get_loc("close")] = 80
    s = pbk.signals(df, pbk.STYLES["breakout"])
    assert s["enter"].iloc[40] and not s["enter"].iloc[39]
    assert s["exit"].iloc[50]


def test_day_trades_are_closed_by_the_end_of_the_day_and_sizing_follows_the_account():
    bars = {"15Min": pbk.grid({c: walk("15min", 96 * 60, seed=i, vol=0.004) for i, c in
                               enumerate(["BTC/USD", "ETH/USD", "SOL/USD"])}, "15Min")}
    bars["1Day"] = {"BTC/USD": walk("1D", 80)}
    eng = pbk.PlaybookEngine(bars, datetime(2026, 8, 5, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc))
    for strategy in ("aggressive", "medium"):
        cfg = pbk.config_for(strategy, "daytrade")
        cfg["markets"]["crypto"] = ["BTC/USD", "ETH/USD", "SOL/USD"]
        r = eng.run(cfg, eng.start, eng.end, cost=0.0)
        assert r.trades
        for t in r.trades:
            o, c = datetime.fromisoformat(t["opened"]), datetime.fromisoformat(t["closed"])
            assert o.date() == c.date() and t["exit"] in ("stop hit", "end of day")
            assert t["cost"] <= cfg["risk"]["max_position_pct"] / 100 * t["equity_at_open"] + 1e-9


def test_the_lab_can_check_a_playbook_rule():
    bars = {"1Day": pbk.grid({c: walk("1D", 1500, seed=i, vol=0.03) for i, c in
                              enumerate(["BTC/USD", "ETH/USD"])}, "1Day")}
    eng = pbk.PlaybookEngine(bars, datetime(2023, 1, 1, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc),
                             min_trades=pbk.MIN_TRADES["breakout"])
    cfg = pbk.config_for("medium", "breakout")
    cfg["markets"]["crypto"] = ["BTC/USD", "ETH/USD"]
    assert [k.path for k in lab.knobs_for("medium", cfg)][0] == "playbook.entry_days"
    v, text = lab.validate("medium", eng, lab.Runner(eng, workers=1), cfg)
    assert "Strategy check: Medium: Breakout" in text and len(v.numbers["nudges"]) == 8
