"""One run of the six-bot team for one strategy.

Order of work each run:
  0. Manage open trades: sell anything that hit its stop, its target, or its time limit (no AI needed).
  1. Scout scans the market for unusual volume + price moves with momentum.
  4. Charts draws the trade plan first, because it is free - setups with no clean plan are
     dropped before we spend money asking Claude about them.
  2. News and 3. Sentiment score the survivors (Claude, with rule-based fallbacks).
  5. Risk approves, shrinks or rejects each one.
  6. Decision makes the final BUY / WAIT / SKIP call; only BUY places an order.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .ai import AI
from .alpaca import norm
from .bots import charts, decision, filters, news, risk, scout, sentiment
from .models import Candidate
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    strategy: str
    started: datetime
    equity: float = 0.0
    gate: str = ""
    exits: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    buys: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ai_calls: int = 0
    # For the bot world page and daily recap
    day_start_equity: float = 0.0
    positions: list[dict] = field(default_factory=list)
    scanned: bool = False                                  # False when this run only managed exits
    scan: dict[str, dict] = field(default_factory=dict)    # Scout's measurements for every market it looked at
    last_scan: str | None = None
    filings: dict = field(default_factory=dict)            # Copycat only: what it read from the SEC this run


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def manage_exits(broker, store: Store, positions: list[dict], cfg: dict, now: datetime,
                 dry_run: bool, can_trade_stocks: bool) -> list[str]:
    exits = []
    plans = store.state["plans"]
    for p in positions:
        key = p["symbol"]
        if p["asset_class"] == "stocks" and not can_trade_stocks:
            continue
        plan = plans.get(key)
        if plan is None:
            # A position we have no plan for (e.g. bought by hand): give it a default safety net.
            e = p["avg_entry_price"]
            plan = plans[key] = {"symbol": key, "asset_class": p["asset_class"], "entry": e, "stop": e * 0.95,
                                 "target": e * 1.075, "opened_at": _iso(now), "adopted": True}
        price = p["current_price"]
        held_h = (now - datetime.fromisoformat(plan["opened_at"])).total_seconds() / 3600
        reason = None
        if price <= plan["stop"]:
            reason = f"stop hit ({price:.6g} <= {plan['stop']:.6g})"
        elif price >= plan["target"]:
            reason = f"target hit ({price:.6g} >= {plan['target']:.6g})"
        elif held_h >= cfg["exits"]["max_hold_hours"]:
            reason = f"held {held_h:.0f}h, past the {cfg['exits']['max_hold_hours']}h limit"
        if reason:
            if not dry_run:
                broker.close_position(key)
            store.append("trades.csv", {"time": _iso(now), "symbol": key, "side": "sell",
                                        "usd": f"{p['market_value']:.2f}", "price": price, "reason": reason})
            plans.pop(key, None)
            exits.append(f"SOLD {key}: {reason}")
            continue
        # Lock in breakeven once the trade is up enough.
        r_unit = plan["entry"] - plan.get("initial_stop", plan["stop"])
        if r_unit > 0 and plan["stop"] < plan["entry"] and \
                price >= plan["entry"] + cfg["exits"]["move_stop_to_breakeven_at_r"] * r_unit:
            plan.setdefault("initial_stop", plan["stop"])
            plan["stop"] = plan["entry"]
            exits.append(f"{key}: stop moved to breakeven {plan['entry']:.6g}")
    # Forget plans for positions that are gone (closed by hand, etc.)
    held = {p["symbol"] for p in positions}
    for key in [k for k in plans if k not in held]:
        plans.pop(key)
    return exits


def run(cfg: dict, broker, ai: AI, store: Store, kill_switch: bool = False, dry_run: bool = False,
        now: datetime | None = None) -> RunResult:
    now = now or datetime.now(timezone.utc)
    res = RunResult(strategy=cfg["name"], started=now)
    st = store.state

    acct = broker.get_account()
    equity = res.equity = acct["equity"]
    if not store.rows("deposits.csv"):
        store.add_deposit(equity, "starting balance", now)
        res.notes.append(f"Recorded starting balance ${equity:,.2f} as the first deposit.")
    today = now.date().isoformat()
    if st["day"] != today:
        st["day"], st["day_start_equity"] = today, equity

    stocks = cfg["markets"].get("stocks") or []
    market_open = broker.is_market_open() if stocks else False

    # 0. exits
    positions = broker.get_positions()
    res.exits = manage_exits(broker, store, positions, cfg, now, dry_run, market_open)
    if res.exits and not dry_run:
        positions = broker.get_positions()
        acct = broker.get_account()
    elif dry_run:  # nothing was really sold, so drop the "sold" ones by hand
        positions = [p for p in positions if p["symbol"] in st["plans"]]

    # Account-level risk gate
    res.positions = positions
    gate = risk.account_gate(acct["equity"], st["day_start_equity"], store.net_deposits(), kill_switch,
                             st["halted_reason"], cfg["risk"])
    res.gate = gate.reason
    if gate.halt_strategy:
        st["halted_reason"] = gate.reason
    if not gate.allowed:
        return _finish(res, store, acct["equity"], now, ai)
    if len(positions) >= cfg["risk"]["max_open_positions"]:
        res.gate = "Max open positions reached; only managing exits."
        return _finish(res, store, acct["equity"], now, ai)

    # 1. Scout (exits above run every time; new-trade scans can be less frequent)
    sc = cfg["scout"]
    last = st.get("last_scan")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < sc["scan_every_minutes"] * 60 - 120:
        res.notes.append(f"Next scan for new trades is due {sc['scan_every_minutes']} min after the last one.")
        return _finish(res, store, acct["equity"], now, ai)
    st["last_scan"] = _iso(now)
    res.scanned = True
    universe = {"crypto": cfg["markets"].get("crypto") or []}
    if market_open:
        universe["stocks"] = stocks
    elif stocks:
        res.notes.append("Stock market closed; scanning crypto only.")
    all_bars, cands = {}, []
    for ac, syms in universe.items():
        bars = broker.get_bars(syms, sc["bar_timeframe"], sc["lookback_bars"], ac)
        all_bars.update(bars)
        cands += scout.scan(bars, ac, sc)
        for s, df in bars.items():
            if (m := scout.measure(df, sc)) is not None:
                res.scan[s] = m
    res.notes.append(f"Scout scanned {len(all_bars)} markets"
                     + (f" (no price data for: {', '.join(s for v in universe.values() for s in v if s not in all_bars)})"
                        if len(all_bars) < sum(len(v) for v in universe.values()) else "") + ".")
    cands.sort(key=lambda c: c.scout_score, reverse=True)
    held_keys = {p["symbol"] for p in positions}
    cands = [c for c in cands if norm(c.symbol) not in held_keys][: sc["max_candidates"] * 2]

    # 4. Charts (before AI, to avoid paying for dead-end setups)
    for c in cands:
        c.plan = charts.make_plan(c, cfg["charts"])
    dropped = [c.symbol for c in cands if c.plan is None]
    if dropped:
        res.notes.append(f"Charts found no clean setup for: {', '.join(dropped)}")
    cands = [c for c in cands if c.plan]
    # Optional "don't buy when..." rules from the config (all off unless switched on)
    cands, blocked = filters.apply(cands, cfg.get("filters"), all_bars.get("BTC/USD"), sentiment.fear_greed)
    if blocked:
        res.notes.append("Filters skipped: " + "; ".join(f"{s} ({why})" for s, why in blocked.items()))
    cands = cands[: sc["max_candidates"]]
    res.candidates = cands
    if not cands:
        res.notes.append("Scout found nothing worth a closer look this run.")
        return _finish(res, store, acct["equity"], now, ai)

    # 2. News, 3. Sentiment
    news.analyze(cands, broker, ai)
    sentiment.analyze(cands, ai)

    # 5. Risk
    held_bars = {norm(s): df for s, df in all_bars.items() if norm(s) in held_keys}
    missing = [p for p in positions if p["symbol"] not in held_bars]
    if missing:
        for ac in {p["asset_class"] for p in missing}:
            syms = [_order_symbol(p) for p in missing if p["asset_class"] == ac]
            for s, df in broker.get_bars(syms, sc["bar_timeframe"], sc["lookback_bars"], ac).items():
                held_bars[norm(s)] = df
    for c in cands:
        risk.review(c, acct["equity"], acct["buying_power"], positions, held_bars, cfg["risk"])

    # 6. Decision
    decision.decide(cands, ai, cfg["name"])

    # Place BUY orders, best first, re-checking risk so several buys can't overrun the limits together.
    planned, bp = 0.0, acct["buying_power"]
    virtual = list(positions)
    for c in sorted(cands, key=lambda x: x.confidence, reverse=True):
        if c.decision != cfg["decision"]["buy_only_on"] or c.confidence < cfg["decision"]["min_confidence"]:
            continue
        risk.review(c, acct["equity"], bp - planned, virtual, held_bars, cfg["risk"], already_planned_usd=planned)
        if c.risk_verdict == "REJECT":
            c.decision_note += f" (Risk re-check: {c.risk_note})"
            continue
        coid = f"{cfg['name'][:3]}-{norm(c.symbol)}-{now.strftime('%Y%m%d%H%M%S')}"
        if not dry_run:
            broker.buy_notional(c.symbol, c.size_usd, c.asset_class, coid)
        st["plans"][norm(c.symbol)] = {
            "symbol": norm(c.symbol), "asset_class": c.asset_class, "entry": c.plan.entry, "stop": c.plan.stop,
            "initial_stop": c.plan.stop, "target": c.plan.target, "opened_at": _iso(now)}
        store.append("trades.csv", {"time": _iso(now), "symbol": c.symbol, "side": "buy", "usd": f"{c.size_usd:.2f}",
                                    "price": c.plan.entry, "reason": c.decision_note})
        planned += c.size_usd
        held_bars[norm(c.symbol)] = c.bars
        virtual.append({"symbol": norm(c.symbol), "market_value": c.size_usd, "asset_class": c.asset_class})
        res.buys.append(f"BUY {c.symbol} ${c.size_usd:,.2f} entry {c.plan.entry:.6g} stop {c.plan.stop:.6g} "
                        f"target {c.plan.target:.6g}")

    for c in cands:
        store.append("decisions.csv", {"time": _iso(now), "symbol": c.symbol, "decision": c.decision,
                                       "confidence": f"{c.confidence:.2f}", "risk": c.risk_verdict,
                                       "size_usd": f"{c.size_usd:.2f}", "note": c.decision_note})
    return _finish(res, store, acct["equity"], now, ai)


def _order_symbol(p: dict) -> str:
    s = p["symbol"]
    if p["asset_class"] == "crypto" and "/" not in s:
        for quote in ("USDT", "USDC", "USD", "BTC"):
            if s.endswith(quote):
                return f"{s[: -len(quote)]}/{quote}"
    return s


def _finish(res: RunResult, store: Store, equity: float, now: datetime, ai: AI | None) -> RunResult:
    store.append("equity.csv", {"time": _iso(now), "equity": f"{equity:.2f}", "net_deposits": f"{store.net_deposits():.2f}"})
    store.save()
    res.ai_calls = ai.calls if ai else 0
    res.day_start_equity = store.state["day_start_equity"]
    res.last_scan = store.state.get("last_scan")
    return res
