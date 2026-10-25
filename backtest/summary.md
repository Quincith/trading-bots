# Backtest: 2025-10-25 to 2026-10-25 (365 days)

Each line starts with $100.00. Trading fees (0.25% per buy or sell) and 0.05% slippage are included. Bots are checked every 30 minutes, like the live ones.

## 1. Full replay with the rule-based bots

| | End value | Return | Worst drop from a high | Worst day | Trades | Wins | Fees paid |
|---|---|---|---|---|---|---|---|
| Aggressive bots | $59.68 | -40.3% | -40.3% | -2.8% | 137 | 18% | $18.58 |
| Medium bots | $84.76 | -15.2% | -15.4% | -1.7% | 67 | 27% | $7.81 |
| Just hold Bitcoin | $72.54 | -27.5% | -49.8% | -12.2% | - | - | $0.25 |
| Hold all 8 coins | $55.62 | -44.4% | -63.3% | -13.4% | - | - | $0.25 |

**Aggressive bots hit its total loss limit** on 2026-03-13: Total loss -40.0% hit the 40% limit. and stopped trading (the live bot would wait for you to press Resume).

**Medium bots hit its total loss limit** on 2026-05-22: Total loss -15.1% hit the 15% limit. and stopped trading (the live bot would wait for you to press Resume).

Month-end values:

| Month | Aggressive bots | Medium bots | Just hold Bitcoin | Hold all 8 coins |
|---|---|---|---|---|
| 2025-10 | $95.86 | $98.83 | $98.39 | $96.84 |
| 2025-11 | $81.56 | $97.81 | $81.44 | $77.21 |
| 2025-12 | $76.70 | $94.59 | $78.61 | $70.09 |
| 2026-01 | $68.13 | $95.68 | $70.84 | $59.26 |
| 2026-02 | $65.72 | $95.26 | $60.08 | $50.91 |
| 2026-03 | $59.68 | $91.94 | $61.25 | $50.85 |
| 2026-04 | $59.68 | $86.35 | $68.53 | $53.78 |
| 2026-05 | $59.68 | $84.76 | $66.19 | $51.64 |
| 2026-06 | $59.68 | $84.76 | $52.56 | $40.50 |
| 2026-07 | $59.68 | $84.76 | $56.50 | $42.79 |
| 2026-08 | $59.68 | $84.76 | $70.55 | $54.09 |
| 2026-09 | $59.68 | $84.76 | $75.09 | $64.52 |
| 2026-10 | $59.68 | $84.76 | $72.54 | $55.62 |

## 2. Claude cost for a year

How often each strategy found a setup (that is when the live bots ask Claude), times the cost per call measured in part 3.

| | Setups found | Claude calls | Opus per year | Haiku per year |
|---|---|---|---|---|
| Aggressive bots | 247 | 662 | $26.48 | $0.66 |
| Medium bots | 186 | 471 | $18.84 | $0.47 |

_Cost per call is an estimate because the Claude check did not run._

## 3. Claude check: Opus vs Haiku vs rules

Did not run (no Claude key, or no setups after the sample start date).

## What this can't tell you

- Part 1 uses the rule-based bots for the whole year. The live bots use Claude, and part 3 is how we check whether Claude does better or worse than the rules.
- Reddit mention counts have no history, so Sentiment only sees the Fear & Greed index here.
- Part 3 is a small sample. A few lucky or unlucky trades can swing it.
- Past prices don't predict future prices.
