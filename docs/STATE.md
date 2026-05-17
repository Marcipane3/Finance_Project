# STATE — Portfolio Optimization Project

*Last updated: 2026-05-17 (Track B spec'd)*
*Always update the "Now" section at the end of each working session.*

## What this project is

A Python rebuild of Marcel's DTU master thesis (co-authored with João Pedro Estudante Romeiro, supervised by Stefan Røpke). Original thesis combined fundamental-score filtering + Monte Carlo return modeling + MILP-CVaR optimization with monthly rebalancing and transaction costs, applied to the S&P 500.

Two tracks, formally separated:

- **Track A — Synapse-style.** Slow, monthly, fundamentals-filtered, MILP-CVaR. Capital sleeve: ~90%.
- **Track B — Fast Ideas.** Bi-weekly recommendation engine for higher-risk medium-term swing trades on a global universe. Capital sleeve: ~10%. Output is a watchlist, not a trade bot.

## What was in the thesis (the inheritance)

### Findings worth carrying forward
- **In-sample 2015–2019** with TC, F-Score 8, MVN, μ₀=0.0375, β=0.15: 128% total return (Sharpe 1.214) vs S&P 500 74% (Sharpe 0.809). p=0.0296 one-sided.
- **Out-of-sample 2020–2024**: G-Score 7 → 158%, F-Score 8 → 130%, S&P 500 → 99.3%.
- Best fixed parameters from the thesis sweep: μ₀=0.0375, β=0.15, MVN return model, F-Score 8 or G-Score 7.
- GARCH variants (cDCC, DCC, gjrGARCH) **underperformed** plain MVN at low μ₀ and were **infeasible** at the thesis-best μ₀ because the F-Score-8 filter leaves too few names.
- Statistical significance: F8 vs S&P combined-period Wilcoxon p=0.0482.

### Constraints to revisit (NOT carried forward unquestioned)
- Capital = $10k (academic assumption — real number TBD)
- Min/max weight = 1%/10% (scales with capital)
- Cardinality 10–30 assets (scales with capital + frequency)
- Monthly rebalance (scores are quarterly — likely Pareto-dominated by quarterly)
- 50/50 return/Sharpe scoring (open to shifting toward return — Marcel is OK with higher risk)
- Revolut fee structure ($1 fixed + 0.25% variable — depends on real broker)

## Real-world setup (locked 2026-05-17)

| Item | Value | Notes |
|---|---|---|
| Capital — Track A | €23,000 (~DKK 174,200) | Capped by Aktiesparekonto 2026 deposit ceiling. Original target €25k → ~€2k overflow goes to Track B sleeve. |
| Capital — Track B | €2,000–2,500 | "Fun money" sleeve in a regular handelskonto (taxed 27/42% on realized gains). |
| Account type | Aktiesparekonto (ASK) at Nordea | 17% lager-beskatning, annual mark-to-market. Turnover is tax-neutral inside ASK; only broker fees matter for trading-frequency questions. |
| Broker fees (Nordea, non-Nordic stocks) | 0.20% commission, min DKK 29 (~€3.90), + 0.25% FX margin | Round-trip on a €1000 US-stock trade ≈ €13 ≈ 1.3%. Roughly 2× the thesis's Revolut assumption. |
| Investable instruments | Stocks + equity-based funds/ETFs on a regulated market | US listings (NYSE/NASDAQ) qualify. |

## What we're building (MVP — v0.1)

End-to-end Python pipeline that:
1. Pulls S&P 500 membership (current snapshot first; point-in-time on backlog)
2. Fetches daily prices and quarterly + annual fundamentals from yfinance
3. Computes F-Score (threshold 8) per reporting period per stock
4. Estimates 5-year rolling sample mean and covariance, simulates 5000 forward returns under MVN
5. Solves MILP-CVaR (cvxpy + HiGHS, no Gurobi) with TC
6. Backtests two rebalance cadences in parallel:
   - **Quarterly** (~20 rebalances over 5y, 2015–2019)
   - **Yearly** (~5 rebalances over 5y) — primary candidate given data quality + fees
7. Comparison against thesis monthly baseline as a sanity check

Parked for later (see BACKLOG.md): G-Score, QMJ-Score, monthly rebal (the thesis baseline is just a reference, not a target), EWMA / Student-t / GARCH return models, regime switching, sector caps, momentum tilt, point-in-time S&P 500 membership, broader universes.

## Optimizer parameter spec (v0.1)

| Parameter | Value | Rationale |
|---|---|---|
| Universe | S&P 500 (current snapshot) | Thesis baseline; PIT membership on backlog |
| Filter | F-Score, threshold 8 | Thesis primary; G/QMJ on backlog |
| Return model | MVN, 5y daily lookback, 5000 sims | Thesis best performer |
| Forecast horizon | 1 quarter (~63 days) for quarterly, 1 year (~252 days) for yearly | Match rebalance cadence |
| μ₀ (min expected return) | Sweep — see below | Thesis showed this is the dominant parameter |
| β (CVaR tail level) | 0.10 fixed | Thesis showed β has modest effect; pin it |
| Cardinality | 10–30 stocks | Marcel's manageability ceiling |
| Min weight | 3.04% (€700 of €23k) | Marcel's minimum meaningful position |
| Max weight | 10% | Diversification floor; thesis baseline |
| Fixed fee per trade | DKK 29 ≈ €3.90 | Nordea minimum |
| Variable fee per trade | 0.20% commission + 0.25% FX = 0.45% | Round-trip ~0.9% (FX paid once each way on the cash leg) |

**μ₀ sweep (annualized):** {0%, 5%, 10%, 15%, 20%, 25%, 30%}. Note this is annual — for monthly horizon the per-month equivalent is 1/12 of these. Sweep produces a Pareto frontier of return vs. drawdown; we pick from inspection rather than auto-tuning.

## Track B — Fast Ideas spec (locked 2026-05-17)

**Purpose.** Bi-weekly recommendation engine for higher-risk, medium-term-hold (weeks to 3–4 months) single stocks on a global universe. Manual execution; agent suggests, Marcel decides. Capital sleeve: €2k–2.5k. Aspirational target: 40% annual (acknowledged as ceiling-of-ceiling; realistic median outcome closer to 10–15%).

**Universe.** Constituents of S&P 500 + STOXX 600 + Nikkei 225 + FTSE 100 + ASX 200, deduped, filtered to liquid names (>$5M ADV) with yfinance coverage. ~1,400–1,600 names.

**Run cadence.** Fixed bi-weekly. Output: a long-form markdown report saved to `/track_b_fast/output/YYYY-MM-DD_report.md`. ~2,000 words covering 5 ranked picks with full thesis per name + BUY/KEEP/SELL diff vs. current holdings.

**Pipeline.**

| Stage | Input | Output | Purpose |
|---|---|---|---|
| 1. Pre-filter | ~1,500 names | ~50 candidates | Cheap composite rank: momentum + earnings surprise + news/analyst movement |
| 2. Deep-dive | ~50 candidates | ~15 ranked | Pull technical + fundamental + news + sentiment + analyst data per name |
| 3. Thesis writer | ~15 ranked | 5 picks with full theses | Claude API call to write 300–500 word thesis per name (setup, bull case, risks, why now) |
| 4. Holdings diff | 5 picks + `holdings.csv` | BUY/KEEP/SELL list | Compare ranked picks to current positions |
| 5. Report | All above | Markdown report | Saved to dated file, history retained for retrospective learning |

**Position sizing.** Rank-weighted, sums to 100% of sleeve. Default schema: 30/25/20/15/10. Bottom ranks can be assigned 0% if confidence below threshold.

**Stop-loss.** -10% from entry. Daily price-check script flags breaches. v0.1: included in bi-weekly report. v0.2: separate daily alert.

**Holdings file.** Manual `holdings.csv`: `ticker, shares, entry_price, entry_date, current_stop_price`. Marcel updates after each trade.

**LLM costs.** Negligible (~$4/year for Claude Sonnet API calls).

**Account.** TBD — pending broker decision (see B6 in BLOCKERS). Three options on the table:
1. New Saxo Bank or Nordnet ASK + close Nordea ASK (only one ASK allowed per person)
2. Track B inside same Nordea ASK as Track A (tax-neutral on trades; fee-burdensome)
3. Track B in regular Nordea handelskonto (tax 27/42% on realized gains, plus fees)

Fee math at Nordea is severe for bi-weekly rotation — see DECISIONS 2026-05-17 entry.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Single language; you said you're fast with Claude Code in Python |
| Data | yfinance + SimFin community (fallback: SEC EDGAR) | Free, no WRDS dependency |
| Optimizer | cvxpy + HiGHS (or pulp + HiGHS) | Free MILP, MIT license, no Gurobi |
| Numerics | numpy, pandas, scipy | Standard |
| Plotting | matplotlib, plotly for dashboards | Standard |
| Storage | parquet for time series, sqlite for fundamentals | Lightweight, no server |
| Runtime | Marcel's laptop, overnight runs OK | Local-only, no HPC |

## Repository layout (target)

```
/track_a_synapse/
  data_pipeline/   # Universe, prices, fundamentals
  scores/          # F-Score (G/QMJ parked)
  returns/         # MVN simulator (EWMA/t/GARCH parked)
  optimizer/       # MILP-CVaR with TC + retries
  backtest/        # Rolling loop, metrics, tear sheets
  live/            # (later) monthly recommendation generator
/track_b_fast/     # (later)
  signals/
  screener/
  ranker/
/shared/
  data/            # raw + processed; gitignored, DVC later if needed
  utils/           # date utilities, broker fee models
docs/
  STATE.md
  DECISIONS.md
  BACKLOG.md
  BLOCKERS.md
```

## Now (current session focus)

- Track A real-world parameters **locked** (2026-05-17)
- Track B spec **locked** (2026-05-17)
- **Open:** Marcel decides on broker for Track B (new Saxo/Nordnet ASK vs. stay at Nordea — see B6)
- **Next session:** start coding. Open question: Track A data pipeline first (deeper foundation) or Track B prototype first (faster dopamine, builds reusable infra)?

## Open blockers

See BLOCKERS.md.
