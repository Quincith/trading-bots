"""Thin Alpaca REST client. Paper trading only: the live URL is not supported on purpose."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

TIMEFRAME_MINUTES = {"5Min": 5, "15Min": 15, "30Min": 30, "1Hour": 60, "4Hour": 240, "1Day": 1440}


def norm(symbol: str) -> str:
    """Alpaca shows crypto positions as BTCUSD but takes orders as BTC/USD. Compare on BTCUSD."""
    return symbol.replace("/", "").upper()


class AlpacaPaper:
    def __init__(self, key_id: str, secret_key: str, session: requests.Session | None = None):
        if not key_id or not secret_key:
            raise ValueError("Missing Alpaca paper keys. See README: GitHub secrets.")
        self.http = session or requests.Session()
        self.http.headers.update({"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key})

    # ---- low level -------------------------------------------------------
    def _req(self, method: str, url: str, **kw):
        for attempt in range(4):
            r = self.http.request(method, url, timeout=30, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Alpaca {method} {url} -> {r.status_code}: {r.text[:300]}")
            return r.json() if r.content else None
        raise RuntimeError(f"Alpaca {method} {url} kept failing")

    def _trade(self, method: str, path: str, **kw):
        return self._req(method, PAPER_URL + path, **kw)

    def _data(self, path: str, params: dict):
        return self._req("GET", DATA_URL + path, params=params)

    # ---- account ---------------------------------------------------------
    def get_account(self) -> dict:
        a = self._trade("GET", "/v2/account")
        return {
            "equity": float(a["equity"]),
            "last_equity": float(a["last_equity"]),
            "cash": float(a["cash"]),
            "buying_power": float(a.get("non_marginable_buying_power") or a["cash"]),
        }

    def get_positions(self) -> list[dict]:
        return [
            {
                "symbol": norm(p["symbol"]),
                "qty": float(p["qty"]),
                "market_value": float(p["market_value"]),
                "avg_entry_price": float(p["avg_entry_price"]),
                "current_price": float(p["current_price"]),
                "asset_class": "crypto" if p["asset_class"] == "crypto" else "stocks",
            }
            for p in self._trade("GET", "/v2/positions")
        ]

    def is_market_open(self) -> bool:
        return bool(self._trade("GET", "/v2/clock")["is_open"])

    # ---- orders ----------------------------------------------------------
    def buy_notional(self, symbol: str, usd: float, asset_class: str, client_order_id: str) -> dict:
        body = {
            "symbol": symbol,
            "notional": f"{usd:.2f}",
            "side": "buy",
            "type": "market",
            "time_in_force": "gtc" if asset_class == "crypto" else "day",
            "client_order_id": client_order_id,
        }
        return self._trade("POST", "/v2/orders", json=body)

    def close_position(self, symbol: str) -> dict:
        return self._trade("DELETE", f"/v2/positions/{norm(symbol)}")

    def close_all(self) -> None:
        self._trade("DELETE", "/v2/positions", params={"cancel_orders": "true"})

    # ---- market data -----------------------------------------------------
    def get_bars(self, symbols: list[str], timeframe: str, lookback: int, asset_class: str) -> dict[str, pd.DataFrame]:
        if not symbols:
            return {}
        minutes = TIMEFRAME_MINUTES[timeframe]
        # Stocks only trade ~6.5h a day, so reach further back to get enough bars.
        stretch = 1.3 if asset_class == "crypto" else 5
        start = datetime.now(timezone.utc) - timedelta(minutes=minutes * lookback * stretch)
        if asset_class == "crypto":
            path, params = "/v1beta3/crypto/us/bars", {}
        else:
            path, params = "/v2/stocks/bars", {"feed": "iex", "adjustment": "split"}
        params.update({"symbols": ",".join(symbols), "timeframe": timeframe,
                       "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 10000})
        raw: dict[str, list] = {}
        while True:
            page = self._data(path, params)
            for sym, bars in (page.get("bars") or {}).items():
                raw.setdefault(sym, []).extend(bars)
            token = page.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        out = {}
        for sym, bars in raw.items():
            df = pd.DataFrame(bars).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            df["t"] = pd.to_datetime(df["t"])
            out[sym] = df.set_index("t")[["open", "high", "low", "close", "volume"]].tail(lookback)
        return out

    def get_news(self, symbols: list[str], hours: int = 48, limit: int = 50) -> list[dict]:
        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        page = self._data("/v1beta1/news", {
            "symbols": ",".join(norm(s) for s in symbols),
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": limit, "sort": "desc",
        })
        return [
            {"headline": n.get("headline", ""), "summary": (n.get("summary") or "")[:300],
             "symbols": n.get("symbols", []), "created_at": n.get("created_at", ""), "source": n.get("source", "")}
            for n in page.get("news", [])
        ]
