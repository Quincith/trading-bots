"""The Forex wing: two offices that trade currency pairs on OANDA practice (demo) accounts.

  Forex office ("trend"): a classic trend-following rule, the one the famous 1980s "Turtle traders" used.
      Buy a currency pair when it closes above its highest price of the last 55 days and is above its
      200-day average; sell it (bet it falls) when it closes below its 55-day low and is below its average.
      Get out when it closes past the opposite 20-day high/low, or when the safety stop is hit.
  Copycat FX office ("cot"): copies the big hedge funds. Every Friday the CFTC publishes how many currency
      futures the "leveraged funds" hold. When their net bet on a currency is large (10%+ of all open
      contracts), copy it; get out when their net bet flips to the other side, or the safety stop is hit.

Both act once a day, after the forex day ends (5pm New York). Each trade risks about 1% of the account:
the size is set so that hitting the safety stop loses about $1 on $100. OANDA holds the stop, so it fills
even between the bot's 30-minute checks. No AI is used.

The same code runs live and in the lab (`simulate`), so the lab tests exactly what the bots do.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import backtest as bt
from . import fxdata
from .bots import risk
from .indicators import atr, ema
from .oanda import base_ccy, decimals, quote_ccy
from .pipeline import RunResult, _finish, _iso
from .report import money, performance_block
from .store import Store

log = logging.getLogger(__name__)

PAIRS = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD", "USD_CHF", "NZD_USD"]
# The smallest gap between the buy and sell price we assume, in pips (0.0001, or 0.01 for yen pairs).
# These are about what OANDA's standard account charges; the lab uses the bigger of these and the real one.
MIN_SPREAD_PIPS = {"EUR_USD": 1.4, "GBP_USD": 2.0, "USD_JPY": 1.4, "AUD_USD": 1.4, "USD_CAD": 2.2,
                   "USD_CHF": 1.8, "NZD_USD": 2.0}
SLIP_PIPS = 0.5          # each market order fills half a pip worse than the price we saw
FINANCING_PCT = 2.0      # holding a trade overnight costs interest; we charge 2% a year of the trade's size


def pip(pair: str) -> float:
    return 0.01 if quote_ccy(pair) == "JPY" else 0.0001


def label(pair: str) -> str:
    return pair.replace("_", "/")


def usd_per_unit_move(pair: str, price: float) -> float:
    """Dollars won or lost per unit when the price moves by 1.0 (all our pairs include the US dollar)."""
    return 1.0 if quote_ccy(pair) == "USD" else 1.0 / price


def notional_usd(pair: str, units: float, price: float) -> float:
    """What the trade controls, in dollars. 1,000 units of EUR/USD at 1.10 controls $1,100."""
    return abs(units) * (price if quote_ccy(pair) == "USD" else 1.0)


def usd_side(pair: str, direction: int) -> int:
    """+1 if the trade wins when the US dollar rises, -1 if it wins when the dollar falls."""
    return direction if base_ccy(pair) == "USD" else -direction


def pnl_usd(pair: str, direction: int, units: float, entry: float, exit_: float) -> float:
    return direction * abs(units) * (exit_ - entry) * usd_per_unit_move(pair, exit_)


def half_cost(pair: str, spread: float, cost: float = 1.0) -> float:
    """Price given up on one side of a trade: half the spread plus slippage."""
    return (max(spread, MIN_SPREAD_PIPS.get(pair, 2.0) * pip(pair)) / 2 + SLIP_PIPS * pip(pair)) * cost


# ---- the two rules ------------------------------------------------------------------------------------

def trend_table(df: pd.DataFrame, fx: dict) -> pd.DataFrame:
    """Each day's breakout levels, built only from the days before it (no peeking at the future)."""
    n_in, n_out = int(fx["entry_days"]), int(fx["exit_days"])
    t = pd.DataFrame(index=df.index)
    t["close"] = df["close"]
    t["hi_in"] = df["high"].shift(1).rolling(n_in).max()
    t["lo_in"] = df["low"].shift(1).rolling(n_in).min()
    t["hi_out"] = df["high"].shift(1).rolling(n_out).max()
    t["lo_out"] = df["low"].shift(1).rolling(n_out).min()
    n_ema = int(fx.get("trend_ema_days") or 0)
    t["ema"] = ema(df["close"], n_ema) if n_ema else float("nan")
    t["atr"] = atr(df, int(fx["atr_days"]))
    return t


