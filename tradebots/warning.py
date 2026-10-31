"""Early warning: a "risk radar" of seven warning lights, from free data, and an honest test of whether it would
have seen past selloffs coming.

The lights (each one is either on or off at a day's close). Settings fixed before any test ran, from the
usual textbook levels, not tuned on these years:

  fear       The fear index (VIX: how big a swing traders expect in the S&P 500 over the next month) is above 25.
             It sits around 12-18 in calm markets.
  fear_flip  The fear index for the next month is above the one for the next 3 months (VIX above VIX3M).
             Normally people fear the far future more; when the near term is scarier, they're scared *now*.
  credit     Junk bonds (HYG: loans to shaky companies) fell more than 2% against safe Treasury bonds (IEF)
             over 20 trading days. Lenders getting nervous often shows up there before it hits stocks.
  oil        Oil (WTI) rose more than 20% in 20 trading days. Oil shocks raise prices everywhere and push
             interest rates up.
  rates      The 2-year Treasury yield rose more than 0.5 points over 3 months (63 trading days). That's the
             market betting on rate hikes, which hurt fast-growing tech stocks most.
  breadth    The average S&P 500 stock (RSP, equal weight) fell more than 2% against the big-company index (SPY)
             over 20 trading days: fewer stocks are holding the market up.
  crack      The Nasdaq 100 (QQQ) closed below its 50-day average: the trend is cracking, well before the
             200-day line the trend bots use.

The score is how many are on: 0-1 CALM, 2-3 CAUTION, 4+ DANGER.

  python -m tradebots.warning test --out report.md     # the history test (needs Alpaca keys; FRED is free)
  python -m tradebots warning                          # the live check, after each trading run
"""
from __future__ import annotations

import copy
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import backtest as bt
from . import hunt

log = logging.getLogger(__name__)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED = {"vix": "VIXCLS", "vix3m": "VXVCLS", "oil": "DCOILWTICO", "y2": "DGS2"}   # free, no key needed
MARKET = ["QQQ", "SPY", "RSP", "HYG", "IEF"]
FUNDS = ["TQQQ", "QLD"]

# The thresholds, fixed before testing (see the module notes).
SET = {"fear_vix": 25.0, "credit_days": 20, "credit_drop": 0.02, "oil_days": 20, "oil_rise": 0.20,
       "rates_days": 63, "rates_rise": 0.5, "breadth_days": 20, "breadth_drop": 0.02, "crack_days": 50}
CAUTION, DANGER = 2, 4

LIGHTS = {
    "fear": ("Fear index high", "The VIX fear index is above 25 (calm is 12-18)."),
    "fear_flip": ("Fear is about now", "Traders fear the next month more than the next three (VIX above VIX3M)."),
    "credit": ("Lenders nervous", "Junk bonds fell 2%+ against safe bonds in 20 trading days."),
    "oil": ("Oil shock", "Oil rose 20%+ in 20 trading days."),
    "rates": ("Rate-hike bets", "The 2-year Treasury yield rose 0.5+ points in 3 months."),
    "breadth": ("Few stocks holding up", "The average stock fell 2%+ against the big-company index in 20 trading days."),
    "crack": ("Nasdaq trend cracking", "The Nasdaq 100 (QQQ) closed below its 50-day average."),
}

# The ways the radar could step in on the trend accounts, fixed before testing. Each has a stricter and a looser
# neighbour, to check that a gain isn't just a lucky number.
OVERLAYS = {
    "danger_cash": {"title": "Sell to cash on DANGER (4+ lights)", "kind": "score", "danger": 4, "caution": None,
                    "nudges": [{"danger": 3}, {"danger": 5}]},
    "caution_half": {"title": "Half on CAUTION (2-3 lights), cash on DANGER", "kind": "score", "danger": 4, "caution": 2,
                     "nudges": [{"danger": 3, "caution": 1}, {"danger": 5, "caution": 3}]},
    "vix_cash": {"title": "Sell to cash while the fear index is above 30", "kind": "vix", "level": 30,
                 "nudges": [{"level": 25}, {"level": 35}]},
    "flip_cash": {"title": "Sell to cash while near-term fear is above 3-month fear", "kind": "flip", "ratio": 1.0,
                  "nudges": [{"ratio": 0.95}, {"ratio": 1.05}]},
}
ACCOUNTS = {"aggressive": ("QQQ", "TQQQ"), "medium": ("QQQ", "QLD")}


