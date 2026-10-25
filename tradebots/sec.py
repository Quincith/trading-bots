"""Reads company insider trades from the SEC (free, official, no key needed).

When a company's officers (CEO, CFO, ...) or board members trade its stock, US law says they must
file a "Form 4" with the SEC within 2 business days. Every filing is public on EDGAR:
  - the "latest filings" feed lists the newest Form 4s, a few hundred per day, and
  - each filing has a small XML document saying who traded, what, how many shares and at what price.

The SEC asks every program to say who is asking, with a real contact email, and to make at most
10 requests a second. It refuses requests without one (and refuses GitHub's "noreply" addresses).
The email comes from the SEC_CONTACT_EMAIL secret (a secret, so GitHub hides it in the public logs). We stay well under the speed limit.
"""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}.txt"
ATOM = "{http://www.w3.org/2005/Atom}"
LINK_RE = re.compile(r"/data/(\d+)/(\d{18})/(\d{10}-\d{2}-\d{6})-index")
NEEDS_EMAIL = ("The SEC needs a contact email before it will share filings. Add a repository secret named "
               "SEC_CONTACT_EMAIL (Settings > Secrets and variables > Actions > New repository secret).")


@dataclass
class InsiderBuy:
    """One open-market purchase by an insider, from one Form 4."""
    accession: str
    ticker: str
    company: str
    who: str
    role: str            # e.g. "CEO", "Director", "10% owner"
    is_officer: bool
    is_director: bool
    shares: float
    price: float
    date: str            # trade date, YYYY-MM-DD
    filed: str           # when the SEC published it (ISO time)

    @property
    def usd(self) -> float:
        return self.shares * self.price


@dataclass
class FeedResult:
    filings_read: int = 0
    buys: list[InsiderBuy] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)     # accession numbers read this time
    error: str = ""


def _flag(el: ET.Element | None) -> bool:
    return el is not None and (el.text or "").strip().lower() in {"1", "true"}


def _val(el: ET.Element | None, path: str) -> str:
    """Form 4 puts most numbers in <thing><value>...</value></thing>; some in <thing>...</thing>."""
    if el is None:
        return ""
    node = el.find(path)
    if node is None:
        return ""
    inner = node.find("value")
    return ((inner.text if inner is not None else node.text) or "").strip()


def _strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_form4(xml_text: str, accession: str, filed: str) -> list[InsiderBuy]:
    """Open-market purchases (transaction code P) in one Form 4. Sales, option exercises, gifts and
    stock grants are skipped: only a purchase means the insider chose to spend their own cash."""
    root = _strip_ns(ET.fromstring(xml_text))
    if _val(root, "documentType") != "4":
        return []
    ticker = _val(root, "issuer/issuerTradingSymbol").upper()
    company = _val(root, "issuer/issuerName")
    if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", ticker):
        return []
    owners = root.findall("reportingOwner")
    if not owners:
        return []
    names, officer, director, roles = [], False, False, []
    for o in owners:
        names.append(_val(o, "reportingOwnerId/rptOwnerName"))
        rel = o.find("reportingOwnerRelationship")
        if rel is None:
            continue
        if _flag(rel.find("isOfficer")):
            officer = True
            roles.append(_val(rel, "officerTitle") or "Officer")
        if _flag(rel.find("isDirector")):
            director = True
            roles.append("Director")
        if _flag(rel.find("isTenPercentOwner")):
            roles.append("10% owner")
        if _flag(rel.find("isOther")):
            roles.append(_val(rel, "otherText") or "Other")
    out = []
    for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        if _val(t, "transactionCoding/transactionCode") != "P":
            continue
        if _val(t, "transactionAmounts/transactionAcquiredDisposedCode") != "A":
            continue
        try:
            shares = float(_val(t, "transactionAmounts/transactionShares"))
            price = float(_val(t, "transactionAmounts/transactionPricePerShare"))
        except ValueError:
            continue
        if shares <= 0 or price <= 0:
            continue
        out.append(InsiderBuy(accession=accession, ticker=ticker, company=company,
                              who=" & ".join(n for n in names if n) or "unknown", role=", ".join(dict.fromkeys(roles)) or "Insider",
                              is_officer=officer, is_director=director, shares=shares, price=price,
                              date=_val(t, "transactionDate")[:10], filed=filed))
    return out


