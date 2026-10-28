"""Strategy lab: test one change to a strategy on past prices, honestly, and keep it only if it really helps.

  python -m tradebots.lab --strategy medium --set filters.btc_ema_bars=200 --idea "Only buy when Bitcoin is healthy"

How a change is tested (the "don't fool yourself" rules):
  1. The year is split in two. The first 60% are the "study months": the weekly loop shows Claude the
     losing trades from these months only. The last 40% are the "unseen months", which nobody has
     looked at when the idea is made, so they show how the idea does on new data.
  2. Fees and price slip are always included, and the change must still win with both doubled.
  3. The unseen months are cut into 5 slices (about a month each). The change must not do worse in
     more than one of them, so one lucky stretch can't carry it ("walk-forward" check).
  4. Each new number is nudged one step up and down, and those versions must also beat the current
     one. If a small nudge loses the gain, the number was probably just lucky ("overfitting":
     memorising the past instead of finding a real pattern).
  5. It must beat a simple yardstick over the unseen months: just holding Bitcoin (for Copycat, the
     S&P 500), and it needs enough trades to judge.
Only a change that passes every check is "kept". Kept changes become a pull request, so nothing
goes live until Quincy merges it. Every experiment, kept or rejected, is logged in data/lab/.

Only the parts that are plain rules can be tested this way (Scout, Charts, the filters, exits and
Copycat's copy rules). News, Sentiment and Decision use their rule-based stand-ins here, like the
backtest, because asking Claude for every 30 minutes of a year would cost too much.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import logging
import math
import multiprocessing as mp
import os
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import backtest as bt
from .bots import filters

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

STUDY_FRACTION = 0.6     # first 60% of the period: what Claude may study
WINDOWS = 5              # unseen months are checked in this many slices
MIN_EDGE_PTS = 1.0       # must beat the current version by at least 1 percentage point on unseen months
MONTH_TOLERANCE = 0.25   # a slice counts as "not worse" if within 0.25 points of the current version
MAX_EXTRA_DRAWDOWN = 5.0 # worst drop may be at most 5 points deeper than the current version's
COST_STRESS = 2.0        # fees and slippage multiplied by this for the "higher costs" check


# ---- the menu of things that can be changed --------------------------------------------------------

@dataclass(frozen=True)
class Knob:
    path: str            # "section.key" in the strategy's config file
    lo: float
    hi: float
    step: float
    what: str            # plain-English meaning, shown to Claude and in reports
    default: float | None = None   # value when the config doesn't set it (filters: 0 = switched off)
    switch: bool = False           # an on/off setting (0 or 1): nothing to nudge


CRYPTO_KNOBS = [
    Knob("scout.min_volume_ratio", 1.0, 4.0, 0.1, "Scout: how many times normal trading volume a coin needs"),
    Knob("scout.min_move_pct", 0.5, 6.0, 0.25, "Scout: how far (%) the price must have moved over the last few candles"),
    Knob("scout.min_rsi", 40, 60, 2, "Scout: lowest momentum score (RSI) allowed", 50),
    Knob("scout.max_rsi", 60, 90, 2, "Scout: highest momentum score (RSI) allowed; above it the move is 'exhausted'", 78),
    Knob("charts.stop_atr_mult", 1.0, 4.0, 0.25, "Charts: how far below the entry the safety exit (stop) sits, in typical candle swings (ATR)"),
    Knob("charts.min_reward_risk", 1.0, 4.0, 0.25, "Charts: the profit goal must be at least this many times the amount risked"),
    Knob("exits.max_hold_hours", 2, 240, 2, "Exits: sell after this many hours no matter what"),
    Knob("exits.move_stop_to_breakeven_at_r", 0.5, 3.0, 0.25, "Exits: once up this many times the risk, move the stop to the entry price"),
    Knob("filters.max_atr_pct", 0.3, 10.0, 0.1, "Filter: skip coins that swing more than this % per candle (too wild)", 0),
    Knob("filters.trend_ema_bars", 50, 200, 25, "Filter: only buy when the coin is above its N-candle average (uptrend)", 0),
    Knob("filters.btc_ema_bars", 50, 200, 25, "Filter: only buy when Bitcoin is above its N-candle average (healthy market)", 0),
    Knob("filters.min_fear_greed", 5, 60, 5, "Filter: skip when the Fear & Greed index is below this (panic)", 0),
    Knob("filters.max_fear_greed", 40, 95, 5, "Filter: skip when the Fear & Greed index is above this (greed)", 0),
    Knob("radar.early_watch", 0, 1, 1, "News radar early watch: 1 lets coins with strong news buzz past Scout with "
         "looser volume and move rules (0 = off)", 0, switch=True),
    Knob("radar.early_min_score", 0.3, 0.8, 0.05, "News radar early watch: news score (-1..+1) a coin needs to qualify"),
    Knob("radar.early_factor", 0.3, 0.9, 0.1, "News radar early watch: share of Scout's usual volume and move rules "
         "an early-watch coin must still meet"),
]
COPYCAT_KNOBS = [
    Knob("copycat.min_buy_usd", 25000, 1000000, 25000, "Only copy when insiders bought at least this many dollars in total"),
    Knob("copycat.min_insiders", 1, 4, 1, "Only copy when at least this many different insiders bought", 1),
    Knob("copycat.min_score", 0, 4, 0.25, "Only copy picks scoring at least this (bigger buys, more insiders, a CEO/CFO buying)", 0),
    Knob("copycat.max_signal_age_days", 1, 10, 1, "Copy a buy only this many days after it was filed"),
    Knob("copycat.max_chase_pct", 1, 25, 1, "Skip if the price is already this % above what the insiders paid"),
    Knob("copycat.stop_pct", 3, 30, 1, "Safety exit this % below our entry"),
    Knob("copycat.target_pct", 5, 60, 5, "Profit goal this % above our entry"),
    Knob("exits.max_hold_hours", 120, 2160, 120, "Sell after this many hours (24 per day) no matter what"),
]


FOREX_KNOBS = [
    Knob("forex.entry_days", 20, 100, 5, "Trade when the price closes past its highest (or lowest) price of this many days"),
    Knob("forex.exit_days", 10, 55, 5, "Get out when the price closes past the opposite high (or low) of this many days"),
    Knob("forex.trend_ema_days", 50, 300, 25, "Only buy above (sell below) the N-day average price (0 = off)", 0),
    Knob("forex.stop_atr_mult", 1.0, 5.0, 0.5, "Safety stop this many typical daily swings (ATR) from the entry"),
]
FXCOPY_KNOBS = [
    Knob("forex.min_net_pct", 2.5, 40, 2.5, "Copy when the hedge funds' net bet is at least this % of all open contracts"),
    Knob("forex.exit_net_pct", -10, 20, 2.5, "Get out when their net bet falls to this % (0 = it flipped sides)", 0),
    Knob("forex.need_growing", 0, 1, 1, "1 = only copy a bet that grew since the week before (0 = off)", 0, switch=True),
    Knob("forex.stop_atr_mult", 1.5, 6.0, 0.5, "Safety stop this many typical daily swings (ATR) from the entry"),
]
MOMENTUM_KNOBS = [
    Knob("forex.momentum_days", 90, 540, 30, "Buy pairs that rose (sell pairs that fell) over this many calendar days"),
    Knob("forex.stop_atr_mult", 2.0, 8.0, 0.5, "Safety stop this many typical daily swings (ATR) from the entry"),
]
CARRY_KNOBS = [
    Knob("forex.carry_enter_pct", 0.25, 3.0, 0.25, "Trade when one currency pays at least this many points more interest"),
    Knob("forex.carry_exit_pct", 0.0, 2.0, 0.25, "Get out when the interest gap shrinks below this many points", 0),
    Knob("forex.stop_atr_mult", 2.0, 8.0, 0.5, "Safety stop this many typical daily swings (ATR) from the entry"),
]
ORB_KNOBS = [
    Knob("forex.range_minutes", 15, 90, 15, "The opening range is the high and low of this many minutes after the open"),
    Knob("forex.entry_hours", 1, 6, 1, "Only take a breakout within this many hours after the range is set"),
    Knob("forex.exit_hour", 11, 17, 1, "Close any open trade at this hour (local time of that market)"),
    Knob("forex.max_cost_pct", 5, 30, 2.5, "Skip days when fees would be more than this % of the risk (0 = off)", 0),
]
# The gold bounce (gold.py), on 30-minute XAU/USD candles
BOUNCE_KNOBS = [
    Knob("forex.selloff_atr", 2.0, 6.0, 0.5, "The selloff must be at least this many typical candle swings (ATR) deep"),
    Knob("forex.target_r", 1.0, 4.0, 0.5, "Profit goal: this many times what the trade risks"),
    Knob("forex.breakeven_r", 0.5, 2.0, 0.25, "Once up this many times the risk, move the stop to the entry price"),
    Knob("forex.max_hold_bars", 16, 96, 8, "Sell after this many 30-minute candles regardless"),
    Knob("forex.trend_days", 20, 200, 10, "Only buy when yesterday closed above the N-day average (0 = off)", 0),
]
FOREX_STRATEGIES = ("forex", "fxcopy")
# The bold rules (hunt.py) tested with an account's loss limits in place of its AI bots.
HUNT_KNOBS = {
    "lev_trend": [Knob("hunt.sma_days", 100, 300, 25, "Hold the 3x fund while the index is above its N-day average")],
    "lev_dip": [Knob("hunt.rsi_entry", 5, 30, 5, "Buy when the 2-day momentum score (RSI) closes under this"),
                Knob("hunt.exit_sma_days", 3, 10, 1, "Sell when the index closes above its N-day average"),
                Knob("hunt.trend_days", 100, 300, 25, "Only buy while the index is above its N-day average")],
    "multi_trend": [Knob("hunt.lookback_days", 126, 378, 21, "Hold a market's leveraged fund if it rose over this many trading days")],
    "crypto_rotation": [Knob("hunt.lookback_days", 7, 84, 7, "Pick the coin that rose most over this many days"),
                        Knob("hunt.btc_sma_days", 70, 280, 35, "Only hold a coin while Bitcoin is above its N-day average")],
}
# The playbook rules (playbook.py) that Aggressive and Medium can be tested with in place of Scout & co.
PLAYBOOK_KNOBS = {
    "trend": [Knob("playbook.fast_days", 20, 100, 10, "Fast average: this many days"),
              Knob("playbook.slow_days", 100, 300, 25, "Slow average: this many days"),
              Knob("playbook.stop_atr_mult", 1.5, 6.0, 0.5, "Safety stop this many typical daily swings (ATR) below the entry")],
    "breakout": [Knob("playbook.entry_days", 10, 60, 5, "Buy a close above the highest price of this many days"),
                 Knob("playbook.exit_days", 5, 30, 5, "Sell a close below the lowest price of this many days"),
                 Knob("playbook.min_volume_ratio", 1.0, 3.0, 0.25, "Volume must be this many times normal"),
                 Knob("playbook.stop_atr_mult", 1.0, 5.0, 0.5, "Safety stop this many typical daily swings (ATR) below the entry")],
    "swing": [Knob("playbook.oversold", 20, 40, 5, "The first low's momentum score (RSI) must be under this"),
              Knob("playbook.exit_rsi", 55, 80, 5, "Sell when the momentum score (RSI) gets above this"),
              Knob("playbook.max_hold_bars", 30, 180, 12, "Sell after this many 4-hour candles regardless")],
    "daytrade": [Knob("playbook.range_minutes", 15, 120, 15, "The opening range is the first this many minutes of the day"),
                 Knob("playbook.entry_hours", 1, 8, 1, "Only buy a break within this many hours after the range")],
    "scalp": [Knob("playbook.stop_atr_mult", 0.5, 3.0, 0.25, "Stop this many typical candle swings (ATR) below the entry"),
              Knob("playbook.target_atr_mult", 0.5, 4.0, 0.25, "Profit goal this many typical candle swings above the entry"),
              Knob("playbook.max_hold_bars", 6, 48, 6, "Sell after this many 5-minute candles regardless")],
}


def knobs_for(strategy: str, cfg: dict | None = None) -> list[Knob]:
    if strategy in FOREX_STRATEGIES:
        style = (cfg or load_config(strategy))["forex"]["style"]
        return {"trend": FOREX_KNOBS, "cot": FXCOPY_KNOBS, "momentum": MOMENTUM_KNOBS, "carry": CARRY_KNOBS,
                "orb": ORB_KNOBS, "bounce": BOUNCE_KNOBS}[style]
    if cfg and cfg.get("playbook"):
        return PLAYBOOK_KNOBS[cfg["playbook"]["style"]]
    if cfg and cfg.get("hunt"):
        return HUNT_KNOBS[cfg["hunt"]["style"]]
    return {"copycat": COPYCAT_KNOBS}.get(strategy, CRYPTO_KNOBS)


def get_value(cfg: dict, path: str, knob: Knob | None = None):
    section, key = path.split(".")
    v = (cfg.get(section) or {}).get(key)
    return v if v is not None else (knob.default if knob else None)


def set_value(cfg: dict, path: str, value) -> None:
    section, key = path.split(".")
    if cfg.get(section) is None:
        cfg[section] = {}
    cfg[section][key] = value


def shown(path: str, v) -> str:
    return "off" if path.startswith("filters.") and not v else str(v)


def apply_changes(cfg: dict, changes: dict) -> dict:
    out = copy.deepcopy(cfg)
    for path, v in changes.items():
        set_value(out, path, v)
    return out


def _snap(k: Knob, v: float) -> float | int:
    v = min(max(float(v), k.lo), k.hi)
    v = k.lo + round((v - k.lo) / k.step) * k.step
    v = round(v, 4)
    return int(v) if float(v).is_integer() and float(k.step).is_integer() else v


def clean_changes(strategy: str, cfg: dict, changes: dict) -> tuple[dict, list[str]]:
    """Keeps only changes on the menu, rounded to the knob's step and inside its range.
    0 (or null, or "off") switches a filter off. Returns (changes, problems)."""
    menu = {k.path: k for k in knobs_for(strategy, cfg)}
    out, problems = {}, []
    for path, v in changes.items():
        k = menu.get(path)
        if k is None:
            problems.append(f"{path} is not something the lab can change")
            continue
        if path.startswith("filters.") and v in (None, 0, "off"):
            v = 0
        else:
            try:
                v = _snap(k, float(v))
            except (TypeError, ValueError):
                problems.append(f"{path}: {v!r} is not a number")
                continue
        if v == get_value(cfg, path, k):
            problems.append(f"{path} is already {v}")
            continue
        out[path] = v
    return out, problems


def nudged(strategy: str, changes: dict, cfg: dict | None = None) -> list[dict]:
    """The same change with each new number moved one step down and one step up."""
    menu = {k.path: k for k in knobs_for(strategy, cfg)}
    out = []
    for path, v in changes.items():
        k = menu[path]
        if k.switch or (not v and path.startswith("filters.")):
            continue
        for d in (-k.step, k.step):
            w = _snap(k, v + d)
            if w != v:
                out.append({**changes, path: w})
    return out


def describe_changes(cfg: dict, changes: dict, strategy: str) -> list[str]:
    menu = {k.path: k for k in knobs_for(strategy, cfg)}
    lines = []
    for path, v in changes.items():
        old = get_value(cfg, path, menu.get(path))
        lines.append(f"`{path}`: {shown(path, old)} → {shown(path, v)}"
                     f" ({menu[path].what if path in menu else ''})")
    return lines


# ---- engines: what replays a strategy over the past --------------------------------------------------

class CryptoEngine:
    """Aggressive and Medium: the real six-bot pipeline replayed every 30 minutes (see backtest.py)."""
    benchmark_label = "Just hold Bitcoin"
    min_trades = 10

    def __init__(self, hist: bt.History, start: datetime, end: datetime, cash: float = 100.0):
        self.hist, self.start, self.end, self.cash = hist, start, end, cash

    def run(self, cfg: dict, start: datetime, end: datetime, cost: float = 1.0) -> bt.SimResult:
        # Without the total loss limit: the lab measures whether the rules make money, and a strategy
        # that halted halfway would hide that. The daily limit still applies.
        return bt.simulate(bt.without_total_limit(cfg), self.hist, start, end, self.cash,
                           bt.FEE * cost, bt.SLIPPAGE * cost)

    def benchmark(self, start: datetime, end: datetime) -> bt.SimResult:
        return bt.buy_and_hold("benchmark", self.hist, ["BTC/USD"], start, end, self.cash)

    def trade_rows(self, res: bt.SimResult, cfg: dict) -> list[dict]:
        """Each trade with what the market looked like when it was bought, for Claude to study."""
        from .bots import scout
        from .indicators import atr, ema
        sc, flt = cfg["scout"], cfg.get("filters") or {}
        tf, lb = sc["bar_timeframe"], sc["lookback_bars"]
        rows = []
        for t in res.trades:
            opened, closed = datetime.fromisoformat(t["opened"]), datetime.fromisoformat(t["closed"])
            w = self.hist.window(tf, t["symbol"], opened, lb)
            btc = self.hist.window(tf, "BTC/USD", opened, lb)
            m = scout.measure(w, sc) if len(w) else None
            px = float(w["close"].iloc[-1]) if len(w) else float("nan")
            rows.append({
                "opened": opened.strftime("%Y-%m-%d %H:%M"), "coin": t["symbol"],
                "result_pct": round(t["pnl"] / t["cost"] * 100, 2), "exit": t.get("exit", "?"),
                "hours_held": round((closed - opened).total_seconds() / 3600, 1),
                "volume_x": round(m["volume_ratio"], 2) if m else None,
                "move_pct": round(m["move_pct"], 2) if m else None,
                "rsi": round(m["rsi"], 1) if m else None,
                "swing_pct": round(float(atr(w).iloc[-1]) / px * 100, 2) if len(w) > 15 else None,
                "vs_200avg_pct": round((px / float(ema(w["close"], 200).iloc[-1]) - 1) * 100, 1) if len(w) >= 50 else None,
                "btc_vs_200avg_pct": round((float(btc["close"].iloc[-1]) / float(ema(btc["close"], 200).iloc[-1]) - 1) * 100, 1)
                if len(btc) >= 50 else None,
                "fear_greed": self.hist.fear_greed(opened),
            })
        return rows


# ---- running many replays at once ----------------------------------------------------------------

_ENGINE = None   # set before the worker processes start, so they share the price history (fork)


def _job(args):
    cfg, start, end, cost = args
    return _ENGINE.run(cfg, start, end, cost)


class Runner:
    """Runs replays, several in parallel, and remembers results so the current version runs once."""

    def __init__(self, engine, workers: int | None = None):
        self.engine = engine
        self.workers = workers if workers is not None else min(4, os.cpu_count() or 1)
        self.memo: dict[str, bt.SimResult] = {}

    @staticmethod
    def _key(args) -> str:
        cfg, start, end, cost = args
        return json.dumps([cfg, start.isoformat(), end.isoformat(), cost], sort_keys=True, default=str)

    def run_many(self, jobs: list[tuple]) -> list[bt.SimResult]:
        global _ENGINE
        todo = [j for j in dict.fromkeys(self._key(j) for j in jobs) if j not in self.memo]
        by_key = {self._key(j): j for j in jobs}
        if self.workers > 1 and len(todo) > 1 and "fork" in mp.get_all_start_methods():
            _ENGINE = self.engine
            with ProcessPoolExecutor(min(self.workers, len(todo)), mp_context=mp.get_context("fork")) as ex:
                for k, r in zip(todo, ex.map(_job, [by_key[k] for k in todo])):
                    self.memo[k] = r
        else:
            for k in todo:
                self.memo[k] = self.engine.run(*by_key[k])
        return [self.memo[self._key(j)] for j in jobs]


# ---- the test itself -------------------------------------------------------------------------------

@dataclass
class Split:
    start: datetime
    study_end: datetime
    end: datetime
    windows: list[tuple[datetime, datetime]]


def make_split(start: datetime, end: datetime, study_fraction: float = STUDY_FRACTION, n: int = WINDOWS) -> Split:
    study_end = start + (end - start) * study_fraction
    study_end = study_end.replace(minute=0, second=0, microsecond=0)
    step = (end - study_end) / n
    edges = [study_end + step * i for i in range(n)] + [end]
    return Split(start, study_end, end, [(edges[i], edges[i + 1]) for i in range(n)])


def pct(res: bt.SimResult, a: datetime | None = None, b: datetime | None = None) -> float:
    """Return (%) between two moments of a replay's value curve."""
    eq = [(t, v) for t, v in res.equity if (a is None or t >= a) and (b is None or t <= b)]
    if len(eq) < 2 or eq[0][1] <= 0:
        return 0.0
    return (eq[-1][1] / eq[0][1] - 1) * 100