# ---- the data -----------------------------------------------------------------------------------------------

def fetch_fred(start: datetime, session: requests.Session | None = None) -> pd.DataFrame:
    """Daily values of the FRED series (fear index, 3-month fear index, oil, 2-year yield), one column each,
    indexed by day at midnight UTC like the Alpaca bars. Missing days are NaN."""
    http = session or requests
    cols = {}
    for name, sid in FRED.items():
        r = http.get(FRED_URL, params={"id": sid, "cosd": start.strftime("%Y-%m-%d")}, timeout=60,
                     headers={"User-Agent": "trading-bots risk radar"})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        idx = pd.to_datetime(df.iloc[:, 0]).dt.tz_localize("UTC")
        cols[name] = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(), index=idx)
        log.warning("  FRED %s: %d days, last %s", sid, cols[name].notna().sum(), cols[name].dropna().index[-1].date())
    return pd.DataFrame(cols)


def align(macro: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """FRED values on the stock market's days. A missing value (a holiday on one side) carries the last one
    forward for up to 5 days."""
    return macro.reindex(macro.index.union(index)).ffill(limit=5).reindex(index)


# ---- the lights ---------------------------------------------------------------------------------------------

def lights(close: pd.DataFrame, macro: pd.DataFrame, s: dict = SET) -> pd.DataFrame:
    """Which lights are on at each day's close (True/False), plus the score. Uses only that close and earlier
    ones. `close` needs QQQ, SPY, RSP, HYG and IEF; `macro` is `align`ed FRED data on the same days."""
    vix, vix3m = macro["vix"], macro["vix3m"]
    credit = close["HYG"] / close["IEF"]
    breadth = close["RSP"] / close["SPY"]
    q = close["QQQ"]
    out = pd.DataFrame({
        "fear": vix > s["fear_vix"],
        "fear_flip": vix > vix3m,
        "credit": credit / credit.shift(s["credit_days"]) - 1 < -s["credit_drop"],
        "oil": macro["oil"] / macro["oil"].shift(s["oil_days"]) - 1 > s["oil_rise"],
        "rates": macro["y2"] - macro["y2"].shift(s["rates_days"]) > s["rates_rise"],
        "breadth": breadth / breadth.shift(s["breadth_days"]) - 1 < -s["breadth_drop"],
        "crack": q < q.rolling(s["crack_days"]).mean(),
    }, index=close.index).fillna(False).astype(bool)
    out["score"] = out[list(LIGHTS)].sum(axis=1)
    return out


def level(score: int) -> str:
    return "DANGER" if score >= DANGER else "CAUTION" if score >= CAUTION else "CALM"


def readings(close: pd.DataFrame, macro: pd.DataFrame, s: dict = SET) -> dict:
    """The numbers behind each light at the last close, in plain words."""
    vix, vix3m = macro["vix"].dropna(), macro["vix3m"].dropna()
    credit = (close["HYG"] / close["IEF"]).dropna()
    breadth = (close["RSP"] / close["SPY"]).dropna()
    oil, y2, q = macro["oil"].dropna(), macro["y2"].dropna(), close["QQQ"].dropna()

    def chg(x, n):
        return (x.iloc[-1] / x.iloc[-1 - n] - 1) * 100 if len(x) > n else float("nan")
    return {
        "fear": f"VIX {vix.iloc[-1]:.1f}" if len(vix) else "no data",
        "fear_flip": f"VIX {vix.iloc[-1]:.1f} vs VIX3M {vix3m.iloc[-1]:.1f}" if len(vix) and len(vix3m) else "no data",
        "credit": f"junk vs safe bonds {chg(credit, s['credit_days']):+.1f}% in {s['credit_days']} days",
        "oil": f"oil ${oil.iloc[-1]:.0f}, {chg(oil, s['oil_days']):+.1f}% in {s['oil_days']} days" if len(oil) else "no data",
        "rates": (f"2-year yield {y2.iloc[-1]:.2f}%, {y2.iloc[-1] - y2.iloc[-1 - s['rates_days']]:+.2f} pts in 3 months"
                  if len(y2) > s["rates_days"] else "no data"),
        "breadth": f"average stock vs big caps {chg(breadth, s['breadth_days']):+.1f}% in {s['breadth_days']} days",
        "crack": f"QQQ {(q.iloc[-1] / q.tail(s['crack_days']).mean() - 1) * 100:+.1f}% vs its 50-day average",
    }


# ---- stepping in on the trend accounts (test only) ----------------------------------------------------------

def scale(lit: pd.DataFrame, macro: pd.DataFrame, ov: dict) -> pd.Series:
    """How much of the trend rule's position to keep (0, 0.5 or 1) after each close."""
    one = pd.Series(1.0, index=lit.index)
    if ov["kind"] == "score":
        sc = lit["score"]
        if ov.get("caution") is not None:
            one[sc >= ov["caution"]] = 0.5
        one[sc >= ov["danger"]] = 0.0
    elif ov["kind"] == "vix":
        one[(macro["vix"] > ov["level"]).to_numpy()] = 0.0
    elif ov["kind"] == "flip":
        one[(macro["vix"] > macro["vix3m"] * ov["ratio"]).to_numpy()] = 0.0
    else:
        raise ValueError(ov["kind"])
    return one


class WarnEngine(hunt.HuntEngine):
    """The trend rule's replay, with the radar allowed to shrink the position (cfg["hunt"]["overlay"])."""

    def __init__(self, bars, lit, macro, start, end, bench="QQQ"):
        super().__init__(bars, start, end, bench, min_trades=hunt.MIN_TRADES["lev_trend"])
        self.lit, self.macro = lit, macro

    def run(self, cfg, start, end, cost=1.0):
        h = cfg["hunt"]
        close = pd.DataFrame({s: self.bars[s]["close"] for s in self.bars})
        want = hunt.targets(close, h)
        if h.get("overlay"):
            want[h["hold"]] = want[h["hold"]] * scale(self.lit, self.macro, h["overlay"]).reindex(close.index).fillna(1.0)
        return hunt.simulate(cfg, self.bars, start, end, self.cash, cost, want=want)


def base_config(strategy: str) -> dict:
    sig, hold = ACCOUNTS[strategy]
    cfg = hunt.config_for("lev_trend", strategy)
    cfg["hunt"].update(signal=sig, hold=hold)
    return cfg


def with_overlay(cfg: dict, name: str, nudge: dict | None = None) -> dict:
    c = copy.deepcopy(cfg)
    ov = {k: v for k, v in OVERLAYS[name].items() if k not in ("title", "nudges")}
    ov.update(nudge or {})
    c["hunt"]["overlay"] = ov
    return c


def judge(eng: WarnEngine, base: dict, name: str) -> tuple[bool, list[dict], dict]:
    """The strategy lab's rules for a change (lab.judge), with the radar as the change."""
    from . import lab
    runner = lab.Runner(eng)
    new = with_overlay(base, name)
    nbs = [with_overlay(base, name, n) for n in OVERLAYS[name]["nudges"]]
    sp = lab.make_split(eng.start, eng.end)
    S, U, A = (sp.start, sp.study_end), (sp.study_end, sp.end), (sp.start, sp.end)
    old_s, new_s, old_u, new_u, old_x, new_x, old_a, new_a, *nb = runner.run_many(
        [(base, *S, 1.0), (new, *S, 1.0), (base, *U, 1.0), (new, *U, 1.0), (base, *U, lab.COST_STRESS),
         (new, *U, lab.COST_STRESS), (base, *A, 1.0), (new, *A, 1.0)] + [(n, *U, 1.0) for n in nbs])
    pct = lab.pct
    so, sn, uo, un, xo, xn = pct(old_s), pct(new_s), pct(old_u), pct(new_u), pct(old_x), pct(new_x)
    months = [(pct(old_u, a, b), pct(new_u, a, b)) for a, b in sp.windows]
    not_worse = sum(n >= o - lab.MONTH_TOLERANCE for o, n in months)
    dd_old, dd_new = (bt.stats(r, eng.cash)["max_drawdown_pct"] for r in (old_a, new_a))
    nbp = [pct(r) for r in nb]
    checks = [
        {"name": "Better on the unseen months", "passed": un - uo >= lab.MIN_EDGE_PTS,
         "detail": f"{un:+.1f}% with the radar vs {uo:+.1f}% without"},
        {"name": "Steady slice to slice", "passed": not_worse >= lab.WINDOWS - 1,
         "detail": f"not worse in {not_worse} of {len(months)} slices"},
        {"name": "Still better with double costs", "passed": xn > xo, "detail": f"{xn:+.1f}% vs {xo:+.1f}%"},
        {"name": "Not a lucky number", "passed": all(p > uo for p in nbp),
         "detail": "stricter / looser: " + ", ".join(f"{p:+.1f}%" for p in nbp) + f" vs {uo:+.1f}% without"},
        {"name": "Also better on the study months", "passed": sn >= so, "detail": f"{sn:+.1f}% vs {so:+.1f}%"},
        {"name": "No deeper worst drop", "passed": dd_new >= dd_old - lab.MAX_EXTRA_DRAWDOWN,
         "detail": f"{dd_new:.1f}% vs {dd_old:.1f}% (whole period)"},
    ]
    nums = {"whole_old": pct(old_a), "whole_new": pct(new_a), "end_old": old_a.equity[-1][1],
            "end_new": new_a.equity[-1][1], "unseen_old": uo, "unseen_new": un, "dd_old": dd_old, "dd_new": dd_new,
            "trades_old": len(old_a.trades), "trades_new": len(new_a.trades)}
    return all(c["passed"] for c in checks), checks, nums


# ---- did the lights come on before the big drops? ------------------------------------------------------------

def forward_drop(q: pd.Series, days: int = 20) -> pd.Series:
    """The deepest close over the next `days` trading days, vs today's close (negative = a fall)."""
    fut = pd.concat([q.shift(-k) for k in range(1, days + 1)], axis=1).min(axis=1)
    return fut / q - 1


def episodes(q: pd.Series, depth: float = 0.10) -> list[dict]:
    """Every time QQQ fell `depth` or more from its high: the high, the day it crossed the line, the bottom."""
    out, peak_t, peak, inside, bottom_t = [], q.index[0], q.iloc[0], False, None
    for t, v in q.items():
        if v > peak:
            if inside:
                out[-1]["recovered"] = t
            peak_t, peak, inside = t, v, False
        elif not inside and v <= peak * (1 - depth):
            inside = True
            out.append({"peak": peak_t, "cross": t, "bottom": t, "depth": v / peak - 1, "recovered": None})
        if inside and v / peak - 1 <= out[-1]["depth"]:
            out[-1]["bottom"], out[-1]["depth"] = t, v / peak - 1
    return out


def event_study(q: pd.Series, lit: pd.DataFrame, start: datetime) -> tuple[dict, str]:
    """How often the lights were on before trouble, and how often they were on for nothing."""
    q = q.dropna()
    lit = lit.reindex(q.index)
    sc = lit["score"]
    days = q.index >= pd.Timestamp(start)
    fd = forward_drop(q)
    ret = q.pct_change()
    has_future = fd.notna() & days & (np.arange(len(q)) < len(q) - 20)
    trouble = fd <= -0.05
    base_rate = trouble[has_future].mean()
    rows = []
    for name, mask in [("CALM (0-1)", sc < CAUTION), ("CAUTION (2-3)", (sc >= CAUTION) & (sc < DANGER)),
                       ("DANGER (4+)", sc >= DANGER)]:
        m = mask & has_future
        rows.append((name, int(m.sum()), m.sum() / has_future.sum(), trouble[m].mean() if m.any() else float("nan")))
    per_light = []
    for k, (title, _) in LIGHTS.items():
        m = lit[k] & has_future
        per_light.append((title, m.sum() / has_future.sum(), trouble[m].mean() if m.any() else float("nan")))
    big = ret[(ret <= -0.03) & days]
    before = sc.shift(1).reindex(big.index)
    eps = [e for e in episodes(q[q.index >= pd.Timestamp(start) - pd.Timedelta(days=400)]) if e["cross"] >= pd.Timestamp(start)]
    sma200 = q.rolling(200).mean()
    ep_rows = []
    for e in eps:
        pos = q.index.get_loc(e["cross"])
        window = sc.iloc[max(0, pos - 10):pos]
        first_danger = next((t for t, v in sc.iloc[q.index.get_loc(e["peak"]):pos + 1].items() if v >= DANGER), None)
        under = q[(q.index >= e["peak"]) & (q < sma200)]
        exit_200 = under.index[0] if len(under) else None
        ep_rows.append({**e, "max_score_10d": int(window.max()) if len(window) else 0,
                        "first_danger": first_danger, "exit_200": exit_200,
                        "q_at_danger": (q[first_danger] / q[e["peak"]] - 1) if first_danger is not None else None,
                        "q_at_200": (q[exit_200] / q[e["peak"]] - 1) if exit_200 is not None else None})
    stats = {"base_rate": base_rate, "levels": rows, "lights": per_light, "big_days": len(big),
             "big_caution": float((before >= CAUTION).mean()) if len(big) else 0.0,
             "big_danger": float((before >= DANGER).mean()) if len(big) else 0.0, "episodes": ep_rows}

    def p(x):
        return "n/a" if x != x else f"{x * 100:.0f}%"
    o = ["## Did the lights come on before the drops?", "",
         f"\"Trouble\" below means QQQ fell 5% or more at some close in the next 20 trading days (about a month). "
         f"On an ordinary day that happened **{p(base_rate)}** of the time.", "",
         "| Radar said | Days | Share of days | Trouble followed |", "|---|---|---|---|"]
    o += [f"| {n} | {d} | {p(s)} | **{p(t)}** |" for n, d, s, t in rows]
    o += ["", "Each light on its own:", "", "| Light | On (share of days) | Trouble followed |", "|---|---|---|"]
    o += [f"| {n} | {p(s)} | {p(t)} |" for n, s, t in per_light]
    o += ["", f"**Sudden drops:** QQQ fell 3% or more in one day {len(big)} times. The night before, the radar said "
          f"CAUTION or worse {p(stats['big_caution'])} of the time and DANGER {p(stats['big_danger'])} of the time.", "",
          "**Every fall of 10%+ in QQQ** (from its high to the bottom), and when each warning came, measured as how far "
          "QQQ had already fallen from its high at that point:", "",
          "| High | Fell 10% on | Bottom | Most lights in the 10 days before the -10% day | First DANGER | 200-day line broke (the trend bots sell) |",
          "|---|---|---|---|---|---|"]
    for e in ep_rows:
        fdg = f"{e['first_danger']:%Y-%m-%d} ({e['q_at_danger'] * 100:+.1f}%)" if e["first_danger"] is not None else "never before -10%"
        x2 = f"{e['exit_200']:%Y-%m-%d} ({e['q_at_200'] * 100:+.1f}%)" if e["exit_200"] is not None else "never"
        o.append(f"| {e['peak']:%Y-%m-%d} | {e['cross']:%Y-%m-%d} | {e['bottom']:%Y-%m-%d} ({e['depth'] * 100:.0f}%) | "
                 f"{e['max_score_10d']} | {fdg} | {x2} |")
    return stats, "\n".join(o) + "\n"


def recent_table(lit: pd.DataFrame, n: int = 15) -> str:
    o = ["| Day | " + " | ".join(t for t, _ in LIGHTS.values()) + " | Score |", "|---" * (len(LIGHTS) + 2) + "|"]
    for t, r in lit.tail(n).iterrows():
        o.append(f"| {t:%a %b %d} | " + " | ".join("🔴" if r[k] else "·" for k in LIGHTS) + f" | {int(r['score'])} {level(r['score'])} |")
    return "\n".join(o)


# ---- the full test ------------------------------------------------------------------------------------------

def load(years: int, end: datetime) -> tuple[dict, pd.DataFrame, datetime]:
    import os
    start = end.replace(year=end.year - years)
    key = os.environ.get("ALPACA_MEDIUM_KEY_ID") or os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", "")
    sec = os.environ.get("ALPACA_MEDIUM_SECRET_KEY") or os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", "")
    stocks = hunt.fetch(start, end, key, sec, symbols=MARKET + FUNDS, coins=False)["stocks"]
    macro = fetch_fred(start - timedelta(days=430))
    return stocks, macro, start


def frame(stocks: dict, syms: list[str]) -> dict[str, pd.DataFrame]:
    idx = stocks[syms[0]].index
    for s in syms[1:]:
        idx = idx.union(stocks[s].index)
    return {s: stocks[s].reindex(idx) for s in syms}


def test(stocks: dict, macro_raw: pd.DataFrame, start: datetime, end: datetime) -> str:
    allb = frame(stocks, MARKET + FUNDS)
    close = pd.DataFrame({s: allb[s]["close"] for s in allb})
    macro = align(macro_raw, close.index)
    lit = lights(close, macro)
    stats, ev_text = event_study(close["QQQ"], lit, start)

    o = ["# Early warning radar: would it have seen the selloffs coming?", "",
         f"Prices: Alpaca daily (adjusted), {start:%b %Y} to {end:%b %d %Y}. Fear index, oil and 2-year yield: FRED "
         "(free). Seven warning lights, settings fixed before testing (see tradebots/warning.py). Score = lights on: "
         "0-1 CALM, 2-3 CAUTION, 4+ DANGER.", "", "## The last 15 trading days", "", recent_table(lit), "", ev_text]
    o += ["## Would stepping in have helped the trend accounts?", "",
          "Each idea below changes only one thing: on top of the 200-day trend rule the accounts run now, the radar may "
          "sell (or halve) the fund early. Judged by the strategy lab's rules for a change: better on the unseen months "
          "by 1+ point, steady in 4 of 5 slices, still better with costs doubled, a stricter and a looser setting also "
          "better, not worse on the study months, and no deeper worst drop. $100 start, 0.1% cost each way.", "",
          "| Account | Idea | Whole period | Without radar | Worst drop | Without radar | Unseen months | Without | Trades | Lab check |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    details = []
    for acct, (sig, hold) in ACCOUNTS.items():
        bars = frame(stocks, sorted({sig, hold}))
        eng = WarnEngine(bars, lit, macro, start, end)
        base = base_config(acct)
        for name, ov in OVERLAYS.items():
            kept, checks, n = judge(eng, base, name)
            passed = sum(c["passed"] for c in checks)
            o.append(f"| {acct.title()} ({hold}) | {ov['title']} | {n['whole_new']:+.0f}% ({bt.money(n['end_new'])}) | "
                     f"{n['whole_old']:+.0f}% ({bt.money(n['end_old'])}) | {n['dd_new']:.0f}% | {n['dd_old']:.0f}% | "
                     f"{n['unseen_new']:+.1f}% | {n['unseen_old']:+.1f}% | {n['trades_new']} vs {n['trades_old']} | "
                     f"{'✅ pass' if kept else f'❌ {passed}/{len(checks)}'} |")
            details.append(f"**{acct.title()}: {ov['title']}**\n\n" +
                           "\n".join(f"- {'✅' if c['passed'] else '❌'} {c['name']}: {c['detail']}" for c in checks))
            log.warning("%s %s: whole %+.0f%% vs %+.0f%%, drop %.0f%% vs %.0f%%, %s", acct, name, n["whole_new"],
                        n["whole_old"], n["dd_new"], n["dd_old"], "PASS" if kept else f"{passed}/6")
    o += ["", "\n\n".join(details), "",
          "_Past results don't guarantee future ones. The radar is a test of history, and no set of signals predicts "
          "selloffs reliably._"]
    return "\n".join(o) + "\n"


# ---- the live check -----------------------------------------------------------------------------------------

def run_live(data_dir: Path, now: datetime | None = None, broker=None, session=None, every_hours: float = 3.0) -> dict | None:
    """Read today's lights and save them to data/warning/. Writes data/warning/alert.md when the level rises
    (CALM to CAUTION, or anything to DANGER) so the workflow can open a GitHub issue (GitHub emails Quincy).
    Skips if it already looked in the last `every_hours` hours. Never trades."""
    import os
    from .alpaca import AlpacaPaper
    now = now or datetime.now(timezone.utc)
    d = data_dir / "warning"
    d.mkdir(parents=True, exist_ok=True)
    latest_p, alert_p = d / "latest.json", d / "alert.md"
    alert_p.unlink(missing_ok=True)
    prev = json.loads(latest_p.read_text()) if latest_p.exists() else {}
    if prev.get("checked") and now - datetime.fromisoformat(prev["checked"]) < timedelta(hours=every_hours):
        return None
    broker = broker or AlpacaPaper(os.environ.get("ALPACA_AGGRESSIVE_KEY_ID", ""), os.environ.get("ALPACA_AGGRESSIVE_SECRET_KEY", ""))
    closes = {s: hunt.daily_closes(broker, s, 260, now) for s in MARKET}
    close = pd.DataFrame(closes).dropna()
    close.index = pd.to_datetime(close.index).tz_localize("UTC")
    macro = align(fetch_fred(now - timedelta(days=200), session), close.index)
    lit = lights(close, macro)
    last = lit.iloc[-1]
    score = int(last["score"])
    read = readings(close, macro)
    out = {"checked": now.isoformat(timespec="seconds"), "close_day": f"{close.index[-1]:%Y-%m-%d}", "score": score,
           "level": level(score), "lights": {k: {"title": LIGHTS[k][0], "on": bool(last[k]), "why": LIGHTS[k][1],
                                                 "reading": read[k]} for k in LIGHTS},
           "fear_index": float(macro["vix"].dropna().iloc[-1]) if macro["vix"].notna().any() else None}
    latest_p.write_text(json.dumps(out, indent=2))
    hist = d / "history.csv"
    row = f"{out['close_day']},{score},{out['level']}," + "".join("1" if last[k] else "0" for k in LIGHTS) + "\n"
    lines = hist.read_text().splitlines(keepends=True) if hist.exists() else ["day,score,level,lights(" + "/".join(LIGHTS) + ")\n"]
    lines = [ln for ln in lines if not ln.startswith(out["close_day"] + ",")] + [row]
    hist.write_text("".join(lines))
    order = {"CALM": 0, "CAUTION": 1, "DANGER": 2}
    if order[out["level"]] > order.get(prev.get("level", "CALM"), 0):
        alert_p.write_text(alert_text(out, prev.get("level", "CALM")))
    return out


def alert_text(out: dict, was: str) -> str:
    on = [v for v in out["lights"].values() if v["on"]]
    o = [f"The early-warning radar went from **{was}** to **{out['level']}** at the {out['close_day']} close: "
         f"{out['score']} of {len(LIGHTS)} warning lights are on.", "", "Lights on:", ""]
    o += [f"- 🔴 **{v['title']}**: {v['why']} Now: {v['reading']}." for v in on]
    o += ["", "Lights off: " + ", ".join(v["title"] for v in out["lights"].values() if not v["on"]) + ".", "",
          "What this means: in past years, a month with the radar at this level was more likely than usual to include "
          "a 5%+ drop in the Nasdaq, but most warnings passed without one. **Nothing is sold automatically**; the trend "
          "accounts still follow their 200-day rule. See the warning test report in the repo for the numbers.", "",
          "_This is information, not advice._"]
    return "\n".join(o) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("command", choices=["test"])
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    now = datetime.now(timezone.utc)
    end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    stocks, macro, start = load(a.years, end)
    text = test(stocks, macro, start, end)
    print(text)
    if a.out:
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
