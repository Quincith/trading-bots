import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tradebots import warning as w
from tests.test_hunt import walk


def market(n=1500):
    return {s: walk(n, seed=i) for i, s in enumerate(w.MARKET + w.FUNDS)}


def macro_for(idx, seed=0):
    rng = np.random.default_rng(seed)
    vix = 15 + np.abs(np.cumsum(rng.normal(0, 1, len(idx)))) % 30
    return pd.DataFrame({"vix": vix, "vix3m": vix * 1.05 + rng.normal(0, 2, len(idx)),
                         "oil": 70 * np.cumprod(1 + rng.normal(0, 0.02, len(idx))),
                         "y2": 3 + np.cumsum(rng.normal(0, 0.03, len(idx)))}, index=idx)


def test_lights_never_look_ahead_and_score_counts_them():
    d = market()
    close = pd.DataFrame({s: d[s]["close"] for s in d})
    macro = macro_for(close.index)
    cut = len(close) - 200
    later_c, later_m = close.copy(), macro.copy()
    later_c.iloc[cut:] *= 0.6
    later_m.iloc[cut:] *= 1.8
    a, b = w.lights(close, macro), w.lights(later_c, later_m)
    pd.testing.assert_frame_equal(a.iloc[:cut], b.iloc[:cut])
    assert (a["score"] == a[list(w.LIGHTS)].sum(axis=1)).all()
    assert w.level(0) == "CALM" and w.level(3) == "CAUTION" and w.level(4) == "DANGER"


def test_each_light_fires_on_its_own_trouble():
    idx = pd.date_range(end="2026-10-01", periods=300, freq="B", tz="UTC")
    flat = pd.DataFrame({s: 100.0 for s in w.MARKET}, index=idx)
    calm = pd.DataFrame({"vix": 14.0, "vix3m": 16.0, "oil": 70.0, "y2": 3.0}, index=idx)
    assert w.lights(flat, calm)["score"].iloc[-1] == 0
    stress = calm.copy()
    stress.iloc[-1] = [32.0, 28.0, 90.0, 3.0]
    stress.iloc[-10:, 3] = 3.8
    c2 = flat.copy()
    c2.iloc[-1] = [90.0, 100.0, 96.0, 95.0, 100.0]     # QQQ cracks, average stock lags, junk bonds slip
    last = w.lights(c2, stress).iloc[-1]
    assert all(last[k] for k in w.LIGHTS) and last["score"] == 7


def test_overlay_only_shrinks_the_trend_position_and_runs_through_the_checks():
    d = market()
    close = pd.DataFrame({s: d[s]["close"] for s in d})
    macro = w.align(macro_for(close.index), close.index)
    lit = w.lights(close, macro)
    start, end = datetime(2022, 1, 1, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc)
    eng = w.WarnEngine(w.frame(d, ["QQQ", "TQQQ"]), lit, macro, start, end)
    base = w.base_config("aggressive")
    for name in w.OVERLAYS:
        s = w.scale(lit, macro, w.with_overlay(base, name)["hunt"]["overlay"])
        assert set(s.unique()) <= {0.0, 0.5, 1.0}
        kept, checks, n = w.judge(eng, base, name)
        assert len(checks) == 6 and n["trades_new"] >= 0
    text = w.test(d, macro_for(close.index), start, end)
    assert "Did the lights come on" in text and "Medium (QLD)" in text


def test_episodes_find_a_ten_percent_fall():
    idx = pd.date_range("2026-01-01", periods=8, freq="B", tz="UTC")
    q = pd.Series([100, 105, 99, 94, 90, 97, 106, 104], index=idx, dtype=float)
    (e,) = w.episodes(q)
    assert e["peak"] == idx[1] and e["cross"] == idx[3] and e["bottom"] == idx[4] and e["recovered"] == idx[6]


def test_live_check_saves_lights_and_alerts_only_when_the_level_rises(tmp_path, monkeypatch):
    d = market(400)
    idx = d["QQQ"].index
    macro = macro_for(idx)
    monkeypatch.setattr(w.hunt, "daily_closes", lambda b, s, n, now: d[s]["close"].set_axis(idx.date))
    monkeypatch.setattr(w, "fetch_fred", lambda start, session=None: macro)
    monkeypatch.setattr(w, "lights", lambda c, m: pd.DataFrame({**{k: [True] * len(c) for k in w.LIGHTS}, "score": 7}, index=c.index))
    now = datetime(2026, 10, 30, 21, tzinfo=timezone.utc)
    out = w.run_live(tmp_path, now, broker=object())
    assert out["level"] == "DANGER" and (tmp_path / "warning" / "alert.md").exists()
    assert json.loads((tmp_path / "warning" / "latest.json").read_text())["score"] == 7
    assert w.run_live(tmp_path, now, broker=object()) is None          # looked less than 3 hours ago
    assert not (tmp_path / "warning" / "alert.md").exists()
    later = datetime(2026, 10, 31, 3, tzinfo=timezone.utc)
    assert w.run_live(tmp_path, later, broker=object())["level"] == "DANGER"
    assert not (tmp_path / "warning" / "alert.md").exists()            # still DANGER: no second alert
    assert len((tmp_path / "warning" / "history.csv").read_text().splitlines()) == 2