@dataclass
class Verdict:
    kept: bool
    checks: list[dict] = field(default_factory=list)    # {name, passed, detail}
    numbers: dict = field(default_factory=dict)


def judge(engine, runner: Runner, cfg: dict, changes: dict, split: Split, strategy: str) -> Verdict:
    new_cfg = apply_changes(cfg, changes)
    S, U = (split.start, split.study_end), (split.study_end, split.end)
    neighbours = [apply_changes(cfg, n) for n in nudged(strategy, changes)]
    jobs = [(cfg, *S, 1.0), (new_cfg, *S, 1.0), (cfg, *U, 1.0), (new_cfg, *U, 1.0),
            (cfg, *U, COST_STRESS), (new_cfg, *U, COST_STRESS)] + [(n, *U, 1.0) for n in neighbours]
    old_s, new_s, old_u, new_u, old_x, new_x, *nb = runner.run_many(jobs)
    bench = engine.benchmark(*U)
    cash = engine.cash

    so, sn, uo, un = pct(old_s), pct(new_s), pct(old_u), pct(new_u)
    xo, xn, bu = pct(old_x), pct(new_x), pct(bench)
    months = [(pct(old_u, a, b), pct(new_u, a, b)) for a, b in split.windows]
    not_worse = sum(n >= o - MONTH_TOLERANCE for o, n in months)
    dd_old, dd_new = bt.stats(old_u, cash)["max_drawdown_pct"], bt.stats(new_u, cash)["max_drawdown_pct"]
    nb_pcts = [pct(r) for r in nb]
    trades = len(new_u.trades)
    need_months = WINDOWS - 1

    checks = [
        {"name": "Better on the unseen months", "passed": un - uo >= MIN_EDGE_PTS,
         "detail": f"{un:+.1f}% with the change vs {uo:+.1f}% now (needs at least {MIN_EDGE_PTS:.0f} point better)"},
        {"name": "Steady month to month", "passed": not_worse >= need_months,
         "detail": f"not worse in {not_worse} of {len(months)} slices (needs {need_months})"},
        {"name": "Still better with double fees and slip", "passed": xn - xo > 0,
         "detail": f"{xn:+.1f}% vs {xo:+.1f}% with costs doubled"},
        {"name": "Not a lucky number", "passed": all(p > uo for p in nb_pcts),
         "detail": ("nudged one step either way: " + ", ".join(f"{p:+.1f}%" for p in nb_pcts) + f" vs {uo:+.1f}% now")
         if nb_pcts else "nothing to nudge (a filter was switched off)"},
        {"name": f"Beats the yardstick ({engine.benchmark_label.lower()})", "passed": un > bu,
         "detail": f"{un:+.1f}% vs {bu:+.1f}% on the unseen months"},
        {"name": "Enough trades to judge", "passed": trades >= engine.min_trades,
         "detail": f"{trades} trades on the unseen months (needs {engine.min_trades})"},
        {"name": "No deeper losing streak", "passed": dd_new >= dd_old - MAX_EXTRA_DRAWDOWN,
         "detail": f"worst drop {dd_new:.1f}% vs {dd_old:.1f}% now"},
        {"name": "Also not worse on the study months", "passed": sn >= so,
         "detail": f"{sn:+.1f}% vs {so:+.1f}% on the months Claude looked at"},
    ]
    numbers = {"study_old": so, "study_new": sn, "unseen_old": uo, "unseen_new": un, "stress_old": xo,
               "stress_new": xn, "benchmark": bu, "months": months, "nudges": nb_pcts, "trades": trades,
               "trades_old": len(old_u.trades), "drawdown_old": dd_old, "drawdown_new": dd_new,
               "fees_new": new_u.fees}
    return Verdict(all(c["passed"] for c in checks), checks, numbers)


