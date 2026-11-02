"""Basket test: a reel's "robot actuator" stock picks, bought and held, through the strategy lab's checks.

Quincy saw an Instagram reel (whymattrs, Sept 2026, "These stocks will make millionaires, buy the dip now")
that named four companies as suppliers for robot actuators (the motors, gears and bearings that move a robot's
joints): Moog (MOG.A), Timken (TKR; the reel wrote "TKM"), Novanta (NOVT) and USA Rare Earth (USAR).

The rules, fixed before any test ran:

  basket        Put an equal share of the money in each stock and hold. Once a year (every 252 trading
                days) move the shares back to equal ("rebalancing"), so one stock can't take over the account.
                A stock that wasn't listed yet joins at the first rebalance after it starts trading.
  basket_trend  The same basket, but only while the S&P 500 (SPY) closes above its 200-day average;
                otherwise cash. This is the rule that worked for the Nasdaq trend accounts, as a cross-check.

Yardsticks: just holding the S&P 500 (SPY, the 500 biggest US companies). Also shown: the Nasdaq 100 (QQQ)
and a robotics fund (BOTZ, Global X Robotics & AI), to see whether the "robot theme" itself beat the market.

USA Rare Earth only started trading in March 2025, so the 10-year lab test uses the other three. The four-stock
basket is shown separately for the short time all four existed; that's too short for the lab to judge.

The "buy the dip" check: every time one of the stocks closed 20%+ below its highest close of the past year
(the first day of each such dip, then at least 3 months before counting another), what did the next 12 months
bring, compared with the S&P 500 over the same 12 months?

  python -m tradebots.basket --out report.md      # needs Alpaca keys (the prices come from Alpaca)
"""
from __future__ import annotations

import copy
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as bt
from . import hunt

log = logging.getLogger(__name__)

REEL = ["MOG.A", "TKR", "NOVT", "USAR"]
CORE = ["MOG.A", "TKR", "NOVT"]          # the three with 10 years of prices
YARDSTICKS = ["SPY", "QQQ", "BOTZ"]
COST = hunt.STOCK_COST                    # 0.1% each way for the buy/sell gap and slip
STYLES = {
    "basket": {"style": "basket", "stocks": CORE, "rebalance_days": 252},
    "basket_trend": {"style": "basket_trend", "stocks": CORE, "rebalance_days": 252, "signal": "SPY", "sma_days": 200},
}
TITLES = {"basket": "Reel basket: Moog + Timken + Novanta, equal shares, held (rebalanced yearly)",
          "basket_trend": "Reel basket, only while the S&P 500 is above its 200-day average"}
DIP = 0.20            # 20% below the past year's high counts as "the dip"
DIP_GAP_DAYS = 63     # at least 3 months between two counted dips of the same stock
FORWARD_DAYS = 252    # then look 12 months ahead


def config_for(style: str, strategy: str = "medium") -> dict:
    cfg = copy.deepcopy(bt.load_config(strategy))
    cfg.pop("trend", None)
    cfg["hunt"] = copy.deepcopy(STYLES[style])
    cfg["name"] = cfg.get("name", strategy)
    cfg["title"] = f"{TITLES[style]} ({strategy.title()} loss limits)"
    return cfg


def targets(close: pd.DataFrame, h: dict) -> tuple[pd.DataFrame, pd.Series]:
    """Share of the account each stock should hold, decided at each close, and which closes are rebalance days.
    Uses only that close and the ones before it."""
    stocks = h["stocks"]
    w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    rebal = pd.Series(False, index=close.index)
    avail = close[stocks].notna()
    start_i = int(np.argmax(avail.any(axis=1).to_numpy()))
    for i in range(start_i, len(close), h["rebalance_days"]):
        live = [s for s in stocks if avail.iloc[i][s]]
        row = {c: 0.0 for c in close.columns}
        for s in live:
            row[s] = 1 / len(live)
        w.iloc[i] = pd.Series(row)
        rebal.iloc[i] = True
    w = w.ffill().fillna(0.0)
    if h["style"] == "basket_trend":
        sig = close[h["signal"]]
        on = (sig > sig.rolling(h["sma_days"]).mean())
        w = w.mul(on.astype(float), axis=0)
        flips = on != on.shift(1)
        rebal = rebal | (flips & on)          # coming back in: buy equal shares again
    return w, rebal


