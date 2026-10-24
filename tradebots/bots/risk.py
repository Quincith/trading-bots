"""Bot 5 - Risk: protects the account. It can approve, shrink or reject any trade.

This bot is plain rules on purpose - no AI. Limits: max daily loss, max total loss,
max position size, total exposure, correlation with what we already hold, and a kill switch.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..alpaca import norm
from ..models import Candidate


@dataclass
class AccountGate:
    allowed: bool
    reason: str
    halt_strategy: bool = False   # True when the total loss limit is hit


def account_gate(equity: float, day_start_equity: float, net_deposits: float, kill_switch: bool,
                 halted_reason: str | None, cfg: dict) -> AccountGate:
    """Checks that apply to the whole account before any new trade is considered."""
    if kill_switch:
        return AccountGate(False, "Kill switch is ON (TRADING_HALTED). No new trades.")
    if halted_reason:
        return AccountGate(False, f"Strategy halted: {halted_reason}")
    if net_deposits > 0:
        total = (equity - net_deposits) / net_deposits * 100
        if total <= -cfg["max_total_loss_pct"]:
            return AccountGate(False, f"Total loss {total:.1f}% hit the {cfg['max_total_loss_pct']}% limit.",
                               halt_strategy=True)
    if day_start_equity > 0:
        daily = (equity - day_start_equity) / day_start_equity * 100
        if daily <= -cfg["max_daily_loss_pct"]:
            return AccountGate(False, f"Down {daily:.1f}% today, past the {cfg['max_daily_loss_pct']}% daily limit.")
    return AccountGate(True, "ok")


def correlation(a: pd.DataFrame, b: pd.DataFrame, bars: int = 100) -> float:
    ra, rb = a["close"].pct_change(), b["close"].pct_change()
    joined = pd.concat([ra, rb], axis=1, join="inner").dropna().tail(bars)
    if len(joined) < 20:
        return 0.0
    v = joined.iloc[:, 0].corr(joined.iloc[:, 1])
    return 0.0 if pd.isna(v) else float(v)


def review(c: Candidate, equity: float, buying_power: float, positions: list[dict],
           held_bars: dict[str, pd.DataFrame], cfg: dict, already_planned_usd: float = 0.0) -> None:
    """Sets c.risk_verdict (APPROVE / REDUCE / REJECT), c.size_usd and c.risk_note."""
    notes = []

    def reject(why: str):
        c.risk_verdict, c.size_usd, c.risk_note = "REJECT", 0.0, why

    if c.plan is None:
        return reject("No valid chart setup.")
    if norm(c.symbol) in {p["symbol"] for p in positions}:
        return reject("Already holding it.")
    if len(positions) >= cfg["max_open_positions"]:
        return reject(f"Already at {cfg['max_open_positions']} open positions.")

    stop_pct = c.plan.risk_pct / 100
    want = equity * cfg["risk_per_trade_pct"] / 100 / stop_pct
    size = want

    cap = equity * cfg["max_position_pct"] / 100
    if size > cap:
        size = cap
        notes.append(f"capped at {cfg['max_position_pct']}% position size")

    exposure = sum(abs(p["market_value"]) for p in positions) + already_planned_usd
    room = equity * cfg["max_total_exposure_pct"] / 100 - exposure
    if size > room:
        size = max(room, 0)
        notes.append(f"limited by {cfg['max_total_exposure_pct']}% total exposure")

    correlated = [sym for sym, df in held_bars.items()
                  if correlation(c.bars, df) >= cfg["correlation_threshold"]]
    if len(correlated) >= cfg["max_correlated_positions"]:
        return reject(f"Moves too closely with {', '.join(correlated)} already held.")
    if correlated:
        size *= cfg["correlated_size_factor"]
        notes.append(f"shrunk because it moves with {', '.join(correlated)}")

    if size > buying_power:
        size = buying_power
        notes.append("limited by available cash")

    if size < cfg["min_order_usd"]:
        return reject("Size too small after limits." + (f" ({'; '.join(notes)})" if notes else ""))

    risk_usd = size * stop_pct
    c.size_usd = round(size, 2)
    c.risk_verdict = "REDUCE" if size < want * 0.999 else "APPROVE"
    c.risk_note = (f"${size:,.2f} position, risking ${risk_usd:,.2f} ({risk_usd / equity * 100:.1f}% of account)"
                   + (f"; {'; '.join(notes)}" if notes else ""))