@dataclass
class Signal:
    pair: str
    direction: int            # +1 buy, -1 sell, 0 nothing to do
    price: float
    atr: float
    strength: float           # used to pick the best ones first
    note: str
    exit_long: bool = False   # should a trade we hold that bets up close now?
    exit_short: bool = False
    info: dict = field(default_factory=dict)


def trend_signal(pair: str, row: pd.Series, fx: dict) -> Signal:
    c, a = float(row["close"]), float(row["atr"])
    if any(math.isnan(float(row[k])) for k in ("hi_in", "lo_in", "hi_out", "lo_out", "atr")):
        return Signal(pair, 0, c, a, 0, "Not enough price history yet.")
    use_ema = bool(fx.get("trend_ema_days"))
    e = float(row["ema"]) if use_ema else float("nan")
    up_ok, down_ok = (c > e, c < e) if use_ema else (True, True)
    n_in = int(fx["entry_days"])
    info = {"hi": round(float(row["hi_in"]), 6), "lo": round(float(row["lo_in"]), 6),
            "avg": None if not use_ema else round(e, 6)}
    d, strength = 0, 0.0
    if c > row["hi_in"] and up_ok:
        d, strength = 1, (c - row["hi_in"]) / a
        note = f"Closed above its {n_in}-day high ({row['hi_in']:.{decimals(pair)}f}) in an uptrend: buy."
    elif c < row["lo_in"] and down_ok:
        d, strength = -1, (row["lo_in"] - c) / a
        note = f"Closed below its {n_in}-day low ({row['lo_in']:.{decimals(pair)}f}) in a downtrend: sell."
    elif c > row["hi_in"] or c < row["lo_in"]:
        note = f"Broke out, but against its {fx['trend_ema_days']}-day average. Skipped."
    else:
        room = min(row["hi_in"] - c, c - row["lo_in"]) / a
        note = f"Inside its {n_in}-day range, {room:.1f} daily swings from a breakout."
    return Signal(pair, d, c, a, float(strength), note, exit_long=c < row["lo_out"], exit_short=c > row["hi_out"],
                  info=info)


def cot_signal(pair: str, close: float, a: float, cot_now: dict, fx: dict) -> Signal:
    ccy = quote_ccy(pair) if base_ccy(pair) == "USD" else base_ccy(pair)
    rec = cot_now.get(ccy)
    if rec is None or math.isnan(a):
        return Signal(pair, 0, close, a, 0, "No hedge fund report yet.")
    group = fx.get("group", "leveraged")
    net, prev = rec[group], rec[f"{group}_prev"]
    flip = -1 if base_ccy(pair) == "USD" else 1    # funds long yen = betting USD/JPY falls
    lo, out = float(fx["min_net_pct"]), float(fx.get("exit_net_pct", 0))
    want = 1 if net >= lo else -1 if net <= -lo else 0
    if want and fx.get("need_growing") and (net - prev) * want <= 0:
        want, why = 0, " but it shrank this week"
    else:
        why = ""
    d = want * flip
    side = "up" if net > 0 else "down"
    note = (f"Hedge funds' net bet on {ccy}: {net:+.1f}% of all contracts ({side}), was {prev:+.1f}% "
            f"(report of {rec['report']}).")
    note += (f" Copy: {'buy' if d > 0 else 'sell'} {label(pair)}." if d else
             f" Below the {lo:g}% needed to copy{why}.")
    # get out once the funds' bet has shrunk to `exit_net_pct` (0 = it flipped sides)
    long_ccy_ok, short_ccy_ok = net > out, net < -out
    exit_long = not (long_ccy_ok if flip == 1 else short_ccy_ok)
    exit_short = not (short_ccy_ok if flip == 1 else long_ccy_ok)
    return Signal(pair, d, close, a, abs(net), note, exit_long=exit_long, exit_short=exit_short,
                  info={"ccy": ccy, "net": round(net, 1), "prev": round(prev, 1), "report": rec["report"]})


