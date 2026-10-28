# Trading bots (paper money)

Six bots that work as a team, modeled on the seb.ai post, trading **Alpaca paper money only**.
The code cannot place real-money trades: it only talks to Alpaca's paper trading address.

| # | Bot | What it does |
|---|---|---|
| 1 | **Scout** | Scans crypto (and stocks if you add them) for unusual volume and price moves, then checks momentum. |
| 2 | **News** | Runs the **News radar** (below) over all crypto news to spot trends while they're forming, then reads the headlines for each coin Scout flagged and has Claude judge whether there's a real catalyst (a news event that could move the price). |
| 3 | **Sentiment** | Reads Reddit chatter (mention counts from ApeWisdom plus recent post titles) and the crypto Fear & Greed index. Claude scores it bullish, bearish or pure hype. X/Twitter has no realistic free option, so it's not used. |
| 4 | **Charts** | Finds the trend, support and resistance, and sets an entry, stop and target. |
| 5 | **Risk** | Plain rules, no AI. Approves, shrinks or rejects each trade. It enforces the daily loss limit, total loss limit, position size, total exposure and correlation limits, plus the kill switch. |
| 6 | **Decision** | Claude reads all five and makes the final call: **BUY**, **WAIT** or **SKIP**. Only BUY places an order. |

If Claude can't be reached, bots 2, 3 and 6 fall back to simple rules, so a run never crashes. If a news site is down, the radar just skips it.

## News radar (spotting the next trend early)

Scout only notices a coin once its price and trading volume are already jumping. By then the news that
caused it is often hours old. So on every scan, before Scout looks at prices, the News bot reads **all**
the crypto news from the last day, for every coin in the list:

| Source | What it gives | Cost |
|---|---|---|
| Alpaca news (Benzinga) | Headlines tagged by coin | free, uses the Alpaca keys |
| CoinDesk, Cointelegraph, Decrypt | Headlines from the big crypto news sites (public RSS feeds) | free, no key |
| CoinGecko "trending" | The coins people searched for most in the last 24 hours. A rush of people looking up a coin often comes before a rush of people buying it. | free, no key |

For each coin it counts **buzz**: headlines in the last 4 hours compared with the usual pace before that
(3x means three times more news than normal). Once an hour Claude (Haiku, the cheapest model, under $1 a
month for this) reads all the headlines together and names up to 3 **themes** that are building, like
"ETF hopes for Solana", and scores each coin from -1 (bad news building) to +1 (good news building).
Between Claude's reads the free counts still update every scan. Every Claude read is saved in
`data/radar/` on the bot-data branch, so we can check later whether its early calls came true.

What it changes today: News and Decision get the radar's notes as background, and the run report and bot
world show the themes. It does **not** change which coins get looked at yet.

**Early watch (off for now):** with `radar.early_watch: true`, a coin with a radar score of 0.5 or more
gets past Scout with half the usual volume jump and price move, so the team can look at it before the
crowd arrives. The catch: getting in earlier also means acting on more stories that go nowhere. That's
why it stays off until it has been tested in the strategy lab on past prices and past Alpaca headlines.
(The news sites and the trending list don't keep history, so the lab can only test it with Alpaca's
headlines.)

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

## Third account: Copycat (copies company insiders)

Copycat doesn't use the six-bot team's guesses. It copies people who know their companies best: **insiders**,
meaning a company's CEO, CFO, other officers and board members. When one of them buys their own company's
stock with their own money, US law says they must report it to the SEC within 2 business days on a public
form called a **Form 4**. Copycat reads those filings (free, official, no extra key) and buys the same stocks.

| | Copycat ([config/copycat.yaml](config/copycat.yaml)) |
|---|---|
| What it buys | US stocks that officers or directors just bought, at least $50,000 worth, in the last 5 days |
| Ranks picks by | how much was bought, how many insiders bought together, and whether a top boss (CEO, CFO, ...) was one of them |
| Skips a pick when | the price is already 10%+ above what the insiders paid (too late to copy), or it's under $5 |
| Biggest single position | 20% of the account, up to 5 stocks |
| Safety exit / profit goal | 10% below / 20% above our buy price |
| Hold time | up to 30 days |
| Daily loss limit | 5% |
| Total loss limit | 20% |
| AI | none, so it costs nothing to run |

