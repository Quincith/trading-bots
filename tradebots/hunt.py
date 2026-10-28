"""Hunt: four bold, high-risk rules replayed on past prices through the strategy lab's checks.

  Leveraged Nasdaq trend ("lev_trend"): hold TQQQ (a fund that moves 3x the Nasdaq 100 each day) while
      QQQ (the Nasdaq 100 itself) closes above its 200-day average; otherwise hold cash.
  Leveraged dip-buying ("lev_dip"): Larry Connors' RSI(2) rule. When QQQ is above its 200-day average and its
      2-day momentum score (RSI) closes under 10 (a sharp short drop in an uptrend), buy TQQQ; sell when QQQ
      closes back above its 5-day average.
  Multi-market trend ("multi_trend"): at each month's end, look at the S&P 500 (SPY), Nasdaq 100 (QQQ),
      gold (GLD) and long US bonds (TLT). Each one that rose over the last 12 months gets an equal share of
      the money in its leveraged fund (UPRO 3x, TQQQ 3x, UGL 2x, TMF 3x); the share of the ones that fell
      stays in cash.
  Crypto rotation ("crypto_rotation"): every 7 days, hold the one coin of BTC, ETH and SOL that rose most
      over the last 28 days, if it rose at all and Bitcoin is above its 140-day (20-week) average; else cash.

The settings above were fixed before any test ran, from the textbook version of each rule, not tuned on these
years. Every rule bets the whole account (it is either all in or in cash), so the risk comes from the
leverage, not from the bet size. Decisions are made at a day's close and filled at the next day's open.

`simulate` is the lab replay; this is a test bench only (no live trading code yet).
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import backtest as bt
from .indicators import rsi

log = logging.getLogger(__name__)

STOCK_COST = 0.001     # stocks and funds: no commission, but assume 0.1% lost to the buy/sell gap and slip each way
CRYPTO_COST = bt.FEE + bt.SLIPPAGE

# The textbook settings, fixed before testing (see the module notes).
STYLES = {
    "lev_trend": {"style": "lev_trend", "signal": "QQQ", "hold": "TQQQ", "sma_days": 200},
    "lev_dip": {"style": "lev_dip", "signal": "QQQ", "hold": "TQQQ", "trend_days": 200, "rsi_bars": 2,
                "rsi_entry": 10, "exit_sma_days": 5},
    "multi_trend": {"style": "multi_trend", "pairs": {"SPY": "UPRO", "QQQ": "TQQQ", "GLD": "UGL", "TLT": "TMF"},
                    "lookback_days": 252},
    "crypto_rotation": {"style": "crypto_rotation", "coins": ["BTC/USD", "ETH/USD", "SOL/USD"],
                        "lookback_days": 28, "btc_sma_days": 140, "every_days": 7},
}
TITLES = {"lev_trend": "Leveraged Nasdaq trend (TQQQ above the 200-day average)",
          "lev_dip": "Leveraged dip-buying (TQQQ on a 2-day RSI under 10)",
          "multi_trend": "Multi-market trend (leveraged stocks, gold and bonds that rose over 12 months)",
          "crypto_rotation": "Crypto rotation (strongest of BTC, ETH, SOL each week)"}
MIN_TRADES = {"lev_trend": 5, "lev_dip": 15, "multi_trend": 8, "crypto_rotation": 10}
CRYPTO_STYLES = ("crypto_rotation",)
STOCKS = sorted({"QQQ", "TQQQ", "SPY", "UPRO", "GLD", "UGL", "TLT", "TMF"})


def config_for(style: str, strategy: str = "aggressive") -> dict:
    """The account's config (for its loss limits) with the rule in place of the AI bots."""
    cfg = copy.deepcopy(bt.load_config(strategy))
    cfg["hunt"] = copy.deepcopy(STYLES[style])
    cfg["title"] = f"{TITLES[style]} ({strategy.title()} loss limits)"
    return cfg


# ---- what each rule wants to hold, decided at each close ---------------------------------------------------

