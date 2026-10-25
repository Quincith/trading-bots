"""Backtest: replay the six-bot team over past prices to see how each strategy would have done.

  python -m tradebots.backtest --days 365 --sample 30 --max-claude-usd 4

Two parts:
  1. Full replay. Both strategies run through the real pipeline code every 30 minutes of the past
     year, against a simulated $100 account with trading fees and slippage. News, Sentiment and
     Decision use their rule-based fallbacks here, because asking Claude ~17,000 times would cost
     far too much. The result is compared with simply buying and holding BTC.
  2. Claude check. A small random sample of the moments where the bots found a setup is replayed
     with Claude Opus and Claude Haiku (and the rules), and every trade either of them would take
     is played forward to see how it ended. This shows whether Claude picks better trades than the
     rules, whether Haiku is as good as Opus, and what each costs. Spending stops at --max-claude-usd.

Things a backtest cannot replay: Reddit mention counts (no history), and the exact live price
between 30-minute checks. Claude may also remember market events before its training cutoff, so
part 2 only samples moments after --ai-from.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import pickle
import random
import tempfile
import threading
from bisect import bisect_left, bisect_right
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

from . import pipeline
from .ai import AI
from .alpaca import TIMEFRAME_MINUTES, AlpacaPaper, norm
from .bots import charts, decision, filters, news, radar, risk, scout, sentiment
from .store import Store

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

TICK = timedelta(minutes=30)   # the live bots run every 30 minutes
FEE = 0.0025                   # Alpaca crypto taker fee at the lowest volume tier (0.25% per buy or sell)
SLIPPAGE = 0.0005              # assume each market order fills 0.05% worse than the last price
# Claude list prices, dollars per million tokens (input, output).
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-haiku-5-5": (0.10, 0.50)}
MODELS = ["claude-opus-5-5", "claude-haiku-5-5"]


def load_config(strategy: str) -> dict:
    return yaml.safe_load((ROOT / "config" / f"{strategy}.yaml").read_text())


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    i, o = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * i + output_tokens * o) / 1e6


def _np_time(t: datetime) -> np.datetime64:
    return pd.Timestamp(t).tz_convert(None).to_datetime64()


# ---- past market data ---------------------------------------------------------------------------

class History:
    """Past candles, headlines and the Fear & Greed index, served as they looked at any moment."""

    def __init__(self, bars: dict[str, dict[str, pd.DataFrame]], news_items: list[dict], fng: dict[str, int]):
        self.bars = bars          # bars[timeframe][symbol], indexed by bar start time (UTC)
        self.fng = fng            # "YYYY-MM-DD" -> 0..100
        self._starts = {tf: {s: df.index.tz_convert(None).values for s, df in d.items()} for tf, d in bars.items()}
        self.news = sorted(news_items, key=lambda n: n["created_at"])
        self._news_t = [n["created_at"] for n in self.news]

    def window(self, timeframe: str, symbol: str, now: datetime, lookback: int) -> pd.DataFrame:
        """The last `lookback` candles that had fully closed by `now` - never anything later."""
        df = self.bars.get(timeframe, {}).get(symbol)
        if df is None:
            return pd.DataFrame()
        cutoff = _np_time(now - timedelta(minutes=TIMEFRAME_MINUTES[timeframe]))
        i = int(np.searchsorted(self._starts[timeframe][symbol], cutoff, side="right"))
        return df.iloc[max(0, i - lookback):i]

    def price(self, symbol: str, now: datetime) -> float | None:
        w = self.window("15Min", symbol, now, 1)
        return float(w["close"].iloc[-1]) if len(w) else None

    def news_between(self, symbols: list[str], start: datetime, end: datetime) -> list[dict]:
        a = bisect_left(self._news_t, start.strftime("%Y-%m-%dT%H:%M:%SZ"))
        b = bisect_left(self._news_t, end.strftime("%Y-%m-%dT%H:%M:%SZ"))
        want = {norm(s) for s in symbols}
        return [n for n in self.news[a:b] if want & {norm(s) for s in n["symbols"]}]

    def fear_greed(self, now: datetime) -> int | None:
        return self.fng.get(now.date().isoformat())


def fetch_history(symbols: list[str], start: datetime, end: datetime, key_id: str, secret: str) -> History:
    broker = AlpacaPaper(key_id, secret)
    bars = {}
    for tf in ("15Min", "1Hour"):
        log.warning("Downloading %s candles for %d coins...", tf, len(symbols))
        bars[tf] = broker.get_bars_range(symbols, tf, start, end, "crypto")
    log.warning("Downloading headlines...")
    try:
        items = broker.get_news_range(symbols, start, end)
    except Exception as e:  # headlines help the News bot but are not required
        log.warning("Headlines unavailable (%s); News will score 'no news'.", e)
        items = []
    fng = {}
    try:
        r = requests.get("https://api.alternative.me/fng/", params={"limit": 0}, timeout=30)
        for row in r.json()["data"]:
            d = datetime.fromtimestamp(int(row["timestamp"]), timezone.utc).date().isoformat()
            fng[d] = int(row["value"])
    except Exception as e:
        log.warning("Fear & Greed history unavailable (%s)", e)
    log.warning("Got %s candles, %d headlines, %d Fear & Greed days.",
                {tf: sum(len(df) for df in d.values()) for tf, d in bars.items()}, len(items), len(fng))
    return History(bars, items, fng)


# ---- simulated paper account --------------------------------------------------------------------

_CLOCK = threading.local()   # the moment being replayed, per thread (Sentiment reads it)


@contextmanager
def offline_sentiment(hist: History):
    """Sentiment and the News radar normally read live websites. In the past, only Fear & Greed has a history."""
    saved = sentiment.fear_greed, sentiment.mentions, sentiment.reddit_titles, radar.rss_headlines, radar.trending
    sentiment.fear_greed = lambda: hist.fear_greed(_CLOCK.now)
    sentiment.mentions = lambda asset_class: {}
    sentiment.reddit_titles = lambda c: []
    # The News radar's news sites and trending list have no history; it counts Alpaca's past headlines only.
    radar.rss_headlines = lambda: []
    radar.trending = lambda: []
    try:
        yield
    finally:
        sentiment.fear_greed, sentiment.mentions, sentiment.reddit_titles, radar.rss_headlines, radar.trending = saved


class SimBroker:
    """Stands in for Alpaca: same methods the pipeline calls, filled from past prices with fees."""

    def __init__(self, hist: History, cash: float, fee: float = FEE, slippage: float = SLIPPAGE):
        self.hist, self.cash, self.fee, self.slip = hist, cash, fee, slippage
        self.pos: dict[str, dict] = {}
        self.now: datetime | None = None
        self.round_trips: list[dict] = []
        self.fees_paid = 0.0

    def _px(self, order_symbol: str) -> float:
        return self.hist.price(order_symbol, self.now)

    def equity(self) -> float:
        return self.cash + sum(p["qty"] * (self._px(p["order_symbol"]) or p["entry"]) for p in self.pos.values())

    def get_account(self) -> dict:
        e = self.equity()
        return {"equity": e, "last_equity": e, "cash": self.cash, "buying_power": self.cash}

    def get_positions(self) -> list[dict]:
        out = []
        for key, p in self.pos.items():
            px = self._px(p["order_symbol"]) or p["entry"]
            out.append({"symbol": key, "qty": p["qty"], "market_value": p["qty"] * px, "avg_entry_price": p["entry"],
                        "current_price": px, "asset_class": "crypto"})
        return out

    def is_market_open(self) -> bool:
        return False

    def get_bars(self, symbols, timeframe, lookback, asset_class):
        out = {}
        for s in symbols:
            w = self.hist.window(timeframe, s, self.now, lookback)
            if len(w):
                out[s] = w
        return out

    def get_news(self, symbols, hours=48, limit=50):
        items = self.hist.news_between(symbols, self.now - timedelta(hours=hours), self.now)
        return items[::-1][:limit]

    def buy_notional(self, symbol, usd, asset_class, client_order_id):
        usd = min(usd, self.cash)
        px = self._px(symbol) * (1 + self.slip)
        fee = usd * self.fee
        self.cash -= usd
        self.fees_paid += fee
        self.pos[norm(symbol)] = {"order_symbol": symbol, "qty": (usd - fee) / px, "entry": px, "cost": usd,
                                  "opened": self.now}

    def close_position(self, symbol):
        p = self.pos.pop(norm(symbol))
        gross = p["qty"] * self._px(p["order_symbol"]) * (1 - self.slip)
        fee = gross * self.fee
        self.cash += gross - fee
        self.fees_paid += fee
        self.round_trips.append({"symbol": p["order_symbol"], "opened": p["opened"].isoformat(),
                                 "closed": self.now.isoformat(), "cost": p["cost"], "pnl": gross - fee - p["cost"]})


# ---- part 1: full replay with the rule-based bots ------------------------------------------------

@dataclass
class Event:
    """A moment where Scout and Charts found a setup, so the live bots would have asked Claude."""
    time: datetime
    strategy: str
    claude_calls: int      # how many Claude calls the live bots would have made
    bought: bool


@dataclass
class SimResult:
    name: str
    equity: list[tuple[datetime, float]]
    trades: list[dict] = field(default_factory=list)
    fees: float = 0.0
    events: list[Event] = field(default_factory=list)
    halted: str | None = None


def without_total_limit(cfg: dict) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg["risk"]["max_total_loss_pct"] = 1e9
    return cfg


def simulate(cfg: dict, hist: History, start: datetime, end: datetime, cash: float = 100.0,
             fee: float = FEE, slippage: float = SLIPPAGE) -> SimResult:
    broker = SimBroker(hist, cash, fee, slippage)
    rules = AI(cfg["ai"]["model"], api_key="")
    if not (cfg.get("radar") or {}).get("early_watch"):
        # With early watch off the radar's notes only reach Claude, which isn't used here, so skip the work
        cfg = copy.deepcopy(cfg)
        cfg.setdefault("radar", {})["enabled"] = False
    res = SimResult(cfg["name"], [])
    with tempfile.TemporaryDirectory() as tmp, offline_sentiment(hist):
        store = Store(tmp, cfg["name"])
        t = start
        while t <= end:
            broker.now = _CLOCK.now = t
            run = pipeline.run(cfg, broker, rules, store, now=t)
            for x in run.exits:   # "SOLD BTCUSD: stop hit (...)" -> remember why each trade ended
                if x.startswith("SOLD ") and broker.round_trips and broker.round_trips[-1]["closed"] == t.isoformat():
                    sym, why = x[5:].split(": ", 1)
                    for rt in broker.round_trips[::-1]:
                        if rt["closed"] != t.isoformat():
                            break
                        if norm(rt["symbol"]) == sym:
                            rt["exit"] = why.split(" (")[0]
            if run.candidates:
                has_news = any(c.news_note != "no recent news" for c in run.candidates)
                approved = any(c.risk_verdict in ("APPROVE", "REDUCE") for c in run.candidates)
                # Live: News asks Claude when there are headlines, Sentiment almost always, Decision if Risk approved.
                res.events.append(Event(t, cfg["name"], int(has_news) + 1 + int(approved), bool(run.buys)))
            res.equity.append((t, broker.equity()))
            if res.halted is None and store.state["halted_reason"]:
                res.halted = f"{t:%Y-%m-%d}: {store.state['halted_reason']}"
            t += TICK
    res.trades, res.fees = broker.round_trips, broker.fees_paid
    return res


def buy_and_hold(name: str, hist: History, symbols: list[str], start: datetime, end: datetime,
                 cash: float = 100.0, fee: float = FEE, slippage: float = SLIPPAGE) -> SimResult:
    """Put the money in on day one (split evenly) and never touch it."""
    qty = {}
    for s in symbols:
        px = hist.price(s, start)
        if px:
            qty[s] = cash / len(symbols) * (1 - fee) / (px * (1 + slippage))
    res = SimResult(name, [], fees=cash * fee * len(qty) / len(symbols))
    t = start
    while t <= end:
        res.equity.append((t, sum(q * (hist.price(s, t) or 0) for s, q in qty.items())))
        t += TICK
    return res


def stats(r: SimResult, cash: float) -> dict:
    eq = pd.Series([e for _, e in r.equity], index=[t for t, _ in r.equity])
    peak = eq.cummax()
    daily = eq.resample("1D").last()
    wins = [t for t in r.trades if t["pnl"] > 0]
    return {
        "name": r.name, "start_value": cash, "end_value": float(eq.iloc[-1]),
        "return_pct": (eq.iloc[-1] / cash - 1) * 100,
        "max_drawdown_pct": float(((eq - peak) / peak).min() * 100),
        "worst_day_pct": float(daily.pct_change().min() * 100) if len(daily) > 1 else 0.0,
        "trades": len(r.trades), "win_rate_pct": len(wins) / len(r.trades) * 100 if r.trades else 0.0,
        "fees": r.fees, "halted": r.halted,
        "monthly_values": {f"{t:%Y-%m}": round(float(v), 2) for t, v in eq.resample("ME").last().items()},
    }


# ---- part 2: Claude check on a sample of moments ------------------------------------------------

def trade_outcome(hist: History, symbol: str, plan, opened: datetime, cfg: dict, fee: float = FEE,
                  slippage: float = SLIPPAGE) -> dict:
    """Play one trade forward with the live exit rules (checked every 30 min) and return its result."""
    stop, entry_fill = plan.stop, plan.entry * (1 + slippage)
    r_unit = plan.entry - plan.stop
    t, px = opened, plan.entry
    limit = opened + timedelta(hours=cfg["exits"]["max_hold_hours"])
    why = "data ran out"
    last = hist.bars["15Min"][symbol].index[-1].to_pydatetime() + 2 * TICK
    while True:
        t += TICK
        p = hist.price(symbol, t)
        if p is None or t > last:
            break
        px = p
        if px <= stop:
            why = "stop"
            break
        if px >= plan.target:
            why = "target"
            break
        if t >= limit:
            why = "time limit"
            break
        if stop < plan.entry and px >= plan.entry + cfg["exits"]["move_stop_to_breakeven_at_r"] * r_unit:
            stop = plan.entry
    ret = (1 - fee) / entry_fill * px * (1 - slippage) * (1 - fee) - 1
    return {"exit": why, "return_pct": ret * 100, "hours": (t - opened).total_seconds() / 3600}


def _setups(cfg: dict, broker: SimBroker) -> list:
    sc = cfg["scout"]
    bars = broker.get_bars(cfg["markets"]["crypto"], sc["bar_timeframe"], sc["lookback_bars"], "crypto")
    cands = sorted(scout.scan(bars, "crypto", sc), key=lambda c: c.scout_score, reverse=True)[: sc["max_candidates"] * 2]
    for c in cands:
        c.plan = charts.make_plan(c, cfg["charts"])
    btc = broker.get_bars(["BTC/USD"], sc["bar_timeframe"], sc["lookback_bars"], "crypto").get("BTC/USD")
    cands, _ = filters.apply([c for c in cands if c.plan], cfg.get("filters"), btc, sentiment.fear_greed)
    return cands[: sc["max_candidates"]]


def judge_moment(cfg: dict, hist: History, t: datetime, models: list[str]) -> dict | None:
    """Re-run News, Sentiment, Risk and Decision at one past moment with each model and with the rules.
    The account is a fresh $100 with nothing held, so every model sees exactly the same setups."""
    broker = SimBroker(hist, 100.0)
    broker.now = _CLOCK.now = t
    setups = _setups(cfg, broker)
    if not setups:
        return None
    outcomes = {c.symbol: trade_outcome(hist, c.symbol, c.plan, t, cfg) for c in setups}
    row = {"time": t.isoformat(), "strategy": cfg["name"], "outcomes": outcomes, "calls": {}}
    for label in ["rules"] + models:
        ai = AI(label, cfg["ai"].get("effort", "low"), api_key="" if label == "rules" else None)
        cands = [copy.copy(c) for c in setups]
        news.analyze(cands, broker, ai)
        sentiment.analyze(cands, ai)
        for c in cands:
            risk.review(c, 100.0, 100.0, [], {}, cfg["risk"])
        decision.decide(cands, ai, cfg["name"])
        row["calls"][label] = {
            "picks": [c.symbol for c in cands if c.decision == cfg["decision"]["buy_only_on"]
                      and c.confidence >= cfg["decision"]["min_confidence"] and c.risk_verdict != "REJECT"],
            "decisions": {c.symbol: f"{c.decision} {c.confidence:.2f}: {c.decision_note}" for c in cands},
            "claude_calls": ai.calls, "input_tokens": ai.input_tokens, "output_tokens": ai.output_tokens,
            "cost": cost_usd(label, ai.input_tokens, ai.output_tokens),
            "fell_back": label != "rules" and any("rule-based" in c.decision_note for c in cands
                                                  if c.risk_verdict != "REJECT"),
        }
    return row


def compare_models(cfgs: dict[str, dict], hist: History, events: list[Event], n: int, budget: float,
                   ai_from: datetime, models: list[str] = MODELS, seed: int = 7, workers: int = 3) -> dict:
    pool = [e for e in events if e.time >= ai_from]
    # Half the sample from each strategy where possible.
    by = {s: [e for e in pool if e.strategy == s] for s in cfgs}
    rng = random.Random(seed)
    picks = []
    for s, evs in by.items():
        picks += rng.sample(evs, min(len(evs), n // len(by)))
    rest = [e for e in pool if e not in picks]
    picks += rng.sample(rest, min(len(rest), n - len(picks)))
    picks.sort(key=lambda e: e.time)

    rows, spent, per_event = [], 0.0, 0.30   # first guess at cost per moment, replaced by real numbers
    with offline_sentiment(hist), ThreadPoolExecutor(workers) as ex:
        for i in range(0, len(picks), workers):
            batch = picks[i:i + workers]
            if spent + per_event * len(batch) > budget:
                log.warning("Stopping the Claude check at $%.2f to stay under the $%.2f cap.", spent, budget)
                break
            for row in ex.map(lambda e: judge_moment(cfgs[e.strategy], hist, e.time, models), batch):
                if row:
                    rows.append(row)
                    spent += sum(c["cost"] for c in row["calls"].values())
            if rows:
                per_event = max(per_event if len(rows) < 3 else 0.0,
                                max(sum(c["cost"] for c in r["calls"].values()) for r in rows))
            log.warning("Claude check: %d moments done, $%.2f spent", len(rows), spent)
    return {"rows": rows, "spent": spent, "pool": len(pool), "requested": n}


def summarize_models(check: dict, models: list[str] = MODELS) -> dict:
    out = {}
    rows = check["rows"]
    for label in ["rules"] + models:
        rets, calls, inp, outp, cost, fell = [], 0, 0, 0, 0.0, 0
        for r in rows:
            c = r["calls"][label]
            rets += [r["outcomes"][s]["return_pct"] for s in c["picks"]]
            calls, inp, outp, cost = calls + c["claude_calls"], inp + c["input_tokens"], outp + c["output_tokens"], cost + c["cost"]
            fell += c["fell_back"]
        out[label] = {"trades_taken": len(rets), "wins": sum(x > 0 for x in rets),
                      "avg_return_pct": float(np.mean(rets)) if rets else 0.0, "total_return_pct": float(sum(rets)),
                      "claude_calls": calls, "input_tokens": inp, "output_tokens": outp, "cost": cost,
                      "cost_per_call": cost / calls if calls else None, "fell_back": fell}
    every = [o["return_pct"] for r in rows for o in r["outcomes"].values()]
    out["every setup"] = {"trades_taken": len(every), "wins": sum(x > 0 for x in every),
                          "avg_return_pct": float(np.mean(every)) if every else 0.0, "total_return_pct": float(sum(every))}
    if len(models) >= 2 and rows:
        a, b = models[0], models[1]
        same = total = 0
        for r in rows:
            for s in r["outcomes"]:
                total += 1
                same += (s in r["calls"][a]["picks"]) == (s in r["calls"][b]["picks"])
        out["agreement_pct"] = same / total * 100 if total else None
    return out


# ---- report ---------------------------------------------------------------------------------------

def money(x: float) -> str:
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def yearly_claude_cost(events: list[Event], days: float, cost_per_call: float) -> float:
    return sum(e.claude_calls for e in events) * cost_per_call * 365 / days


def render(results: dict) -> str:
    s, days = results["stats"], results["days"]
    o = [f"# Backtest: {results['start'][:10]} to {results['end'][:10]} ({days:.0f} days)", "",
         f"Each line starts with {money(results['cash'])}. Trading fees ({FEE * 100:.2f}% per buy or sell) and "
         f"{SLIPPAGE * 100:.2f}% slippage are included. Bots are checked every 30 minutes, like the live ones.", "",
         "## 1. Full replay with the rule-based bots", "",
         "| | End value | Return | Worst drop from a high | Worst day | Trades | Wins | Fees paid |",
         "|---|---|---|---|---|---|---|---|"]
    rows = [k for k in ("aggressive", "aggressive_nostop", "medium", "medium_nostop", "hold_btc", "hold_all") if k in s]
    for k in rows:
        x = s[k]
        wins = f"{x['win_rate_pct']:.0f}%" if x["trades"] else "-"
        o.append(f"| {x['label']} | {money(x['end_value'])} | {x['return_pct']:+.1f}% | {x['max_drawdown_pct']:.1f}% "
                 f"| {x['worst_day_pct']:.1f}% | {x['trades'] or '-'} | {wins} | {money(x['fees'])} |")
    for k in ("aggressive", "medium"):
        if s[k]["halted"]:
            day, why = s[k]["halted"].split(": ", 1)
            o.append(f"\n**{s[k]['label']} hit its total loss limit on {day}** ({why.rstrip('.')}) and stopped trading, "
                     "as the live bot would until you press Resume. The \"never stopped\" line shows what would have "
                     "happened if it had kept going.")
    o += ["", "Month-end values:", "", "| Month | " + " | ".join(s[k]["label"] for k in rows) + " |",
          "|---|" + "---|" * len(rows)]
    for m in s["aggressive"]["monthly_values"]:
        o.append(f"| {m} | " + " | ".join(money(s[k]["monthly_values"].get(m, 0)) for k in rows) + " |")

    o += ["", "## 2. Claude cost for a year", "",
          "How often each strategy found a setup over the year (that is when the live bots ask Claude), times the "
          "cost per call measured in part 3.", "", "| | Setups found | Claude calls | Opus per year | Haiku per year |", "|---|---|---|---|---|"]
    for k in ("aggressive", "medium"):
        c = results["claude_cost"][k]
        o.append(f"| {s[k]['label']} | {c['events']} | {c['calls']} | {money(c['claude-opus-5-5'])} | {money(c['claude-haiku-5-5'])} |")
    if results["claude_cost"].get("estimated"):
        o.append("\n_Cost per call is an estimate because the Claude check did not run._")

    m = results.get("models")
    o += ["", "## 3. Claude check: Opus vs Haiku vs rules", ""]
    if not m or not results["check"]["rows"]:
        o.append("Did not run (no Claude key, or no setups after the sample start date).")
    else:
        ch = results["check"]
        o += [f"{len(ch['rows'])} moments picked at random from {ch['pool']} setups after {results['ai_from'][:10]}. "
              f"Each trade a bot chose to take was played forward with the real stop, target and time limit. "
              f"Claude spend for this check: {money(ch['spent'])}.", "",
              "| Who decides | Trades taken | Winners | Avg result per trade | Claude calls | Cost of this check | Cost per call |",
              "|---|---|---|---|---|---|---|"]
        names = {"rules": "Rules only (no Claude)", "claude-opus-5-5": "Claude Opus 5.5 (current)",
                 "claude-haiku-5-5": "Claude Haiku 5.5", "every setup": "Take every setup"}
        for label in ["claude-opus-5-5", "claude-haiku-5-5", "rules", "every setup"]:
            x = m[label]
            per = x.get("cost_per_call")
            o.append(f"| {names[label]} | {x['trades_taken']} | {x['wins']} | {x['avg_return_pct']:+.2f}% | "
                     f"{x.get('claude_calls', '-')} | {money(x['cost']) if 'cost' in x else '-'} | "
                     f"{money(per) if per else '-'} |")
        if m.get("agreement_pct") is not None:
            o.append(f"\nOpus and Haiku made the same take/skip call on {m['agreement_pct']:.0f}% of setups.")
        fb = {k: m[k]["fell_back"] for k in MODELS if m[k]["fell_back"]}
        if fb:
            o.append(f"\nClaude did not answer every time, so the rules filled in: {fb}.")
    o += ["", "## What this can't tell you", "",
          "- Part 1 uses the rule-based bots for the whole year. The live bots use Claude, and part 3 is how we check "
          "whether Claude does better or worse than the rules.",
          "- Reddit mention counts have no history, so Sentiment only sees the Fear & Greed index here.",
          "- Part 3 is a small sample. A few lucky or unlucky trades can swing it.",
          "- Past prices don't predict future prices."]
    return "\n".join(o) + "\n"


# ---- command line ---------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="tradebots.backtest")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--cash", type=float, default=100.0)
    ap.add_argument("--sample", type=int, default=30, help="moments to replay with Claude (0 = skip)")
    ap.add_argument("--max-claude-usd", type=float, default=4.0, help="hard cap on Claude spend for the check")
    ap.add_argument("--ai-from", default="2026-07-01", help="only sample moments after this date (Claude's memory)")
    ap.add_argument("--end", help="last day to replay (default: now)")
    ap.add_argument("--out", default="backtest-results")
    ap.add_argument("--cache", help="save/load downloaded history here (pickle) to avoid re-downloading")
    args = ap.parse_args(argv)

    cfgs = {s: load_config(s) for s in ("aggressive", "medium")}
    symbols = cfgs["aggressive"]["markets"]["crypto"]
    end = (datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end
           else datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0))
    start = end - timedelta(days=args.days)
    warmup = timedelta(days=15)   # Medium reads 300 hourly candles before its first decision

    if args.cache and Path(args.cache).exists():
        hist = pickle.loads(Path(args.cache).read_bytes())
    else:
        key = os.environ.get("ALPACA_MEDIUM_KEY_ID") or os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", "")
        sec = os.environ.get("ALPACA_MEDIUM_SECRET_KEY") or os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", "")
        hist = fetch_history(symbols, start - warmup, end, key, sec)
        if args.cache:
            Path(args.cache).write_bytes(pickle.dumps(hist))

    sims = {}
    for name, cfg in cfgs.items():
        log.warning("Replaying %s...", name)
        sims[name] = simulate(cfg, hist, start, end, args.cash)
        if sims[name].halted:
            # Also run it as if you had pressed Resume every time, to see whether it would have recovered.
            log.warning("Replaying %s without the total loss limit...", name)
            sims[f"{name}_nostop"] = simulate(without_total_limit(cfg), hist, start, end, args.cash)
    sims["hold_btc"] = buy_and_hold("hold_btc", hist, ["BTC/USD"], start, end, args.cash)
    sims["hold_all"] = buy_and_hold("hold_all", hist, symbols, start, end, args.cash)
    labels = {"aggressive": "Aggressive bots", "medium": "Medium bots", "hold_btc": "Just hold Bitcoin",
              "hold_all": "Hold all 8 coins", "aggressive_nostop": "Aggressive, never stopped",
              "medium_nostop": "Medium, never stopped"}
    st = {k: {**stats(v, args.cash), "label": labels[k]} for k, v in sims.items()}

    # A strategy that hit its loss limit stops looking for trades, so take the moments the bots found a
    # setup (for the Claude check and the cost estimate) from the run that kept going.
    running = {k: sims.get(f"{k}_nostop", sims[k]) for k in cfgs}
    events = running["aggressive"].events + running["medium"].events
    ai_from = datetime.fromisoformat(args.ai_from).replace(tzinfo=timezone.utc)
    check, models = {"rows": [], "spent": 0.0, "pool": 0}, None
    if args.sample and os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("Claude check on up to %d moments (cap $%.2f)...", args.sample, args.max_claude_usd)
        check = compare_models(cfgs, hist, events, args.sample, args.max_claude_usd, ai_from)
        models = summarize_models(check)

    days = (end - start).total_seconds() / 86400
    claude_cost = {"estimated": not (models and models["claude-opus-5-5"]["cost_per_call"])}
    for k in ("aggressive", "medium"):
        evs = running[k].events
        claude_cost[k] = {"events": len(evs), "calls": sum(e.claude_calls for e in evs)}
        for mdl in MODELS:
            per = (models or {}).get(mdl, {}).get("cost_per_call") or cost_usd(mdl, 2500, 1500)  # rough guess per call
            claude_cost[k][mdl] = yearly_claude_cost(evs, days, per)

    results = {"start": start.isoformat(), "end": end.isoformat(), "days": days, "cash": args.cash,
               "ai_from": ai_from.isoformat(), "stats": st, "claude_cost": claude_cost, "models": models,
               "check": check}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str))
    (out / "summary.md").write_text(text := render(results))
    eq = pd.DataFrame({k: pd.Series(dict(v.equity)) for k, v in sims.items()}).resample("1D").last().round(2)
    eq.to_csv(out / "daily_values.csv", index_label="day")
    for k in ("aggressive", "medium"):
        pd.DataFrame(sims[k].trades).to_csv(out / f"{k}_trades.csv", index=False)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
