"""Opening Range Breakout (ORB) for the Forex wing, as a day trade.

Each trading day, once a big market opens (London or New York):
1. The "opening range" is the highest and lowest price of the first `range_minutes` after the open.
2. If the price then breaks above the range, buy; if it breaks below, sell (only the first break counts).
   OANDA can hold these as "buy if it gets here" orders, so the bot doesn't have to watch every minute.
3. The safety stop sits on the other side of the range. Sizing risks about 1% of the account, so a wide
   range means a small trade.
   With `max_cost_pct` set, a day is skipped when the round trip's spread and slip would be more than that
   % of the range (the risk), so fees don't eat a narrow day's small move.
4. Every trade still open at `exit_hour` (local time) is closed: nothing is held overnight, so there is
   no overnight interest.

`simulate` is the lab replay, on 5-minute candles. `run_live` is the same rule on the OANDA practice account,
checked every 30 minutes (see its notes for where live trading can differ a little). Same costs as the rest of the wing: at least OANDA's
usual spread plus half a pip of slip on every fill, and a gap past a price fills at the worse price.
When the entry and the stop are both touched inside one 5-minute candle, the replay assumes the loss.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import backtest as bt
from .forex import (FxEngine, _done, half_cost, label, notional_usd, pip, pnl_usd, size, stops_hit,
                    usd_per_unit_move)
from .oanda import decimals
from .pipeline import RunResult, _iso
from .report import money
from .store import Store

log = logging.getLogger(__name__)

SESSIONS = {"london": ("Europe/London", 8, 0), "newyork": ("America/New_York", 8, 0)}


def sessions(bars: pd.DataFrame, fx: dict) -> dict:
    """Each trading day's 5-minute candles from the open to `exit_hour`, in that market's local time.
    Returns {day: (times, open, high, low, close)} with times as UTC timestamps."""
    tz, h, m = SESSIONS[fx["session"]]
    local = bars.index.tz_convert(tz)
    mins = local.hour * 60 + local.minute
    start, stop = h * 60 + m, int(fx["exit_hour"]) * 60
    keep = (mins >= start) & (mins < stop) & (local.dayofweek < 5)
    sub = bars[keep]
    days = pd.Index(local[keep].date)
    out = {}
    for day, idx in sub.groupby(days).indices.items():
        g = sub.iloc[idx]
        out[day] = (g.index, g["open"].to_numpy(), g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy())
    return out


def day_trade(pair: str, sess: tuple, fx: dict, cost: float) -> dict | None:
    """The day's one trade for a pair, before sizing: entry time and price, direction, stop and exit."""
    times, o, h, l, c = sess
    n_rng = int(fx["range_minutes"]) // 5
    if len(times) <= n_rng:
        return None
    if (times[n_rng - 1] - times[0]) > pd.Timedelta(minutes=int(fx["range_minutes"]) - 5):
        return None    # gaps in the opening minutes (a holiday or a quiet day): skip
    hi, lo = float(h[:n_rng].max()), float(l[:n_rng].min())
    if hi <= lo:
        return None
    hc = half_cost(pair, 0.0, cost)
    # the fee filter: skip days whose range is so narrow that the spread and slip are a big share of the risk
    max_cost = float(fx.get("max_cost_pct") or 0)
    if max_cost and 2 * half_cost(pair, 0.0) > (hi - lo) * max_cost / 100:
        return None
    last_entry = times[0] + pd.Timedelta(minutes=int(fx["range_minutes"])) + pd.Timedelta(hours=float(fx["entry_hours"]))
    for i in range(n_rng, len(times)):
        if times[i] >= last_entry:
            return None
        up, down = h[i] > hi, l[i] < lo
        if not (up or down):
            continue
        if up and down:          # broke both ways inside one candle: count it as a losing buy
            d = 1
        else:
            d = 1 if up else -1
        level, stop = (hi, lo) if d > 0 else (lo, hi)
        entry = (max(o[i], level) if d > 0 else min(o[i], level)) + d * hc
        # the rest of the day: the stop, else close at the exit time. Inside the entry candle we can't tell
        # which came first, so a candle that broke both ways counts as entry-then-stop.
        for j in range(i, len(times)):
            hit = (up and down) if j == i else ((l[j] <= stop) if d > 0 else (h[j] >= stop))
            if hit:
                px = stop if j == i else (min(o[j], stop) if d > 0 else max(o[j], stop))
                return {"pair": pair, "d": d, "t_in": times[i], "entry": entry, "stop": stop, "t_out": times[j],
                        "exit": px - d * hc, "why": "stop hit", "hi": hi, "lo": lo}
        return {"pair": pair, "d": d, "t_in": times[i], "entry": entry, "stop": stop, "t_out": times[-1],
                "exit": float(c[-1]) - d * hc, "why": "end of session", "hi": hi, "lo": lo}
    return None