def targets(close: pd.DataFrame, h: dict) -> pd.DataFrame:
    """Share of the account (0..1) each symbol should hold, decided at each day's close. Uses only that close
    and the ones before it."""
    s = h["style"]
    out = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    if s == "lev_trend":
        sig = close[h["signal"]]
        out[h["hold"]] = (sig > sig.rolling(h["sma_days"]).mean()).astype(float)
    elif s == "lev_dip":
        sig = close[h["signal"]]
        up = sig > sig.rolling(h["trend_days"]).mean()
        enter = up & (rsi(sig, h["rsi_bars"]) < h["rsi_entry"])
        leave = sig > sig.rolling(h["exit_sma_days"]).mean()
        held, w = False, np.zeros(len(sig))
        for i, (e, x) in enumerate(zip(enter.to_numpy(), leave.to_numpy())):
            if held and x:
                held = False
            elif not held and e:
                held = True
            w[i] = float(held)
        out[h["hold"]] = w
    elif s == "multi_trend":
        pairs = h["pairs"]
        month_end = pd.Series(close.index.tz_localize(None).to_period("M"), index=close.index)
        last_day = month_end != month_end.shift(-1)
        w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        share = 1 / len(pairs)
        for sig, hold in pairs.items():
            mom = close[sig] / close[sig].shift(h["lookback_days"]) - 1
            w.loc[last_day, hold] = np.where(mom[last_day] > 0, share, 0.0)
        w.loc[last_day] = w.loc[last_day].fillna(0.0)
        out = w.ffill().fillna(0.0)
        # a month-end decision made before the fund existed can't be carried out
        out = out.where(close.notna(), 0.0)
    elif s == "crypto_rotation":
        coins = h["coins"]
        btc = close["BTC/USD"]
        healthy = btc > btc.rolling(h["btc_sma_days"]).mean()
        mom = close[coins] / close[coins].shift(h["lookback_days"]) - 1
        w = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        for i in range(0, len(close), h["every_days"]):
            row = {c: 0.0 for c in close.columns}
            m = mom.iloc[i].dropna()
            if healthy.iloc[i] and not m.empty and m.max() > 0:
                row[m.idxmax()] = 1.0
            w.iloc[i] = pd.Series(row)
        out = w.ffill().fillna(0.0)
    else:
        raise ValueError(f"unknown style {s}")
    return out


# ---- the replay ---------------------------------------------------------------------------------------------

def simulate(cfg: dict, bars: dict[str, pd.DataFrame], start: datetime, end: datetime, cash: float = 100.0,
             cost: float = 1.0) -> bt.SimResult:
    """Day-by-day replay. The holdings decided at a close are bought or sold at the next day's open, paying
    the cost rate on every dollar traded (times `cost`). Holdings only change when the rule's choice changes.
    The daily loss limit blocks new buys decided at a close that ended a day down more than the limit. The
    total loss limit is left off so the replay shows what the rule itself does (the lab checks the worst drop
    against it separately)."""
    h, rk = cfg["hunt"], cfg["risk"]
    rate = (CRYPTO_COST if h["style"] in CRYPTO_STYLES else STOCK_COST) * cost
    syms = list(bars)
    opens = pd.DataFrame({s: bars[s]["open"] for s in syms})
    close = pd.DataFrame({s: bars[s]["close"] for s in syms})
    want = targets(close, h)
    s0, e0 = pd.Timestamp(start), pd.Timestamp(end)
    days = close.index[(close.index >= s0) & (close.index < e0)]
    daily_limit = rk["max_daily_loss_pct"] / 100

    qty = {s: 0.0 for s in syms}
    basis = {s: 0.0 for s in syms}
    opened: dict[str, str] = {}
    money, fees, eq_prev = cash, 0.0, cash
    res = bt.SimResult(cfg["name"], [(start, cash)])
    plan, plan_eq = None, cash
    last_w = pd.Series(0.0, index=syms)

    def trade(s, usd, px, when):
        """Buy (usd > 0) or sell (usd < 0) this many dollars of s at px."""
        nonlocal money, fees
        f = abs(usd) * rate
        fees += f
        if usd > 0:
            if not qty[s]:
                opened[s] = when.isoformat()
            qty[s] += usd / px
            basis[s] += usd + f
            money -= usd + f
        else:
            part = min(1.0, -usd / (qty[s] * px)) if qty[s] else 0.0
            got = -usd - f
            money += got
            cost_part = basis[s] * part
            qty[s] *= 1 - part
            basis[s] -= cost_part
            if qty[s] * px < 0.01:
                res.trades.append({"symbol": s, "opened": opened.pop(s, when.isoformat()), "closed": when.isoformat(),
                                   "cost": cost_part, "pnl": got - cost_part, "exit": "rule exit",
                                   "equity_at_open": plan_eq})
                money += qty[s] * px
                qty[s], basis[s] = 0.0, 0.0

    for t in days:
        o = opens.loc[t]
        if plan is not None:
            eq_open = money + sum(qty[s] * o[s] for s in syms if qty[s] and o[s] == o[s])
            moves = {s: plan[s] * eq_open - qty[s] * o[s] for s in syms if o[s] == o[s]}
            for s, d in sorted(moves.items(), key=lambda kv: kv[1]):     # sell first, then buy
                if d < 0 and qty[s]:
                    trade(s, d if plan[s] > 0 else -qty[s] * o[s], o[s], t)
            for s, d in moves.items():
                if d > 0.01:
                    trade(s, min(d, money / (1 + rate)), o[s], t)
            plan = None
        c = close.loc[t]
        eq = money + sum(qty[s] * c[s] for s in syms if qty[s] and c[s] == c[s])
        res.equity.append((t + timedelta(hours=1), eq))
        w = want.loc[t].fillna(0.0)
        if not w.equals(last_w):
            if eq < eq_prev * (1 - daily_limit):
                w = pd.Series({s: min(w[s], last_w[s]) for s in syms})   # the daily limit: no new buys today
            if not w.equals(last_w):
                plan, plan_eq, last_w = w, eq, w
        eq_prev = eq
    res.fees = fees
    return res


