import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import yaml
from conftest import FakeBroker, make_bars
from test_backtest import synth_history

from tradebots import backtest as bt
from tradebots import improve, insider_history, lab, pipeline, sec, weekly
from tradebots.__main__ import ROOT
from tradebots.ai import AI
from tradebots.bots import filters
from tradebots.models import Candidate
from tradebots.store import Store

START = datetime(2026, 7, 16, tzinfo=timezone.utc)
END = datetime(2026, 7, 24, tzinfo=timezone.utc)


def cfg(name):
    return yaml.safe_load((ROOT / "config" / f"{name}.yaml").read_text())


@pytest.fixture(scope="module")
def engine():
    return lab.CryptoEngine(synth_history(), START, END)


# ---- the settings menu ------------------------------------------------------------------------------

def test_every_knob_exists_in_the_config_and_is_inside_its_range():
    for s in ("aggressive", "medium", "copycat"):
        c = cfg(s)
        for k in lab.knobs_for(s):
            v = lab.get_value(c, k.path, k)
            assert v is not None, k.path
            assert v == 0 and k.path.startswith("filters.") or k.lo <= v <= k.hi, (s, k.path, v)


def test_clean_changes_snaps_to_steps_and_refuses_off_menu_or_no_op():
    c = cfg("aggressive")
    ch, problems = lab.clean_changes("aggressive", c, {"filters.max_atr_pct": 0.83, "charts.min_reward_risk": 9,
                                                       "risk.max_daily_loss_pct": 50, "scout.min_rsi": 50})
    assert ch == {"filters.max_atr_pct": 0.8, "charts.min_reward_risk": 4.0}
    assert any("risk.max_daily_loss_pct" in p for p in problems)      # loss limits are Quincy's, not the lab's
    assert any("already 50" in p for p in problems)
    on = lab.apply_changes(c, {"filters.btc_ema_bars": 200})
    assert lab.clean_changes("aggressive", on, {"filters.btc_ema_bars": "off"})[0] == {"filters.btc_ema_bars": 0}


def test_nudges_move_each_number_one_step_and_skip_switched_off_filters():
    n = lab.nudged("aggressive", {"charts.min_reward_risk": 2.0, "filters.btc_ema_bars": 0})
    assert {x["charts.min_reward_risk"] for x in n} == {1.75, 2.25}
    assert lab.nudged("aggressive", {"filters.btc_ema_bars": 200}) == [{"filters.btc_ema_bars": 175}]  # 225 is past the top