# ---- checking a whole strategy (not just a change to it) -------------------------------------------------

def validate(strategy: str, engine, runner: Runner, cfg: dict) -> tuple[Verdict, str]:
    """Is the strategy itself worth running? Same honesty rules as `judge`, but against doing nothing:
    it must make money after costs on the unseen months, on the study months, with doubled costs, with
    every main setting nudged a step, and without a drop deeper than the total loss limit."""
    if strategy in FOREX_STRATEGIES:
        from . import forex
        engine.min_trades = forex.min_trades(cfg)   # the rule being checked may not be the config file's
    split = make_split(engine.start, engine.end)
    S, U, A = (split.start, split.study_end), (split.study_end, split.end), (split.start, split.end)
    nudges = [n for k in knobs_for(strategy, cfg) if not k.switch and get_value(cfg, k.path, k)
              for n in nudged(strategy, {k.path: get_value(cfg, k.path, k)}, cfg)]
    neighbours = [apply_changes(cfg, n) for n in nudges]
    study, unseen, stress, full, *nb = runner.run_many(
        [(cfg, *S, 1.0), (cfg, *U, 1.0), (cfg, *U, COST_STRESS), (cfg, *A, 1.0)] + [(n, *U, 1.0) for n in neighbours])
    bench = pct(engine.benchmark(*U))
    sp, up, xp = pct(study), pct(unseen), pct(stress)
    months = [pct(unseen, a, b) for a, b in split.windows]
    good_months = sum(m >= -MONTH_TOLERANCE for m in months)
    nb_pcts = [pct(r) for r in nb]
    dd = bt.stats(full, engine.cash)["max_drawdown_pct"]
    limit = cfg["risk"]["max_total_loss_pct"]
    trades = len(unseen.trades)
    checks = [
        {"name": "Makes money on the unseen months", "passed": up > max(bench, 0),
         "detail": f"{up:+.1f}% vs {bench:+.1f}% for {engine.benchmark_label.lower()}"},
        {"name": "Also makes money on the study months", "passed": sp > 0, "detail": f"{sp:+.1f}%"},
        {"name": "Steady from slice to slice", "passed": good_months >= WINDOWS - 2,
         "detail": f"not losing in {good_months} of {len(months)} slices (needs {WINDOWS - 2}): "
                   + ", ".join(f"{m:+.1f}%" for m in months)},
        {"name": "Still makes money with double fees and slip", "passed": xp > 0, "detail": f"{xp:+.1f}%"},
        {"name": "Not a lucky setting", "passed": bool(nb_pcts) and all(x > 0 for x in nb_pcts),
         "detail": "each main setting nudged one step: " + ", ".join(f"{x:+.1f}%" for x in nb_pcts)},
        {"name": "Enough trades to judge", "passed": trades >= engine.min_trades,
         "detail": f"{trades} trades on the unseen months (needs {engine.min_trades})"},
        {"name": "Worst drop stays inside the total loss limit", "passed": -dd < limit,
         "detail": f"worst drop {dd:.1f}% over the whole period (limit -{limit}%)"},
    ]
    v = Verdict(all(c["passed"] for c in checks), checks,
                {"study": sp, "unseen": up, "stress": xp, "months": months, "nudges": nb_pcts, "drawdown": dd})
    eq = pd.Series([e for _, e in full.equity], index=[t for t, _ in full.equity])
    yearly = eq.resample("YE").last()
    prev, rows = engine.cash, []
    for t, val in yearly.items():
        rows.append(f"| {t.year} | {(val / prev - 1) * 100:+.1f}% | {bt.money(val)} |")
        prev = val
    wins = [t for t in full.trades if t["pnl"] > 0]
    head = "✅ Passed every check" if v.kept else "❌ Did not pass: " + "; ".join(c["name"].lower() for c in checks if not c["passed"])
    o = [f"# Strategy check: {cfg.get('title', strategy.title())}", "", f"**{head}**", "",
         f"Starts with {bt.money(engine.cash)}. Fees, the buy/sell gap (spread), slip and overnight interest included. "
         f"Study months: {split.start:%b %Y} to {split.study_end:%b %Y}. Unseen months: {split.study_end:%b %Y} to "
         f"{split.end:%b %Y}. The settings were picked before the test, from the textbook version of the rule, "
         "not tuned on these years.", "",
         "| | Result |", "|---|---|",
         f"| Whole period | {pct(full):+.1f}% ({bt.money(full.equity[-1][1])}) |",
         f"| Study months | {sp:+.1f}% |", f"| **Unseen months** | **{up:+.1f}%** |",
         f"| Unseen, costs doubled | {xp:+.1f}% |", f"| Worst drop from a high | {dd:.1f}% |",
         f"| Trades (whole period) | {len(full.trades)}, {len(wins)} winners ({len(wins) / max(1, len(full.trades)) * 100:.0f}%) |",
         "", "Year by year:", "", "| Year | Return | Value at year end |", "|---|---|---|", *rows, "", "## Checks", ""]
    o += [f"- {'✅' if c['passed'] else '❌'} **{c['name']}**: {c['detail']}" for c in checks]
    o += ["", "_Past results don't guarantee future ones. Even a pass has to prove itself on the practice account._"]
    return v, "\n".join(o) + "\n"


