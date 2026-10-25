"""Plain-English run report, shown on the GitHub Actions run page and saved as summary.md."""
from __future__ import annotations

from .pipeline import RunResult
from .store import Store


def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def performance_block(store: Store) -> list[str]:
    p = store.performance()
    return [
        "| | |", "|---|---|",
        f"| Account value | {money(p['equity'])} |",
        f"| Money put in (deposits minus withdrawals) | {money(p['net_deposits'])} |",
        f"| Strategy profit / loss | {money(p['profit'])} ({p['simple_return_pct']:+.2f}%) |",
        f"| Time-weighted return (ignores when deposits happened) | {p['twr_pct']:+.2f}% |",
    ]


def render(res: RunResult, store: Store, dry_run: bool) -> str:
    out = [f"# {res.strategy.title()} strategy — {res.started:%Y-%m-%d %H:%M} UTC"
           + (" (DRY RUN, no orders sent)" if dry_run else ""), ""]
    out += performance_block(store) + [""]
    if res.gate and res.gate != "ok":
        out += [f"**Risk:** {res.gate}", ""]
    if res.exits:
        out += ["## Open trades managed"] + [f"- {x}" for x in res.exits] + [""]
    if res.buys:
        out += ["## New buys"] + [f"- {x}" for x in res.buys] + [""]
    if res.filings:
        f = res.filings
        out += ["## Insider buys on the watchlist", "",
                f"Read {f['read']} new SEC filings this run. {f['watchlist']} stocks on the watchlist.", ""]
        if f["top"]:
            out += ["| Stock | Score | Who bought |", "|---|---|---|"]
            out += [f"| {t['ticker']} ({t['company']}) | {t['score']} | {t['note']} |" for t in f["top"]]
            out.append("")
    if res.candidates and res.filings:
        out += ["## Copy decisions", "", "| Stock | Price check | Risk | Decision |", "|---|---|---|---|"]
        for c in res.candidates:
            out.append(f"| {c.symbol} | {c.sentiment_note or '-'} | {c.risk_verdict or '-'} {c.risk_note} "
                       f"| **{c.decision}** — {c.decision_note} |")
        out.append("")
    elif res.candidates:
        out += ["## What the bots thought", "",
                "| Asset | Scout | News | Sentiment | Chart plan | Risk | Decision |",
                "|---|---|---|---|---|---|---|"]
        for c in res.candidates:
            p = c.plan
            plan = f"{p.trend}, entry {p.entry:.6g} / stop {p.stop:.6g} / target {p.target:.6g}" if p else "none"
            out.append(
                f"| {c.symbol} | vol {c.volume_ratio:.1f}x, move {c.move_pct:+.1f}% | {c.news_score:+.2f} {c.news_note} "
                f"| {c.sentiment_score:+.2f} (hype {c.hype:.1f}) {c.sentiment_note} | {plan} "
                f"| {c.risk_verdict} {c.risk_note} | **{c.decision}** {c.confidence:.2f} — {c.decision_note} |")
        out.append("")
    if res.notes:
        out += ["## Notes"] + [f"- {n}" for n in res.notes] + [""]
    out.append("_Copycat uses no AI._" if res.filings else f"_Claude calls this run: {res.ai_calls}_")
    return "\n".join(out) + "\n"