def simulate(cfg: dict, sess_by_pair: dict[str, dict], start: datetime, end: datetime, cash: float = 100.0,
             cost: float = 1.0) -> bt.SimResult:
    fx, rk = cfg["forex"], cfg["risk"]
    s, e = start.date(), end.date()
    days = sorted({d for ss in sess_by_pair.values() for d in ss if s <= d < e})
    equity, fees = cash, 0.0
    res = bt.SimResult(cfg["name"], [(start, cash)])
    for day in days:
        cands = [t for p, ss in sess_by_pair.items() if day in ss
                 for t in [day_trade(p, ss[day], fx, cost)] if t]
        held, day_pl, day_start = [], 0.0, equity
        for t in sorted(cands, key=lambda x: x["t_in"]):
            if day_pl <= -day_start * rk["max_daily_loss_pct"] / 100:
                break    # the daily loss limit: no new trades today
            held = [h for h in held if h["t_out"] > t["t_in"]]
            gap = abs(t["entry"] - t["stop"])
            # the stop is the far edge of the range: size so that hitting it loses about risk_per_trade_pct
            units, _ = size(t["pair"], t["d"], t["entry"], gap, day_start, held, {**fx, "stop_atr_mult": 1.0}, rk)
            if not units:
                continue
            pl = pnl_usd(t["pair"], t["d"], units, t["entry"], t["exit"])
            fee = units * half_cost(t["pair"], 0.0, cost) * usd_per_unit_move(t["pair"], t["entry"]) * 2
            fees += fee
            day_pl += pl
            held.append({"pair": t["pair"], "direction": t["d"], "notional": notional_usd(t["pair"], units, t["entry"]),
                         "t_out": t["t_out"]})
            res.trades.append({"symbol": t["pair"], "direction": t["d"], "opened": _iso(t["t_in"].to_pydatetime()),
                               "closed": _iso(t["t_out"].to_pydatetime()), "pnl": pl,
                               "cost": notional_usd(t["pair"], units, t["entry"]), "equity_at_open": day_start,
                               "exit": t["why"], "ctx": {"range": f"{t['lo']:.5g}-{t['hi']:.5g}"}})
        equity += day_pl
        res.equity.append((datetime(day.year, day.month, day.day, 23, tzinfo=timezone.utc), equity))
    res.fees = fees
    return res


class OrbEngine(FxEngine):
    """Lab engine for the ORB rule: 5-minute candles, cut into each day's session once per session choice."""

    def __init__(self, intraday: dict[str, pd.DataFrame], start: datetime, end: datetime, cash: float = 100.0):
        super().__init__({}, None, start, end, cash, min_trades=50)
        self.intraday, self._sess = intraday, {}

    def sessions_for(self, fx: dict) -> dict[str, dict]:
        key = (fx["session"], int(fx["exit_hour"]))
        if key not in self._sess:
            self._sess[key] = {p: sessions(df, fx) for p, df in self.intraday.items()}
        return self._sess[key]

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        return simulate(cfg, self.sessions_for(cfg["forex"]), start, end, self.cash, cost)

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        return [{"opened": t["opened"][:16], "pair": label(t["symbol"]), "side": "buy" if t["direction"] > 0 else "sell",
                 "result_pct": round(t["pnl"] / max(t["equity_at_open"], 1e-9) * 100, 2), "exit": t["exit"]}
                for t in res.trades]


def load_engine(cfg: dict, years: int = 8, cache: str | None = None, end: datetime | None = None) -> OrbEngine:
    import os
    import pickle
    from pathlib import Path

    from .oanda import OandaPractice
    now = datetime.now(timezone.utc)
    end = end or datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = end.replace(year=end.year - years)
    if cache and Path(cache).exists():
        intraday = pickle.loads(Path(cache).read_bytes())
    else:
        token = os.environ.get("OANDA_API_TOKEN")
        if not token:
            raise RuntimeError("The ORB test needs OANDA's 5-minute prices: set OANDA_API_TOKEN")
        api = OandaPractice(token, os.environ.get("OANDA_FOREX_ACCOUNT_ID") or "-")
        intraday = {p: api.history(p, "M5", start - timedelta(days=3), end) for p in cfg["markets"]["pairs"]}
        if cache:
            Path(cache).write_bytes(pickle.dumps(intraday))
    return OrbEngine(intraday, start, end)