# ---- the lab engine -----------------------------------------------------------------------------------------

class HuntEngine:
    """Lab engine for the hunt rules: daily prices for every fund (or coin) a rule needs, and a yardstick."""

    def __init__(self, bars: dict[str, pd.DataFrame], start: datetime, end: datetime, bench: str,
                 cash: float = 100.0, min_trades: int = 10):
        self.bars, self.start, self.end, self.bench = bars, start, end, bench
        self.cash, self.min_trades = cash, min_trades
        self.benchmark_label = f"Just hold {bench.split('/')[0]}"

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        return simulate(cfg, self.bars, start, end, self.cash, cost)

    def benchmark(self, start: datetime, end: datetime) -> bt.SimResult:
        """Buy the yardstick with all the money at the first open (paying the cost) and never sell."""
        df = self.bars[self.bench]
        c = df["close"][(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))].dropna()
        if c.empty:
            return bt.SimResult("benchmark", [(start, self.cash), (end, self.cash)])
        rate = CRYPTO_COST if "/" in self.bench else STOCK_COST
        qty = self.cash * (1 - rate) / float(df["open"][c.index[0]])
        return bt.SimResult("benchmark", [(start, self.cash)] + [(t + timedelta(hours=1), qty * v) for t, v in c.items()])

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        return [{"opened": t["opened"][:10], "symbol": t["symbol"], "exit": t["exit"],
                 "result_pct": round(t["pnl"] / t["cost"] * 100, 2) if t["cost"] else 0.0} for t in res.trades]