Stocks only trade on weekdays, 9:30am to 4pm New York time. Insiders often file in the evening, so Copycat
keeps a watchlist and buys at the next open if the pick still checks out. It compares itself with the
**S&P 500** (the 500 biggest US companies) in the Sunday report, since that's the fair yardstick for stocks.

Honest caveats: research has found that insider buying has, on average, been followed by slightly better than
normal returns, but it's a small edge, it's an average over thousands of trades, and some years it doesn't work.
A few weeks of results on $100 will mostly be luck either way.

**Setup:** make a third Alpaca paper account named "Copycat" with $100 (same as step 1 below), then add its keys as
two more GitHub secrets, `ALPACA_COPYCAT_KEY_ID` and `ALPACA_COPYCAT_SECRET_KEY` (same as step 3 below).
Then add one more **secret** the same way: name `SEC_CONTACT_EMAIL`, value: an email address you check.
The SEC requires every program that reads its filings to say who's asking, and it refuses GitHub's "noreply"
addresses. Keep it a secret, not a variable: this repo is public, and GitHub prints variables in the run logs.
Until the Copycat secrets exist, Copycat is simply skipped and the other two keep running.

## The Forex wing (currency trading, practice money)

Forex means trading one country's money for another's, like euros for US dollars. Prices are quoted as
**currency pairs**: EUR/USD at 1.10 means 1 euro costs $1.10. You can bet a pair goes up (buy) or down
(sell first and buy back later, called **selling short**). Alpaca has no forex, so this wing uses
**OANDA practice (demo) accounts**: free, real prices, pretend money. The code only talks to OANDA's practice
address, so it can't place a real-money trade.

| | Forex office ([config/forex.yaml](config/forex.yaml)) | Copycat FX office ([config/fxcopy.yaml](config/fxcopy.yaml)) |
|---|---|---|
| Idea | Follow the trend (the 1980s "Turtle traders" rule) | Copy the big hedge funds' currency bets |
| Gets in when | a pair closes above its 55-day high and above its 200-day average (buy), or below its 55-day low and below the average (sell) | hedge funds' net bet on a currency is 10%+ of all open contracts in the CFTC's weekly report |
| Gets out when | it closes past the opposite 20-day high or low, or the safety stop is hit | their net bet flips to the other side, or the safety stop is hit |
| Safety stop | 2 typical daily swings away | 3 typical daily swings away |
| Pairs | EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, NZD/USD | same |
| Decides | once a day, after the forex day ends at 5pm New York time | same (the report comes out Fridays) |
| Loss limits | 3% daily, 15% total | 3% daily, 15% total |
| AI | none | none |

**Sizing with $100.** Forex trades are measured in **units** of currency. A "standard lot" is 100,000 units,
a "micro lot" is 1,000. OANDA lets us trade any number of units, even 1, so $100 works. Each trade is sized
so that hitting the safety stop loses about **1% of the account** ($1 on $100). Example: EUR/USD at 1.10
usually swings about 0.006 a day, so the stop goes 0.012 away, and $1 / 0.012 = about **83 units**
(controlling about $91). Hard limits on top: one trade controls at most 1x the account, and all trades together
at most **3x** (3:1 **leverage**; US rules allow up to 50:1, which is how beginners blow up accounts). At most 4
trades open, and at most 3 that win or lose together when the US dollar moves. OANDA holds the stop, so it
fills even between the bot's 30-minute checks.

**Why copy the CFTC report and not a copy-trading site?** Sites like Myfxbook, MQL5 Signals, ZuluTrade or
cTrader Copy rank traders by past returns, but: accounts that blew up quietly disappear from the rankings
(survivorship bias); many top "signals" use risky grid or doubling-down systems that look smooth until one
bad week wipes them out; the track records are short and hand-picked; and none of them offers a free API to
read another trader's trades (copying only works inside their own apps, at their partner brokers). The CFTC
report is official, free, has 20+ years of history so the lab can test it, and says exactly whose bets we copy.
The catch: it's weekly and about 3 days late (Tuesday's positions are published Friday), so we copy slow,
big bets, not quick trades. Research on following these positions is mixed: big speculators often just follow
the trend themselves.