# ---- position sizing (the same rules live and in the lab) ------------------------------------------------

def size(pair: str, direction: int, price: float, a: float, equity: float, held: list[dict], fx: dict,
         rk: dict) -> tuple[int, str]:
    """How many units to trade. Returns (units, note); 0 units means Risk said no, and the note says why."""
    if len(held) >= rk["max_open_positions"]:
        return 0, f"Already at {rk['max_open_positions']} open trades."
    side = usd_side(pair, direction)
    same = sum(usd_side(h["pair"], h["direction"]) == side for h in held)
    if same >= rk["max_same_usd_side"]:
        return 0, (f"Already {same} trades betting the US dollar will {'rise' if side > 0 else 'fall'}; "
                   "they move together, so one more would be the same bet again.")
    stop_dist = a * float(fx["stop_atr_mult"])
    risk_usd = equity * rk["risk_per_trade_pct"] / 100
    units = risk_usd / (stop_dist * usd_per_unit_move(pair, price))
    notes = []
    cap = equity * rk["max_position_pct"] / 100
    if notional_usd(pair, units, price) > cap:
        units = units * cap / notional_usd(pair, units, price)
        notes.append(f"capped at {rk['max_position_pct']}% of the account")
    room = equity * rk["max_total_exposure_pct"] / 100 - sum(h["notional"] for h in held)
    if notional_usd(pair, units, price) > room:
        units = max(room, 0) / max(notional_usd(pair, 1, price), 1e-9)
        notes.append(f"limited by the {rk['max_total_exposure_pct'] / 100:g}x leverage cap")
    units = int(units)
    if units < 1:
        return 0, "Too small after the limits."
    risk_now = units * stop_dist * usd_per_unit_move(pair, price)
    return units, (f"{units:,} units (controls {money(notional_usd(pair, units, price))}), risking "
                   f"{money(risk_now)} ({risk_now / equity * 100:.1f}% of the account) if the stop is hit"
                   + (f"; {', '.join(notes)}" if notes else ""))


def stop_price(direction: int, entry: float, a: float, fx: dict) -> float:
    return entry - direction * a * float(fx["stop_atr_mult"])


def signals_at(cfg: dict, tables: dict[str, pd.DataFrame], i_by_pair: dict[str, int], cot: pd.DataFrame | None,
               when: datetime) -> dict[str, Signal]:
    fx, out = cfg["forex"], {}
    cot_now = fxdata.cot_as_of(cot, when) if fx["style"] == "cot" and cot is not None else {}
    for pair, i in i_by_pair.items():
        row = tables[pair].iloc[i]
        if fx["style"] == "trend":
            out[pair] = trend_signal(pair, row, fx)
        else:
            out[pair] = cot_signal(pair, float(row["close"]), float(row["atr"]), cot_now, fx)
    return out