# ---- the experiment log ------------------------------------------------------------------------------

LOG_FIELDS = ["id", "time", "strategy", "source", "idea", "changes", "verdict", "unseen_new_pct", "unseen_old_pct",
              "benchmark_pct", "months_not_worse", "trades", "unseen_from", "unseen_to", "link"]


def lab_dir(data: Path) -> Path:
    d = Path(data) / "lab"
    (d / "reports").mkdir(parents=True, exist_ok=True)
    return d


def read_log(data: Path) -> list[dict]:
    p = lab_dir(data) / "experiments.csv"
    if not p.exists():
        return []
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def append_log(data: Path, row: dict) -> None:
    p = lab_dir(data) / "experiments.csv"
    new = not p.exists()
    with p.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def new_id(data: Path, strategy: str, now: datetime) -> str:
    n = sum(r["strategy"] == strategy for r in read_log(data)) + 1
    return f"{now:%Y%m%d}-{strategy}-{n}"


def tries_on_same_months(data: Path, strategy: str, split: Split) -> int:
    """How many ideas were already tested on (mostly) the same unseen months. Each extra try makes a
    lucky pass more likely, so the report says so."""
    n = 0
    for r in read_log(data):
        if r["strategy"] != strategy or not r.get("unseen_from"):
            continue
        a, b = datetime.fromisoformat(r["unseen_from"]), datetime.fromisoformat(r["unseen_to"])
        overlap = (min(b, split.end) - max(a, split.study_end)).total_seconds()
        if overlap > 0.5 * (split.end - split.study_end).total_seconds():
            n += 1
    return n


