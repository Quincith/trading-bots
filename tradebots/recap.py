"""Daily recap in plain words, written for someone new to trading.

Built from the run logs, trades.csv and deposits, with no AI, so it costs nothing and never
makes things up. Every trading word it uses is explained in the "Words to know" list.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from . import runlog
from .store import Store

GLOSSARY = {
    "paper trading": "Practice trading with pretend money. Prices are real, the money isn't.",
    "account value": "What everything in the account is worth right now: cash plus coins, at today's prices.",
    "money put in": "The money you added (deposits) minus any you took out. Profit is measured against this.",
    "profit / loss": "Account value minus money put in. Adding money never counts as profit.",
    "volume": "How much of a coin is being bought and sold. A jump in volume means lots of people suddenly care.",
    "momentum": "When a price keeps moving the same way for a while, like a ball rolling downhill.",
    "RSI": "A 0-100 score of how hard a price has been pushed lately. Above 70 can mean it has run too far, too fast.",
    "trend": "The general direction of the price: up, down, or sideways.",
    "support": "A price where buyers have stepped in before, like a floor.",
    "resistance": "A price where sellers have shown up before, like a ceiling.",
    "entry": "The price we buy at.",
    "stop-loss": "A safety exit. If the price falls to this level, the bots sell to keep the loss small.",
    "target": "The profit goal. If the price rises to this level, the bots sell and keep the gain.",
    "reward-to-risk": "How much the trade could win compared with how much it could lose. 2 means it aims to win $2 for every $1 at risk.",
    "position": "A coin the account currently owns.",
    "breakeven": "The price where you neither win nor lose. Moving the stop-loss there means the trade can't lose money anymore.",
    "catalyst": "A news event that could move the price, like a big partnership or a new law.",
    "hype": "Buzz that's mostly excitement and not backed by real news.",
    "Fear & Greed index": "A daily 0-100 mood score for crypto. Low means people are scared, high means they're greedy.",
    "confidence": "How sure the Decision bot is, from 0% to 100%. Each strategy only buys above its own minimum.",
    "correlation": "When two coins tend to move together. Owning both is almost like owning one big bet.",
    "daily loss limit": "If the account drops this much in one day, the bots stop buying until tomorrow.",
    "total loss limit": "If the account drops this much below the money put in, the strategy stops until you restart it.",
    "unrealized": "A gain or loss on a coin we still own. It only becomes real when we sell.",
}


def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < -0.005 else f"${x:,.2f}"


def plain_exit(reason: str) -> tuple[str, list[str]]:
    r = reason.lower()
    if r.startswith("stop hit"):
        return "the price fell to the safety exit, so the bots sold to keep the loss small", ["stop-loss"]
    if r.startswith("target hit"):
        return "the price reached the profit goal, so the bots sold and kept the gain", ["target"]
    if r.startswith("held"):
        return "it was held as long as this strategy allows, so the bots sold it", []
    return reason, []


def _day_rows(rows: list[dict], day: str) -> list[dict]:
    return [r for r in rows if r["time"][:10] == day]


def short(symbol: str) -> str:
    return symbol.split("/")[0].removesuffix("USD")


def closed_trades(store: Store, since: str = "") -> list[dict]:
    """Each sell matched to the buy before it, with the rough gain or loss in dollars."""
    rows = store.rows("trades.csv")
    out = []
    for i, t in enumerate(rows):
        if t["side"] != "sell" or t["time"] < since:
            continue
        buy = next((b for b in reversed(rows[:i]) if b["side"] == "buy"
                    and b["symbol"].replace("/", "") == t["symbol"].replace("/", "")), None)
        pl = float(t["usd"]) - float(buy["usd"]) if buy else None
        out.append({"time": t["time"], "symbol": short(t["symbol"]), "usd": float(t["usd"]), "pl": pl,
                    "reason": t["reason"]})
    return out


def build(store: Store, day: str) -> dict:
    """A short description plus key-takeaway bullets for one strategy on one UTC day (YYYY-MM-DD)."""
    name = store.dir.name
    runs = runlog.load_day(store, day)
    terms: set[str] = set()
    out = {"strategy": name, "day": day, "runs": len(runs), "summary": "", "bullets": [], "terms": []}
    if not runs:
        out["headline"] = f"{name.title()}: no runs logged on {day}."
        return out

    first, last = runs[0], runs[-1]
    start = first["day_start_equity"] or first["equity"]
    added = last["net_deposits"] - first["net_deposits"]
    change = last["equity"] - start - added
    pct = change / start * 100 if start else 0.0
    out.update(start_value=start, end_value=last["equity"], change=change, change_pct=pct,
               profit=last["profit"], net_deposits=last["net_deposits"])
    word = "up" if change > 0.005 else "down" if change < -0.005 else "flat"
    out["headline"] = f"{name.title()}: {word}" + (f" {money(abs(change))} ({pct:+.2f}%)" if word != "flat" else "")
    b = []

    # Money
    b.append(f"Account value: {money(start)} \u2192 {money(last['equity'])}"
             + (f" ({'+' if change >= 0 else ''}{money(change)}, {pct:+.2f}%)" if word != "flat" else " (no change)")
             + (f". Includes {money(added)} you added." if abs(added) > 0.005 else "."))
    b.append(f"Profit / loss since start: {'+' if last['profit'] >= 0 else ''}{money(last['profit'])} "
             f"on {money(last['net_deposits'])} money put in.")
    terms |= {"account value", "profit / loss", "money put in"}

    # What the bots looked at
    scans = [r for r in runs if r["scanned"]]
    coins = sorted({s for r in scans for s in r["scan"]})
    flagged = Counter(c["symbol"] for r in runs for c in r["candidates"])
    busiest = max(((s, m["volume_ratio"], m["move_pct"]) for r in scans for s, m in r["scan"].items()),
                  key=lambda x: x[1], default=None)
    b.append(f"Scout scanned {len(coins)} coins, {len(scans)} times."
             + (f" Most active: {short(busiest[0])} at {busiest[1]:.1f}x normal volume, price {busiest[2]:+.1f}%."
                if busiest else ""))
    terms.add("volume")
    if flagged:
        b.append("Sent for review: " + ", ".join(f"{short(s)} ({n}x)" for s, n in flagged.most_common()) + ".")
    else:
        b.append("Nothing passed Scout's filter, so no trade was considered.")

    # Decisions
    calls = [c for r in runs for c in r["candidates"]]
    if calls:
        n = Counter(c["decision"] for c in calls)
        b.append(f"Decisions: {n.get('BUY', 0)} buy, {n.get('WAIT', 0)} wait, {n.get('SKIP', 0)} skip.")
        latest = {c["symbol"]: c for c in calls}
        for c in [c for c in latest.values() if c["decision"] != "BUY"][:2]:
            b.append(f"Passed on {short(c['symbol'])} ({c['decision']}, {int(c['confidence'] * 100)}% confident): "
                     f"{c['decision_note'].strip()}")
        terms.add("confidence")

    # Trades
    buys = [t for t in _day_rows(store.rows("trades.csv"), day) if t["side"] == "buy"]
    sells = [t for t in closed_trades(store) if t["time"][:10] == day]
    for t in buys:
        b.append(f"Bought {money(float(t['usd']))} of {short(t['symbol'])} at {float(t['price']):,.6g}. "
                 f"Reason: {t['reason'].strip() or 'signals lined up'}")
        terms |= {"entry", "stop-loss", "target"}
    for t in sells:
        why, extra = plain_exit(t["reason"])
        terms |= set(extra)
        res = (f" {'Gain' if t['pl'] >= 0 else 'Loss'}: {money(t['pl'])}." if t["pl"] is not None else "")
        b.append(f"Sold {t['symbol']} for {money(t['usd'])}: {why}.{res}")
    out["closed"] = sells
    if not buys and not sells:
        b.append("No trades.")

    # Risk
    gates = [r["gate"] for r in runs if r["gate"] and r["gate"] != "ok"]
    if any("daily" in g for g in gates):
        b.append("Daily loss limit hit. New buys stopped until tomorrow (UTC).")
        terms.add("daily loss limit")
    if any("Total loss" in g or "halted" in g for g in gates):
        b.append("Total loss limit hit. Strategy halted until you press Resume in the Control panel.")
        terms.add("total loss limit")
    if any("Kill switch" in g for g in gates):
        b.append("Kill switch was on. No new trades.")

    # Holdings
    if last["positions"]:
        held = [f"{short(p['symbol'])} {money(p['market_value'])} "
                f"({'+' if (g := (p['current_price'] - p['avg_entry_price']) * p['qty']) >= 0 else ''}{money(g)} unrealized)"
                for p in last["positions"]]
        b.append("Holding: " + "; ".join(held) + ".")
        terms |= {"position", "unrealized"}
    else:
        b.append("Holding: nothing, all cash.")

    # Description at the top
    wins = [t for t in sells if t["pl"] is not None and t["pl"] >= 0]
    losses = [t for t in sells if t["pl"] is not None and t["pl"] < 0]
    if buys or sells:
        parts = []
        if buys:
            parts.append(f"bought {len(buys)} time{'s' if len(buys) != 1 else ''}")
        if sells:
            parts.append(f"closed {len(sells)} trade{'s' if len(sells) != 1 else ''} "
                         f"({len(wins)} win{'s' if len(wins) != 1 else ''}, {len(losses)} loss{'es' if len(losses) != 1 else ''})")
        summary = f"Active day. The bots {' and '.join(parts)}."
    elif flagged:
        summary = "Watchful day. Scout flagged some moves, but none met the bar for a trade."
    else:
        summary = "Quiet day. The market showed no setup strong enough to look at, so the bots stayed in cash."
    summary += (f" The account ended {word}" + (f" {money(abs(change))} ({pct:+.2f}%)" if word != "flat" else "")
                + f" at {money(last['equity'])}. Paper money only.")
    terms.add("paper trading")

    out["summary"], out["bullets"] = summary, b
    out["terms"] = sorted(terms, key=str.lower)
    return out


def to_markdown(recaps: list[dict], day: str) -> str:
    out = [f"# Daily recap: {datetime.fromisoformat(day):%A, %B %-d, %Y}", "",
           "_Times are UTC. Paper money only._", ""]
    terms: set[str] = set()
    for r in recaps:
        out += [f"## {r['headline']}", ""]
        if r.get("summary"):
            out += [r["summary"], "", "**Key takeaways**", ""] + [f"- {x}" for x in r["bullets"]] + [""]
        terms |= set(r["terms"])
    if terms:
        out += ["## Words to know", ""] + [f"- **{t}**: {GLOSSARY[t]}" for t in sorted(terms, key=str.lower)]
    return "\n".join(out) + "\n"
