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
        if w.OVERLAYS[name]["kind"] == "news":
            continue
        s = w.scale(lit, macro, w.with_overlay(base, name)["hunt"]["overlay"], close, pd.Series(1.0, index=close.index), "TQQQ")
        assert set(s.unique()) <= {0.0, 0.25, 0.5, 0.75, 1.0}
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
    monkeypatch.setattr(w, "lights", lambda c, m: pd.DataFrame({**{k: [False] * len(c) for k in w.LIGHTS}, "score": 0}, index=c.index))
    assert w.run_live(tmp_path, datetime(2026, 11, 2, tzinfo=timezone.utc), broker=object())["level"] == "CALM"
    monkeypatch.setattr(w, "lights", lambda c, m: pd.DataFrame({**{k: [True] * len(c) for k in w.LIGHTS}, "score": 7}, index=c.index))
    w.run_live(tmp_path, datetime(2026, 11, 3, tzinfo=timezone.utc), broker=object())
    assert not (tmp_path / "warning" / "alert.md").exists()            # DANGER again within 10 days: quiet
    w.run_live(tmp_path, datetime(2026, 11, 4, tzinfo=timezone.utc), broker=object())
    monkeypatch.setattr(w, "lights", lambda c, m: pd.DataFrame({**{k: [False] * len(c) for k in w.LIGHTS}, "score": 0}, index=c.index))
    w.run_live(tmp_path, datetime(2026, 11, 20, tzinfo=timezone.utc), broker=object())
    monkeypatch.setattr(w, "lights", lambda c, m: pd.DataFrame({**{k: [True] * len(c) for k in w.LIGHTS}, "score": 7}, index=c.index))
    w.run_live(tmp_path, datetime(2026, 11, 21, tzinfo=timezone.utc), broker=object())
    assert (tmp_path / "warning" / "alert.md").exists()                # a new DANGER after the quiet spell
    assert len((tmp_path / "warning" / "history.csv").read_text().splitlines()) == 2  # one row per close day


def test_news_desk_in_trend_offices_reads_the_radar(tmp_path):
    from tradebots import world
    (tmp_path / "warning").mkdir()
    (tmp_path / "warning" / "latest.json").write_text(json.dumps({"level": "DANGER", "score": 4, "lights": {
        k: {"title": t, "on": i < 4, "reading": "x"} for i, (k, (t, _)) in enumerate(w.LIGHTS.items())}}))
    trend = {"crew": [{"job": world.TREND_JOBS[k]} for k, *_ in world.CREW], "stations": {"news": {}}}
    other = {"crew": None, "stations": {"news": {"say": "crypto"}}}
    world.radar_on_news_desk({"a": trend, "c": other}, tmp_path)
    assert trend["stations"]["news"]["status"] == "blocked" and "DANGER" in trend["stations"]["news"]["say"]
    assert other["stations"]["news"]["say"] == "crypto"


def test_round_two_overlays():
    idx = pd.date_range(end="2026-10-01", periods=10, freq="B", tz="UTC")
    base = pd.Series(1.0, index=idx)
    fund = pd.Series([100, 110, 120, 95, 90, 100, 110, 125, 130, 120], index=idx, dtype=float)
    q = pd.Series([1, 2, 3, 2, 2, 2, 2, 1, 5, 4], index=idx, dtype=float)
    s = w.trail_scale(base, fund, q, 0.20)
    assert list(s) == [1, 1, 1, 0, 0, 0, 0, 0, 1, 1]     # stopped at 95 (-21% from 120), back on a new 20-day high
    news = [{"headline": "Stocks plunge as panic spreads", "created_at": "2026-09-26T14:00:00Z"},   # a Saturday
            {"headline": "Nasdaq hits record", "created_at": "2026-09-28T14:00:00Z"}]
    c = w.scary_counts(news, idx)
    assert c.sum() == 1 and c[pd.Timestamp("2026-09-28", tz="UTC")] == 1
    many = pd.Series([1.0] * 200 + [10.0] * 5, index=pd.date_range(end="2026-10-01", periods=205, freq="B", tz="UTC"))
    st = w.news_stress(many, 2.0)
    assert st.iloc[-1] and not st.iloc[-10]


def test_round_two_overlays_run_through_the_checks():
    d = market()
    close = pd.DataFrame({s: d[s]["close"] for s in d})
    macro = macro_for(close.index)
    news = [{"headline": "Market crash fears" if i % 7 else "calm", "created_at": f"{t:%Y-%m-%dT15:00:00Z}"}
            for i, t in enumerate(close.index[::3])]
    start, end = datetime(2022, 1, 1, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc)
    text = w.test(d, macro, start, end, news)
    for name in w.ROUND2:
        assert w.OVERLAYS[name]["title"] in text
    assert "Scary-headline light" in text


def test_radar_blocks_uses_the_close_before_the_day():
    idx = pd.date_range("2026-10-26", periods=5, freq="B", tz="UTC")
    sc = pd.Series([0, 5, 0, 0, 2], index=idx)
    assert not w.radar_blocks(sc, idx[1], 4)                       # Tuesday's own score isn't known at its open
    assert w.radar_blocks(sc, idx[2], 4)                           # Wednesday after a DANGER Tuesday close
    assert w.radar_blocks(sc, pd.Timestamp("2026-10-28"), 4)       # naive dates (Copycat's days) work too
    assert not w.radar_blocks(sc, idx[2], 0) and not w.radar_blocks(None, idx[2], 4)


def test_headline_watch_counts_only_new_news(tmp_path):
    idx = pd.date_range(end="2026-10-30", periods=200, freq="B", tz="UTC")

    class News:
        calls = []

        def get_news_range(self, syms, start, end):
            self.calls.append(start)
            return [{"headline": "Stocks plunge" if i % 2 else "Stocks rise", "created_at": f"{t:%Y-%m-%d}T15:00:00Z"}
                    for t in idx[-130:] for i in range(2)] + \
                   [{"headline": "Panic selloff", "created_at": f"{t:%Y-%m-%d}T16:00:00Z"} for t in idx[-5:] for _ in range(3)]
    b = News()
    h = w.headline_watch(b, tmp_path, idx, datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert h["on"] and h["last_5_days"] == 20 and h["usual_5_days"] == 5.0
    w.headline_watch(b, tmp_path, idx, datetime(2026, 10, 31, 3, tzinfo=timezone.utc))
    assert b.calls[-1] == datetime(2026, 10, 30, tzinfo=timezone.utc)      # only re-reads from the last day it has