def extract_xml(full_text: str) -> str | None:
    """A filing's full text file wraps the Form 4 XML in <XML> ... </XML>."""
    m = re.search(r"<XML>\s*(.*?)\s*</XML>", full_text, re.S | re.I)
    return m.group(1) if m else None


def parse_feed(atom_text: str) -> list[dict]:
    """Newest Form 4 filings from the EDGAR "latest filings" Atom feed: accession, cik, filed time."""
    root = ET.fromstring(atom_text)
    out, seen = [], set()
    for e in root.iter(ATOM + "entry"):
        link = e.find(ATOM + "link")
        m = LINK_RE.search(link.get("href", "") if link is not None else "")
        if not m:
            continue
        cik, folder, acc = m.groups()
        if acc in seen:      # each filing is listed once for the insider and once for the company
            continue
        seen.add(acc)
        upd = e.find(ATOM + "updated")
        out.append({"accession": acc, "cik": cik, "folder": folder,
                    "filed": (upd.text or "").strip() if upd is not None else ""})
    return out


class SecFeed:
    def __init__(self, session: requests.Session | None = None, pause: float = 0.15):
        self.http = session or requests.Session()
        self.email = (os.environ.get("SEC_CONTACT_EMAIL") or "").strip()
        self.http.headers.update({"User-Agent": f"Paper trading research bot {self.email}",
                                  "Accept-Encoding": "gzip, deflate"})
        self.pause = pause

    def _get(self, url: str, **params) -> str:
        for attempt in range(4):
            time.sleep(self.pause)
            r = self.http.get(url, params=params or None, timeout=30)
            if r.status_code in (429, 503) or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 403:
                raise RuntimeError("the SEC refused the request (403). Check that SEC_CONTACT_EMAIL is a real email "
                                   "address; GitHub noreply addresses are refused")
            r.raise_for_status()
            return r.text
        raise RuntimeError(f"SEC kept failing for {url}")

    def latest(self, seen: set[str], limit: int = 300) -> FeedResult:
        """Reads up to `limit` Form 4 filings not in `seen`, newest first, and returns the insider buys."""
        res = FeedResult()
        if "@" not in self.email:
            res.error = NEEDS_EMAIL
            return res
        try:
            todo = []
            for start in range(0, 1000, 100):
                page = parse_feed(self._get(FEED_URL, action="getcurrent", type="4", owner="include",
                                            count=100, start=start, output="atom"))
                fresh = [f for f in page if f["accession"] not in seen]
                todo += fresh
                # Stop once we reach filings we already read, or have enough to do.
                if not page or len(fresh) < len(page) or len(todo) >= limit:
                    break
            for f in todo[:limit]:
                try:
                    text = self._get(ARCHIVE_URL.format(cik=f["cik"], folder=f["folder"], accession=f["accession"]))
                    xml = extract_xml(text)
                    if xml:
                        res.buys += parse_form4(xml, f["accession"], f["filed"])
                except (requests.RequestException, ET.ParseError, RuntimeError) as e:
                    log.warning("skipping filing %s: %s", f["accession"], e)
                res.seen.append(f["accession"])
                res.filings_read += 1
        except (requests.RequestException, ET.ParseError, RuntimeError) as e:
            res.error = f"Couldn't read the SEC feed: {e}"
            log.warning(res.error)
        return res


def filed_time(b: InsiderBuy) -> datetime:
    try:
        t = datetime.fromisoformat(b.filed)
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
