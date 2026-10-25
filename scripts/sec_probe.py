import requests
urls = ["https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&owner=include&count=10&output=atom",
        "https://www.sec.gov/Archives/edgar/daily-index/",
        "https://efts.sec.gov/LATEST/search-index?forms=4&dateRange=custom",
        "https://data.sec.gov/submissions/CIK0000320193.json",
        "https://www.sec.gov/files/company_tickers.json"]
agents = ["Quincith trading-bots (paper trading research) trading-bots@users.noreply.github.com",
          "trading-bots trading-bots@users.noreply.github.com",
          "Quincy Research quincith.bots@gmail.com",
          "Mozilla/5.0 (compatible; trading-bots/1.0; +https://github.com/Quincith/trading-bots)"]
for a in agents:
    for u in urls:
        try:
            r = requests.get(u, headers={"User-Agent": a, "Accept-Encoding": "gzip, deflate"}, timeout=20)
            print(r.status_code, len(r.content), "|", a[:40], "|", u[:70], "|", r.text[:120].replace("\n", " ") if r.status_code != 200 else "")
        except Exception as e:
            print("ERR", a[:40], u[:70], e)