def test_split_keeps_study_months_before_unseen_slices():
    sp = lab.make_split(datetime(2025, 10, 25, tzinfo=timezone.utc), datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert sp.start < sp.study_end == sp.windows[0][0] and sp.windows[-1][1] == sp.end
    assert len(sp.windows) == lab.WINDOWS and abs((sp.study_end - sp.start).days - 219) <= 1
    assert all(a < b for a, b in sp.windows)


# ---- filters in the live pipeline ---------------------------------------------------------------------

def test_filters_are_off_by_default_and_each_one_can_block():
    bars = make_bars(drift=0.0008, surge=True, seed=1)
    c = Candidate(symbol="SOL/USD", asset_class="crypto", bars=bars)
    assert filters.active(cfg("aggressive")["filters"]) == {}
    assert filters.check(c, {"max_atr_pct": 0.1}, filters.Context()).startswith("too wild")
    falling = make_bars(drift=-0.003, seed=3)
    assert "Bitcoin" in filters.check(c, {"btc_ema_bars": 100}, filters.Context(btc=falling))
    assert filters.check(c, {"btc_ema_bars": 100}, filters.Context(btc=make_bars(drift=0.003, seed=3))) is None
    assert "panic" in filters.check(c, {"min_fear_greed": 20}, filters.Context(fng=10))
    assert "greed" in filters.check(c, {"max_fear_greed": 80}, filters.Context(fng=90))
    asked = []
    filters.apply([c], {"max_atr_pct": 50}, None, lambda: asked.append(1))
    assert not asked                     # Fear & Greed is only fetched when a Fear & Greed filter is on


def test_pipeline_skips_setups_a_filter_blocks(tmp_path):
    c = cfg("aggressive")
    bars = {"SOL/USD": make_bars(drift=0.0008, surge=True, seed=1), "BTC/USD": make_bars(drift=-0.003, seed=3)}
    no_ai = AI("claude-opus-5-5", api_key="")
    res = pipeline.run(c, FakeBroker(bars=bars), no_ai, Store(tmp_path / "a", "aggressive"))
    assert res.buys
    blocked = lab.apply_changes(c, {"filters.btc_ema_bars": 100})
    res = pipeline.run(blocked, FakeBroker(bars=bars), no_ai, Store(tmp_path / "b", "aggressive"))
    assert not res.buys and any("Bitcoin is below" in n for n in res.notes)


# ---- the test itself -------------------------------------------------------------------------------

def test_judge_reports_every_check_and_a_no_effect_change_is_rejected(engine, tmp_path):
    c = cfg("medium")
    runner = lab.Runner(engine, workers=1)
    exp_id, v, text = lab.run_experiment("medium", engine, runner, c, {"filters.max_fear_greed": 95}, "test",
                                         "", "manual", tmp_path, END)
    assert not v.kept and len(v.checks) == 8
    assert v.numbers["unseen_new"] == v.numbers["unseen_old"]          # synthetic history has no Fear & Greed most days
    assert "Better on the unseen months" in text and exp_id == "20260724-medium-1"
    row = lab.read_log(tmp_path)[0]
    assert row["verdict"] == "rejected" and json.loads(row["changes"]) == {"filters.max_fear_greed": 95}
    assert (tmp_path / "lab" / "reports" / f"{exp_id}.md").exists()
    # A second idea on the same unseen months is flagged as such.
    assert lab.tries_on_same_months(tmp_path, "medium", lab.make_split(engine.start, engine.end)) == 1


class SlopeEngine:
    """Pretend replays: value grows 2 a day for the hold times in `good`, 1 a day otherwise."""
    cash, benchmark_label, min_trades = 100.0, "Just hold Bitcoin", 0
    start, end = START, END

    def __init__(self, good):
        self.good = good

    def run(self, c, a, b, cost=1.0):
        slope = 2.0 if c["exits"]["max_hold_hours"] in self.good else 1.0
        r, t = bt.SimResult("x", []), a
        while t <= b:
            r.equity.append((t, 100 + slope * (t - a).total_seconds() / 86400 - (cost - 1)))
            t += timedelta(hours=6)
        return r

    def benchmark(self, a, b):
        return bt.SimResult("b", [(a, 100.0), (b, 100.0)])


def test_a_change_is_kept_only_if_its_neighbours_hold_up_too():
    change, split = {"exits.max_hold_hours": 48}, lab.make_split(START, END)
    spike = SlopeEngine({48})
    v = lab.judge(spike, lab.Runner(spike, workers=1), cfg("medium"), change, split, "medium")
    assert [c["name"] for c in v.checks if not c["passed"]] == ["Not a lucky number"] and not v.kept
    plateau = SlopeEngine({46, 48, 50})
    v = lab.judge(plateau, lab.Runner(plateau, workers=1), cfg("medium"), change, split, "medium")
    assert v.kept and all(c["passed"] for c in v.checks)


def test_parallel_runner_matches_one_at_a_time(engine):
    c = cfg("medium")
    jobs = [(c, START, END, 1.0), (lab.apply_changes(c, {"charts.min_reward_risk": 3.0}), START, END, 1.0)]
    one = lab.Runner(engine, workers=1).run_many(jobs)
    two = lab.Runner(engine, workers=2).run_many(jobs)
    assert [r.equity[-1][1] for r in one] == [r.equity[-1][1] for r in two]


def test_losing_trades_come_with_what_the_market_looked_like(engine):
    c = cfg("aggressive")
    res = engine.run(c, START, END)
    rows = engine.trade_rows(res, c)
    assert rows and {"result_pct", "exit", "rsi", "swing_pct", "btc_vs_200avg_pct"} <= set(rows[0])
    assert all(r["exit"] in ("stop hit", "target hit", "held") or r["exit"].startswith("held") for r in rows)


# ---- the weekly loop ---------------------------------------------------------------------------------

class FakeAI:
    def __init__(self, answers):
        self.answers, self.calls, self.prompts = list(answers), 0, []
        self.enabled = True

    def ask(self, system, prompt, schema):
        self.calls += 1
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else None


def answer(changes, idea="Skip wild coins"):
    return {"pattern": "most losses were wild coins", "idea": idea, "why": "Calmer coins hit the stop less.",
            "changes": [{"setting": k, "value": v} for k, v in changes.items()]}


def test_claude_is_asked_again_when_it_repeats_a_rejected_idea():
    past = [{"time": "2026-10-18T14:00:00", "verdict": "rejected", "idea": "x", "unseen_new_pct": "1",
             "unseen_old_pct": "2", "changes": json.dumps({"filters.max_atr_pct": 2.0})}]
    ai = FakeAI([answer({"filters.max_atr_pct": 2.0}), answer({"filters.max_atr_pct": 3.0})])
    sp = lab.make_split(START, END)
    ans, changes, _ = improve.propose(ai, "aggressive", cfg("aggressive"), sp, 1.0, 2.0, "Just hold Bitcoin",
                                      [{"result_pct": -1.0, "exit": "stop hit"}], past)
    assert changes == {"filters.max_atr_pct": 3.0} and ai.calls == 2
    assert "already tested" in ai.prompts[1] and "REJECTED" in ai.prompts[0]


def test_weekly_round_logs_the_idea_and_writes_a_pull_request_only_when_kept(engine, tmp_path, monkeypatch):
    runner = lab.Runner(engine, workers=1)
    ai = FakeAI([answer({"filters.max_atr_pct": 2.0})])
    lines = improve.improve_one("aggressive", engine, runner, tmp_path / "data", tmp_path / "out", END, ai)
    assert "rejected" in "\n".join(lines) and not (tmp_path / "out" / "prs").exists()
    assert "most losses were wild coins" in (tmp_path / "data/lab/reports/20260724-aggressive-1.md").read_text()

    monkeypatch.setattr(lab, "judge", lambda *a, **k: lab.Verdict(True, [], {
        "unseen_new": 5.0, "unseen_old": 1.0, "benchmark": 0.0, "months": [(0, 1)] * 5, "trades": 20,
        "study_old": 0, "study_new": 1, "stress_old": 0, "stress_new": 1, "drawdown_old": -5, "drawdown_new": -4,
        "trades_old": 20, "nudges": [], "fees_new": 1}))
    ai = FakeAI([answer({"filters.btc_ema_bars": 200}, "Only buy when Bitcoin is healthy")])
    lines = improve.improve_one("aggressive", engine, runner, tmp_path / "data", tmp_path / "out", END, ai)
    pr = tmp_path / "out" / "prs" / "aggressive"
    assert "kept" in "\n".join(lines) and (pr / "id").read_text() == "20260724-aggressive-2"
    new = yaml.safe_load((pr / "aggressive.yaml").read_text())
    assert new["filters"]["btc_ema_bars"] == 200 and new["risk"] == cfg("aggressive")["risk"]
    assert "Merge this pull request" in (pr / "body.md").read_text()


def test_manual_change_skips_claude(engine, tmp_path):
    lines = improve.improve_one("medium", engine, lab.Runner(engine, workers=1), tmp_path, tmp_path / "o", END, None,
                                manual={"charts.min_reward_risk": 2.5}, manual_idea="Aim higher")
    assert "**Idea:** Aim higher" in "\n".join(lines)
    assert lab.read_log(tmp_path)[0]["source"] == "manual"


def test_config_edit_keeps_comments_and_matches_the_tested_settings():
    for s, ch in [("aggressive", {"filters.btc_ema_bars": 200, "charts.min_reward_risk": 2.0}),
                  ("medium", {"exits.max_hold_hours": 96}), ("copycat", {"copycat.min_insiders": 2})]:
        text = (ROOT / "config" / f"{s}.yaml").read_text()
        new = improve.edit_config_text(text, ch, "strategy lab X")
        assert improve._tidy(yaml.safe_load(new)) == improve._tidy(lab.apply_changes(yaml.safe_load(text), ch))
        assert new.count("\n") == text.count("\n") and "# strategy lab X, was" in new
        assert sum(a != b for a, b in zip(text.splitlines(), new.splitlines())) == len(ch)


def test_weekly_report_lists_this_weeks_experiments():
    now = datetime(2026, 11, 1, 13, tzinfo=timezone.utc)
    rows = [{"time": "2026-10-31T14:00:00+00:00", "strategy": "medium", "verdict": "kept", "idea": "Healthy market only",
             "unseen_new_pct": "3.2", "unseen_old_pct": "-1.0"},
            {"time": "2026-10-10T14:00:00+00:00", "strategy": "aggressive", "verdict": "rejected", "idea": "old",
             "unseen_new_pct": "0", "unseen_old_pct": "0"}]
    text = weekly.lab_section(rows, now)
    assert "Healthy market only" in text and "✅ kept" in text and "old" not in text
    assert weekly.lab_section([], now) == ""


# ---- Copycat: past insider buys ------------------------------------------------------------------------

def sec_zip(rows):
    def tsv(cols, data):
        return "\t".join(cols) + "\n" + "".join("\t".join(r) + "\n" for r in data)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", tsv(["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERNAME",
                                          "ISSUERTRADINGSYMBOL"], [r[:5] for r in rows]))
        z.writestr("REPORTINGOWNER.tsv", tsv(["ACCESSION_NUMBER", "RPTOWNERNAME", "RPTOWNER_RELATIONSHIP",
                                              "RPTOWNER_TITLE"], [[r[0], *r[5:8]] for r in rows]))
        z.writestr("NONDERIV_TRANS.tsv", tsv(["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                              "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD"],
                                             [[r[0], *r[8:]] for r in rows]))
    return buf.getvalue()


def test_sec_quarter_file_gives_open_market_buys_like_the_live_feed():
    raw = sec_zip([
        ["0001-26-1", "02-JUL-2026", "4", "Acme Corp", "ACME", "Doe Jane", "Officer", "CEO", "01-JUL-2026", "P", "1000", "20", "A"],
        ["0001-26-2", "02-JUL-2026", "4", "Acme Corp", "ACME", "Roe Rick", "Director", "", "01-JUL-2026", "S", "1000", "20", "D"],
        ["0001-26-3", "03-JUL-2026", "4", "Big Fund", "BIGF", "Whale LP", "TenPercentOwner", "", "02-JUL-2026", "P", "9", "9", "A"],
    ])
    buys = insider_history.parse_quarter(raw)
    assert [(b.ticker, b.role, b.is_officer, b.usd, b.date, b.filed) for b in buys] == [
        ("ACME", "CEO", True, 20000.0, "2026-07-01", "2026-07-02T21:00:00+00:00"),
        ("BIGF", "10% owner", False, 81.0, "2026-07-02", "2026-07-03T21:00:00+00:00")]
    assert insider_history.quarters(datetime(2025, 11, 1).date(), datetime(2026, 4, 2).date()) == \
        ["2025q4", "2026q1", "2026q2"]


def daily(prices, start="2026-06-01"):
    idx = pd.bdate_range(start, periods=len(prices))
    s = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame({"open": s, "high": s * 1.01, "low": s * 0.99, "close": s, "volume": 1e6})


def insider_buy(ticker, who, usd, price, filed):
    return sec.InsiderBuy(accession=f"a-{ticker}-{who}", ticker=ticker, company=f"{ticker} Inc", who=who, role="CEO",
                          is_officer=True, is_director=False, shares=usd / price, price=price, date=filed,
                          filed=f"{filed}T21:00:00+00:00")


def test_copycat_replay_copies_the_next_morning_and_exits_at_the_target():
    n = 60
    up = [50.0] * 30 + [50.0 * 1.02 ** i for i in range(1, 31)]          # rallies after the filing
    flat = [30.0] * n
    hist = insider_history.InsiderHistory(
        buys=[insider_buy("UPCO", "Ann", 100000, 50, "2026-07-10"), insider_buy("FLAT", "Bob", 20000, 30, "2026-07-10")],
        bars={"UPCO": daily(up), "FLAT": daily(flat)}, spy=daily([400.0 + i for i in range(n)]),
        last_data_day=datetime(2026, 8, 20).date())
    eng = insider_history.CopycatEngine(hist, datetime(2026, 7, 1, tzinfo=timezone.utc),
                                        datetime(2026, 8, 20, tzinfo=timezone.utc))
    c = cfg("copycat")
    res = eng.run(c, eng.start, eng.end)
    assert [t["symbol"] for t in res.trades] == ["UPCO"]                  # FLAT's $20k is under the $50k minimum
    t = res.trades[0]
    assert t["opened"].startswith("2026-07-13") and t["exit"] == "target" and t["pnl"] > 0
    assert res.equity[-1][1] > 100
    assert eng.benchmark(eng.start, eng.end).equity[-1][1] > 100
    rows = eng.trade_rows(res, c)
    assert rows[0]["insiders"] == 1 and rows[0]["result_pct"] > 15
    # The lab's "min_insiders" knob means a single insider is no longer enough.
    assert not eng.run(lab.apply_changes(c, {"copycat.min_insiders": 2}), eng.start, eng.end).trades