def simulate(cfg: dict, bars: dict[str, pd.DataFrame], start: datetime, end: datetime, cash: float = 100.0,
             cost: float = 1.0) -> bt.SimResult:
    """Day by day. A choice made at a close is carried out at the next day's open, paying the cost on every
    dollar traded. Between rebalance days the shares just ride (that's what holding means)."""
    h = cfg["hunt"]
    rate = COST * cost
    syms = list(bars)
    opens = pd.DataFrame({s: bars[s]["open"] for s in syms})
    close = pd.DataFrame({s: bars[s]["close"] for s in syms})
    want, rebal = targets(close, h)
    days = close.index[(close.index >= pd.Timestamp(start)) & (close.index < pd.Timestamp(end))]
    qty = {s: 0.0 for s in syms}
    basis = {s: 0.0 for s in syms}
    opened: dict[str, str] = {}
    money, fees = cash, 0.0
    res = bt.SimResult(cfg.get("name", "basket"), [(start, cash)])
    plan, plan_eq, first = None, cash, True
    last_w = pd.Series(0.0, index=syms)

    for t in days:
        o = opens.loc[t]
        if plan is not None:
            eq_open = money + sum(qty[s] * o[s] for s in syms if qty[s] and o[s] == o[s])
            moves = {s: plan[s] * eq_open - qty[s] * o[s] for s in syms if o[s] == o[s]}
            for s, d in sorted(moves.items(), key=lambda kv: kv[1]):
                if d < -0.01 and qty[s]:
                    usd = min(-d, qty[s] * o[s])
                    part = usd / (qty[s] * o[s])
                    f = usd * rate
                    fees += f
                    money += usd - f
                    cpart = basis[s] * part
                    qty[s] *= 1 - part
                    basis[s] -= cpart
                    if plan[s] == 0 or qty[s] * o[s] < 0.01:
                        res.trades.append({"symbol": s, "opened": opened.pop(s, t.isoformat()), "closed": t.isoformat(),
                                           "cost": cpart, "pnl": usd - f - cpart, "exit": "rule exit",
                                           "equity_at_open": plan_eq})
                        money += qty[s] * o[s]
                        qty[s], basis[s] = 0.0, 0.0
            for s, d in moves.items():
                if d > 0.01:
                    usd = min(d, money / (1 + rate))
                    if usd <= 0:
                        continue
                    f = usd * rate
                    fees += f
                    if not qty[s]:
                        opened[s] = t.isoformat()
                    qty[s] += usd / o[s]
                    basis[s] += usd + f
                    money -= usd + f
            plan = None
        c = close.loc[t]
        eq = money + sum(qty[s] * c[s] for s in syms if qty[s] and c[s] == c[s])
        res.equity.append((t + timedelta(hours=1), eq))
        w = want.loc[t].fillna(0.0)
        if first or bool(rebal.loc[t]) or not ((w > 0) == (last_w > 0)).all():
            plan, plan_eq, last_w, first = w, eq, w, False
    # what's still held at the end counts as a trade too (marked to the last close), so "trades" means positions
    if days.size:
        c = close.loc[days[-1]]
        for s in syms:
            if qty[s] and c[s] == c[s]:
                res.trades.append({"symbol": s, "opened": opened.get(s, ""), "closed": days[-1].isoformat(),
                                   "cost": basis[s], "pnl": qty[s] * c[s] - basis[s], "exit": "still held",
                                   "equity_at_open": plan_eq})
    res.fees = fees
    return res


