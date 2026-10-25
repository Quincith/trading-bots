# Trading bots (paper money)

Six bots that work as a team, modeled on the seb.ai post, trading **Alpaca paper money only**.
The code cannot place real-money trades: it only talks to Alpaca's paper trading address.

| # | Bot | What it does |
|---|---|---|
| 1 | **Scout** | Scans crypto (and stocks if you add them) for unusual volume and price moves, then checks momentum. |
| 2 | **News** | Pulls recent headlines from Alpaca's free news feed and has Claude judge whether there's a real catalyst. |
| 3 | **Sentiment** | Reads Reddit chatter (mention counts from ApeWisdom plus recent post titles) and the crypto Fear & Greed index. Claude scores it bullish, bearish or pure hype. X/Twitter has no realistic free option, so it's not used. |
| 4 | **Charts** | Finds the trend, support and resistance, and sets an entry, stop and target. |
| 5 | **Risk** | Plain rules, no AI. Approves, shrinks or rejects each trade. It enforces the daily loss limit, total loss limit, position size, total exposure and correlation limits, plus the kill switch. |
| 6 | **Decision** | Claude reads all five and makes the final call: **BUY**, **WAIT** or **SKIP**. Only BUY places an order. |

If Claude can't be reached, bots 2, 3 and 6 fall back to simple rules, so a run never crashes.

## Two strategies, two accounts

The code is the same for both. Each strategy has its own settings file and its own Alpaca paper account, so the results stay separate.

| | Aggressive ([config/aggressive.yaml](config/aggressive.yaml)) | Medium ([config/medium.yaml](config/medium.yaml)) |
|---|---|---|
| Risk per trade | 7.5% of the account | 2% of the account |
| Biggest single position | 40% | 25% |
| Hold time | up to 12 hours | up to 5 days |
| Candles it reads | 15 minutes | 1 hour |
| Looks for new trades | every 30 min | every 2 hours |
| Buys when | Decision says BUY with 55%+ confidence | Decision says BUY with 70%+ confidence |
| Daily loss limit | 10% | 3% |
| Total loss limit | 40% | 15% |

When the daily limit is hit, no new trades are opened until the next day (UTC). When the total limit is hit (measured against the money you put in), the strategy halts until you resume it.

Every trade is sized as a percent of the account, so the bots scale up as you add money.

## Setup (about 20 minutes, one time)

**Never paste keys into chat, email or code.** They only go into GitHub secrets (step 3).

