from datetime import datetime, timedelta, timezone

import yaml
from conftest import FakeBroker, make_bars

from tradebots import copycat, recap, report, runlog, sec, weekly, world
from tradebots.__main__ import ROOT
from tradebots.store import Store

CFG = yaml.safe_load((ROOT / "config/copycat.yaml").read_text())
NOW = datetime(2026, 10, 27, 15, tzinfo=timezone.utc)   # a Tuesday, market open

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion>
  <documentType>4</documentType>
  <issuer><issuerCik>0000012345</issuerCik><issuerName>Acme Widgets Inc</issuerName>
    <issuerTradingSymbol>acme</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0000099999</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>true</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-23</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>20.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-10-23</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>21.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>4 - DOE JANE (0000099999) (Reporting)</title>
 <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/99999/000009999926000001/0000099999-26-000001-index.htm"/>
 <updated>2026-10-26T17:01:02-04:00</updated></entry>
<entry><title>4 - Acme Widgets Inc (0000012345) (Issuer)</title>
 <link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/12345/000009999926000001/0000099999-26-000001-index.htm"/>
 <updated>2026-10-26T17:01:02-04:00</updated></entry>
</feed>"""


def buy(ticker="ACME", who="DOE JANE", usd=200_000, price=20.0, officer=True, director=False, acc="a1",
        filed="2026-10-26T21:00:00+00:00", role="Chief Executive Officer"):
    return sec.InsiderBuy(accession=acc, ticker=ticker, company=f"{ticker} Inc", who=who, role=role,
                          is_officer=officer, is_director=director, shares=usd / price, price=price,
                          date="2026-10-23", filed=filed)


class FakeFeed:
    def __init__(self, buys):
        self.buys, self.calls = buys, []

    def latest(self, seen, limit):
        self.calls.append(set(seen))
        fresh = [b for b in self.buys if b.accession not in seen]
        return sec.FeedResult(filings_read=len({b.accession for b in fresh}), buys=fresh,
                              seen=sorted({b.accession for b in fresh}))


class StockBroker(FakeBroker):
    def __init__(self, prices, open_=True, **kw):
        super().__init__(**kw)
        self.prices, self.open_ = prices, open_

    def is_market_open(self):
        return self.open_

    def can_buy_fractional(self, symbol):
        return symbol in self.prices

    def latest_price(self, symbol):
        return self.prices.get(symbol)

    def buy_notional(self, symbol, usd, asset_class, client_order_id):
        self.orders.append((symbol, usd, asset_class))


def test_parse_form4_keeps_only_open_market_buys():
    [b] = sec.parse_form4(FORM4, "acc", "2026-10-26T17:01:02-04:00")
    assert (b.ticker, b.shares, b.price, b.usd) == ("ACME", 10000, 20.0, 200_000)
    assert b.is_officer and b.is_director and "Chief Executive Officer" in b.role and b.who == "DOE JANE"
    assert sec.parse_form4(FORM4.replace("<documentType>4<", "<documentType>4/A<"), "acc", "") == []


def test_parse_feed_dedupes_filings_and_extract_xml():
    [f] = sec.parse_feed(ATOM)
    assert f == {"accession": "0000099999-26-000001", "cik": "99999", "folder": "000009999926000001",
                 "filed": "2026-10-26T17:01:02-04:00"}
    assert sec.extract_xml(f"<SEC-DOCUMENT>\n<XML>\n{FORM4}\n</XML>\n</SEC-DOCUMENT>").startswith("<?xml")


def test_watchlist_ranks_clusters_and_drops_stale_and_outsiders():
    st = {}
    buys = [buy("ACME", "A", acc="1"), buy("ACME", "B", 100_000, acc="2", role="Director", officer=False, director=True),
            buy("BIGF", "Fund LP", 5_000_000, acc="3", officer=False, role="10% owner"),
            buy("SOLO", "C", 300_000, acc="4", role="VP Sales"),
            buy("OLD", "D", 900_000, acc="5", filed="2026-10-10T00:00:00+00:00"),
            buy("PNNY", "E", 900_000, price=1.5, acc="6")]
    copycat.update_watchlist(st, buys, CFG["copycat"], NOW)
    assert set(st["watchlist"]) == {"ACME", "SOLO"}            # outside fund, stale filing, penny stock dropped
    order = [e["ticker"] for e in copycat.ranked(st, CFG["copycat"], set(), NOW)]
    assert order == ["ACME", "SOLO"]                            # two insiders incl. the CEO beat one VP
    copycat.update_watchlist(st, buys[:1], CFG["copycat"], NOW)   # the same filing again is not double counted
    assert len(st["watchlist"]["ACME"]["buys"]) == 2


def test_copycat_buys_when_open_and_skips_late_copies(tmp_path):
    store = Store(tmp_path, "copycat")
    feed = FakeFeed([buy("ACME", acc="1"), buy("LATE", price=10.0, acc="2")])
    broker = StockBroker({"ACME": 20.5, "LATE": 12.0}, equity=100,
                         bars={"ACME": make_bars(seed=1, start=20), "LATE": make_bars(seed=2, start=12)})
    res = copycat.run(CFG, broker, store, now=NOW, feed=feed)
    assert [o[0] for o in broker.orders] == ["ACME"] and broker.orders[0][2] == "stocks"
    assert broker.orders[0][1] <= 20.0 + 1e-9                    # max 20% of a $100 account
    late = next(c for c in res.candidates if c.symbol == "LATE")
    assert late.decision == "SKIP" and "Too late" in late.decision_note
    plan = store.state["plans"]["ACME"]
    assert abs(plan["stop"] - 20.5 * 0.9) < 1e-9 and abs(plan["target"] - 20.5 * 1.2) < 1e-9
    assert "ACME" not in store.state["watchlist"] and store.rows("trades.csv")[0]["side"] == "buy"

    # Next run: filings already read are skipped, and ACME is not bought again.
    broker.positions = [{"symbol": "ACME", "qty": 1, "market_value": 20, "avg_entry_price": 20.5,
                         "current_price": 20.6, "asset_class": "stocks"}]
    res2 = copycat.run(CFG, broker, store, now=NOW + timedelta(minutes=30), feed=feed)
    assert feed.calls[1] >= {"1", "2"} and len(broker.orders) == 1 and res2.filings["read"] == 0

    text = report.render(res, store, False)
    assert "Insider buys on the watchlist" in text and "Copy decisions" in text and "no AI" in text


def test_copycat_waits_while_market_closed_and_dry_run_sends_nothing(tmp_path):
    store = Store(tmp_path, "copycat")
    broker = StockBroker({"ACME": 20.5}, open_=False, equity=100)
    res = copycat.run(CFG, broker, store, now=NOW, feed=FakeFeed([buy(acc="1")]))
    assert not broker.orders and res.candidates[0].decision == "WAIT" and "ACME" in store.state["watchlist"]
    broker.open_ = True
    res = copycat.run(CFG, broker, store, now=NOW + timedelta(hours=1), feed=FakeFeed([]), dry_run=True)
    assert not broker.orders and res.buys


def test_copycat_on_world_page_recap_and_weekly(tmp_path):
    store = Store(tmp_path, "copycat")
    broker = StockBroker({"ACME": 20.5}, equity=100, bars={"ACME": make_bars(seed=1, start=20)})
    res = copycat.run(CFG, broker, store, now=NOW, feed=FakeFeed([buy(acc="1")]))
    runlog.save(res, store, False)
    r = recap.build(store, NOW.date().isoformat())
    assert any(b.startswith("Spotter read 1 insider filings") for b in r["bullets"])
    assert all(t in recap.GLOSSARY for t in r["terms"]) and "insider" in r["terms"]
    html = world.build(tmp_path, tmp_path / "site", now=NOW + timedelta(minutes=5)).read_text()
    assert '"copycat"' in html and "copies company insiders" in html and "Reads the newest SEC insider filings" in html
    st = world.copycat_stations(runlog.load_day(store, NOW.date().isoformat())[-1], CFG)
    assert st["decision"]["status"] == "buy" and st["news"]["say"].startswith("ACME: 1 insider bought $200,000")

    flat = lambda when: 100.0  # noqa: E731
    stats = weekly.strategy_stats(store, NOW + timedelta(days=1), flat, flat)
    text = weekly.render({"aggressive": None, "medium": None, "copycat": stats}, NOW + timedelta(days=1))
    assert "## Copycat" in text and "S&P 500" in text
