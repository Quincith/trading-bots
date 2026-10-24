"""Everything the bots remember between runs, kept as small files in data/<strategy>/.

GitHub Actions saves this folder to the `bot-data` branch after every run, so it is
easy to browse on GitHub and nothing is lost when the runner shuts down.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

FILES = {
    "deposits.csv": ["time", "amount", "note"],
    "equity.csv": ["time", "equity", "net_deposits"],
    "trades.csv": ["time", "symbol", "side", "usd", "price", "reason"],
    "decisions.csv": ["time", "symbol", "decision", "confidence", "risk", "size_usd", "note"],
}


class Store:
    def __init__(self, root: Path | str, strategy: str):
        self.dir = Path(root) / strategy
        self.dir.mkdir(parents=True, exist_ok=True)
        for name, header in FILES.items():
            p = self.dir / name
            if not p.exists():
                with p.open("w", newline="") as f:
                    csv.writer(f).writerow(header)
        self.state = self._load_state()

    # ---- state.json --------------------------------------------------------
    def _load_state(self) -> dict:
        p = self.dir / "state.json"
        s = json.loads(p.read_text()) if p.exists() else {}
        s.setdefault("day", None)
        s.setdefault("day_start_equity", 0.0)
        s.setdefault("halted_reason", None)
        s.setdefault("plans", {})
        return s

    def save(self) -> None:
        (self.dir / "state.json").write_text(json.dumps(self.state, indent=2, sort_keys=True))

    # ---- csv logs ------------------------------------------------------------
    def append(self, name: str, row: dict) -> None:
        with (self.dir / name).open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=FILES[name]).writerow(row)

    def rows(self, name: str) -> list[dict]:
        with (self.dir / name).open(newline="") as f:
            return list(csv.DictReader(f))

    # ---- deposits ----------------------------------------------------------
    def add_deposit(self, amount: float, note: str, when: datetime) -> None:
        """Positive for money added, negative for money taken out."""
        self.append("deposits.csv", {"time": when.isoformat(timespec="seconds"), "amount": f"{amount:.2f}", "note": note})

    def net_deposits(self) -> float:
        return sum(float(r["amount"]) for r in self.rows("deposits.csv"))

    def performance(self) -> dict:
        """Strategy returns with deposits taken out, so adding money never looks like profit.

        time_weighted_return chains the return between each pair of snapshots after removing
        any deposit made in between - the standard way funds report returns with cash flows.
        """
        snaps = self.rows("equity.csv")
        net = self.net_deposits()
        if not snaps:
            return {"equity": 0.0, "net_deposits": net, "profit": 0.0, "simple_return_pct": 0.0, "twr_pct": 0.0}
        growth = 1.0
        for prev, cur in zip(snaps, snaps[1:]):
            e0, e1 = float(prev["equity"]), float(cur["equity"])
            flow = float(cur["net_deposits"]) - float(prev["net_deposits"])
            if e0 > 0:
                growth *= (e1 - flow) / e0
        equity = float(snaps[-1]["equity"])
        profit = equity - net
        return {
            "equity": equity, "net_deposits": net, "profit": profit,
            "simple_return_pct": profit / net * 100 if net else 0.0,
            "twr_pct": (growth - 1) * 100,
        }
