"""Builds the "bot world" web page and the daily recaps from the saved bot data.

  python -m tradebots.world            # reads ./data (or $DATA_DIR), writes data/world/index.html

The page is one self-contained HTML file with the data baked in, so it works on GitHub Pages
or opened straight from a download. Recaps are also saved as data/recaps/<day>.md.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import recap, runlog
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).with_name("world_template.html")
PIXELWORLD = Path(__file__).with_name("pixelworld.js")
STRATEGIES = ("aggressive", "medium", "copycat")
CREW = [  # pipeline order: Charts runs before News and Sentiment so Claude isn't paid for dead-end setups
    ("scout", "Scout", "Scans every coin for sudden jumps in trading activity with the price moving up."),
    ("charts", "Charts", "Draws the trade plan: where to buy, where the safety exit goes, and the profit goal."),
    ("news", "News", "Watches all the crypto news for trends that are starting, and checks if there's a real reason for a move."),
    ("sentiment", "Sentiment", "Listens to Reddit chatter and the crypto mood score to spot real interest or empty hype."),
    ("risk", "Risk", "The safety officer. Plain rules, no AI. Approves, shrinks or blocks every trade."),
    ("decision", "Decision", "Reads everyone's notes and makes the final call: BUY, WAIT or SKIP."),
]

# Copycat uses the same six rooms, but each bot does a copy-trading job.
COPYCAT_JOBS = {
    "scout": "Reads the newest SEC insider filings and keeps a watchlist of stocks that company bosses just bought.",
    "charts": "Sets the safety exit 10% below our buy price and the profit goal 20% above it.",
    "news": "Reports who bought: their job at the company, how much, and at what price.",
    "sentiment": "Checks the price now against what the insiders paid, so we don't copy too late.",
    "risk": "The safety officer. Plain rules, no AI. Approves, shrinks or blocks every trade.",
    "decision": "Plain rule: if a pick passes every check, copy it. No AI on this account.",
}


def coin(symbol: str) -> str:
    return symbol.split("/")[0].replace("USD", "") if "/" in symbol else symbol.removesuffix("USD")


def price(x: float | None) -> str:
    if x is None:
        return "?"
    return f"${x:,.2f}" if x >= 1 else f"${x:.4g}"


def stations(run: dict | None, cfg: dict) -> dict:
    """What each bot says about the latest run, in plain, friendly words."""
    s = {k: {"status": "idle", "say": "", "detail": []} for k, *_ in CREW}
    if not run:
        for k in s:
            s[k]["say"] = "Waiting for the first run."
        return s
    cands = run["candidates"]
    every = cfg["scout"]["scan_every_minutes"]

    # Scout
    sc = s["scout"]
    if run["scanned"]:
        sc["status"] = "found" if cands else "working"
        scan = run["scan"]
        if cands:
            names = ", ".join(coin(c["symbol"]) for c in cands)
            sc["say"] = f"Scanned {len(scan)} coins. Unusual activity in {names}. Sent for review."
        else:
            top = max(scan.items(), key=lambda kv: kv[1]["volume_ratio"], default=None)
            sc["say"] = f"Scanned {len(scan)} coins. No unusual activity."
            if top:
                sc["say"] += f" Most active: {coin(top[0])} at {top[1]['volume_ratio']:.1f}x normal volume."
        for sym, m in sorted(scan.items(), key=lambda kv: -kv[1]["volume_ratio"]):
            sc["detail"].append(f"{coin(sym)}: {price(m['price'])}, volume {m['volume_ratio']:.1f}x normal, "
                                f"price {m['move_pct']:+.1f}%, RSI {m['rsi']:.0f}"
                                + (" ✔ passed" if m["passed"] else ""))
    else:
        sc["status"] = "resting"
        nxt = ""
        if run.get("last_scan"):
            due = datetime.fromisoformat(run["last_scan"]) + timedelta(minutes=every)
            nxt = f" Next scan around {due:%H:%M} UTC."
        sc["say"] = f"Standing by. This strategy scans for new trades every {every} minutes.{nxt}"
        if run["gate"] and run["gate"] != "ok":
            sc["say"] = "Not scanning. Risk has paused new trades."

    for k in ("charts", "news", "sentiment", "risk", "decision"):
        if not cands:
            s[k]["say"] = "Standing by. Nothing passed Scout this run."

    if cands:
        ch, nw, se, rk, de = (s[k] for k in ("charts", "news", "sentiment", "risk", "decision"))
        for k in ("charts", "news", "sentiment", "risk", "decision"):
            s[k]["status"] = "working"
        c0 = cands[0]
        ch["say"] = (f"{coin(c0['symbol'])}: trend {c0['trend']}. Entry {price(c0['entry'])}, safety exit "
                     f"{price(c0['stop'])}, profit goal {price(c0['target'])}.")
        nw["say"] = f"{coin(c0['symbol'])}: {c0['news'] or 'No recent news.'}"
        se["say"] = f"{coin(c0['symbol'])}: {c0['sentiment'] or 'Little discussion.'}"
        buys = [c for c in cands if c["decision"] == "BUY"]
        best = max(cands, key=lambda c: c["confidence"])
        if buys:
            b = buys[0]
            de["status"] = "buy"
            de["say"] = f"BUY {coin(b['symbol'])}, {int(b['confidence'] * 100)}% confidence. {b['decision_note']}"
        else:
            de["say"] = (f"{best['decision']} {coin(best['symbol'])}, {int(best['confidence'] * 100)}% confidence. "
                         f"{best['decision_note']}")
        blocked = [c for c in cands if c["risk"] == "REJECT"]
        rk["say"] = (f"Blocked {', '.join(coin(c['symbol']) for c in blocked)}: {blocked[0]['risk_note']}" if blocked
                     else f"{coin(c0['symbol'])} approved, up to {price(c0['size_usd'])}.")
        if blocked:
            rk["status"] = "blocked"
        for c in cands:
            ch["detail"].append(f"{coin(c['symbol'])}: trend {c['trend']}, buy {price(c['entry'])}, safety exit "
                                f"{price(c['stop'])}, goal {price(c['target'])}, reward-to-risk {c['reward_risk']}")
            nw["detail"].append(f"{coin(c['symbol'])}: score {c['news_score']:+.2f}. {c['news']}")
            se["detail"].append(f"{coin(c['symbol'])}: score {c['sentiment_score']:+.2f}, hype {c['hype']:.1f}. "
                                f"{c['sentiment']}")
            rk["detail"].append(f"{coin(c['symbol'])}: {c['risk']} {price(c['size_usd'])}. {c['risk_note']}")
            de["detail"].append(f"{coin(c['symbol'])}: {c['decision']} ({int(c['confidence'] * 100)}%). "
                                f"{c['decision_note']}")

    # News also runs the radar on every scan, so it has something to say even when Scout found nothing
    rad = run.get("radar") or {}
    if rad:
        nw = s["news"]
        top = rad["themes"][0] if rad["themes"] else None
        hot = max(rad["coins"].items(), key=lambda kv: kv[1]["score"], default=None)
        if not cands:
            nw["status"] = "working"
            if top:
                nw["say"] = f"Trend forming: {top['title']}. {top['note']}"
            elif hot and hot[1]["score"] >= 0.3:
                nw["say"] = f"{hot[0]} news is picking up: {hot[1]['note']}."
            else:
                nw["say"] = f"Read {rad['headlines']} headlines. Nothing building yet."
        nw["detail"] += [f"Trend: {t['title']}. {t['note']}" for t in rad["themes"]]
        nw["detail"] += [f"{c}: radar {x['score']:+.2f}. {x['note']}"
                         for c, x in sorted(rad["coins"].items(), key=lambda kv: -kv[1]["score"])
                         if x["recent"] or x["score"]]
        if rad.get("trending_elsewhere"):
            nw["detail"].append(f"Trending, not in our list: {', '.join(rad['trending_elsewhere'])}")

    # Risk always reports on the account, even on a quiet run
    rk = s["risk"]
    lim = cfg["risk"]
    today = (run["equity"] - run["day_start_equity"]) / run["day_start_equity"] * 100 if run["day_start_equity"] else 0
    if run["gate"] and run["gate"] != "ok":
        rk["status"], rk["say"] = "blocked", f"New buys paused. {run['gate']}"
    elif not cands:
        rk["status"] = "working"
        rk["say"] = (f"All limits clear. Today {today:+.1f}%; new buys stop at "
                     f"-{lim['max_daily_loss_pct']}%.")
    rk["detail"] += [f"Today so far: {today:+.2f}% (daily loss limit -{lim['max_daily_loss_pct']}%)",
                     f"Total loss limit: -{lim['max_total_loss_pct']}% of the money put in",
                     f"Max per trade: about {lim['risk_per_trade_pct']}% of the account at risk, "
                     f"never more than {lim['max_position_pct']}% in one coin"]

    if run["exits"] or run["buys"]:
        s["decision"]["detail"] += run["buys"] + run["exits"]
    return s


def copycat_stations(run: dict | None, cfg: dict) -> dict:
    """What each bot says on the Copycat account."""
    s = {k: {"status": "idle", "say": "", "detail": []} for k, *_ in CREW}
    if not run:
        for k in s:
            s[k]["say"] = "Waiting for the first run."
        return s
    f, cands, cc = run.get("filings") or {}, run["candidates"], cfg["copycat"]
    top = f.get("top") or []
    sc = s["scout"]
    sc["status"] = "found" if top else "working"
    sc["say"] = (f"Read {f.get('read', 0)} new insider filings. Watchlist: {f.get('watchlist', 0)} stocks."
                 + (f" Best: {top[0]['ticker']}, {top[0]['insiders']} insider(s) bought ${top[0]['usd']:,.0f}." if top
                    else " Nothing big enough to copy yet."))
    if f.get("error"):
        sc["status"], sc["say"] = "blocked", f["error"]
    sc["detail"] = [f"{t['ticker']} ({t['company']}), score {t['score']}" for t in top]
    nw = s["news"]
    nw["status"] = "working" if top else "idle"
    nw["say"] = f"{top[0]['ticker']}: {top[0]['note']}" if top else "No big insider buys this week so far."
    nw["detail"] = [f"{t['ticker']}: {t['note']}" for t in top]
    ch, se, rk, de = (s[k] for k in ("charts", "sentiment", "risk", "decision"))
    ch["say"] = (f"Safety exit {cc['stop_pct']}% below the buy price, profit goal {cc['target_pct']}% above. "
                 f"Holds up to {cfg['exits']['max_hold_hours'] // 24} days.")
    checked = [c for c in cands if c.get("entry")]
    if checked:
        ch["status"] = "working"
        ch["detail"] = [f"{c['symbol']}: buy {price(c['entry'])}, safety exit {price(c['stop'])}, "
                        f"goal {price(c['target'])}" for c in checked]
    priced = [c for c in cands if c.get("sentiment")]
    se["say"] = (f"{priced[0]['symbol']}: {priced[0]['sentiment']}" if priced
                 else "Checks prices when the stock market is open.")
    se["status"] = "working" if priced else "idle"
    se["detail"] = [f"{c['symbol']}: {c['sentiment']}" for c in priced]
    if cands:
        buys = [c for c in cands if c["decision"] == "BUY"]
        c0 = buys[0] if buys else cands[0]
        de["status"] = "buy" if buys else "working"
        de["say"] = f"{c0['decision']} {c0['symbol']}. {c0['decision_note']}"
        de["detail"] = [f"{c['symbol']}: {c['decision']}. {c['decision_note']}" for c in cands]
    else:
        de["say"] = "Standing by. Nothing on the watchlist is ready to copy."
    lim = cfg["risk"]
    today = (run["equity"] - run["day_start_equity"]) / run["day_start_equity"] * 100 if run["day_start_equity"] else 0
    blocked = [c for c in cands if c["risk"] == "REJECT"]
    if run["gate"] and run["gate"] != "ok":
        rk["status"], rk["say"] = "blocked", f"New buys paused. {run['gate']}"
    elif blocked:
        rk["status"], rk["say"] = "blocked", f"Blocked {blocked[0]['symbol']}: {blocked[0]['risk_note']}"
    else:
        rk["status"] = "working"
        rk["say"] = f"All limits clear. Today {today:+.1f}%; new buys stop at -{lim['max_daily_loss_pct']}%."
    rk["detail"] = [f"{c['symbol']}: {c['risk']} {price(c['size_usd'])}. {c['risk_note']}" for c in cands if c["risk"]]
    rk["detail"] += [f"Today so far: {today:+.2f}% (daily loss limit -{lim['max_daily_loss_pct']}%)",
                     f"Total loss limit: -{lim['max_total_loss_pct']}% of the money put in",
                     f"Never more than {lim['max_position_pct']}% of the account in one stock, "
                     f"at most {lim['max_open_positions']} stocks at once"]
    if run["exits"] or run["buys"]:
        de["detail"] += run["buys"] + run["exits"]
    return s


def captain(run: dict | None, name: str) -> str:
    if not run:
        return "Awaiting first run."
    bits = []
    if run["buys"]:
        bits.append(f"Bought {', '.join(coin(b.split()[1]) for b in run['buys'])}.")
    sold = [x for x in run["exits"] if x.startswith("SOLD")]
    if sold:
        bits.append(f"Sold {', '.join(coin(x.split()[1].rstrip(':')) for x in sold)}.")
    if not bits:
        bits.append("No trades this run.")
    n, what = len(run["positions"]), "stock" if name == "copycat" else "coin"
    bits.append(f"Holding {n} {what}{'s' if n != 1 else ''}." if n else "All cash.")
    pl = run["profit"]
    bits.append(f"Since start: {'+' if pl >= 0 else ''}{recap.money(pl)}.")
    return f"{name.title()} status. " + " ".join(bits)


def event(store: Store, run: dict | None) -> dict | None:
    """The effect the page plays for the latest run: a win, a loss, or a new buy."""
    if not run:
        return None
    closed = [t for t in recap.closed_trades(store, since=run["time"]) if t["pl"] is not None]
    if closed:
        pl = sum(t["pl"] for t in closed)
        return {"kind": "win" if pl >= 0 else "loss", "pl": pl, "coins": [t["symbol"] for t in closed]}
    if run["buys"]:
        return {"kind": "buy", "coins": [coin(b.split()[1]) for b in run["buys"]]}
    return None


def equity_series(store: Store, max_points: int = 400) -> list[list]:
    rows = store.rows("equity.csv")
    step = max(1, len(rows) // max_points)
    picked = rows[::step] + ([rows[-1]] if rows and (len(rows) - 1) % step else [])
    return [[r["time"], float(r["equity"]), float(r["net_deposits"])] for r in picked]


def levels(store: Store, days: list[str]) -> tuple[int, dict]:
    """How many runs this account has done, and each bot's level for its desk name plate.

    Every bot earns a point for each run it checks in on, and extra points for real work:
    Scout for each scan, the analysts for each coin or stock they review, Decision for each buy.
    """
    runs, xp = 0, {k: 0 for k, *_ in CREW}
    for d in days:
        for r in runlog.load_day(store, d):
            runs += 1
            seen = len(r.get("candidates") or [])
            xp["scout"] += 2 if r.get("scanned") or r.get("filings") else 1
            for k in ("charts", "news", "sentiment", "risk", "decision"):
                xp[k] += 1 + 3 * seen
            xp["decision"] += 5 * len(r.get("buys") or [])
    return runs, {k: 1 + v // 12 for k, v in xp.items()}


def strategy_data(store: Store, cfg: dict, days_back: int = 7) -> dict:
    days = runlog.days(store)
    run_count, lv = levels(store, days)
    latest = None
    for d in reversed(days):
        runs = runlog.load_day(store, d)
        if runs:
            latest = runs[-1]
            break
    copy = "copycat" in cfg
    return {
        "name": cfg["name"],
        "crew": [{"id": k, "name": n, "job": COPYCAT_JOBS[k]} for k, n, _ in CREW] if copy else None,
        "rules": (f"Rules for this account: copies company insiders who bought at least "
                  f"${cfg['copycat']['min_buy_usd']:,} of their own stock in the last "
                  f"{cfg['copycat']['max_signal_age_days']} days, skips it if the price already rose "
                  f"{cfg['copycat']['max_chase_pct']}%+, puts at most {cfg['risk']['max_position_pct']}% of the "
                  f"account in one stock, holds up to {cfg['exits']['max_hold_hours'] // 24} days. "
                  f"Stocks only trade on weekdays, 9:30am to 4pm New York time.") if copy else None,
        "limits": {k: cfg["risk"][k] for k in ("max_daily_loss_pct", "max_total_loss_pct", "risk_per_trade_pct")},
        "scan_every": cfg["scout"]["scan_every_minutes"],
        "min_confidence": cfg["decision"]["min_confidence"],
        "max_hold_hours": cfg["exits"]["max_hold_hours"],
        "performance": store.performance(),
        "latest": latest,
        "stations": copycat_stations(latest, cfg) if copy else stations(latest, cfg),
        "captain": captain(latest, cfg["name"]),
        "runs": run_count,
        "levels": lv,
        "event": event(store, latest),
        "equity": equity_series(store),
        "trades": store.rows("trades.csv")[-25:][::-1],
        "recaps": [recap.build(store, d) for d in reversed(days[-days_back:])],
    }


def build(data_dir: Path, out_dir: Path, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    stores = {n: Store(data_dir, n) for n in STRATEGIES}
    cfgs = {n: yaml.safe_load((ROOT / "config" / f"{n}.yaml").read_text()) for n in STRATEGIES}

    # Daily recap files: refresh today and yesterday (yesterday's last runs may have landed after midnight)
    rec_dir = data_dir / "recaps"
    rec_dir.mkdir(parents=True, exist_ok=True)
    for d in sorted({now.date().isoformat(), (now - timedelta(days=1)).date().isoformat()}):
        recs = [recap.build(s, d) for s in stores.values()]
        if any(r["runs"] for r in recs):
            md = recap.to_markdown(recs, d)
            (rec_dir / f"{d}.md").write_text(md)
            if d == now.date().isoformat():
                (rec_dir / "latest.md").write_text(md)

    payload = {
        "built": now.isoformat(timespec="seconds"),
        "crew": [{"id": k, "name": n, "job": j} for k, n, j in CREW],
        "glossary": recap.GLOSSARY,
        "strategies": {n: strategy_data(stores[n], cfgs[n]) for n in STRATEGIES},
    }
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", blob)
    # the pixel-art world is inlined so the page is one file
    html = html.replace("/*__PIXELWORLD__*/", PIXELWORLD.read_text().replace("</script", "<\\/script"), 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html)
    (out_dir / ".nojekyll").write_text("")
    return out_dir / "index.html"


def main() -> int:
    data = Path(os.environ.get("DATA_DIR", ROOT / "data"))
    out = Path(os.environ.get("SITE_DIR", data / "world"))
    path = build(data, out)
    print(f"Bot world page written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