def log_row(exp_id: str, now: datetime, strategy: str, source: str, idea: str, changes: dict, v: Verdict,
            split: Split, link: str = "") -> dict:
    n = v.numbers
    return {"id": exp_id, "time": now.isoformat(timespec="seconds"), "strategy": strategy, "source": source,
            "idea": idea, "changes": json.dumps(changes), "verdict": "kept" if v.kept else "rejected",
            "unseen_new_pct": f"{n['unseen_new']:.2f}", "unseen_old_pct": f"{n['unseen_old']:.2f}",
            "benchmark_pct": f"{n['benchmark']:.2f}",
            "months_not_worse": sum(b >= a - MONTH_TOLERANCE for a, b in n["months"]), "trades": n["trades"],
            "unseen_from": split.study_end.isoformat(), "unseen_to": split.end.isoformat(), "link": link}


# ---- reports -----------------------------------------------------------------------------------------

def render(exp_id: str, strategy: str, idea: str, why: str, cfg: dict, changes: dict, v: Verdict, split: Split,
           engine, earlier_tries: int) -> str:
    n = v.numbers
    head = "✅ Kept: passed every check" if v.kept else "❌ Rejected: " + \
        "; ".join(c["name"] for c in v.checks if not c["passed"])
    o = [f"# Lab experiment {exp_id}: {strategy.title()}", "", f"**{head}**", "",
         f"**Idea:** {idea}", ""]
    if why:
        o += [f"**Why:** {why}", ""]
    o += ["**Change:**", ""] + [f"- {x}" for x in describe_changes(cfg, changes, strategy)] + [""]
    o += [f"Study months: {split.start:%b %-d, %Y} to {split.study_end:%b %-d, %Y}. "
          f"Unseen months: {split.study_end:%b %-d, %Y} to {split.end:%b %-d, %Y}. "
          f"Each replay starts with {bt.money(engine.cash)}, fees and price slip included.", "",
          "| | Now | With the change |", "|---|---|---|",
          f"| Study months | {n['study_old']:+.1f}% | {n['study_new']:+.1f}% |",
          f"| **Unseen months** | **{n['unseen_old']:+.1f}%** | **{n['unseen_new']:+.1f}%** |",
          f"| Unseen, fees and slip doubled | {n['stress_old']:+.1f}% | {n['stress_new']:+.1f}% |",
          f"| Worst drop from a high (unseen) | {n['drawdown_old']:.1f}% | {n['drawdown_new']:.1f}% |",
          f"| Trades (unseen) | {n['trades_old']} | {n['trades']} |",
          f"| {engine.benchmark_label} (unseen) | {n['benchmark']:+.1f}% | |", "",
          "Slice by slice (unseen months):", "", "| Slice | Now | With the change |", "|---|---|---|"]
    for (a, b), (x, y) in zip(split.windows, n["months"]):
        o.append(f"| {a:%b %-d} – {b:%b %-d} | {x:+.1f}% | {y:+.1f}% |")
    o += ["", "## Checks", ""]
    o += [f"- {'✅' if c['passed'] else '❌'} **{c['name']}**: {c['detail']}" for c in v.checks]
    if earlier_tries:
        o += ["", f"_Heads-up: {earlier_tries} earlier idea(s) were tested on mostly the same unseen months. "
                  "The more ideas we try on the same months, the likelier one passes by luck, so a kept change "
                  "still has to prove itself on paper before any real money._"]
    o += ["", "_Tested with the rule-based stand-ins for News, Sentiment and Decision (no Claude), like the "
              "backtest. Past results don't guarantee future ones._"]
    return "\n".join(o) + "\n"