def tables_for(cfg: dict, bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    fx = cfg["forex"]
    if fx["style"] == "trend":
        return {p: trend_table(df, fx) for p, df in bars.items()}
    return {p: pd.DataFrame({"close": df["close"], "atr": atr(df, int(fx["atr_days"]))}) for p, df in bars.items()}


def bar_close(t: pd.Timestamp) -> datetime:
    """Daily candles are labelled by their start; the decision is made when the day ends."""
    return (t + pd.Timedelta(days=1)).to_pydatetime()


# ---- the lab: replay the rules over past prices ------------------------------------------------------------

def simulate(cfg: dict, bars: dict[str, pd.DataFrame], cot: pd.DataFrame | None, start: datetime, end: datetime,
             cash: float = 100.0, cost: float = 1.0) -> bt.SimResult:
    """Day-by-day replay. Decisions at each day's close are filled at the next day's open, with the spread,
    slippage and overnight financing charged. Safety stops are checked against each day's high and low."""
    fx, rk = cfg["forex"], cfg["risk"]
    pairs = [p for p in cfg["markets"]["pairs"] if p in bars]
    tables = tables_for(cfg, {p: bars[p] for p in pairs})
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    days = sorted(set().union(*[set(bars[p].index[(bars[p].index >= s) & (bars[p].index < e)]) for p in pairs]))
    pos: dict[str, dict] = {}
    pending_exit: set[str] = set()
    pending_entry: list[tuple] = []
    realized, fees = cash, 0.0
    res = bt.SimResult(cfg["name"], [(start, cash)])
    last_close: dict[str, float] = {}

    def close_trade(p, px, when, why):
        nonlocal realized
        t = pos.pop(p)
        pl = pnl_usd(p, t["direction"], t["units"], t["entry"], px)
        realized += pl
        res.trades.append({"symbol": p, "direction": t["direction"], "opened": t["opened"], "closed": _iso(when),
                           "pnl": pl - t["financing"], "cost": t["notional"], "equity_at_open": t["equity"],
                           "exit": why, "ctx": t["ctx"]})

    for day in days:
        i_by_pair = {}
        opened_now = set()
        for p in pairs:
            df = bars[p]
            if day not in df.index:
                continue
            i = df.index.get_loc(day)
            i_by_pair[p] = i
            row = df.iloc[i]
            hc = half_cost(p, float(row["spread"]), cost)
            # 1. orders decided at yesterday's close fill at today's open
            if p in pending_exit and p in pos:
                d = pos[p]["direction"]
                fees += pos[p]["units"] * hc * usd_per_unit_move(p, float(row["open"]))
                close_trade(p, float(row["open"]) - d * hc, day, "rule exit")
            for (q, d, units, a, note, ctx, eq) in pending_entry:
                if q != p or p in pos:
                    continue
                fill = float(row["open"]) + d * hc
                pos[p] = {"direction": d, "units": units, "entry": fill, "stop": stop_price(d, fill, a, fx),
                          "notional": notional_usd(p, units, fill), "opened": _iso(day), "financing": 0.0,
                          "ctx": ctx, "equity": eq}
                fees += units * hc * usd_per_unit_move(p, fill)
                opened_now.add(p)
            # 2. the safety stop, held by the broker, can fill any time during the day
            if p in pos:
                t = pos[p]
                d, stp = t["direction"], t["stop"]
                hit = float(row["low"]) <= stp if d > 0 else float(row["high"]) >= stp
                if hit:
                    gap = float(row["open"]) if p not in opened_now else stp
                    px = min(gap, stp) if d > 0 else max(gap, stp)    # a gap past the stop fills at the open
                    fees += t["units"] * hc * usd_per_unit_move(p, px)
                    close_trade(p, px - d * hc, day, "stop hit")
                else:   # overnight financing, paid each day the trade stays open
                    f = t["notional"] * FINANCING_PCT / 100 / 365 * cost
                    t["financing"] += f
                    realized -= f
            last_close[p] = float(row["close"])
        pending_exit, pending_entry = set(), []
        when = bar_close(day)
        eq = realized + sum(pnl_usd(p, t["direction"], t["units"], t["entry"], last_close[p]) for p, t in pos.items())
        res.equity.append((when, eq))
        # 3. at the close: decide tomorrow's exits and entries
        sig = signals_at(cfg, tables, i_by_pair, cot, when)
        for p, t in pos.items():
            sg = sig.get(p)
            if sg and ((t["direction"] > 0 and sg.exit_long) or (t["direction"] < 0 and sg.exit_short)):
                pending_exit.add(p)
        held = [{"pair": p, "direction": t["direction"], "notional": t["notional"]}
                for p, t in pos.items() if p not in pending_exit]
        for sg in sorted((x for x in sig.values() if x.direction and x.pair not in pos), key=lambda x: -x.strength):
            units, _ = size(sg.pair, sg.direction, sg.price, sg.atr, eq, held, fx, rk)
            if units:
                pending_entry.append((sg.pair, sg.direction, units, sg.atr, sg.note, dict(sg.info), eq))
                held.append({"pair": sg.pair, "direction": sg.direction,
                             "notional": notional_usd(sg.pair, units, sg.price)})
    # trades still open at the end count in the value at the last close, not as finished trades
    res.fees = fees
    return res


class FxEngine:
    """Lab engine for the Forex wing: past daily prices for each pair (and the CFTC reports for Copycat FX)."""
    benchmark_label = "Do nothing (keep the cash)"

    def __init__(self, bars: dict[str, pd.DataFrame], cot: pd.DataFrame | None, start: datetime, end: datetime,
                 cash: float = 100.0, min_trades: int = 15):
        self.bars, self.cot, self.start, self.end, self.cash, self.min_trades = bars, cot, start, end, cash, min_trades

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        return simulate(cfg, self.bars, self.cot, start, end, self.cash, cost)

    def benchmark(self, start: datetime, end: datetime) -> bt.SimResult:
        return bt.SimResult("benchmark", [(start, self.cash), (end, self.cash)])

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        rows = []
        for t in res.trades:
            o, c = datetime.fromisoformat(t["opened"]), datetime.fromisoformat(t["closed"])
            rows.append({"opened": o.strftime("%Y-%m-%d"), "pair": label(t["symbol"]),
                         "side": "buy" if t["direction"] > 0 else "sell",
                         "result_pct": round(t["pnl"] / max(t["equity_at_open"], 1e-9) * 100, 2),
                         "exit": t["exit"], "days_held": round((c - o).total_seconds() / 86400, 1),
                         **{k: v for k, v in t["ctx"].items() if k in ("net", "prev")}})
        return rows


def load_engine(strategy: str, cfg: dict, years: int = 8, cache: str | None = None,
                end: datetime | None = None) -> FxEngine:
    """Downloads `years` of daily prices (plus a warm-up year for the averages) and, for Copycat FX, the
    CFTC reports. The month in progress is left out."""
    import pickle
    from pathlib import Path
    now = datetime.now(timezone.utc)
    end = end or datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = end.replace(year=end.year - years)
    if cache and Path(cache).exists():
        bars, cot = pickle.loads(Path(cache).read_bytes())
    else:
        bars = {p: fxdata.daily_prices(p, (start - timedelta(days=400)).date(), end.date())
                for p in cfg["markets"]["pairs"]}
        cot = fxdata.fetch_cot((start - timedelta(days=60)).date())
        if cache:
            Path(cache).write_bytes(pickle.dumps((bars, cot)))
    return FxEngine(bars, cot, start, end, min_trades=20 if cfg["forex"]["style"] == "trend" else 12)


# ---- the live run -------------------------------------------------------------------------------------------

def run(cfg: dict, broker, store: Store, kill_switch: bool = False, dry_run: bool = False,
        now: datetime | None = None, cot_source=None) -> RunResult:
    """One 30-minute check. Most checks only look at the account; the real work happens once a day, on the
    first check after the forex day closes (5pm New York)."""
    now = now or datetime.now(timezone.utc)
    res = RunResult(strategy=cfg["name"], started=now)
    st, fx, rk = store.state, cfg["forex"], cfg["risk"]
    acct = broker.get_account()
    if not store.rows("deposits.csv"):
        store.add_deposit(cfg["start_balance"], "starting balance (practice money)", now)
        res.notes.append(f"Started this office with {money(cfg['start_balance'])} of the practice account's money.")
    st.setdefault("base_nav", acct["nav"])
    # The practice account may hold far more than $100; this office counts only its own gains and losses.
    equity = store.net_deposits() + acct["nav"] - st["base_nav"]
    res.equity = equity
    today = now.date().isoformat()
    if st["day"] != today:
        st["day"], st["day_start_equity"] = today, equity

    # Trades OANDA closed on its own (a safety stop was hit)
    open_now = {t["id"]: t for t in broker.open_trades()}
    for p, plan in list(st["plans"].items()):
        if plan["trade_id"] in open_now:
            continue
        done = broker.closed_trade(plan["trade_id"]) or {"price": plan["stop"], "pl": 0.0}
        store.append("trades.csv", {"time": _iso(now), "symbol": p, "side": "sell",
                                    "usd": f"{plan['notional'] + done['pl']:.2f}", "price": done["price"],
                                    "reason": f"stop hit ({done['price']:.{decimals(p)}f}), {money(done['pl'])}"})
        res.exits.append(f"SOLD {label(p)}: stop hit at {done['price']:.{decimals(p)}f}, {money(done['pl'])}")
        st["plans"].pop(p)

    bars = {p: broker.daily_bars(p, int(cfg["lookback_days"])) for p in cfg["markets"]["pairs"]}
    bars = {p: df for p, df in bars.items() if len(df)}
    newest = max((df.index[-1] for df in bars.values()), default=None)
    gate = risk.account_gate(equity, st["day_start_equity"], store.net_deposits(), kill_switch, st["halted_reason"], rk)
    res.gate = gate.reason
    if gate.halt_strategy:
        st["halted_reason"] = gate.reason

    fxinfo = {"style": fx["style"], "pairs": {}, "bar": newest.isoformat() if newest is not None else None}
    res.forex = fxinfo
    if newest is None:
        res.notes.append("OANDA sent no prices this run.")
        return _done(res, store, broker, equity, now, bars)
    if st.get("last_bar") == newest.isoformat():
        res.notes.append("Already traded on the last finished day. The next one ends at 5pm New York time.")
        fxinfo["pairs"] = st.get("last_signals", {})
        return _done(res, store, broker, equity, now, bars)

    res.scanned = True
    st["last_scan"] = _iso(now)
    cot = None
    if fx["style"] == "cot":
        try:
            cot = (cot_source or fxdata.fetch_cot)((now - timedelta(days=120)).date())
        except Exception as e:   # the CFTC site can be slow; try again on the next check
            res.notes.append(f"Couldn't read the CFTC report ({e}). Will try again next run.")
            return _done(res, store, broker, equity, now, bars)
    tables = tables_for(cfg, bars)
    sig = signals_at(cfg, tables, {p: len(t) - 1 for p, t in tables.items()}, cot, now)
    fxinfo["report"] = next((s.info.get("report") for s in sig.values() if s.info.get("report")), None)

    # Exits by rule
    for p, plan in list(st["plans"].items()):
        sg = sig.get(p)
        if not sg or not ((plan["direction"] > 0 and sg.exit_long) or (plan["direction"] < 0 and sg.exit_short)):
            continue
        why = ("closed past its " + str(fx["exit_days"]) + "-day " + ("low" if plan["direction"] > 0 else "high")
               if fx["style"] == "trend" else "the hedge funds' bet shrank or flipped")
        done = {"price": sg.price, "pl": pnl_usd(p, plan["direction"], plan["units"], plan["entry"], sg.price)}
        if not dry_run:
            done = broker.close_trade(plan["trade_id"])
            store.append("trades.csv", {"time": _iso(now), "symbol": p, "side": "sell",
                                        "usd": f"{plan['notional'] + done['pl']:.2f}", "price": done["price"],
                                        "reason": f"rule exit: {why}, {money(done['pl'])}"})
            st["plans"].pop(p)
        res.exits.append(f"SOLD {label(p)}: {why}, {money(done['pl'])}")

    # Entries
    held = [{"pair": p, "direction": t["direction"], "notional": t["notional"]} for p, t in st["plans"].items()]
    for sg in sorted(sig.values(), key=lambda x: -x.strength):
        row = {"price": sg.price, "direction": sg.direction, "note": sg.note, **sg.info, "decision": "WAIT",
               "risk": ""}
        fxinfo["pairs"][sg.pair] = row
        if not sg.direction:
            continue
        if sg.pair in st["plans"]:
            row["decision"], row["risk"] = "HOLD", "Already in this trade."
            continue
        if not gate.allowed:
            row["decision"], row["risk"] = "SKIP", gate.reason
            continue
        units, note = size(sg.pair, sg.direction, sg.price, sg.atr, equity, held, fx, rk)
        row["risk"] = note
        if not units:
            row["decision"] = "SKIP"
            continue
        stop = stop_price(sg.direction, sg.price, sg.atr, fx)
        row.update(decision="BUY" if sg.direction > 0 else "SELL", units=units, stop=round(stop, 6))
        side = "buy" if sg.direction > 0 else "sell"
        if not dry_run:
            got = broker.market_order(sg.pair, units * sg.direction, stop, f"{cfg['name']}-{now:%Y%m%d}")
            if not got["filled"]:
                row["decision"], row["risk"] = "SKIP", f"OANDA didn't fill it: {got['reason']}"
                continue
            fill = got["price"]
            st["plans"][sg.pair] = {"pair": sg.pair, "trade_id": got["trade_id"], "direction": sg.direction,
                                    "units": units, "entry": fill, "stop": stop, "notional": notional_usd(sg.pair, units, fill),
                                    "opened_at": _iso(now)}
            store.append("trades.csv", {"time": _iso(now), "symbol": sg.pair, "side": "buy",
                                        "usd": f"{notional_usd(sg.pair, units, fill):.2f}", "price": fill,
                                        "reason": f"{side.upper()} {units:,} units. {sg.note}"})
        held.append({"pair": sg.pair, "direction": sg.direction, "notional": notional_usd(sg.pair, units, sg.price)})
        res.buys.append(f"{side.upper()} {label(sg.pair)} {units:,} units at {sg.price:.{decimals(sg.pair)}f}, "
                        f"stop {stop:.{decimals(sg.pair)}f}")
    for p, r in fxinfo["pairs"].items():
        store.append("decisions.csv", {"time": _iso(now), "symbol": p, "decision": r["decision"], "confidence": "",
                                       "risk": r.get("risk", ""), "size_usd": "", "note": r["note"]})
    if not dry_run:
        st["last_bar"], st["last_signals"] = newest.isoformat(), fxinfo["pairs"]
    return _done(res, store, broker, equity, now, bars)


def _done(res: RunResult, store: Store, broker, equity: float, now: datetime, bars: dict) -> RunResult:
    trades = {t["id"]: t for t in broker.open_trades()}
    for p, plan in store.state["plans"].items():
        t = trades.get(plan["trade_id"])
        px = float(bars[p]["close"].iloc[-1]) if p in bars and len(bars[p]) else plan["entry"]
        res.positions.append({"symbol": p, "qty": plan["units"] * plan["direction"], "market_value": plan["notional"],
                              "avg_entry_price": plan["entry"], "current_price": px, "stop": plan["stop"],
                              "unrealized": t["unrealized"] if t else None})
    return _finish(res, store, equity, now, None)


# ---- run report -------------------------------------------------------------------------------------------

def render(res: RunResult, store: Store, cfg: dict, dry_run: bool) -> str:
    title = cfg.get("title", res.strategy.title())
    out = [f"# {title} office — {res.started:%Y-%m-%d %H:%M} UTC" + (" (DRY RUN, no orders sent)" if dry_run else ""),
           "", "_OANDA practice account. This office counts only its own trades, starting from "
           f"{money(cfg['start_balance'])}._", ""]
    out += performance_block(store) + [""]
    if res.gate and res.gate != "ok":
        out += [f"**Risk:** {res.gate}", ""]
    if res.exits:
        out += ["## Trades closed"] + [f"- {x}" for x in res.exits] + [""]
    if res.buys:
        out += ["## New trades"] + [f"- {x}" for x in res.buys] + [""]
    pairs = (res.forex or {}).get("pairs") or {}
    if pairs:
        out += ["## Today's read on each pair", "", "| Pair | Price | What the rule sees | Risk | Decision |",
                "|---|---|---|---|---|"]
        out += [f"| {label(p)} | {r['price']:.{decimals(p)}f} | {r['note']} | {r.get('risk', '')} | **{r['decision']}** |"
                for p, r in pairs.items()]
        out.append("")
    if res.positions:
        out += ["## Open trades", ""] + [
            f"- {label(p['symbol'])}: {'bought' if p['qty'] > 0 else 'sold'} {abs(p['qty']):,.0f} units at "
            f"{p['avg_entry_price']:.{decimals(p['symbol'])}f}, safety stop {p['stop']:.{decimals(p['symbol'])}f}"
            + (f", {money(p['unrealized'])} so far" if p.get("unrealized") is not None else "")
            for p in res.positions] + [""]
    if res.notes:
        out += ["## Notes"] + [f"- {n}" for n in res.notes] + [""]
    out.append("_No AI is used in the Forex wing._")
    return "\n".join(out) + "\n"
