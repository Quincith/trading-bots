"""Saves what every bot saw and said in a run, for the bot world page and the daily recap.

One JSON line per run goes into data/<strategy>/runs/<YYYY-MM-DD>.jsonl (UTC day).
"""
from __future__ import annotations

import json
from pathlib import Path

from .pipeline import RunResult
from .store import Store


def record(res: RunResult, store: Store, dry_run: bool) -> dict:
    perf = store.performance()
    cands = []
    for c in res.candidates:
        d = c.summary()
        d.update(decision=c.decision, confidence=round(c.confidence, 2), decision_note=c.decision_note,
                 support=round(c.plan.support, 6) if c.plan else None,
                 resistance=round(c.plan.resistance, 6) if c.plan else None)
        cands.append(d)
    return {
        "time": res.started.isoformat(timespec="seconds"),
        "strategy": res.strategy,
        "dry_run": dry_run,
        "equity": round(perf["equity"] or res.equity, 2),
        "net_deposits": round(perf["net_deposits"], 2),
        "profit": round(perf["profit"], 2),
        "day_start_equity": round(res.day_start_equity, 2),
        "gate": res.gate,
        "scanned": res.scanned,
        "last_scan": res.last_scan,
        "scan": {s: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()} for s, m in res.scan.items()},
        "candidates": cands,
        "positions": [{k: p.get(k) for k in ("symbol", "qty", "market_value", "avg_entry_price", "current_price")}
                      for p in res.positions],
        "exits": res.exits,
        "buys": res.buys,
        "notes": res.notes,
        "ai_calls": res.ai_calls,
        "filings": res.filings,
    }


def _plain(o):
    """numpy numbers and bools -> plain Python, so json can write them."""
    return o.item() if hasattr(o, "item") else str(o)


def save(res: RunResult, store: Store, dry_run: bool) -> Path:
    rec = record(res, store, dry_run)
    folder = store.dir / "runs"
    folder.mkdir(exist_ok=True)
    path = folder / f"{res.started:%Y-%m-%d}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(rec, default=_plain) + "\n")
    return path


def load_day(store: Store, day: str) -> list[dict]:
    path = store.dir / "runs" / f"{day}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def days(store: Store) -> list[str]:
    """Days that have run logs, oldest first."""
    folder = store.dir / "runs"
    return sorted(p.stem for p in folder.glob("*.jsonl")) if folder.exists() else []
