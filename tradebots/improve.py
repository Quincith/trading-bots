"""Weekly improvement loop: Claude studies the losing trades, suggests one change, and the lab tests it.

  python -m tradebots.improve --out lab-out                      # every strategy, Claude suggests
  python -m tradebots.improve --strategy medium --change filters.btc_ema_bars=200 --idea "..."   # your own idea

For each strategy:
  1. Observe: replay the current version over the study months (the first 60% of the past year).
  2. Diagnose + hypothesize: show Claude every trade from those months, what the market looked like
     when each was bought and how it ended, plus every idea already tried. Claude names the pattern
     behind the losses and proposes ONE change from a fixed menu of settings.
  3. Experiment + validate: the strategy lab tests it on the unseen months (see lab.py).
  4. Keep or revert: a change that passes every check becomes a pull request. Nothing changes until
     Quincy merges it. Rejected ideas are logged so Claude doesn't suggest them again.
The workflow then opens one issue with what was tried this week.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import lab
from .ai import AI

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-5-5"
MAX_TRADE_ROWS = 400

STYLE = {
    "aggressive": "Crypto, short holds (hours), bigger bets. Buys coins that suddenly move up on heavy volume.",
    "medium": "Crypto, holds for days, smaller bets. Buys coins that move up on heavy volume in a clear trend.",
    "copycat": "US stocks. Copies company officers and directors who buy their own company's stock "
               "(SEC Form 4 filings), and holds for up to a month.",
}

SYSTEM = (
    "You are the research analyst for a small paper-trading project run by a beginner. Each week you get "
    "one strategy's trades from a set of past 'study months' and must propose ONE change that would have "
    "avoided losing trades without throwing away the winners. Rules:\n"
    "- Look for a real pattern: compare losing and winning trades on the columns given, and quote the numbers "
    "(for example '31 of 40 losses came when Bitcoin was below its 200-candle average, vs 12 of 30 wins').\n"
    "- Choose only from the settings menu, and change one idea (one setting, or two that belong together).\n"
    "- Prefer simple, sensible ideas over finely tuned numbers; a change that only fits these exact months "
    "will fail on the unseen months it is tested on next.\n"
    "- Do not repeat an idea that was already rejected, unless you explain what is different.\n"
    "- A strategy that trades less is fine only if the trades it skips were mostly losers.\n"
    "- Write 'idea' and 'why' for a beginner: plain words, no jargon, short sentences.\n"
    "To switch a filter off, set it to 0."
)


def schema(strategy: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "What the losing trades have in common, with numbers"},
            "idea": {"type": "string", "description": "The change in one plain sentence"},
            "why": {"type": "string", "description": "Why it should help, for a beginner, under 80 words"},
            # One idea = one setting, or two that belong together (the API doesn't take maxItems, so
            # anything past the second is dropped in propose()).
            "changes": {"type": "array", "items": {
                "type": "object",
                "properties": {"setting": {"type": "string", "enum": [k.path for k in lab.knobs_for(strategy)]},
                               "value": {"type": "number"}},
                "required": ["setting", "value"], "additionalProperties": False}},
        },
        "required": ["pattern", "idea", "why", "changes"], "additionalProperties": False,
    }


def _csv(rows: list[dict]) -> str:
    if not rows:
        return "(no trades)"
    cols = list(rows[0])
    return "\n".join([",".join(cols)] + [",".join("" if r.get(c) is None else str(r[c]) for c in cols) for r in rows])


def prompt(strategy: str, cfg: dict, split: lab.Split, study_pct: float, bench_pct: float, bench_label: str,
           rows: list[dict], past: list[dict], problems: list[str] | None = None) -> str:
    losers, total = [r for r in rows if r["result_pct"] <= 0], len(rows)
    by_exit: dict[str, list[float]] = {}
    for r in rows:
        by_exit.setdefault(r["exit"], []).append(r["result_pct"])
    if len(rows) > MAX_TRADE_ROWS:   # keep every loss, thin out the wins
        wins = [r for r in rows if r["result_pct"] > 0]
        rows = losers + wins[:: max(1, len(wins) // max(1, MAX_TRADE_ROWS - len(losers)))]
    menu = "\n".join(f"- {k.path} = {lab.shown(k.path, lab.get_value(cfg, k.path, k))}"
                     f" (allowed {k.lo:g} to {k.hi:g}, step {k.step:g}): {k.what}" for k in lab.knobs_for(strategy))
    tried = "\n".join(f"- {r['time'][:10]} {r['verdict'].upper()}: {r['idea']} {r['changes']} "
                      f"(unseen months {float(r['unseen_new_pct']):+.1f}% vs {float(r['unseen_old_pct']):+.1f}%)"
                      for r in past[-25:]) or "(none yet)"
    exits = ", ".join(f"{k}: {len(v)} trades, average {sum(v) / len(v):+.2f}%" for k, v in by_exit.items())
    out = [
        f"Strategy: {strategy}. {STYLE.get(strategy, '')}",
        f"Study months: {split.start:%Y-%m-%d} to {split.study_end:%Y-%m-%d}. The current version made "
        f"{study_pct:+.1f}% (starting from $100, fees included); {bench_label.lower()} made {bench_pct:+.1f}%.",
        f"Trades: {len(losers)} losers out of {total}. By how they ended: {exits}.",
        "", "Settings menu (current value first):", menu,
        "", "Ideas already tested for this strategy:", tried,
        "", "Column guide: result_pct = profit or loss of the trade after fees; exit = why it was sold; "
        "volume_x = volume vs normal; move_pct = recent price move; rsi = momentum 0-100; swing_pct = average "
        "candle size in % (ATR); vs_200avg_pct / btc_vs_200avg_pct = how far the coin / Bitcoin was above (+) or "
        "below (-) its 200-candle average; fear_greed = crypto Fear & Greed index; insiders / insider_usd / "
        "score / chase_pct = Copycat's signal (how many insiders, dollars, rank, and how far the price had "
        "already risen past what they paid); sp500_vs_200day_avg_pct = stock market trend.",
        "", "Trades in the study months (CSV):", _csv(rows),
    ]
    if problems:
        out += ["", "Your last answer could not be used: " + "; ".join(problems) + ". Please propose again."]
    return "\n".join(out)


def propose(ai: AI, strategy: str, cfg: dict, split: lab.Split, study_pct: float, bench_pct: float,
            bench_label: str, rows: list[dict], past: list[dict]) -> tuple[dict | None, dict, list[str]]:
    """Asks Claude for one change. Returns (answer, cleaned changes, problems). Tries twice."""
    problems: list[str] = []
    ans = None
    for _ in range(2):
        ans = ai.ask(SYSTEM, prompt(strategy, cfg, split, study_pct, bench_pct, bench_label, rows, past, problems),
                     schema(strategy))
        if not ans:
            return None, {}, ["Claude did not answer"]
        raw = {c["setting"]: c["value"] for c in ans["changes"][:2]}
        changes, problems = lab.clean_changes(strategy, cfg, raw)
        if changes and json.dumps(changes) in {r["changes"] for r in past}:
            problems.append("that exact change was already tested")
            changes = {}
        if changes:
            return ans, changes, problems
    return ans, {}, problems


# ---- turning a kept change into a config file edit ---------------------------------------------------

def _fmt(v) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def edit_config_text(text: str, changes: dict, note: str = "") -> str:
    """Changes values in a config file but keeps its layout. The changed line's comment becomes `note`
    plus the old value. A None value removes the line."""
    lines = text.splitlines()
    for path, v in changes.items():
        section, key = path.split(".")
        head = next((i for i, l in enumerate(lines) if re.match(rf"^{section}:\s*(#.*)?$", l)), None)
        if head is None:
            if v is not None:
                lines += ["", f"{section}:", f"  {key}: {_fmt(v)}" + (f"  # {note}" if note else "")]
            continue
        end = head + 1
        while end < len(lines) and (not lines[end].strip() or lines[end].startswith((" ", "\t", "#"))):
            end += 1
        while end > head + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
            end -= 1
        hit = next((i for i in range(head + 1, end) if re.match(rf"^\s+{key}:", lines[i])), None)
        if hit is None:
            if v is not None:
                lines.insert(end, f"  {key}: {_fmt(v)}" + (f"  # {note}" if note else ""))
        elif v is None:
            lines.pop(hit)
        else:
            m = re.match(rf"^(\s+{key}:\s*)([^#]*?)(\s*#.*)?$", lines[hit])
            old = m.group(2).strip()
            comment = f"  # {note}, was {old}" if note else (m.group(3) or "")
            new = ("true" if v else "false") if old in ("true", "false") else _fmt(v)   # keep on/off settings yes/no
            lines[hit] = f"{m.group(1)}{new}{comment}"
    return "\n".join(lines) + "\n"


def write_pr(out: Path, strategy: str, exp_id: str, idea: str, report: str, cfg_text: str, cfg: dict,
             changes: dict) -> None:
    new_text = edit_config_text(cfg_text, changes, f"strategy lab {exp_id}")
    if _tidy(yaml.safe_load(new_text)) != _tidy(lab.apply_changes(cfg, changes)):
        raise RuntimeError("editing the config file did not give the tested settings")
    d = out / "prs" / strategy
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{strategy}.yaml").write_text(new_text)
    (d / "id").write_text(exp_id)
    (d / "title").write_text(f"Strategy lab: {strategy.title()}: {idea}"[:120])
    (d / "body.md").write_text(
        "**This change passed every check in the strategy lab. Merge this pull request to switch it on for the "
        f"{strategy.title()} paper account, or close it to say no.** Nothing changes until you merge.\n\n" + report)


def _tidy(d):
    """Drops empty settings, so 'switched off' and 'not there' compare equal."""
    if isinstance(d, dict):
        d = {k: _tidy(v) for k, v in d.items()}
        return {k: v for k, v in d.items() if v not in ({}, None)}
    return d


# ---- the weekly run --------------------------------------------------------------------------------

def report_link(exp_id: str) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    path = f"lab/reports/{exp_id}.md"
    return f"https://github.com/{repo}/blob/bot-data/{path}" if repo else path


def improve_one(strategy: str, engine, runner: lab.Runner, data: Path, out: Path, now: datetime,
                ai: AI | None, manual: dict | None = None, manual_idea: str = "") -> list[str]:
    """Runs one round for one strategy. Returns lines for the weekly issue."""
    cfg_path = ROOT / "config" / f"{strategy}.yaml"
    cfg_text = cfg_path.read_text()
    cfg = yaml.safe_load(cfg_text)
    split = lab.make_split(engine.start, engine.end)
    lines = [f"## {strategy.title()}", ""]

    if manual is not None:
        changes, problems = lab.clean_changes(strategy, cfg, manual)
        idea, why, source, pattern = manual_idea or "Tested by hand", "", "manual", ""
        if not changes:
            return lines + [f"Nothing to test: {'; '.join(problems) or 'no change given'}.", ""]
    else:
        base = runner.run_many([(cfg, split.start, split.study_end, 1.0)])[0]
        rows = engine.trade_rows(base, cfg)
        bench = lab.pct(engine.benchmark(split.start, split.study_end))
        past = [r for r in lab.read_log(data) if r["strategy"] == strategy]
        ans, changes, problems = propose(ai, strategy, cfg, split, lab.pct(base), bench, engine.benchmark_label,
                                         rows, past)
        if not changes:
            why = "; ".join(problems) or "no usable suggestion"
            return lines + [f"No experiment this week ({why}).", ""]
        idea, why, source, pattern = ans["idea"], ans["why"], "claude", ans["pattern"]
        lines += [f"**What Claude noticed in the losing trades:** {pattern}", ""]

    exp_id, verdict, report = lab.run_experiment(strategy, engine, runner, cfg, changes, idea, why, source, data, now)
    if pattern:
        report = report.replace("**Change:**", f"**What Claude noticed:** {pattern}\n\n**Change:**", 1)
        (lab.lab_dir(data) / "reports" / f"{exp_id}.md").write_text(report)
    n = verdict.numbers
    lines += [f"**Idea:** {idea}", "",
              f"**Result: {'✅ kept' if verdict.kept else '❌ rejected'}.** On the months it had never seen it made "
              f"{n['unseen_new']:+.1f}% vs {n['unseen_old']:+.1f}% for the current version and {n['benchmark']:+.1f}% "
              f"for {engine.benchmark_label.lower()}."]
    if verdict.kept:
        write_pr(out, strategy, exp_id, idea, report, cfg_text, cfg, changes)
        lines.append("A pull request with this change is waiting for your OK (link below).")
    else:
        failed = [c for c in verdict.checks if not c["passed"]]
        lines.append("Failed: " + "; ".join(f"{c['name'].lower()} ({c['detail']})" for c in failed) + ".")
    lines += ["", f"[Full lab report]({report_link(exp_id)})", ""]
    return lines


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="tradebots.improve")
    ap.add_argument("--strategy", default="all", choices=["all", "aggressive", "medium", "copycat"])
    ap.add_argument("--change", default="", help="test this instead of asking Claude, e.g. 'filters.btc_ema_bars=200'")
    ap.add_argument("--idea", default="")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--out", default="lab-out")
    ap.add_argument("--cache-dir", help="keep downloaded history here between runs")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    data = Path(os.environ.get("DATA_DIR", ROOT / "data"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manual = lab.parse_sets([s for s in re.split(r"[,\s]+", args.change) if s]) if args.change.strip() else None
    strategies = ["aggressive", "medium", "copycat"] if args.strategy == "all" else [args.strategy]
    ai = AI(MODEL, "high") if manual is None else None
    body = [f"# Strategy lab: week of {now:%B %-d, %Y}", "",
            "Each week Claude studies the losing trades from the past months, suggests one change, and the lab "
            "tests it on months it has never seen, with fees. Only a change that passes every check becomes a "
            "pull request for you to approve.", ""]
    if ai is not None and not ai.enabled:
        body += ["**The Claude key is missing, so no ideas were suggested this week.**", ""]
        strategies = []

    engines: dict[str, object] = {}
    for s in strategies:
        kind = "copycat" if s == "copycat" else "crypto"
        try:
            if kind not in engines:
                cache = f"{args.cache_dir}/{kind}.pkl" if args.cache_dir else None
                engines[kind] = lab.load_engine(s, args.days, cache)
                engines[kind + "_runner"] = lab.Runner(engines[kind])
            body += improve_one(s, engines[kind], engines[kind + "_runner"], data, out, now, ai, manual, args.idea)
        except Exception as e:   # one strategy's data problem shouldn't stop the others
            log.exception("lab failed for %s", s)
            body += [f"## {s.title()}", "", f"Couldn't run the lab this week: {e}", ""]
    if ai is not None:
        body.append(f"_Claude made {ai.calls} call(s) for this ({MODEL})._")
    text = "\n".join(body) + "\n"
    (out / "summary.md").write_text(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