# ---- the live run -------------------------------------------------------------------------------------------

def run_live(cfg: dict, broker, store: Store, res: RunResult, equity: float, gate, now: datetime,
             dry_run: bool = False) -> RunResult:
    """One 30-minute check of the ORB office on the OANDA practice account.

    - The first check after the opening range ends (8:30 London) marks each pair's range from OANDA's
      5-minute candles and leaves two waiting orders with OANDA: buy just above the range, sell just below.
      Each carries its safety stop (the other edge) and expires when the entry window ends (11:30).
    - Later checks notice fills, cancel the other side, and cancel waiting orders that no longer fit the limits.
    - The first check at or after `exit_hour` (16:00) closes every trade and cancels what's left.

    Where live can differ a little from the lab: a check can come up to 30 minutes after a time, so the
    orders may go in after a break has already started (then only that side is placed, and it fills at
    the current price) and trades close between 16:00 and 16:30. Two fills inside one 30-minute gap can
    briefly go past the open-trade limits. If both sides of a pair fill, only the first counts and the
    second is closed at the next check."""
    from zoneinfo import ZoneInfo
    st, fx, rk = store.state, cfg["forex"], cfg["risk"]
    tz, h, m = SESSIONS[fx["session"]]
    local = now.astimezone(ZoneInfo(tz))
    opens = local.replace(hour=h, minute=m, second=0, microsecond=0)
    range_end = opens + timedelta(minutes=int(fx["range_minutes"]))
    entry_end = range_end + timedelta(hours=float(fx["entry_hours"]))
    close_at = local.replace(hour=int(fx["exit_hour"]), minute=0, second=0, microsecond=0)
    day = local.date().isoformat()
    city = {"london": "London", "newyork": "New York"}[fx["session"]]

    o = st.get("orb") or {"day": day, "placed": False, "orders": {}, "rows": {}}
    _sync(o, broker, store, res, now, dry_run)
    stops_hit(res, store, broker, now)
    if o["day"] != day:          # a new day: anything left from an earlier day is stale
        _cancel_all(o, broker, dry_run)
        _close_all(st, broker, store, res, now, dry_run, "end of session (closed late)")
        o = {"day": day, "placed": False, "orders": {}, "rows": {}}
    st["orb"] = o
    fxinfo = {"style": "orb", "session": fx["session"], "pairs": o["rows"], "bar": None}
    res.forex = fxinfo

    if local.weekday() >= 5:
        res.notes.append("Weekend: the forex market is closed or quiet. The next session is Monday.")
    elif local >= close_at:
        _cancel_all(o, broker, dry_run)
        _close_all(st, broker, store, res, now, dry_run, "end of the trading session")
        res.notes.append(f"After {fx['exit_hour']}:00 {city} time: nothing is held overnight. Next session tomorrow.")
    elif not gate.allowed:
        _cancel_all(o, broker, dry_run)
        res.notes.append(f"No new trades: {gate.reason}")
    elif local < range_end:
        res.notes.append(f"Waiting for the opening range: {opens:%H:%M} to {range_end:%H:%M} {city} time.")
    elif not o["placed"]:
        if local < entry_end:
            _place(cfg, broker, store, res, o, equity, opens, range_end, entry_end, now, dry_run)
        else:
            res.notes.append(f"Missed today's entry window (it ended at {entry_end:%H:%M} {city} time).")
    else:
        _fit_limits(cfg, broker, st, equity, dry_run)
    return _done(res, store, broker, equity, now, {})


def _held(st: dict) -> list[dict]:
    return [{"pair": p, "direction": t["direction"], "notional": t["notional"]} for p, t in st["plans"].items()]