# ---- loading history ---------------------------------------------------------------------------------

def load_config(strategy: str) -> dict:
    return bt.load_config(strategy)


def load_engine(strategy: str, days: int = 365, cache: str | None = None, end: datetime | None = None):
    """The engine for a strategy, with its past data downloaded (or read from `cache`)."""
    if strategy == "copycat":
        from . import insider_history
        return insider_history.load_engine(load_config("copycat"), days, cache, end)
    if strategy in FOREX_STRATEGIES:
        # Daily trend rules trade a few times a month, so one year is far too few trades to judge:
        # the Forex wing is tested on the last 8 years instead.
        from . import forex
        cfg = load_config(strategy)
        if cfg["forex"]["style"] == "orb":    # the day-trade rule replays 5-minute candles
            from . import orb
            return orb.load_engine(cfg, max(8, days // 365), cache, end)
        return forex.load_engine(strategy, cfg, max(8, days // 365), cache, end)
    import pickle
    end = end or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    if cache and Path(cache).exists():
        hist = pickle.loads(Path(cache).read_bytes())
    else:
        symbols = bt.load_config("aggressive")["markets"]["crypto"]
        key = os.environ.get("ALPACA_MEDIUM_KEY_ID") or os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", "")
        sec = os.environ.get("ALPACA_MEDIUM_SECRET_KEY") or os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", "")
        hist = bt.fetch_history(symbols, start - timedelta(days=15), end, key, sec)
        if cache:
            Path(cache).write_bytes(pickle.dumps(hist))
    return CryptoEngine(hist, start, end)


def parse_sets(items: list[str]) -> dict:
    out = {}
    for s in items:
        m = re.fullmatch(r"\s*([a-z_]+\.[a-z_]+)\s*=\s*(\S+)\s*", s)
        if not m:
            raise SystemExit(f"--set wants section.key=value, got {s!r}")
        v = m.group(2)
        out[m.group(1)] = 0 if v.lower() in ("off", "none", "null") else float(v)
    return out


def run_experiment(strategy: str, engine, runner: Runner, cfg: dict, changes: dict, idea: str, why: str,
                   source: str, data: Path, now: datetime) -> tuple[str, Verdict, str]:
    """Tests one change, logs it, and returns (experiment id, verdict, report markdown)."""
    split = make_split(engine.start, engine.end)
    earlier = tries_on_same_months(data, strategy, split)
    v = judge(engine, runner, cfg, changes, split, strategy)
    exp_id = new_id(data, strategy, now)
    text = render(exp_id, strategy, idea, why, cfg, changes, v, split, engine, earlier)
    (lab_dir(data) / "reports" / f"{exp_id}.md").write_text(text)
    append_log(data, log_row(exp_id, now, strategy, source, idea, changes, v, split, f"reports/{exp_id}.md"))
    return exp_id, v, text


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="tradebots.lab")
    ap.add_argument("--strategy", required=True, choices=["aggressive", "medium", "copycat", *FOREX_STRATEGIES])
    ap.add_argument("--validate", action="store_true",
                    help="test the strategy itself against doing nothing, instead of a change to it")
    ap.add_argument("--set", action="append", default=[], metavar="section.key=value",
                    help="the change to test, e.g. filters.btc_ema_bars=200 (repeat for two numbers)")
    ap.add_argument("--idea", default="", help="the idea in plain words, for the log")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--cache", help="save/load downloaded history here")
    ap.add_argument("--end", help="test up to this date (YYYY-MM-DD) instead of now")
    ap.add_argument("--workers", type=int)
    args = ap.parse_args(argv)

    cfg = load_config(args.strategy)
    if args.validate:
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end else None
        engine = load_engine(args.strategy, args.days, args.cache, end)
        cfg = apply_changes(cfg, parse_sets(args.set))
        _, text = validate(args.strategy, engine, Runner(engine, args.workers), cfg)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as f:
                f.write(text)
        print(text)
        return 0
    changes, problems = clean_changes(args.strategy, cfg, parse_sets(args.set))
    if problems:
        print("\n".join(f"- {p}" for p in problems))
    if not changes:
        print("Nothing to test. Things the lab can change:")
        for k in knobs_for(args.strategy):
            print(f"  {k.path} (now {get_value(cfg, k.path, k)}, {k.lo}..{k.hi}): {k.what}")
        return 1
    engine = load_engine(args.strategy, args.days, args.cache)
    data = Path(os.environ.get("DATA_DIR", ROOT / "data"))
    _, v, text = run_experiment(args.strategy, engine, Runner(engine, args.workers), cfg, changes,
                                args.idea or "Tested by hand", "", "manual", data, datetime.now(timezone.utc))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