def fetch(start: datetime, end: datetime, key: str, secret: str) -> dict[str, dict[str, pd.DataFrame]]:
    """Daily prices from Alpaca: the funds (adjusted for splits and dividends, from the full "SIP" feed) and
    the coins, each with about 14 months before `start` to warm up the averages."""
    from .alpaca import AlpacaPaper
    broker = AlpacaPaper(key, secret)
    a = start - timedelta(days=430)
    stocks = {}
    params_base = {"timeframe": "1Day", "adjustment": "all", "feed": "sip", "limit": 10000,
                   "start": a.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
    raw: dict[str, list] = {}
    params = {**params_base, "symbols": ",".join(STOCKS)}
    while True:
        page = broker._data("/v2/stocks/bars", params)
        for sym, b in (page.get("bars") or {}).items():
            raw.setdefault(sym, []).extend(b)
        if not page.get("next_page_token"):
            break
        params["page_token"] = page["next_page_token"]
    for sym, b in raw.items():
        df = pd.DataFrame(b).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df["t"] = pd.to_datetime(df["t"]).dt.tz_convert("UTC").dt.normalize()
        stocks[sym] = df.set_index("t")[["open", "high", "low", "close", "volume"]]
        log.warning("  %s: %d days from %s", sym, len(df), stocks[sym].index[0].date())
    coins = broker.get_bars_range(STYLES["crypto_rotation"]["coins"], "1Day", a, end, "crypto")
    for s, df in coins.items():
        coins[s] = df[~df.index.duplicated()]
        log.warning("  %s: %d days from %s", s, len(df), df.index[0].date())
    return {"stocks": stocks, "crypto": coins}


def engines(data: dict, start: datetime, end: datetime) -> dict[str, HuntEngine]:
    """One engine per rule, each on the symbols and the period it has prices for."""
    def frame(d: dict, syms: list[str]) -> dict[str, pd.DataFrame]:
        idx = d[syms[0]].index
        for s in syms[1:]:
            idx = idx.union(d[s].index)
        return {s: d[s].reindex(idx) for s in syms}

    out = {}
    for style, h in STYLES.items():
        if style in CRYPTO_STYLES:
            bars = frame(data["crypto"], h["coins"])
            first = max(df["close"].first_valid_index() for df in bars.values())
            s = max(start, (first + timedelta(days=h["btc_sma_days"])).to_pydatetime())
            out[style] = HuntEngine(bars, s, end, "BTC/USD", min_trades=MIN_TRADES[style])
        else:
            syms = sorted({h["signal"], h["hold"]} if "signal" in h else set(h["pairs"]) | set(h["pairs"].values()))
            bars = frame(data["stocks"], sorted(set(syms) | {"QQQ"}))
            out[style] = HuntEngine(bars, start, end, "QQQ", min_trades=MIN_TRADES[style])
    return out


def load_data(years: int = 10, cache: str | None = None, end: datetime | None = None) -> tuple[dict, datetime, datetime]:
    import os
    import pickle
    from pathlib import Path
    now = datetime.now(timezone.utc)
    end = end or datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    start = end.replace(year=end.year - years)
    if cache and Path(cache).exists():
        data = pickle.loads(Path(cache).read_bytes())
    else:
        key = os.environ.get("ALPACA_MEDIUM_KEY_ID") or os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", "")
        sec = os.environ.get("ALPACA_MEDIUM_SECRET_KEY") or os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", "")
        data = fetch(start, end, key, sec)
        if cache:
            Path(cache).write_bytes(pickle.dumps(data))
    return data, start, end


# ---- the full comparison ------------------------------------------------------------------------------------

def hold_row(eng: HuntEngine, sym: str) -> str:
    """What just holding one fund or coin did over the same period, for comparison."""
    from . import lab
    alt = HuntEngine(eng.bars, eng.start, eng.end, sym)
    r = alt.benchmark(eng.start, eng.end)
    dd = bt.stats(r, eng.cash)["max_drawdown_pct"]
    return f"| Just hold {sym.split('/')[0]} | {lab.pct(r):+.1f}% ({bt.money(r.equity[-1][1])}) | worst drop {dd:.1f}% |"


def compare(data: dict, start: datetime, end: datetime, styles=tuple(STYLES), strategy: str = "aggressive") -> str:
    from . import lab
    rows, details, holds = [], [], []
    for style, eng in engines(data, start, end).items():
        if style not in styles:
            continue
        runner = lab.Runner(eng)
        cfg = config_for(style, strategy)
        v, text = lab.validate(strategy, eng, runner, cfg)
        full = runner.run_many([(cfg, eng.start, eng.end, 1.0)])[0]
        free = eng.run(cfg, eng.start, eng.end, cost=0.0)
        bench = lab.pct(eng.benchmark(eng.start, eng.end))
        passed = sum(c["passed"] for c in v.checks)
        rows.append(f"| {TITLES[style]} | {eng.start:%b %Y} | {lab.pct(full):+.1f}% ({bt.money(full.equity[-1][1])}) | "
                    f"{lab.pct(free):+.1f}% | {v.numbers['unseen']:+.1f}% | {bench:+.1f}% | {v.numbers['drawdown']:.1f}% | "
                    f"{len(full.trades)} | {'✅ pass' if v.kept else f'❌ {passed}/{len(v.checks)}'} |")
        details.append(text + f"\nBefore costs, the whole period would have been {lab.pct(free):+.1f}%.\n")
        holds += [hold_row(eng, s) for s in ([eng.bench] + ([STYLES[style]["hold"]] if "hold" in STYLES[style] else []))]
        log.warning("%s: %+.1f%% (before costs %+.1f%%), unseen %+.1f%%, drop %.1f%%, %s", style, lab.pct(full),
                    lab.pct(free), v.numbers["unseen"], v.numbers["drawdown"], "PASS" if v.kept else f"{passed}/7")
    head = ["# Hunt: four bold rules through the strategy lab", "",
            f"Prices: Alpaca daily, {start:%b %Y} to {end:%b %Y} (crypto from when Alpaca has it). $100 start, "
            f"{strategy.title()} loss limits. Settings fixed before testing. Costs: 0.1% each way on funds, "
            "0.3% each way on coins.", "",
            "| Rule | From | Whole period | Before costs | Unseen months | Hold yardstick (whole period) | Worst drop | Trades | Lab check |",
            "|---|---|---|---|---|---|---|---|---|"]
    holds_t = ["", "Just holding, same periods:", "", "| | Whole period | |", "|---|---|---|", *dict.fromkeys(holds)]
    return "\n".join(head + rows + holds_t) + "\n\n" + "\n---\n\n".join(details)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--cache", default=None, help="save/load the downloaded prices here")
    p.add_argument("--end", default=None, help="last day, YYYY-MM-DD (default: the start of this month)")
    p.add_argument("--style", action="append", choices=list(STYLES), help="only these rules (default: all)")
    p.add_argument("--strategy", default="aggressive", help="whose loss limits to judge against")
    p.add_argument("--out", default=None, help="also write the report to this file")
    a = p.parse_args(argv)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else None
    data, start, end = load_data(a.years, a.cache, end)
    text = compare(data, start, end, tuple(a.style or STYLES), a.strategy)
    print(text)
    if a.out:
        from pathlib import Path
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