def _place(cfg, broker, store, res, o, equity, opens, range_end, entry_end, now, dry_run) -> None:
    st, fx, rk = store.state, cfg["forex"], cfg["risk"]
    utc = timezone.utc
    n_rng = int(fx["range_minutes"]) // 5
    max_cost = float(fx.get("max_cost_pct") or 0)
    candles = {p: broker.history(p, "M5", opens.astimezone(utc), now) for p in cfg["markets"]["pairs"]}
    ranges = {p: c[(c.index >= opens) & (c.index < range_end)] for p, c in candles.items()}
    if not any(len(r) >= n_rng for r in ranges.values()) and now < range_end + timedelta(hours=1):
        # OANDA may not have finished the last opening candle yet: try again at the next check
        res.notes.append("OANDA hasn't finished the opening range's candles yet. Trying again at the next check.")
        return
    res.scanned = True
    st["last_scan"] = _iso(now)
    held = _held(st)
    for pair in cfg["markets"]["pairs"]:
        dp = decimals(pair)
        row = o["rows"][pair] = {"price": 0.0, "direction": 0, "note": "", "decision": "WAIT", "risk": ""}
        c, rng = candles[pair], ranges[pair]
        if len(c):
            row["price"] = float(c["close"].iloc[-1])
        if len(rng) < n_rng:
            row["note"] = f"OANDA had {len(rng)} of the {n_rng} opening candles (a holiday?). Skipped today."
            continue
        hi, lo = float(rng["high"].max()), float(rng["low"].min())
        rng_txt = f"Range {lo:.{dp}f} to {hi:.{dp}f} ({(hi - lo) / pip(pair):.1f} pips)"
        if hi <= lo:
            row["note"] = f"{rng_txt}: no range. Skipped today."
            continue
        if max_cost and 2 * half_cost(pair, 0.0) > (hi - lo) * max_cost / 100:
            row["decision"] = "SKIP"
            row["note"] = f"{rng_txt}: too narrow, fees would be over {max_cost:g}% of the risk. Skipped today."
            continue
        # a break that already started before this check: only that side counts (the lab's "first break")
        first, stopped = 0, False
        for _, b in c[c.index >= range_end].iterrows():
            up, down = float(b["high"]) > hi, float(b["low"]) < lo
            if first == 0 and (up or down):
                first, stopped = (1 if up else -1), up and down
            elif first:
                stopped = stopped or (float(b["low"]) <= lo if first > 0 else float(b["high"]) >= hi)
            if stopped:
                break
        if stopped:
            row["note"] = f"{rng_txt}: it already broke out and came back to the other side. Skipped today."
            continue
        rec = o["orders"][pair] = {"buy": None, "sell": None, "hi": hi, "lo": lo, "taken": False}
        placed = []
        for d in ([first] if first else [1, -1]):
            level, stop = (hi, lo) if d > 0 else (lo, hi)
            units, note = size(pair, d, level, hi - lo, equity, held, {**fx, "stop_atr_mult": 1.0}, rk)
            row["risk"] = note
            if not units:
                continue
            side = "buy" if d > 0 else "sell"
            if not dry_run:
                got = broker.stop_order(pair, units * d, level, stop, entry_end.astimezone(utc),
                                        f"{cfg['name']}-{now:%Y%m%d}-{side}")
                if got["filled"]:
                    _filled(pair, d, got["trade_id"], {"price": got["price"], "state": "OPEN"}, rec, units, broker, store,
                            res, now)
                    break
                if not got["order_id"]:
                    row["risk"] = f"OANDA didn't take the {side} order: {got['reason']}"
                    continue
                rec[side] = got["order_id"]
                rec[f"{side}_units"] = units
            placed.append(f"{side} {units:,} above {level:.{dp}f}" if d > 0 else f"{side} {units:,} below {level:.{dp}f}")
        if rec["taken"]:
            continue
        if placed:
            row["decision"] = "ORDERS"
            row["note"] = f"{rng_txt}. Waiting orders: " + ", ".join(placed) + "."
            res.notes.append(f"{label(pair)}: waiting orders to " + " and ".join(placed) + " (safety stop at the other edge).")
        else:
            row["decision"] = "SKIP"
            row["note"] = f"{rng_txt}. No room for a trade."
    if not dry_run:
        o["placed"] = True
    for p, r in o["rows"].items():
        store.append("decisions.csv", {"time": _iso(now), "symbol": p, "decision": r["decision"], "confidence": "",
                                       "risk": r.get("risk", ""), "size_usd": "", "note": r["note"]})


