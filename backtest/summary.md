# Backtest: 2025-10-25 to 2026-10-25 (365 days)

Each line starts with $100.00. Trading fees (0.25% per buy or sell) and 0.05% slippage are included. Bots are checked every 30 minutes, like the live ones.

## 1. Full replay with the rule-based bots

| | End value | Return | Worst drop from a high | Worst day | Trades | Wins | Fees paid |
|---|---|---|---|---|---|---|---|
| Aggressive bots | $59.68 | -40.3% | -40.3% | -2.8% | 137 | 18% | $18.58 |
| Aggressive, never stopped | $40.69 | -59.3% | -59.3% | -3.1% | 406 | 30% | $40.99 |
| Medium bots | $84.76 | -15.2% | -15.4% | -1.7% | 67 | 27% | $7.81 |
| Medium, never stopped | $86.41 | -13.6% | -20.3% | -4.1% | 143 | 31% | $16.00 |
| Just hold Bitcoin | $72.54 | -27.5% | -49.8% | -12.2% | - | - | $0.25 |
| Hold all 8 coins | $55.62 | -44.4% | -63.3% | -13.4% | - | - | $0.25 |

**Aggressive bots hit its total loss limit on 2026-03-13** (Total loss -40.0% hit the 40% limit) and stopped trading, as the live bot would until you press Resume. The "never stopped" line shows what would have happened if it had kept going.

**Medium bots hit its total loss limit on 2026-05-22** (Total loss -15.1% hit the 15% limit) and stopped trading, as the live bot would until you press Resume. The "never stopped" line shows what would have happened if it had kept going.

Month-end values:

| Month | Aggressive bots | Aggressive, never stopped | Medium bots | Medium, never stopped | Just hold Bitcoin | Hold all 8 coins |
|---|---|---|---|---|---|---|
| 2025-10 | $95.86 | $95.86 | $98.83 | $98.83 | $98.39 | $96.84 |
| 2025-11 | $81.56 | $81.56 | $97.81 | $97.81 | $81.44 | $77.21 |
| 2025-12 | $76.70 | $76.70 | $94.59 | $94.59 | $78.61 | $70.09 |
| 2026-01 | $68.13 | $68.13 | $95.68 | $95.68 | $70.84 | $59.26 |
| 2026-02 | $65.72 | $65.72 | $95.26 | $95.26 | $60.08 | $50.91 |
| 2026-03 | $59.68 | $58.04 | $91.94 | $91.94 | $61.25 | $50.85 |
| 2026-04 | $59.68 | $54.92 | $86.35 | $86.35 | $68.53 | $53.78 |
| 2026-05 | $59.68 | $51.97 | $84.76 | $84.43 | $66.19 | $51.64 |
| 2026-06 | $59.68 | $48.39 | $84.76 | $82.40 | $52.56 | $40.50 |
| 2026-07 | $59.68 | $46.85 | $84.76 | $79.89 | $56.50 | $42.79 |
| 2026-08 | $59.68 | $48.37 | $84.76 | $88.41 | $70.55 | $54.09 |
| 2026-09 | $59.68 | $43.99 | $84.76 | $88.30 | $75.09 | $64.52 |
| 2026-10 | $59.68 | $40.69 | $84.76 | $86.41 | $72.54 | $55.62 |

## 2. Claude cost for a year

How often each strategy found a setup over the year (that is when the live bots ask Claude), times the cost per call measured in part 3.

| | Setups found | Claude calls | Opus per year | Haiku per year |
|---|---|---|---|---|
| Aggressive bots | 545 | 1465 | $11.17 | $0.29 |
| Medium bots | 331 | 841 | $6.41 | $0.17 |

## 3. Claude check: Opus vs Haiku vs rules

30 moments picked at random from 279 setups after 2026-07-01. Each trade a bot chose to take was played forward with the real stop, target and time limit. Claude spend for this check: $0.38.

| Who decides | Trades taken | Winners | Avg result per trade | Claude calls | Cost of this check | Cost per call |
|---|---|---|---|---|---|---|
| Claude Opus 5.5 (current) | 8 | 3 | -0.36% | 49 | $0.37 | $0.01 |
| Claude Haiku 5.5 | 0 | 0 | +0.00% | 49 | $0.01 | $0.00 |
| Rules only (no Claude) | 36 | 15 | -0.01% | 0 | $0.00 | - |
| Take every setup | 47 | 16 | -0.38% | - | - | - |

Opus and Haiku made the same take/skip call on 83% of setups.

## What this can't tell you

- Part 1 uses the rule-based bots for the whole year. The live bots use Claude, and part 3 is how we check whether Claude does better or worse than the rules.
- Reddit mention counts have no history, so Sentiment only sees the Fear & Greed index here.
- Part 3 is a small sample. A few lucky or unlucky trades can swing it.
- Past prices don't predict future prices.
