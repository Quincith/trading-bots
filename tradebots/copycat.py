"""The Copycat strategy: copy company insiders who buy their own company's stock.

Each run:
  0. Manage open trades the same way the other strategies do (stop, target, time limit).
  1. Spotter reads the newest SEC Form 4 filings and keeps every open-market purchase by an
     officer or director on a watchlist for a few days. Several insiders buying the same stock
     ("a cluster") and big dollar amounts rank higher.
  2. When the stock market is open, the best watchlist picks are checked: can Alpaca buy part of
     a share, and has the price already run up too far past what the insider paid?
  3. Risk sizes each buy with the same rules as the other strategies.
  4. Decision is a plain rule: if the pick passed every check, copy it (BUY).
No AI is used: the picks come from the insiders, which also keeps this strategy free to run.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import sec
from .bots import risk
from .models import Candidate, Plan
from .pipeline import RunResult, _finish, _iso, manage_exits
from .store import Store

log = logging.getLogger(__name__)
C_SUITE = ("ceo", "chief", "president", "cfo", "coo", "chair")
SEEN_KEEP = 4000


def score(entry: dict) -> float:
    """Bigger buys, more insiders buying together, and top bosses buying all rank higher."""
    total = sum(b["usd"] for b in entry["buys"])
    people = len({b["who"] for b in entry["buys"]})
    boss = any(any(w in b["role"].lower() for w in C_SUITE) for b in entry["buys"])
    return round(max(math.log10(max(total, 1)) - 4, 0) + 0.75 * (people - 1) + (0.5 if boss else 0), 2)


def describe(entry: dict) -> str:
    people = {}
    for b in entry["buys"]:
        people.setdefault(b["who"], [b["role"], 0.0])[1] += b["usd"]
    total = sum(b["usd"] for b in entry["buys"])
    who = "; ".join(f"{name.title()} ({role}) ${usd:,.0f}" for name, (role, usd) in
                    sorted(people.items(), key=lambda kv: -kv[1][1])[:3])
    more = f" and {len(people) - 3} more" if len(people) > 3 else ""
    return f"{len(people)} insider{'s' if len(people) != 1 else ''} bought ${total:,.0f} at about " \
           f"${avg_price(entry):,.2f}: {who}{more}."


def avg_price(entry: dict) -> float:
    shares = sum(b["usd"] / b["price"] for b in entry["buys"])
    return sum(b["usd"] for b in entry["buys"]) / shares if shares else 0.0


def update_watchlist(st: dict, buys: list[sec.InsiderBuy], cc: dict, now: datetime) -> int:
    """Adds qualifying insider buys and drops stale ones. Returns how many buys were added."""
    wl = st.setdefault("watchlist", {})
    roles, added = set(cc["insider_roles"]), 0
    for b in buys:
        if not (("officer" in roles and b.is_officer) or ("director" in roles and b.is_director)):
            continue
        if b.price < cc["min_price"]:
            continue
        e = wl.setdefault(b.ticker, {"ticker": b.ticker, "company": b.company, "buys": []})
        if any(x["accession"] == b.accession and x["date"] == b.date and x["usd"] == round(b.usd, 2)
               for x in e["buys"]):
            continue
        e["buys"].append({"accession": b.accession, "who": b.who, "role": b.role, "usd": round(b.usd, 2),
                          "price": b.price, "date": b.date, "filed": _iso(sec.filed_time(b))})
        added += 1
    cutoff = now - timedelta(days=cc["max_signal_age_days"])
    for t in list(wl):
        wl[t]["buys"] = [x for x in wl[t]["buys"] if datetime.fromisoformat(x["filed"]) >= cutoff]
        if not wl[t]["buys"]:
            wl.pop(t)
        else:
            wl[t]["score"] = score(wl[t])
    return added


def ranked(st: dict, cc: dict, held: set[str], now: datetime) -> list[dict]:
    recent = {t for t, when in st.get("copied", {}).items()
              if datetime.fromisoformat(when) > now - timedelta(days=30)}
    picks = [e for t, e in st.get("watchlist", {}).items()
             if t not in held and t not in recent and sum(b["usd"] for b in e["buys"]) >= cc["min_buy_usd"]]
    return sorted(picks, key=lambda e: -e["score"])


def run(cfg: dict, broker, store: Store, kill_switch: bool = False, dry_run: bool = False,
        now: datetime | None = None, feed=None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    res = RunResult(strategy=cfg["name"], started=now)
    st, cc = store.state, cfg["copycat"]

    acct = broker.get_account()
    res.equity = acct["equity"]
    if not store.rows("deposits.csv"):
        store.add_deposit(acct["equity"], "starting balance", now)
        res.notes.append(f"Recorded starting balance ${acct['equity']:,.2f} as the first deposit.")
    today = now.date().isoformat()
    if st["day"] != today:
        st["day"], st["day_start_equity"] = today, acct["equity"]
    market_open = broker.is_market_open()

    # 0. exits (stocks can only be sold while the market is open)
    positions = broker.get_positions()
    res.exits = manage_exits(broker, store, positions, cfg, now, dry_run, market_open)
    if res.exits and not dry_run:
        positions, acct = broker.get_positions(), broker.get_account()
    elif dry_run:
        positions = [p for p in positions if p["symbol"] in st["plans"]]
    res.positions = positions

    # 1. Spotter: read new insider filings (even when trading is paused, so the watchlist stays fresh)
    feed = feed or sec.SecFeed()
    seen = st.setdefault("seen_filings", [])
    got = feed.latest(set(seen), cc["max_filings_per_run"])
    st["seen_filings"] = (seen + got.seen)[-SEEN_KEEP:]
    added = update_watchlist(st, got.buys, cc, now)
    st["last_scan"] = _iso(now)
    res.scanned, res.last_scan = True, st["last_scan"]
    held = {p["symbol"] for p in positions}
    picks = ranked(st, cc, held, now)
    res.filings = {"read": got.filings_read, "insider_buys": len(got.buys), "added": added,
                   "watchlist": len(st["watchlist"]), "error": got.error,
                   "top": [{"ticker": e["ticker"], "company": e["company"], "score": e["score"],
                            "usd": round(sum(b["usd"] for b in e["buys"]), 2), "insiders": len({b["who"] for b in e["buys"]}),
                            "note": describe(e)} for e in picks[:5]]}
    res.notes.append(f"Spotter read {got.filings_read} new insider filings and found {len(got.buys)} purchases "
                     f"({added} by officers or directors). Watchlist: {len(st['watchlist'])} stocks, "
                     f"{len(picks)} big enough to copy.")
    if got.error:
        res.notes.append(got.error)

    # Account-level risk gate
    gate = risk.account_gate(acct["equity"], st["day_start_equity"], store.net_deposits(), kill_switch,
                             st["halted_reason"], cfg["risk"])
    res.gate = gate.reason
    if gate.halt_strategy:
        st["halted_reason"] = gate.reason
    if not gate.allowed:
        return _finish(res, store, acct["equity"], now, None)
    if len(positions) >= cfg["risk"]["max_open_positions"]:
        res.gate = "Max open positions reached; only managing exits."
        return _finish(res, store, acct["equity"], now, None)
    if not picks:
        res.notes.append("No insider buy on the watchlist is big enough to copy yet.")
        return _finish(res, store, acct["equity"], now, None)

    if not market_open:
        for e in picks[:3]:
            c = _candidate(e, pd.DataFrame())
            c.decision, c.decision_note = "WAIT", "Stock market is closed. Will copy when it opens if it still checks out."
            res.candidates.append(c)
        res.notes.append("Stock market closed; picks wait for the next open.")
        return _finish(res, store, acct["equity"], now, None)

    # 2-4. Check the best picks, size them, copy them
    planned, bp, bought = 0.0, acct["buying_power"], 0
    virtual, held_bars = list(positions), {}
    for p in positions:
        held_bars.update(broker.get_bars([p["symbol"]], "1Day", cfg["scout"]["lookback_bars"], "stocks"))
    for e in picks[: cc["max_buys_per_run"] * 3]:
        t = e["ticker"]
        bars = broker.get_bars([t], "1Day", cfg["scout"]["lookback_bars"], "stocks").get(t, pd.DataFrame())
        c = _candidate(e, bars)
        res.candidates.append(c)
        if bought >= cc["max_buys_per_run"]:
            c.decision, c.decision_note = "WAIT", "Already copied enough this run; next run."
            continue
        if not broker.can_buy_fractional(t):
            c.decision, c.decision_note = "SKIP", "Alpaca can't buy part of a share of this stock."
            st["watchlist"].pop(t, None)
            continue
        price = broker.latest_price(t) or (float(bars["close"].iloc[-1]) if len(bars) else None)
        if not price:
            c.decision, c.decision_note = "WAIT", "No live price yet."
            continue
        c.price = price
        chase = (price / avg_price(e) - 1) * 100
        c.move_pct = chase
        c.sentiment_note = f"Now ${price:,.2f}, {chase:+.1f}% vs. what the insiders paid."
        if chase > cc["max_chase_pct"]:
            c.decision, c.decision_note = "SKIP", (f"Price already up {chase:.0f}% since the insiders bought "
                                                   f"(limit {cc['max_chase_pct']}%). Too late to copy.")
            continue
        stop, target = price * (1 - cc["stop_pct"] / 100), price * (1 + cc["target_pct"] / 100)
        c.plan = Plan(trend="copy", support=stop, resistance=target, entry=price, stop=stop, target=target)
        risk.review(c, acct["equity"], bp - planned, virtual, held_bars, cfg["risk"], already_planned_usd=planned)
        if c.risk_verdict == "REJECT":
            c.decision, c.decision_note = "SKIP", f"Risk said no: {c.risk_note}"
            continue
        c.decision, c.confidence = "BUY", 1.0
        c.decision_note = f"Copying {e['company']} insiders. {describe(e)}"
        if not dry_run:
            broker.buy_notional(t, c.size_usd, "stocks", f"cop-{t}-{now:%Y%m%d%H%M%S}")
        st["plans"][t] = {"symbol": t, "asset_class": "stocks", "entry": price, "stop": stop, "initial_stop": stop,
                          "target": target, "opened_at": _iso(now)}
        st.setdefault("copied", {})[t] = _iso(now)
        st["watchlist"].pop(t, None)
        store.append("trades.csv", {"time": _iso(now), "symbol": t, "side": "buy", "usd": f"{c.size_usd:.2f}",
                                    "price": price, "reason": c.decision_note})
        planned += c.size_usd
        bought += 1
        if len(bars):
            held_bars[t] = bars
        virtual.append({"symbol": t, "market_value": c.size_usd, "asset_class": "stocks"})
        res.buys.append(f"BUY {t} ${c.size_usd:,.2f} entry {price:.6g} stop {stop:.6g} target {target:.6g}")

    for c in res.candidates:
        store.append("decisions.csv", {"time": _iso(now), "symbol": c.symbol, "decision": c.decision,
                                       "confidence": f"{c.confidence:.2f}", "risk": c.risk_verdict,
                                       "size_usd": f"{c.size_usd:.2f}", "note": c.decision_note})
    return _finish(res, store, acct["equity"], now, None)


def _candidate(e: dict, bars: pd.DataFrame) -> Candidate:
    return Candidate(symbol=e["ticker"], asset_class="stocks", bars=bars,
                     price=float(bars["close"].iloc[-1]) if len(bars) else avg_price(e),
                     scout_score=e["score"], news_note=describe(e))
