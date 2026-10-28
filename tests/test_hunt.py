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