### 1. Alpaca: two paper accounts
1. Log in at [alpaca.markets](https://alpaca.markets) and switch to **Paper Trading**.
2. Open the account menu (top left) and create a second paper account. Name one "Aggressive" and one "Medium".
3. For each account, set the starting balance to **$100**. You can choose the amount when you create or reset a paper account.
4. In each account, go to **Home → API Keys → Generate New Keys**. Copy the Key ID and Secret straight into the GitHub secrets in step 3. Alpaca shows the secret only once.

### 2. Claude API key
1. Go to [console.anthropic.com](https://console.anthropic.com), add a payment method, and create an API key.

### 3. Add the keys to GitHub
In this repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add these five secrets, using exactly these names:

| Secret name | Value |
|---|---|
| `ALPACA_AGGRESSIVE_KEY_ID` | Key ID from the Aggressive paper account |
| `ALPACA_AGGRESSIVE_SECRET_KEY` | Secret from the Aggressive paper account |
| `ALPACA_MEDIUM_KEY_ID` | Key ID from the Medium paper account |
| `ALPACA_MEDIUM_SECRET_KEY` | Secret from the Medium paper account |
| `ANTHROPIC_API_KEY` | Your Claude API key |

### 4. Turn it on
1. Merge the pull request. The schedule only starts once the code is on `main`.
2. Do a test first: go to **Actions → Trade (paper) → Run workflow**, tick **Dry run**, and click Run. A dry run does all the thinking but places no orders.
3. After that it runs by itself every 30 minutes.

## Checking results

- **After each run:** go to **Actions → Trade (paper)** and click a run. The page shows the account value, the money you put in, profit or loss, and what each bot thought about every coin it looked at.
- **History:** the `bot-data` branch has a folder for each strategy with `summary.md` (latest run), `trades.csv`, `decisions.csv`, `deposits.csv` and `equity.csv`.

Profit is always measured as **account value minus the money you put in**, so adding money never looks like a gain. The "time-weighted return" also ignores when deposits happened, which makes it the fair number for comparing the two strategies.

## Bot World page and daily recap

After every run, the bots rebuild a web page that shows the crew at work: each bot's latest report, a replay of the last run, the account value chart, recent trades, and a **daily recap** written for beginners (a short description, then key-takeaway bullets, plus a "Words to know" list).

- **Where:** your GitHub Pages address, `https://quincith.github.io/trading-bots/` (after the one-time setup below).
- **Effects:** a green laser and a party on a winning trade, tomatoes on a losing one. Use the **Win / Loss / Buy** buttons under the ship to show them off any time. Sound is off until you press **Sound**.
- **Accounts:** the switch at the top flips between Aggressive (light-blue denim crew) and Medium (dark-blue denim crew).
- **Recaps as files:** `recaps/<date>.md` and `recaps/latest.md` on the `bot-data` branch.
- **Without Pages:** the same page is saved as `world/index.html` on the `bot-data` branch. Download it and open it in a browser.

One-time setup: the repository must be **public** (GitHub Pages is free only for public repositories), then go to **Settings → Pages → Build and deployment → Source** and pick **GitHub Actions**. The page appears after the next run.

The characters are original designs. They aren't copies of any movie characters, so the page is safe to share.

## Buttons you might need

All of these are under **Actions → Control panel → Run workflow**:

- **Log a deposit / withdrawal:** record money you add or take out. The first run records the starting balance automatically. (Alpaca can't deposit into paper accounts, so to simulate adding money, reset the paper balance in Alpaca and log the difference here.)
- **Close all positions:** sell everything in one strategy's account right away.
- **Resume after a loss-limit halt:** restart a strategy that hit its total loss limit.

**Kill switch:** go to **Settings → Secrets and variables → Actions → Variables → New repository variable**, name it `TRADING_HALTED` and set it to `true`. Both strategies stop opening trades, but they keep managing exits on the trades already open. Set it to `false` to resume.

## Changing settings

Open `config/aggressive.yaml` or `config/medium.yaml` on GitHub, click the pencil icon, edit, and commit. Every line has a comment. Useful ones:
- `stocks: [NVDA, AMD]` adds stocks. They're only traded while the US market is open.
- `max_daily_loss_pct` / `max_total_loss_pct` are the loss limits.
- `model` sets which Claude model the bots use.

## Costs

- **Claude:** Claude is only asked when Scout and Charts find a real setup, and then it makes 3 calls per scan. On `claude-opus-5-5` that should come to roughly $1–2 a day across both strategies, depending on how busy the market is. Changing `model` to `claude-haiku-5-5` in both config files cuts that to pennies, but the judgment is weaker.
- **GitHub Actions:** a private repo gets 2,000 free minutes a month. One run every 30 minutes uses about 1,500.

## Honest limitations

- Stops and targets are checked every 30 minutes, not instantly, so a fast drop can go past the stop before the bot sells.
- Paper fills are kinder than real ones. Real trading has slippage and fees, so live results will be worse.
- The Reddit and Fear & Greed sources are free public sites and can be down or block GitHub's servers. When that happens the Sentiment bot scores from whatever it got.
- Nothing here is a promise of profit. Turning $100 into $1,000 would take a 10x return, which very few strategies achieve. Run both on paper for a few weeks and compare them before considering real money.

## For developers

```bash
pip install -r requirements.txt
python -m pytest -q
ALPACA_MEDIUM_KEY_ID=... ALPACA_MEDIUM_SECRET_KEY=... python -m tradebots run --strategy medium --dry-run
```

Code map: `tradebots/bots/` (one file per bot), `tradebots/pipeline.py` (runs the team), `tradebots/alpaca.py` (paper broker and market data), `tradebots/ai.py` (Claude), `tradebots/store.py` (memory and deposit-adjusted returns).
