"""Command line entry point.

  python -m tradebots run --strategy aggressive [--dry-run]
  python -m tradebots deposit --strategy medium --amount 50
  python -m tradebots close-all --strategy aggressive
  python -m tradebots resume --strategy medium
  python -m tradebots weekly
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import pipeline, report, weekly
from .ai import AI
from .alpaca import AlpacaPaper
from .store import Store
from . import runlog

ROOT = Path(__file__).resolve().parent.parent


def load_config(strategy: str) -> dict:
    return yaml.safe_load((ROOT / "config" / f"{strategy}.yaml").read_text())


def truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def broker_for(cfg: dict) -> AlpacaPaper:
    key, secret = os.environ.get(cfg["alpaca_key_secret"], ""), os.environ.get(cfg["alpaca_secret_secret"], "")
    missing = [n for n, v in ((cfg["alpaca_key_secret"], key), (cfg["alpaca_secret_secret"], secret)) if not v]
    if missing:
        write_summary(f"**{cfg['name']}: GitHub can't see the secret(s) {', '.join(missing)}.** Add them under "
                      "Settings > Secrets and variables > Actions > Secrets tab > New repository secret, "
                      "spelled exactly like this.")
        sys.exit(1)
    return AlpacaPaper(key, secret)


def write_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")
    print(text)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="tradebots")
    ap.add_argument("command", choices=["run", "deposit", "close-all", "resume", "weekly"])
    ap.add_argument("--strategy", choices=["aggressive", "medium"])
    ap.add_argument("--amount", type=float, help="deposit amount; negative for a withdrawal")
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true", help="do everything except send orders")
    args = ap.parse_args(argv)

    if args.command == "weekly":
        return weekly_report()
    if not args.strategy:
        ap.error("--strategy is required")

    cfg = load_config(args.strategy)
    store = Store(os.environ.get("DATA_DIR", ROOT / "data"), cfg["name"])
    now = datetime.now(timezone.utc)

    if args.command == "deposit":
        if not args.amount:
            ap.error("--amount is required")
        store.add_deposit(args.amount, args.note or ("deposit" if args.amount > 0 else "withdrawal"), now)
        write_summary(f"Logged {'deposit' if args.amount > 0 else 'withdrawal'} of ${abs(args.amount):,.2f} "
                      f"for {cfg['name']}. Money put in is now ${store.net_deposits():,.2f}.")
        return 0

    if args.command == "resume":
        store.state["halted_reason"] = None
        store.save()
        write_summary(f"{cfg['name']}: halt cleared. Trading resumes on the next run (if the kill switch is off).")
        return 0

    broker = broker_for(cfg)
    if args.command == "close-all":
        broker.close_all()
        store.state["plans"] = {}
        store.save()
        write_summary(f"{cfg['name']}: sent orders to close every position.")
        return 0

    ai = AI(cfg["ai"]["model"], cfg["ai"].get("effort", "low"))
    dry = args.dry_run or truthy(os.environ.get("DRY_RUN"))
    res = pipeline.run(cfg, broker, ai, store, kill_switch=truthy(os.environ.get("TRADING_HALTED")), dry_run=dry, now=now)
    res.notes.insert(0, ai.check())
    text = report.render(res, store, dry)
    (store.dir / "summary.md").write_text(text)
    runlog.save(res, store, dry)
    write_summary(text)
    return 0


def weekly_report() -> int:
    data, now = Path(os.environ.get("DATA_DIR", ROOT / "data")), datetime.now(timezone.utc)
    stores = {name: Store(data, name) for name in ("aggressive", "medium")}
    first = min((datetime.fromisoformat(r["time"]) for s in stores.values() for r in s.rows("deposits.csv")),
                default=now - timedelta(days=7))
    btc = weekly.btc_prices(broker_for(load_config("aggressive")), min(first, now - timedelta(days=7)))
    text = weekly.render({n: weekly.strategy_stats(s, now, btc) for n, s in stores.items()}, now)
    out = data / "weekly"
    out.mkdir(exist_ok=True)
    (out / f"{now:%Y-%m-%d}.md").write_text(text)
    (out / "latest.md").write_text(text)
    write_summary(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