class BasketEngine(hunt.HuntEngine):
    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        return simulate(cfg, self.bars, start, end, self.cash, cost)


# ---- prices -------------------------------------------------------------------------------------------------

def fetch(start: datetime, end: datetime, key: str, secret: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Daily prices from Alpaca's full ("SIP") feed, adjusted for splits and dividends, one symbol at a time
    so one unknown ticker can't sink the rest. Moog's class A shares are tried as MOG.A and MOG/A."""
    from .alpaca import AlpacaPaper
    broker = AlpacaPaper(key, secret)
    a = start - timedelta(days=430)
    out = {}
    for sym in symbols:
        for name in ([sym, sym.replace(".", "/")] if "." in sym else [sym]):
            params = {"timeframe": "1Day", "adjustment": "all", "feed": "sip", "limit": 10000, "symbols": name,
                      "start": a.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
            rows: list = []
            try:
                while True:
                    page = broker._data("/v2/stocks/bars", params)
                    for b in (page.get("bars") or {}).values():
                        rows.extend(b)
                    if not page.get("next_page_token"):
                        break
                    params["page_token"] = page["next_page_token"]
            except Exception as e:   # noqa: BLE001 - try the other spelling
                log.warning("  %s: %s", name, e)
                rows = []
            if rows:
                df = pd.DataFrame(rows).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
                df["t"] = pd.to_datetime(df["t"]).dt.tz_convert("UTC").dt.normalize()
                out[sym] = df.set_index("t")[["open", "high", "low", "close", "volume"]]
                out[sym] = out[sym][~out[sym].index.duplicated()]
                log.warning("  %s (as %s): %d days from %s", sym, name, len(df), out[sym].index[0].date())
                break
        else:
            log.warning("  %s: no prices", sym)
    return out


def frame(d: dict, syms: list[str]) -> dict[str, pd.DataFrame]:
    idx = d[syms[0]].index
    for s in syms[1:]:
        idx = idx.union(d[s].index)
    return {s: d[s].reindex(idx) for s in syms}


# ---- the report ---------------------------------------------------------------------------------------------

def hold(bars: dict[str, pd.DataFrame], sym: str, start: datetime, end: datetime, cash: float = 100.0) -> tuple[float, float, float]:
    """Just holding one stock: (% return, end value, worst drop %)."""
    eng = hunt.HuntEngine(bars, start, end, sym, cash)
    r = eng.benchmark(start, end)
    from . import lab
    return lab.pct(r), r.equity[-1][1], bt.stats(r, cash)["max_drawdown_pct"]


def yearly(bars: dict[str, pd.DataFrame], syms: list[str], start: datetime, end: datetime) -> list[str]:
    """Each year's return for each stock and the yardsticks."""
    close = pd.DataFrame({s: bars[s]["close"] for s in syms})
    close = close[(close.index >= pd.Timestamp(start)) & (close.index < pd.Timestamp(end))]
    ye = close.resample("YE").last()
    first = close.apply(lambda c: c.dropna().iloc[0] if c.notna().any() else np.nan)
    prev = pd.concat([first.to_frame().T.set_axis([ye.index[0] - pd.Timedelta(days=366)]), ye]).shift(1).iloc[1:]
    rows = ["| Year | " + " | ".join(syms) + " |", "|---" * (len(syms) + 1) + "|"]
    for t in ye.index:
        cells = []
        for s in syms:
            a, b = prev.loc[t, s], ye.loc[t, s]
            cells.append("" if not (a == a and b == b) else f"{(b / a - 1) * 100:+.0f}%")
        rows.append(f"| {t.year}{' (so far)' if t.year == end.year or t >= pd.Timestamp(end) else ''} | " + " | ".join(cells) + " |")
    return rows


def dips(bars: dict[str, pd.DataFrame], syms: list[str], bench: str = "SPY") -> list[str]:
    """The buy-the-dip check (see the module notes)."""
    rows = ["| Stock | Dips counted | Avg next 12 months | S&P 500 same 12 months | Beat the S&P 500 | Lost money |",
            "|---|---|---|---|---|---|"]
    b = bars[bench]["close"]
    for s in syms:
        c = bars[s]["close"].dropna()
        high = c.rolling(252, min_periods=126).max()
        hit = c <= high * (1 - DIP)
        fw, bw, last = [], [], -10**9
        idx = c.index
        for i, t in enumerate(idx):
            if not hit.iloc[i] or i - last < DIP_GAP_DAYS or i + FORWARD_DAYS >= len(idx):
                continue
            last = i
            t2 = idx[i + FORWARD_DAYS]
            fw.append(c.iloc[i + FORWARD_DAYS] / c.iloc[i] - 1)
            bb = b.reindex([t, t2]).to_numpy()
            bw.append(bb[1] / bb[0] - 1 if np.isfinite(bb).all() else np.nan)
        if not fw:
            rows.append(f"| {s} | 0 | | | | |")
            continue
        fw, bw = np.array(fw), np.array(bw)
        rows.append(f"| {s} | {len(fw)} | {np.mean(fw) * 100:+.1f}% | {np.nanmean(bw) * 100:+.1f}% | "
                    f"{np.mean(fw > bw) * 100:.0f}% of the time | {np.mean(fw < 0) * 100:.0f}% of the time |")
    return rows


def now_vs_high(bars: dict[str, pd.DataFrame], syms: list[str]) -> list[str]:
    rows = ["| Stock | Last close | Highest close, past year | Below the high by | 1 year ago | Change over the year |",
            "|---|---|---|---|---|---|"]
    for s in syms:
        c = bars[s]["close"].dropna()
        last, t = c.iloc[-1], c.index[-1]
        yr = c[c.index >= t - pd.Timedelta(days=365)]
        ago = yr.iloc[0]
        rows.append(f"| {s} | ${last:,.2f} ({t:%b %d}) | ${yr.max():,.2f} | {(1 - last / yr.max()) * 100:.0f}% | "
                    f"${ago:,.2f} | {(last / ago - 1) * 100:+.0f}% |")
    return rows


def report(data: dict[str, pd.DataFrame], start: datetime, end: datetime, strategy: str = "medium") -> str:
    from . import lab
    missing = [s for s in REEL + YARDSTICKS if s not in data]
    o = ["# Reel basket test: Moog, Timken, Novanta, USA Rare Earth", "",
         f"Prices: Alpaca daily (adjusted for splits and dividends), {start:%b %Y} to {end:%b %d %Y}. $100 start. "
         f"Costs: 0.1% each way. Settings fixed before testing. {strategy.title()} loss limits.", ""]
    if missing:
        o += [f"**Missing prices:** {', '.join(missing)}", ""]

    core = [s for s in CORE if s in data]
    syms = sorted(set(core) | {"SPY"})
    bars = frame(data, syms)
    rows = ["| Rule | Whole period | Unseen months | S&P 500, unseen months | Worst drop | Lab check |", "|---|---|---|---|---|---|"]
    details = []
    for style in STYLES:
        cfg = config_for(style, strategy)
        cfg["hunt"]["stocks"] = core
        eng = BasketEngine(bars, start, end, "SPY", min_trades=0)
        runner = lab.Runner(eng)
        v, text = lab.validate(strategy, eng, runner, cfg)
        full = eng.run(cfg, start, end)
        passed = sum(c["passed"] for c in v.checks)
        rows.append(f"| {TITLES[style]} | {lab.pct(full):+.1f}% ({bt.money(full.equity[-1][1])}) | {v.numbers['unseen']:+.1f}% | "
                    f"{lab.pct(eng.benchmark(lab.make_split(start, end).study_end, end)):+.1f}% | {v.numbers['drawdown']:.1f}% | "
                    f"{'✅ pass' if v.kept else f'❌ {passed}/{len(v.checks)}'} |")
        details.append(text)
        log.warning("%s: %+.1f%%, unseen %+.1f%%, drop %.1f%%, %s", style, lab.pct(full), v.numbers["unseen"],
                    v.numbers["drawdown"], "PASS" if v.kept else f"{passed}/{len(v.checks)}")
    o += ["## 1. The lab test (10 years, the three older stocks)", ""] + rows + [""]

    o += ["Just holding each one, same 10 years:", "", "| | Whole period | Worst drop |", "|---|---|---|"]
    for s in core + [y for y in YARDSTICKS if y in data]:
        b2 = frame(data, sorted({s, "SPY"}))
        first = data[s]["close"].first_valid_index()
        s0 = max(start, first.to_pydatetime())
        p, v_, dd = hold(b2, s, s0, end)
        o.append(f"| {s}{f' (from {s0:%b %Y})' if s0 > start else ''} | {p:+.1f}% ({bt.money(v_)}) | {dd:.1f}% |")
    o += [""]

    if "USAR" in data:
        first = data["USAR"]["close"].first_valid_index().to_pydatetime()
        s4 = (first + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        four = [s for s in REEL if s in data]
        b4 = frame(data, sorted(set(four) | {"SPY"}))
        cfg = config_for("basket", strategy)
        cfg["hunt"]["stocks"] = four
        r4 = simulate(cfg, b4, s4, end)
        sp, spv, spd = hold(b4, "SPY", s4, end)
        o += [f"## 2. All four, since USA Rare Earth started trading ({s4:%b %d %Y})", "",
              "Too short for the lab to judge (it needs years), so this is just what happened.", "",
              "| | Return | Worst drop |", "|---|---|---|",
              f"| Four-stock basket (equal shares) | {lab.pct(r4):+.1f}% ({bt.money(r4.equity[-1][1])}) | "
              f"{bt.stats(r4, 100.0)['max_drawdown_pct']:.1f}% |",
              f"| S&P 500 (SPY) | {sp:+.1f}% ({bt.money(spv)}) | {spd:.1f}% |"]
        for s in four:
            p, v_, dd = hold(frame(data, sorted({s, "SPY"})), s, s4, end)
            o.append(f"| {s} alone | {p:+.1f}% ({bt.money(v_)}) | {dd:.1f}% |")
        o += [""]

    have = [s for s in REEL + YARDSTICKS if s in data]
    o += ["## 3. Year by year", ""] + yearly(data, have, start, end) + [""]
    o += ["## 4. Where they are now (the \"dip\")", ""] + now_vs_high(data, have) + [""]
    o += ["## 5. Did buying a 20% dip pay off in the past?", "",
          "Each time a stock closed 20%+ below its highest close of the past year (first day of each dip, at least "
          "3 months apart), what it did over the next 12 months, against the S&P 500 over the same 12 months.", ""]
    o += dips(data, [s for s in REEL if s in data] + ["QQQ"]) + [""]
    o += ["## Lab details", "", "\n---\n\n".join(details)]
    return "\n".join(o) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import pickle
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--strategy", default="medium", help="whose loss limits to judge against")
    p.add_argument("--cache", default=None)
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    now = datetime.now(timezone.utc)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end.replace(year=end.year - a.years)
    if a.cache and Path(a.cache).exists():
        data = pickle.loads(Path(a.cache).read_bytes())
    else:
        key = os.environ.get("ALPACA_MEDIUM_KEY_ID") or os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", "")
        sec = os.environ.get("ALPACA_MEDIUM_SECRET_KEY") or os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", "")
        data = fetch(start, end, key, sec, REEL + YARDSTICKS)
        if a.cache:
            Path(a.cache).write_bytes(pickle.dumps(data))
    text = report(data, start, end, a.strategy)
    print(text)
    if a.out:
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
