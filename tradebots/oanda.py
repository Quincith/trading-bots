"""Thin OANDA v20 REST client. Practice (demo) accounts only: the live URL is not supported on purpose.

One OANDA login can hold several practice sub-accounts, and one API token works for all of them, so the
Forex and Copycat FX offices share a token and each has its own account id.

The practice account starts with pretend money (often $100,000 unless you change it). The bots don't need
that much: each office acts as if it had `start_balance` (default $100) and sizes its trades from that.
See `virtual_equity` below.
"""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import requests

PRACTICE_URL = "https://api-fxpractice.oanda.com"


def quote_ccy(pair: str) -> str:
    return pair.split("_")[1]


def base_ccy(pair: str) -> str:
    return pair.split("_")[0]


def decimals(pair: str) -> int:
    """How many decimals OANDA takes for prices: 3 for yen pairs, 5 for the rest."""
    return 3 if quote_ccy(pair) == "JPY" else 5


class OandaPractice:
    def __init__(self, token: str, account_id: str, session: requests.Session | None = None):
        if not token or not account_id:
            raise ValueError("Missing OANDA practice token or account id. See README: GitHub secrets.")
        self.account = account_id
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                  "Accept-Datetime-Format": "RFC3339"})

    def _req(self, method: str, path: str, **kw):
        for attempt in range(4):
            r = self.http.request(method, PRACTICE_URL + path, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"OANDA {method} {path} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else None
        raise RuntimeError(f"OANDA {method} {path} kept failing")

    # ---- account -------------------------------------------------------------------------------
    def get_account(self) -> dict:
        a = self._req("GET", f"/v3/accounts/{self.account}/summary")["account"]
        return {"nav": float(a["NAV"]), "balance": float(a["balance"]), "unrealized": float(a["unrealizedPL"]),
                "currency": a.get("currency", "USD")}

    def open_trades(self) -> list[dict]:
        out = []
        for t in self._req("GET", f"/v3/accounts/{self.account}/openTrades")["trades"]:
            out.append({"id": t["id"], "pair": t["instrument"], "units": float(t["currentUnits"]),
                        "price": float(t["price"]), "unrealized": float(t.get("unrealizedPL", 0)),
                        "opened": t["openTime"],
                        "stop": float(t["stopLossOrder"]["price"]) if t.get("stopLossOrder") else None})
        return out

    # ---- prices --------------------------------------------------------------------------------
    def daily_bars(self, pair: str, count: int = 300) -> pd.DataFrame:
        """Finished daily candles (a day ends at 5pm New York time, the forex market's usual day end).
        Columns: open, high, low, close (mid prices) and spread (ask minus bid at the close)."""
        js = self._req("GET", f"/v3/instruments/{pair}/candles",
                       params={"granularity": "D", "count": count, "price": "MBA"})
        rows = []
        for c in js.get("candles", []):
            if not c.get("complete"):
                continue
            m = c["mid"]
            rows.append({"t": pd.Timestamp(c["time"]), "open": float(m["o"]), "high": float(m["h"]),
                         "low": float(m["l"]), "close": float(m["c"]),
                         "spread": float(c["ask"]["c"]) - float(c["bid"]["c"]), "volume": c.get("volume", 0)})
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "spread", "volume"])
        return pd.DataFrame(rows).set_index("t")

    def history(self, pair: str, granularity: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Finished mid-price candles between two times, fetched 5,000 at a time (OANDA's limit per request).
        Used by the lab; columns: open, high, low, close, spread (0: the lab charges OANDA's usual one)."""
        rows, t = [], pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        while t < end_ts:
            js = self._req("GET", f"/v3/instruments/{pair}/candles",
                           params={"granularity": granularity, "from": t.isoformat(), "count": 5000, "price": "M"})
            got = [c for c in js.get("candles", []) if c.get("complete")]
            if not got:
                break
            for c in got:
                m = c["mid"]
                rows.append((pd.Timestamp(c["time"]), float(m["o"]), float(m["h"]), float(m["l"]), float(m["c"])))
            nxt = pd.Timestamp(got[-1]["time"]) + pd.Timedelta(seconds=1)
            if nxt <= t:
                break
            t = nxt
        df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close"]).drop_duplicates("t").set_index("t")
        df["spread"] = 0.0
        return df[df.index < end_ts]

    # ---- orders --------------------------------------------------------------------------------
    def market_order(self, pair: str, units: int, stop: float, tag: str) -> dict:
        """Opens a trade (units > 0 buys, < 0 sells) with a safety stop that OANDA holds, so it can fill
        between the bot's 30-minute checks. Returns {"filled", "price", "trade_id", "reason"}."""
        body = {"order": {"type": "MARKET", "instrument": pair, "units": str(int(units)), "timeInForce": "FOK",
                          "positionFill": "DEFAULT",
                          "stopLossOnFill": {"price": f"{stop:.{decimals(pair)}f}", "timeInForce": "GTC"},
                          "clientExtensions": {"tag": tag[:100]}, "tradeClientExtensions": {"tag": tag[:100]}}}
        js = self._req("POST", f"/v3/accounts/{self.account}/orders", json=body)
        fill = js.get("orderFillTransaction")
        if fill and fill.get("tradeOpened"):
            return {"filled": True, "price": float(fill["price"]), "trade_id": fill["tradeOpened"]["tradeID"],
                    "reason": ""}
        cancel = js.get("orderCancelTransaction") or {}
        return {"filled": False, "price": None, "trade_id": None, "reason": cancel.get("reason", "not filled")}

    def close_trade(self, trade_id: str) -> dict:
        js = self._req("PUT", f"/v3/accounts/{self.account}/trades/{trade_id}/close", json={"units": "ALL"})
        fill = js.get("orderFillTransaction") or {}
        return {"price": float(fill["price"]) if fill.get("price") else None, "pl": float(fill.get("pl", 0))}

    def closed_trade(self, trade_id: str) -> dict | None:
        """A trade OANDA closed by itself (its stop was hit): when, at what price, and the profit or loss."""
        t = self._req("GET", f"/v3/accounts/{self.account}/trades/{trade_id}").get("trade", {})
        if t.get("state") != "CLOSED":
            return None
        return {"price": float(t.get("averageClosePrice") or 0), "pl": float(t.get("realizedPL", 0)),
                "closed": t.get("closeTime")}

    def close_all(self) -> None:
        for t in self.open_trades():
            self.close_trade(t["id"])


def parse_time(s: str) -> datetime:
    return pd.Timestamp(s).to_pydatetime()
