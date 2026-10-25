"""Sunday report: how each strategy did this week and since it started, next to simply holding Bitcoin.

Returns are always net of deposits, so adding money never looks like profit. The Bitcoin
comparison pretends every deposit was spent on Bitcoin at the moment it was made. Copycat buys
stocks, so it is also compared with the S&P 500 (the SPY fund), the usual yardstick for stocks.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from .report import money
from .store import Store, time_weighted_return

PriceAt = Callable[[datetime], float]


def _t(row: dict) -> datetime:
    return datetime.fromisoformat(row["time"])


def window(snaps: list[dict], start: datetime) -> list[dict]:
    """Snapshots from the last one at or before `start` onward (all of them if the bot is newer than that)."""
    before = [i for i, s in enumerate(snaps) if _t(s) <= start]
    return snaps[before[-1]:] if before else snaps


def strategy_stats(store: Store, now: datetime, btc: PriceAt, spy: PriceAt | None = None,
                   days: int = 7) -> dict | None:
    snaps = store.rows("equity.csv")
    if not snaps:
        return None
    week = window(snaps, now - timedelta(days=days))
    w0, w1 = week[0], week[-1]
    week_flow = float(w1["net_deposits"]) - float(w0["net_deposits"])
    btc_now = btc(now)

    # What the same deposits would be worth if each had bought Bitcoin instead.
    btc_value = sum(float(d["amount"]) * btc_now / btc(_t(d)) for d in store.rows("deposits.csv"))
    perf = store.performance()
    trades = [t for t in store.rows("trades.csv") if _t(t) > _t(w0)]
    extra = {}
    if spy:
        spy_now = spy(now)
        extra = {"spy_week_pct": (spy_now / spy(_t(w0)) - 1) * 100,
                 "spy_value": sum(float(d["amount"]) * spy_now / spy(_t(d)) for d in store.rows("deposits.csv"))}
    return extra | {
        "week_start": _t(w0), "full_week": _t(w0) <= now - timedelta(days=days),
        "week_pct": time_weighted_return(week) * 100,
        "week_profit": float(w1["equity"]) - float(w0["equity"]) - week_flow,
        "week_deposits": week_flow,
        "btc_week_pct": (btc_now / btc(_t(w0)) - 1) * 100,
        "buys": sum(t["side"] == "buy" for t in trades),
        "sells": sum(t["side"] == "sell" for t in trades),
        "started": _t(snaps[0]),
        "equity": perf["equity"], "net_deposits": perf["net_deposits"], "profit": perf["profit"],
        "total_pct": perf["twr_pct"],
        "btc_value": btc_value,
        "halted": store.state.get("halted_reason"),
    }


def _vs(mine: float, btc: float) -> str:
    gap = mine - btc
    if abs(gap) < 0.05:
        return "did about the same as Bitcoin"
    return f"**{'beat' if gap > 0 else 'trailed'} Bitcoin by {abs(gap):.1f} points**"


def render(stats: dict[str, dict | None], now: datetime, lab: str = "") -> str:
    out = [f"# Weekly bot report: week ending {now:%B %-d, %Y}", ""]
    live = {n: s for n, s in stats.items() if s}
    if len(live) > 1:
        best = max(live, key=lambda n: live[n]["week_pct"])
        out += ["| Strategy | This week | Since the start | Profit / loss |", "|---|---|---|---|"]
        out += [f"| {n.title()}{' 🏆' if n == best else ''} | {s['week_pct']:+.1f}% | {s['total_pct']:+.1f}% "
                f"| {money(s['profit'])} |" for n, s in live.items()]
        out.append("")
    for name, s in stats.items():
        out.append(f"## {name.title()}")
        if not s:
            out += ["No runs recorded yet.", ""]
            continue
        period = "This week" if s["full_week"] else f"Since it started on {s['week_start']:%b %-d}"
        out.append(f"- **{period}:** {s['week_pct']:+.1f}% ({money(s['week_profit'])}). "
                   f"Holding Bitcoin did {s['btc_week_pct']:+.1f}%, so it {_vs(s['week_pct'], s['btc_week_pct'])}.")
        if "spy_week_pct" in s:
            out.append(f"- **Vs. the stock market:** the S&P 500 did {s['spy_week_pct']:+.1f}%, so it "
                       f"{_vs(s['week_pct'], s['spy_week_pct']).replace('Bitcoin', 'the S&P 500')}. "
                       f"The same money in the S&P 500 would be worth {money(s['spy_value'])}.")
        out.append(f"- **Trades:** {s['buys']} buys, {s['sells']} sells.")
        if s["week_deposits"]:
            out.append(f"- **Money added this week:** {money(s['week_deposits'])} (not counted as profit).")
        out.append(f"- **Since the start ({s['started']:%b %-d}):** account is worth {money(s['equity'])} "
                   f"from {money(s['net_deposits'])} put in, {money(s['profit'])} profit ({s['total_pct']:+.1f}%). "
                   f"The same money in Bitcoin would be worth {money(s['btc_value'])}.")
        if s["halted"]:
            out.append(f"- **Stopped:** {s['halted']}")
        out.append("")
    if lab:
        out += [lab, ""]
    out.append("_Paper money only. Percentages leave out deposits, so adding money never looks like a gain. "
               "Claude's running cost is not included. Copycat uses no AI, so it costs nothing to run._")
    return "\n".join(out) + "\n"


def lab_section(experiments: list[dict], now: datetime, days: int = 7) -> str:
    """What the strategy lab tested this past week (from data/lab/experiments.csv)."""
    recent = [r for r in experiments if datetime.fromisoformat(r["time"]) > now - timedelta(days=days)]
    if not recent:
        return ""
    out = ["## Strategy lab", "", "Ideas tested on past prices this week (only kept ones become a pull request "
           "for you to approve):", ""]
    for r in recent:
        mark = "✅ kept" if r["verdict"] == "kept" else "❌ rejected"
        out.append(f"- **{r['strategy'].title()}**, {mark}: {r['idea']} (unseen months {float(r['unseen_new_pct']):+.1f}% "
                   f"vs {float(r['unseen_old_pct']):+.1f}% now)")
    return "\n".join(out)


def btc_prices(broker, since: datetime) -> PriceAt:
    """Hourly Bitcoin closes from Alpaca; returns the last close at or before any time asked for."""
    hours = int((datetime.now(since.tzinfo) - since).total_seconds() // 3600) + 6
    bars = broker.get_bars(["BTC/USD"], "1Hour", hours, "crypto").get("BTC/USD")
    if bars is None or bars.empty:
        raise RuntimeError("Alpaca returned no Bitcoin prices")
    closes = bars["close"]

    def at(when: datetime) -> float:
        earlier = closes[closes.index <= when]
        return float(earlier.iloc[-1] if len(earlier) else closes.iloc[0])
    return at


def stock_prices(broker, symbol: str, since: datetime) -> PriceAt:
    """Daily closes for a stock or fund (like SPY); returns the last close at or before any time asked for."""
    days = int((datetime.now(since.tzinfo) - since).total_seconds() // 86400) + 10
    bars = broker.get_bars([symbol], "1Day", days, "stocks").get(symbol)
    if bars is None or bars.empty:
        raise RuntimeError(f"Alpaca returned no prices for {symbol}")
    closes = bars["close"]

    def at(when: datetime) -> float:
        earlier = closes[closes.index <= when]
        return float(earlier.iloc[-1] if len(earlier) else closes.iloc[0])
    return at
