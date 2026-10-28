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
    "insider": "A company's own bosses (CEO, CFO and so on) and board members. They know the company best.",
    "Form 4": "The form insiders must send the SEC within 2 business days of trading their company's stock. It's public.",
    "S&P 500": "The 500 biggest US companies. Its fund, SPY, is the usual yardstick: did you beat just owning the market?",
    "forex": "Trading one country's money for another's, like euros for dollars. The biggest market in the world.",
    "currency pair": "Two currencies priced against each other. EUR/USD at 1.10 means 1 euro costs 1.10 US dollars.",
    "selling short": "Betting a price will fall. In forex you can sell a pair first and buy it back later, cheaper if you're right.",
    "units": "How much currency a forex trade controls. 1,000 units (a 'micro lot') of EUR/USD is 1,000 euros, about $1,100.",
    "pip": "The tiny step forex prices move in: 0.0001 for most pairs (0.01 for yen pairs).",
    "spread": "The gap between the buying and selling price. It's the main cost of each forex trade.",
    "leverage": "Controlling more money than you have. 3:1 means $100 controls up to $300. It makes wins and losses bigger.",
    "opening range": "A pair's highest and lowest price in the first 30 minutes after a big market opens. "
                     "The Forex office buys if the price breaks above it and sells if it breaks below.",
    "breakout": "When a price moves past its highest (or lowest) point of recent weeks. Trend followers trade in that direction.",
    "COT report": "The CFTC's free weekly report (Commitments of Traders) of who holds which futures bets, including currencies.",
    "hedge fund": "A big investment firm that makes large, often leveraged bets. Copycat FX copies their currency bets.",
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
    if "_" in symbol:   # a currency pair (Forex wing), e.g. EUR_USD -> EUR/USD
        return symbol.replace("_", "/")
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

    if any(r.get("forex") for r in runs):
        return _forex_day(out, runs, store, day, b, terms, word, change, pct)

    # What the bots looked at
    scans = [r for r in runs if r["scanned"]]
    coins = sorted({s for r in scans for s in r["scan"]})
    flagged = Counter(c["symbol"] for r in runs for c in r["candidates"])
    busiest = max(((s, m["volume_ratio"], m["move_pct"]) for r in scans for s, m in r["scan"].items()),
                  key=lambda x: x[1], default=None)
    copy = [r["filings"] for r in runs if r.get("filings")]
    if copy:
        b.append(f"Spotter read {sum(f['read'] for f in copy)} insider filings from the SEC and found "
                 f"{sum(f['insider_buys'] for f in copy)} insider purchases. Watchlist at day end: "
                 f"{copy[-1]['watchlist']} stocks.")
        if copy[-1]["top"]:
            t = copy[-1]["top"][0]
            b.append(f"Top pick: {t['ticker']} ({t['company']}). {t['note']}")
        terms |= {"insider", "Form 4"}
    else:
        b.append(f"Scout scanned {len(coins)} coins, {len(scans)} times."
                 + (f" Most active: {short(busiest[0])} at {busiest[1]:.1f}x normal volume, price {busiest[2]:+.1f}%."
                    if busiest else ""))
        terms.add("volume")
    if copy and not flagged:
        b.append("Nothing was ready to copy, so no trade was considered.")
    elif flagged:
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
        summary = ("Watchful day. Insiders bought some stocks, but none passed the copy checks yet." if copy else
                   "Watchful day. Scout flagged some moves, but none met the bar for a trade.")
    elif copy:
        summary = "Quiet day. No insider buy was big enough to copy, so Copycat stayed in cash."
    else:
        summary = "Quiet day. The market showed no setup strong enough to look at, so the bots stayed in cash."
    summary += (f" The account ended {word}" + (f" {money(abs(change))} ({pct:+.2f}%)" if word != "flat" else "")
                + f" at {money(last['equity'])}. Paper money only.")
    terms.add("paper trading")

    out["summary"], out["bullets"] = summary, b
    out["terms"] = sorted(terms, key=str.lower)
    return out


