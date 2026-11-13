from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tradebots import basket, lab


def walk(n, seed=0, vol=0.015, drift=0.0004, end="2026-10-30"):
    idx = pd.date_range(end=end, periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + rng.normal(drift, vol, n))
    o = np.r_[100, c[:-1]] * (1 + rng.normal(0, vol / 5, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 1.0},
                        index=idx)


def data(n=2700):
    d = {s: walk(n, seed=i) for i, s in enumerate(basket.REEL + basket.YARDSTICKS)}
    d["USAR"] = d["USAR"].iloc[-400:]          # listed late, like the real one
    return d


def test_targets_never_look_ahead_and_sum_to_one():
    d = data()
    bars = basket.frame(d, sorted(basket.CORE + ["SPY"]))
    close = pd.DataFrame({s: bars[s]["close"] for s in bars})
    for style, h in basket.STYLES.items():
        later = close.copy()
        later.iloc[2000:] *= 1.5
        a, ra = basket.targets(close, h)
        b, rb = basket.targets(later, h)
        pd.testing.assert_frame_equal(a.iloc[:2000], b.iloc[:2000])
        pd.testing.assert_series_equal(ra.iloc[:2000], rb.iloc[:2000])
        if style == "basket":
            assert np.allclose(a.sum(axis=1).iloc[5:], 1.0)


def test_buy_and_hold_tracks_the_stocks_and_costs_cost_money():
    d = data()
    bars = basket.frame(d, sorted(basket.CORE + ["SPY"]))
    start, end = datetime(2018, 1, 1, tzinfo=timezone.utc), datetime(2026, 10, 1, tzinfo=timezone.utc)
    cfg = basket.config_for("basket")
    r = basket.simulate(cfg, bars, start, end)
    free = basket.simulate(cfg, bars, start, end, cost=0.0)
    assert free.equity[-1][1] > r.equity[-1][1] > 0
    assert r.fees > 0
    # with no rebalancing at all it's exactly the average of the three stocks' returns (before costs)
    cfg["hunt"]["rebalance_days"] = 10**6
    r = basket.simulate(cfg, bars, start, end, cost=0.0)
    ix = bars["SPY"].index
    first = ix[(ix >= pd.Timestamp(start)) & (ix < pd.Timestamp(end))]
    t0, t1 = first[1], first[-1]
    expect = np.mean([bars[s]["close"][t1] / bars[s]["open"][t0] for s in basket.CORE]) * 100
    assert abs(r.equity[-1][1] - expect) < 0.01


def test_the_full_report_runs():
    d = data()
    start, end = datetime(2017, 1, 1, tzinfo=timezone.utc), datetime(2026, 10, 30, tzinfo=timezone.utc)
    text = basket.report(d, start, end)
    assert "Lab check" in text and "Did buying a 20% dip" in text and "All four" in text
    assert all(k.path.startswith("hunt.") for k in lab.HUNT_KNOBS["basket_trend"])