def _filled(pair, d, trade_id, t, rec, units, broker, store, res, now) -> None:
    """A waiting order filled. The first fill of the day is the trade; a second one (the other side) is closed."""
    st = store.state
    side = "BUY" if d > 0 else "SELL"
    dp = decimals(pair)
    fill = float(t["price"])
    stop = rec["lo"] if d > 0 else rec["hi"]
    usd = notional_usd(pair, units, fill)
    store.append("trades.csv", {"time": _iso(now), "symbol": pair, "side": "buy", "usd": f"{usd:.2f}", "price": fill,
                                "reason": f"{side} {units:,} units: broke {'above' if d > 0 else 'below'} the opening range"})
    if rec["taken"]:      # the other side filled too: only the first break counts
        done = ({"price": fill, "pl": float(t.get("pl", 0))} if t.get("state") == "CLOSED"
                else broker.close_trade(trade_id))
        store.append("trades.csv", {"time": _iso(now), "symbol": pair, "side": "sell", "usd": f"{usd + done['pl']:.2f}",
                                    "price": done["price"], "reason": f"second break of the day, closed: {money(done['pl'])}"})
        res.exits.append(f"SOLD {label(pair)}: the other side filled too, so it was closed ({money(done['pl'])})")
        return
    rec["taken"] = True
    st["plans"][pair] = {"pair": pair, "trade_id": trade_id, "direction": d, "units": units, "entry": fill,
                         "stop": stop, "notional": usd, "opened_at": _iso(now), "day": st["orb"]["day"]}
    res.buys.append(f"{side} {label(pair)} {units:,} units at {fill:.{dp}f}, stop {stop:.{dp}f}")
    row = st["orb"]["rows"].get(pair)
    if row is not None:
        row.update(direction=d, decision=side)
    other = "sell" if d > 0 else "buy"
    if rec.get(other):
        broker.cancel_order(rec[other])
        rec[other] = None


def _sync(o: dict, broker, store: Store, res: RunResult, now: datetime, dry_run: bool) -> None:
    """Waiting orders that are gone since the last check: filled (a trade opened) or expired."""
    if dry_run or not any(r.get("buy") or r.get("sell") for r in o["orders"].values()):
        return
    store.state["orb"] = o
    waiting = {x["id"] for x in broker.pending_orders()}
    for pair, rec in o["orders"].items():
        fills = []
        for side, d in (("buy", 1), ("sell", -1)):
            oid = rec.get(side)
            if not oid or oid in waiting:
                continue
            rec[side] = None
            got = broker.get_order(oid)
            if got["state"] == "FILLED" and got["trade_id"]:
                fills.append((d, got["trade_id"], broker.trade(got["trade_id"]), rec.get(f"{side}_units", 0)))
        for d, tid, t, units in sorted(fills, key=lambda x: x[2].get("opened") or ""):
            _filled(pair, d, tid, t, rec, int(units or abs(t.get("units", 0))), broker, store, res, now)


def _cancel_all(o: dict, broker, dry_run: bool) -> None:
    for rec in o["orders"].values():
        for side in ("buy", "sell"):
            if rec.get(side):
                if not dry_run:
                    broker.cancel_order(rec[side])
                rec[side] = None


def _close_all(st: dict, broker, store: Store, res: RunResult, now: datetime, dry_run: bool, why: str) -> None:
    for p, plan in list(st["plans"].items()):
        dp = decimals(p)
        if dry_run:
            res.exits.append(f"SOLD {label(p)}: {why} (dry run)")
            continue
        done = broker.close_trade(plan["trade_id"])
        px = done["price"] if done["price"] is not None else plan["entry"]
        store.append("trades.csv", {"time": _iso(now), "symbol": p, "side": "sell",
                                    "usd": f"{plan['notional'] + done['pl']:.2f}", "price": px,
                                    "reason": f"{why}, {money(done['pl'])}"})
        res.exits.append(f"SOLD {label(p)}: {why} at {px:.{dp}f}, {money(done['pl'])}")
        st["plans"].pop(p)


def _fit_limits(cfg: dict, broker, st: dict, equity: float, dry_run: bool) -> None:
    """After a fill, waiting orders for other pairs may no longer fit the limits (open trades, same dollar bet,
    leverage): cancel those."""
    fx, rk, o = cfg["forex"], cfg["risk"], st["orb"]
    held = _held(st)
    for pair, rec in o["orders"].items():
        for side, d in (("buy", 1), ("sell", -1)):
            if not rec.get(side) or pair in st["plans"]:
                continue
            level = rec["hi"] if d > 0 else rec["lo"]
            units, note = size(pair, d, level, rec["hi"] - rec["lo"], equity, held, {**fx, "stop_atr_mult": 1.0}, rk)
            if units:
                continue
            if not dry_run:
                broker.cancel_order(rec[side])
            rec[side] = None
            row = o["rows"].get(pair)
            if row is not None:
                row.update(decision="SKIP", risk=f"Cancelled the waiting {side} order: {note}")