def _forex_day(out: dict, runs: list[dict], store: Store, day: str, b: list[str], terms: set[str], word: str,
               change: float, pct: float) -> dict:
    """The day for a Forex wing office: what its rule saw, the trades it opened and closed, what it holds."""
    last = runs[-1]
    cot = last["forex"].get("style") == "cot"
    reads = [r for r in runs if r["scanned"]]
    pairs = (reads[-1] if reads else last)["forex"].get("pairs") or {}
    orb = last["forex"].get("style") == "orb"
    if reads:
        rep = reads[-1]["forex"].get("report")
        b.append(f"Read the hedge funds' weekly report (as of {rep}) and checked {len(pairs)} currency pairs." if cot else
                 f"Marked the opening range on {len(pairs)} currency pairs at the London open." if orb else
                 f"Checked {len(pairs)} currency pairs at the end of the forex day.")
    elif orb:
        b.append("No opening range marked today (a weekend, a holiday, or the check came too late).")
    else:
        b.append("No new forex day finished yet, so no new trade decisions (forex days end at 5pm New York time).")
    picks = [f"{short(p).replace('_', '/')} ({r['decision'].lower()})" for p, r in pairs.items() if r["decision"] != "WAIT"]
    if picks:
        b.append("Signals: " + ", ".join(picks) + ".")
    terms |= {"forex", "currency pair"} | ({"COT report", "hedge fund"} if cot else
                                           {"opening range", "breakout"} if orb else {"breakout"})
    opened = [t for t in _day_rows(store.rows("trades.csv"), day) if t["side"] == "buy"]
    sells = [t for t in closed_trades(store) if t["time"][:10] == day]
    for t in opened:
        b.append(f"Opened {t['symbol'].replace('_', '/')} at {float(t['price']):,.6g}, controlling {money(float(t['usd']))}. "
                 f"{t['reason'].strip()}")
        terms |= {"units", "stop-loss", "leverage"}
        if t["reason"].startswith("SELL"):
            terms.add("selling short")
    for t in sells:
        why, extra = plain_exit(t["reason"])
        if t["reason"].startswith("stop hit"):
            why = "the price reached the safety stop, so OANDA closed it to keep the loss small"
        elif t["reason"].startswith("rule exit: "):
            why = t["reason"][len("rule exit: "):].rsplit(",", 1)[0]
        terms |= set(extra)
        b.append(f"Closed {t['symbol'].replace('_', '/')}: {why}." + (f" {'Gain' if t['pl'] >= 0 else 'Loss'}: "
                                                                   f"{money(t['pl'])}." if t["pl"] is not None else ""))
    out["closed"] = sells
    if not opened and not sells:
        b.append("No trades.")
    gates = [r["gate"] for r in runs if r["gate"] and r["gate"] != "ok"]
    if gates:
        b.append(f"Risk paused new trades: {gates[-1]}")
    if last["positions"]:
        b.append("Open trades: " + "; ".join(
            f"{p['symbol'].replace('_', '/')} {'bought' if p['qty'] > 0 else 'sold'} {abs(p['qty']):,.0f} units"
            + (f" ({'+' if p['unrealized'] >= 0 else ''}{money(p['unrealized'])} so far)" if p.get("unrealized") is not None else "")
            for p in last["positions"]) + ".")
        terms |= {"position", "unrealized"}
    else:
        b.append("Open trades: none, all cash.")
    summary = ("Active day. " + " and ".join(x for x in (f"opened {len(opened)} trade{'s' if len(opened) != 1 else ''}" if opened else "",
                                                          f"closed {len(sells)}" if sells else "") if x).capitalize() + "."
               if opened or sells else "Quiet day. No new currency trade.")
    summary += (f" The office ended {word}" + (f" {money(abs(change))} ({pct:+.2f}%)" if word != "flat" else "")
                + f" at {money(last['equity'])}. Practice money only.")
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
