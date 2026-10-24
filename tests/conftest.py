import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_bars(n=200, drift=0.0, surge=False, seed=0, start=100.0):
    """Synthetic candles. surge=True adds a strong rally on heavy volume in the last bars."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.004, n)
    vol = rng.uniform(900, 1100, n)
    if surge:
        rets[-6:] = 0.006
        vol[-2:] = 4000
    close = start * np.cumprod(1 + rets)
    idx = pd.date_range("2026-10-20", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": close / (1 + rets), "high": close * 1.002, "low": close / (1 + rets) * 0.998,
                         "close": close, "volume": vol}, index=idx)


class FakeBroker:
    def __init__(self, equity=100.0, bars=None, positions=None):
        self.equity = equity
        self.bars = bars or {}
        self.positions = positions or []
        self.orders, self.closed = [], []

    def get_account(self):
        return {"equity": self.equity, "last_equity": self.equity, "cash": self.equity, "buying_power": self.equity}

    def get_positions(self):
        return [p for p in self.positions if p["symbol"] not in self.closed]

    def is_market_open(self):
        return False

    def get_bars(self, symbols, timeframe, lookback, asset_class):
        return {s: self.bars[s] for s in symbols if s in self.bars}

    def get_news(self, symbols, hours=48, limit=50):
        return [{"headline": "SOL ETF approval sparks record inflow", "summary": "", "symbols": ["SOLUSD"],
                 "created_at": "2026-10-24T20:00:00Z", "source": "test"}]

    def buy_notional(self, symbol, usd, asset_class, client_order_id):
        self.orders.append((symbol, usd))

    def close_position(self, symbol):
        self.closed.append(symbol)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Sentiment sources are public websites; keep tests offline."""
    from tradebots.bots import sentiment
    monkeypatch.setattr(sentiment, "_get", lambda url, **p: None)