**Testing.** The strategy lab replays both offices over the last **8 years** of daily prices (from OANDA once
its key is saved, otherwise free from Dukascopy), charging the spread (the buy/sell gap, at least OANDA's typical one), half a pip of
slippage per trade, and overnight interest (the real gap between the two countries' central bank rates, from the
BIS, plus about 2% a year that OANDA keeps). It's compared with **doing nothing** (keeping the cash).

**Results so far (Oct 2018 to Oct 2026, $100 start): every rule failed, so both offices are switched off**
(`enabled: false` in their configs; dry runs still work):

| Rule | $100 became | Unseen months | Why it failed |
|---|---|---|---|
| Trend breakout (Forex office) | $39 | -35% | loses even with zero fees; most breakouts reversed |
| Copy hedge funds (Copycat FX office) | $90 | -7% | about break-even before fees |
| 12-month momentum (`style: momentum`) | $80 | -11% | loses before fees too |
| Carry trade (`style: carry`) | $94 | +0.7% | lost on the study years and with double fees; only 5 trades to judge |

The last two were a second try with their textbook settings fixed before the test, so the lab couldn't fish
for a lucky result.
To run the check yourself: **Actions → Strategy lab → Run workflow**, pick forex or fxcopy (leave "change" empty
and Claude suggests an improvement, like for the other strategies), or locally
`python -m tradebots.lab --strategy forex --validate`.

**Setup (about 15 minutes):**
1. Go to [oanda.com](https://www.oanda.com), pick your country, and choose the free **demo (practice)**
   account, not "Open a live account". No money or ID is needed for demo. If you applied for a live account by
   mistake, that's fine: don't deposit anything, and use the demo side of the same login. The bots can't use a
   live account anyway.
2. In the OANDA hub ([hub.oanda.com](https://hub.oanda.com)), the badge next to your initials in the top
   right says **LIVE** or **DEMO**. Click it and switch to **DEMO**; everything below happens there. Create a
   second demo sub-account, so you have two: name one
   "Forex" and one "Copycat FX". If it lets you choose or reset the balance, pick the smallest it allows.
   (Either way, each office acts as if it had $100 and counts only its own gains and losses.)
3. Write down each sub-account's **account number** (it looks like `101-001-1234567-001`).
4. Go to **Manage API Access** (in the hub's tools or profile menu) and click **Generate** to make an API
   token, while the badge still says **DEMO**. A token made on the live side won't work. One token works
   for both practice sub-accounts. OANDA shows it once.
5. In GitHub, add 3 **secrets** (Settings → Secrets and variables → Actions → New repository secret; the name
   and the value are two separate boxes): `OANDA_API_TOKEN` (the token), `OANDA_FOREX_ACCOUNT_ID` and
   `OANDA_FXCOPY_ACCOUNT_ID` (the account numbers). Never paste the token into chat.
6. Try it: **Actions → Trade (paper) → Run workflow**, pick `forex`, tick Dry run. Until the secrets exist,
   the Forex wing is simply skipped and everything else keeps running.

**Going live with real money** is not built in on purpose. That's a decision for after a few months of
practice results, and it would need a separate change you approve.

## Timer (why the runs happen on time)

GitHub's built-in schedule skipped most runs on this repo (on October 25, 2026 only 5 of about 38 ran).
So the **Timer** workflow keeps the beat instead: it starts **Trade (paper)** every 30 minutes, and every 5.5 hours
it hands over to a fresh copy of itself. GitHub's schedule is still there as a backup. Start it once with
**Actions → Timer → Run workflow**. To stop it: **Actions → Timer → ⋯ → Disable workflow**.

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
In this repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add these secrets, using exactly these names:

| Secret name | Value |
|---|---|
| `ALPACA_AGGRESSIVE_KEY_ID` | Key ID from the Aggressive paper account |
| `ALPACA_AGGRESSIVE_SECRET_KEY` | Secret from the Aggressive paper account |
| `ALPACA_MEDIUM_KEY_ID` | Key ID from the Medium paper account |
| `ALPACA_MEDIUM_SECRET_KEY` | Secret from the Medium paper account |
| `ALPACA_COPYCAT_KEY_ID` | Key ID from the Copycat paper account (optional, see above) |
| `ALPACA_COPYCAT_SECRET_KEY` | Secret from the Copycat paper account (optional, see above) |
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `OANDA_API_TOKEN`, `OANDA_FOREX_ACCOUNT_ID`, `OANDA_FXCOPY_ACCOUNT_ID` | OANDA practice token and account numbers (optional, see the Forex wing) |

### 4. Turn it on
1. Merge the pull request. The schedule only starts once the code is on `main`.
2. Do a test first: go to **Actions → Trade (paper) → Run workflow**, tick **Dry run**, and click Run. A dry run does all the thinking but places no orders.
3. After that it runs by itself every 30 minutes.

## Checking results

- **After each run:** go to **Actions → Trade (paper)** and click a run. The page shows the account value, the money you put in, profit or loss, and what each bot thought about every coin it looked at.
- **Every Sunday:** a **Weekly bot report** issue shows up in the repo's **Issues** tab (GitHub also emails you). It shows how each strategy did that week and since the start, next to what you'd have if you had just bought Bitcoin with the same money. Old reports are kept in `bot-data/weekly/`. To get one right now: **Actions → Weekly report → Run workflow**.
- **History:** the `bot-data` branch has a folder for each strategy with `summary.md` (latest run), `trades.csv`, `decisions.csv`, `deposits.csv` and `equity.csv`.

Profit is always measured as **account value minus the money you put in**, so adding money never looks like a gain. The "time-weighted return" also ignores when deposits happened, which makes it the fair number for comparing the two strategies.

## Bot World page and daily recap

After every run, the bots rebuild a web page called **Bot World HQ**: a 90s pixel-art space station seen from above, like a floor plan.

- **The Trading Wing** holds one office per account, side by side: Aggressive (light-blue denim crew), Medium (dark-blue denim crew) and Copycat (black denim crew). Each office has six walled rooms, one per bot, with big wall screens showing the real numbers from that account's last run (Scout's scanner and radar, Charts' trade plan, News' headlines, Sentiment's mood gauge, Risk's limits, Decision's BUY / WAIT / SKIP board).
- **The bots walk.** They get up from their desks to check their screens, and walk to the door when the courier arrives. Bots with nothing to do this run doze at their desk. Each desk has a name plate with the bot's level (it grows with every run and every trade it works on) and a timer since the crew's last run.
- **Shared rooms:** the Captain (a chrome villain titan in black and red) sits in the throne room, and the beam room shows the whole wing's value. Cables run from every bot into its office's Decision room, and a gold cable runs from each Decision room to the beam.
- **The Forex Wing** (top left) has two smaller offices with three rooms each (spotter, Risk, Decision): Forex
  (green denim crew) and Copycat FX (plum denim crew), plus world clocks for Tokyo, London and New York.
- **Room to grow:** one more wing sits dark, with boxes and cobwebs, waiting for a future business.
- **Crew list:** the panel on the left lists every bot, whether it's working or idle, what it said on the last run, and the time since that run. Click a bot to fly to it.
- **Moving around:** drag to move, scroll or pinch to zoom, click a room or a bot to fly to it, and press **Zoom out** to see the whole station. On a phone, the crew list sits under the map.

The page also shows the chosen bot's full report, a replay of the last run, the account value chart, recent trades, and a **daily recap** written for beginners (a short description, then key-takeaway bullets, plus a "Words to know" list). There is no chat box, because the page is public.

- **Where:** your GitHub Pages address, `https://quincith.github.io/trading-bots/` (after the one-time setup below).
- **Effects:** a green laser out of the beam room and a party on a winning trade, tomatoes on a losing one. Use the **Win / Loss / Buy** buttons under the map to show them off any time. Sound is off until you press **Sound**.
- **Accounts:** the switch at the top picks which office you're watching (it glows gold) and flies the camera there.
- **Recaps as files:** `recaps/<date>.md` and `recaps/latest.md` on the `bot-data` branch.
- **Without Pages:** the same page is saved as `world/index.html` on the `bot-data` branch. Download it and open it in a browser.

One-time setup: the repository must be **public** (GitHub Pages is free only for public repositories), then go to **Settings → Pages → Build and deployment → Source** and pick **GitHub Actions**. The page appears after the next run.

The characters are original designs. They aren't copies of any movie characters, so the page is safe to share.

## Backtest (how would it have done last year?)

**Actions → Backtest → Run workflow** replays both strategies over the past year of prices, with trading fees, and compares them with simply buying and holding Bitcoin. It takes about 15–30 minutes. The report shows on the run page and is saved on the `bot-data` branch in `backtest/summary.md`.

- **Part 1** runs the real bot code every 30 minutes of the year against a pretend $100 account. Claude isn't used here, because asking it ~20,000 times would cost too much, so News, Sentiment and Decision use their simple rules.
- **Part 2** picks a few dozen of those moments at random and asks both Claude Opus (what the bots use now) and Claude Haiku (much cheaper) to decide, then plays each chosen trade forward to see how it ended. This shows whether Claude beats the rules and whether Haiku is good enough. It spends real Claude money, capped at $4 by default; set the sample to 0 to skip it.

Limits: Reddit chatter has no history, so Sentiment only sees the Fear & Greed index. Claude may remember news from before its training cutoff, so Part 2 only uses moments from July 2026 on.

## Strategy lab (keep only what works)

The backtest showed both crypto strategies losing money, so the bots now have a lab that looks for improvements and only keeps the ones that hold up. **Every Sunday** (after the weekly report), **Actions → Strategy lab** does this for each strategy:

1. **Observe:** replay the current version over the "study months" (the first 60% of the past year).
2. **Diagnose and suggest:** Claude reads every trade from those months: what the market looked like when it bought and how the trade ended. It names the pattern behind the losses (for example "most losses came when Bitcoin itself was falling") and suggests **one** change from a fixed menu of settings. It also sees every idea tried before, so it doesn't repeat rejected ones.
3. **Test honestly:** the lab replays the change, with fees and price slip, and keeps it only if it passes **every** check:
   - better than the current version by at least 1 point on the **unseen months** (the last 40% of the year, which Claude was never shown),
   - not worse in more than one of the 5 month-long slices of those months, so one lucky stretch can't carry it,
   - still better with fees and slip doubled,
   - still better when each new number is nudged one step up or down (a number that only works at one exact value is probably luck, which traders call "overfitting"),
   - beats the yardstick on the unseen months: just holding Bitcoin (for Copycat, the S&P 500),
   - enough trades to judge (10, or 8 for Copycat), no deeper losing streak, and not worse on the study months either.
4. **You decide:** a change that passes becomes a **pull request** that edits the strategy's config file. **Nothing changes until you merge it.** Merge to switch it on for that paper account, or close it to say no. Rejected ideas are just logged.

You get one issue each Sunday ("Strategy lab <date>") saying what was tried and why it was kept or rejected, and the weekly report lists the week's experiments. Every experiment is logged on the `bot-data` branch in `lab/experiments.csv`, with a full report per experiment in `lab/reports/`.

**Test your own idea:** Actions → Strategy lab → Run workflow, pick a strategy and type the change, for example `filters.btc_ema_bars=200` (two changes: `scout.min_rsi=54 scout.max_rsi=72`). Use `off` to switch a filter off.

What the lab can change (loss limits and bet sizes are yours, so it never touches those):

| Setting | Meaning |
|---|---|
| `scout.min_volume_ratio`, `scout.min_move_pct` | how unusual the volume and the price move must be |
| `scout.min_rsi`, `scout.max_rsi` | the momentum window (RSI) Scout accepts |
| `charts.stop_atr_mult`, `charts.min_reward_risk` | how far away the safety exit is, and how big the profit goal must be compared with the risk |
| `exits.max_hold_hours`, `exits.move_stop_to_breakeven_at_r` | when to give up on a trade, and when to move the stop to the entry price |
| `filters.max_atr_pct` | skip coins that swing too wildly |
| `filters.trend_ema_bars` | only buy coins in an uptrend (above their N-candle average) |
| `filters.btc_ema_bars` | only buy when Bitcoin itself is above its N-candle average (a healthy market) |
| `filters.min_fear_greed`, `filters.max_fear_greed` | skip days of panic or greed |
| Copycat: `copycat.min_buy_usd`, `min_insiders`, `min_score`, `max_signal_age_days`, `max_chase_pct`, `stop_pct`, `target_pct`, `exits.max_hold_hours` | which insider buys to copy, and its exits |

**One-time setup** so the bot can open the pull requests itself: **Settings → Actions → General → Workflow permissions**, tick **Allow GitHub Actions to create and approve pull requests**, and Save. (The bot never approves or merges anything; only you do.) Without it, the issue gives you a one-click link to open the pull request yourself.

Good to know:
- The lab tests the rule-based versions of News, Sentiment and Decision (like the backtest). Claude still makes the live calls; the lab's changes are to the parts before and after Claude (Scout, Charts, the filters, the exits), which work the same either way.
- Copycat's past insider buys come from the SEC's free quarterly files, which appear a few weeks after each quarter ends, so its lab stops at the newest file. It replays one trading day at a time (buying at the open), while the live bot checks every 30 minutes, so prices differ a little.
- Trying many ideas on the same months makes a lucky pass more likely, even with these checks. The report says how many ideas were already tested on the same months, and a kept change still has to prove itself on paper before any real money.
- Cost: one Claude Opus call per strategy per week, a few cents.

## Buttons you might need

All of these are under **Actions → Control panel → Run workflow**:

- **Log a deposit / withdrawal:** record money you add or take out. The first run records the starting balance automatically. (Alpaca can't deposit into paper accounts, so to simulate adding money, reset the paper balance in Alpaca and log the difference here.)
- **Close all positions:** sell everything in one strategy's account right away.
- **Resume after a loss-limit halt:** restart a strategy that hit its total loss limit.

**Kill switch:** go to **Settings → Secrets and variables → Actions → Variables → New repository variable**, name it `TRADING_HALTED` and set it to `true`. All strategies stop opening trades, but they keep managing exits on the trades already open. Set it to `false` to resume.

## Changing settings

Open `config/aggressive.yaml`, `config/medium.yaml` or `config/copycat.yaml` on GitHub, click the pencil icon, edit, and commit. Every line has a comment. Useful ones:
- `stocks: [NVDA, AMD]` adds stocks. They're only traded while the US market is open.
- `max_daily_loss_pct` / `max_total_loss_pct` are the loss limits.
- `model` sets which Claude model the bots use.

## Costs

- **Claude:** Claude is only asked when Scout and Charts find a real setup, and then it makes up to 3 calls. The October 2026 backtest measured about $0.008 per call on `claude-opus-5-5`, which over a year of setups comes to roughly $18 a year (about $1.50 a month) for both strategies together. `claude-haiku-5-5` measured about $0.0002 per call, under $1 a year. Busier markets mean more setups and more calls.
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

Code map: `tradebots/bots/` (one file per bot), `tradebots/pipeline.py` (runs the team), `tradebots/copycat.py` and `tradebots/sec.py` (Copycat and the SEC insider feed; `python -m tradebots copycat-preview` shows the latest insider buys with no keys), `tradebots/alpaca.py` (paper broker and market data), `tradebots/ai.py` (Claude), `tradebots/store.py` (memory and deposit-adjusted returns), `tradebots/backtest.py` (replay over past prices), `tradebots/lab.py` (strategy lab checks; `python -m tradebots.lab --strategy medium --set filters.btc_ema_bars=200` tests one change), `tradebots/improve.py` (weekly loop with Claude), `tradebots/insider_history.py` (past SEC insider buys for Copycat), `tradebots/bots/filters.py` (optional entry filters).
