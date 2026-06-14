# STATE — Portfolio Optimization Project

*Last updated: 2026-06-14 (cockpit live on GitHub Pages; NL-4/5/6 done; brokerage = consolidate to Saxo)*
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

## Track B — Fast Ideas spec (locked 2026-05-17, monthly 1-pick variant)

**Purpose.** Monthly single-stock recommendation engine for higher-risk, medium-term holds (weeks to 3–4 months) on a global universe. Manual execution; agent suggests, Marcel decides. Capital sleeve: ~€2k, 100% in the current pick. Aspirational target: 40% annual (realistic median outcome closer to 10–15%).

**Why monthly 1-pick (not bi-weekly 5-pick).** Fee math: at Nordea, full rotation costs ~7% of sleeve/year at this cadence vs. 30–74% at bi-weekly multi-pick. One pick forces commitment, sharpens the learning loop, halves the code. Always fully invested (or in cash if stop-loss triggered).

**Universe.** Constituents of S&P 500 + STOXX 600 + Nikkei 225 + FTSE 100 + ASX 200, deduped, filtered to liquid names (>$5M ADV) with yfinance coverage. ~1,400–1,600 names.

**Run cadence.** Fixed monthly. Output: a long-form markdown report saved to `/track_b/output/reports/YYYY-MM-DD_report.md`. ~1,500–2,000 words covering one pick with full thesis + KEEP-or-ROTATE recommendation vs. current holding.

**Pipeline.**

| Stage | Input | Output | Purpose |
|---|---|---|---|
| 1. Universe load | indices | ~1,500 names | Wikipedia scraping + dedup |
| 2. Pre-filter | ~1,500 names | ~50 candidates | Cheap composite rank: momentum + earnings surprise + news/analyst movement |
| 3. Deep-dive | ~50 candidates | ~10 ranked | Pull technical + fundamental + news + sentiment + analyst data per name |
| 4. Thesis writer | top ranked | 1 pick with full thesis | Claude API call: ~1,500-word thesis (setup, bull case, risks, why now, why not the alternatives) |
| 5. Holdings diff | 1 pick + `holdings.csv` | KEEP or ROTATE | Compare new pick to current single position |
| 6. Report | All above | Markdown report | Saved to dated file, history retained |

**Position sizing.** 100% of sleeve in the current pick. Cash position only if stop-loss triggered between monthly runs.

**Stop-loss.** -10% from entry. Daily price-check script flags breach. v0.1: report includes stop-loss status. v0.2: separate daily alert.

**Holdings file.** Manual `holdings.csv`: `ticker, shares, entry_price, entry_date, current_stop_price, status` (status = held|stopped|sold). Marcel updates after each trade. Typically one active row.

**LLM costs.** Negligible (~$2/year at monthly cadence, ~10k output tokens per run).

**Account.** Stays at Nordea ASK for now. Broker-switch question deferred to backlog (not blocking).

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

## Repository layout (actual, as of 2026-06-14)

```
/track_a/             # Synapse-style: F-Score + MILP-CVaR (v0.1 COMPLETE)
  src/               # fundamentals, fscore, returns, optimizer, backtest, metrics, live, report
  tests/             # 4 test modules
  output/            # live recommendation markdown
  run.py             # CLI: --mode smoke|backtest|live
/track_b/             # Fast Ideas: monthly 1-pick engine (v0.1 COMPLETE)
  src/               # universe, fetch, prefilter, ranker, thesis, holdings, report, stopwatch
  tests/             # 5 test modules
  output/reports/    # dated monthly reports
  output/alerts/     # dated stop-loss alerts
  holdings.csv       # manual holdings (private)
  run.py             # full monthly pipeline
  daily_check.py     # stop-loss check (cron-friendly exit codes)
config.yaml           # all parameters, both tracks
docs/                 # STATE / DECISIONS / BACKLOG / BLOCKERS

# Proposed "next level" (see BACKLOG "Roadmap — proposed", pending Marcel's review):
/web/                 # static GitHub Pages cockpit (NL-1)
/.github/workflows/   # monthly + daily cron automation (NL-3)
/data/latest.json     # machine-readable contract the cockpit reads (NL-5)
```

Note: earlier target layout (`track_a_synapse/`, `/shared/`, per-stage subpackages) was
superseded by the flatter `track_a/` + `track_b/` actual layout. Cleaner; no change needed.

## Now (current session focus)

- Track A real-world parameters **locked** (2026-05-17)
- Track B spec **locked: monthly 1-pick variant** (2026-05-17)
- **`track_b/src/universe.py` — DONE (2026-05-17)**
  - Scrapes SP500 (503), STOXX600 (466), FTSE100 (100), ASX200 (200) from Wikipedia
  - Deduplicates to **1,269 unique tickers**, caches to parquet (7-day TTL)
  - Nikkei 225 skipped at first: Wikipedia has no `<table>` → fixed 2026-05-18 with BeautifulSoup list parser (see below)
  - Uses `curl_cffi` browser impersonation + retry backoff to handle Wikipedia rate limiting
- **`track_b/src/fetch.py` — DONE (2026-05-17)**
  - `fetch_prices(tickers, lookback_days, force_refresh)` → `(closes, volumes)` wide DataFrames
  - Per-ticker parquet cache at `track_b/data/cache/prices/`, 1-day TTL
  - Dead tickers (no yfinance data) get an empty marker file — no retry within TTL
  - Smoke test (20 tickers across 4 indices): 17/20 resolved, 3 STOXX600 failures (suffix mismatches, expected)
  - Cache read: 0.11s for 17 tickers × 281 days
- **`track_b/src/prefilter.py` — DONE (2026-05-17)**
  - `run_prefilter(universe, closes, config)` → top-N candidates DataFrame
  - Two-stage: vectorised momentum on all tickers → top-300 screen → threaded per-ticker signal fetch
  - Signals: momentum_12_1, momentum_1 (from closes), earnings_surprise, analyst_upgrade_30d, news_volume_30d (yfinance, 7-day cache)
  - Missing signal values filled with set median; composite score = percentile-rank-weighted sum
  - Smoke test (17 tickers): rankings sensible, news fix required (yfinance 1.3+ nests timestamp in `content['pubDate']`), cache second run 0.12s
  - Expected: non-US tickers (FTSE, ASX, STOXX600) get NaN on earnings/analyst → median fill
- **`track_b/src/ranker.py` — DONE (2026-05-17)**
  - `run_ranker(candidates, closes, config)` → top-N DataFrame with full signal set
  - Technical signals (RSI, price vs 52w high/MA50, realized vol) computed from closes — free
  - Fundamental/analyst/metadata from `yf.Ticker.info` — threaded, 1-day cache
  - Config weights added to `config.yaml` under `deep_dive.weights`
  - UK stocks: yfinance reports market_cap in GBp (pence) — thesis writer must ÷100 for GBP
  - Smoke test (17 tickers): ICG.L tops (36% analyst upside, 96% earnings growth, PE 10x); AVGO #2; full pipeline 0.49s from cache
- **`track_b/src/thesis.py` — DONE (2026-05-17)**
  - `generate_thesis(pick, alternatives, config)` → markdown string
  - Stable system prompt (analyst persona + 6 required sections) with `cache_control: ephemeral`
  - Volatile per-ticker signal block in user message: all technical, fundamental, analyst signals + runner-up list
  - Streaming via `client.messages.stream()` + `get_final_message()`, logs token usage including cache hits
  - Caches per ticker per calendar date at `track_b/data/cache/thesis/`, safe to re-run same day
  - UK market_cap pence→GBP conversion in `_fmt_market_cap`; NaN/None → "N/A" throughout
  - Smoke test: 15/15 passing (prompt builder + all formatters, no API call)
- **`track_b/src/holdings.py` — DONE (2026-05-17)**
  - `get_recommendation(pick, ranked, closes, config, holdings_path)` → dict with action/rationale/stop fields
  - Decision branches: INITIATE (no active holding), KEEP (same ticker #1), ROTATE (new top pick), ROTATE with stop-loss warning
  - Reads `track_b/holdings.csv` (schema: ticker, shares, entry_price, entry_date, current_stop_price, status=held|stopped|sold)
  - Creates empty holdings.csv if missing; handles multiple stale held-rows gracefully (uses most recent entry_date)
  - `format_recommendation(rec)` → markdown block for insertion into the report
  - P&L vs entry shown in ROTATE rationale when price data available
  - Smoke test: 12/12 passing (INITIATE/KEEP/ROTATE/stop-loss branches, rank lookup, markdown formatting)
- **`track_b/src/report.py` + `track_b/run.py` — DONE (2026-05-17)**
  - `run_pipeline(config, force_refresh)` — full orchestrator: universe → prices → prefilter → ranker → thesis → holdings diff → report
  - `_assemble()` builds the dated markdown: title + thesis sections + holdings diff + pipeline summary table + footer stats
  - Pipeline summary table: top-N ranked candidates with Score, Fwd PE, Rev Gr, EPS Gr, Analyst Upside, RSI, Mom 12m
  - `track_b/run.py` — thin CLI entry point with `--force-refresh`, `--config`, `--log-level` flags
  - `load_config()` reads `config.yaml` relative to project root
  - Assembler smoke test: 14/14 passing; full suite: **41/41 passing**
  - Output: `track_b/output/reports/YYYY-MM-DD_report.md`

## Track B v0.1 pipeline — COMPLETE

All six pipeline modules built and tested:
1. `universe.py` — Wikipedia scraper, 1,269 tickers, 7-day cache
2. `fetch.py` — yfinance prices, per-ticker parquet, 1-day cache
3. `prefilter.py` — momentum + signals, top-50, 7-day signal cache
4. `ranker.py` — technical + fundamental deep-dive, top-15, 1-day cache
5. `thesis.py` — Claude API, ~1,500-word thesis, per-ticker per-day cache
6. `holdings.py` — KEEP/ROTATE/INITIATE logic, reads holdings.csv
7. `report.py` + `run.py` — full pipeline orchestrator + CLI

**To run a full monthly pick:**
```
uv run python track_b/run.py
```

## Now (current session focus)

- Track B v0.1 pipeline **COMPLETE** (2026-05-17)
- **Four post-integration-run fixes applied (2026-05-17)**:
  1. **ranker.py — retry + backoff**: `_fetch_one_fundamental` retries 3× with 2s/4s backoff on exception; 0.5s sleep per call; max_workers reduced 10→5
  2. **ranker.py — cache validation**: `_fetch_and_cache` skips writing cache when all key financial fields (forward_pe, revenue_growth, earnings_growth, profit_margin, analyst_upside) are NaN; forces re-fetch next run
  3. **Cache cleanup**: deleted 50 all-NaN deepdive cache files; deleted universe.parquet so STOXX 600 re-scrapes with suffix mapping
  4. **universe.py — STOXX 600 suffix mapping**: `_clean_stoxx_ticker(ticker, country, exchange)` applies country→suffix (20 countries) and exchange→suffix (15 exchanges); class-share spaces → hyphens (NOVO B → NOVO-B.CO); already-suffixed tickers left as-is; 12/12 known cases verified
- All 41 tests still passing

- **`track_b/src/universe.py` — Nikkei 225 scraper DONE (2026-05-18)**
  - Replaced `NotImplementedError` with BeautifulSoup `<ul>/<li>` parser
  - Regex `TYO:\s*(\d{4,5})` extracts TSE codes; appends `.T` suffix
  - Live test: **223 tickers** returned, all `.T`, known anchors confirmed (7203.T Toyota, 9984.T SoftBank, 6857.T Advantest)
  - Universe now: **~1,492 unique tickers** (was ~1,269, +223)
  - BACKLOG Wikidata SPARQL approach was dead — wrong QID + P249 0.04% populated; documented
  - 7 offline unit tests + 41 existing = **48/48 passing**

- **`track_b/src/stopwatch.py` + `track_b/daily_check.py` — DONE (2026-05-18)**
  - `check_stop_loss(config, holdings_path)` → structured status dict (no_position / safe / breached / price_unavailable)
  - Fetches latest close via `yf.Ticker.history(period="5d")` — works outside market hours
  - `format_alert(status)` → markdown with table: price, stop, distance-to-stop, P&L vs entry
  - `save_alert(status)` → writes `track_b/output/alerts/YYYY-MM-DD.md`
  - CLI: `uv run python track_b/daily_check.py` — exit 0=safe, 1=breach, 2=price unavailable (cron-friendly)
  - Flags: `--holdings`, `--config`, `--no-save`, `--log-level`
  - 13/13 smoke tests; **61/61 total passing**

- **Five post-integration-run fixes applied (2026-05-18):**
  1. **fetch.py — suffix remapping**: `_retry_with_alt_suffixes()` tries `.MI, .PA, .DE, .L, .AS, .SW, .ST, .CO, .HE, .OL, .VI, .BR, .MC, .IR, .LS, .AT` for tickers with no data; caches under original ticker name; logs remap summary. `_SUFFIX_REMAP` module-level dict persists working suffixes for inspection.
  2. **thesis.py + config.yaml — max_tokens 2000→3500**: `max_tokens_per_pick` raised to 3500 in both code default and `config.yaml`. Truncation warning logged when `output_tokens ≥ max_tokens - 50`.
  3. **thesis.py — prompt caching fix**: `_SYSTEM_PROMPT` trimmed to role-only (~130 tokens). New `_FORMAT_INSTRUCTIONS` constant (~900 tokens) carries the detailed section guide + data interpretation notes. Placed as the first content block in the user message with `cache_control: ephemeral`. Combined system + format instructions > 1024 token threshold → caching now activates.
  4. **prefilter.py — earnings surprise NaN rate fix**: `_get_earnings_surprise` limit raised 8→12; surprise column detection checks `"surprise"` OR `"pct"` in column name (case-insensitive); manual fallback `(Reported EPS - Estimated EPS) / |Estimated EPS|` when EPS columns present but no surprise column.
  5. **prefilter.py + report.py — ADV liquidity filter**: `run_prefilter()` signature adds `volumes: pd.DataFrame`. ADV filter inserted after stage 1 momentum: `adv = (volumes.tail(30) * closes.tail(30)).mean()`; tickers below `config.track_b.universe.min_adv_usd` ($5M/day) removed before expensive signal fetch. `report.py` updated to pass `_volumes`.
- All 61 tests still passing.

- **Integration run completed + cross-listing dedup added (2026-05-18):**
  - Full pipeline: 7.8s from warm cache, pick = WDC (Western Digital)
  - ADV filter confirmed working: 53 illiquid tickers removed (1076→1023)
  - Prompt caching confirmed: `cache_write=1339` — combined system + `_FORMAT_INSTRUCTIONS` = 1339 tokens (above 1024 threshold)
  - `max_tokens=3500` confirmed: `out=1958`, Position Parameters section now complete
  - **`track_b/src/ranker.py` — cross-listing dedup added**: `_dedup_cross_listings()` runs after scoring, before top-N selection. Two passes: (1) base-ticker dedup strips exchange suffix (NEM vs NEM.AX → same base → keep higher scorer); (2) name-normalisation dedup strips "(Class X)" share-class designations (GOOGL vs GOOG → same normalised name → keep GOOGL). Removed 2 duplicates in live run. 61/61 tests passing.
  - Note: 134 STOXX600 suffix mismatches still showing — Fix 1 suffix retry will fire when price cache expires (tomorrow's run)

- **Track A v0.1 COMPLETE (2026-05-19)**

  All 5 phases built, tested, and confirmed working:

  **Phase 1 — Data foundation:**
  - `track_a/src/fundamentals.py` — `fetch_fundamentals()`: yfinance balance_sheet/income_stmt/cashflow, per-ticker parquet cache, 7-day TTL, 5 concurrent workers
  - `track_a/src/fscore.py` — full Piotroski F-Score: all 9 binary signals, filing-lag guard (90 days), `filter_by_fscore()` with threshold auto-lowering, 27 unit tests passing

  **Phase 2 — Return model:**
  - `track_a/src/returns.py` — `fetch_prices()` from 2016-01-01 (Track A's own price cache); `estimate_mvn()` 5-year rolling window, coverage filter, nearest-PD covariance; `simulate_scenarios()` MVN draw with horizon scaling + reproducible seed. 11 tests passing.

  **Phase 3 — Optimizer:**
  - `track_a/src/optimizer.py` — MILP-CVaR via cvxpy + HiGHS
  - `solve_a1()`: full rebalance, TC in objective (variable 0.45%), new_capital dilution of prev_weights
  - `solve_a2()`: buy-only, existing returns fixed as constant, allocate new_capital_frac across new stocks only; weights sum to new_capital_frac (not 1.0); mu0 applied per unit of new capital (not total portfolio). 11 tests passing.

  **Phase 4 — Backtest + metrics:**
  - `track_a/src/backtest.py` — rolling loop 2021→present; quarterly/yearly cadences; F-Score filter per rebalance date; A1 + A2 solved each period; A2 cumulative holdings marked to market; fixed TC deducted post-hoc
  - `track_a/src/metrics.py` — CAGR, Sharpe, max DD, CVaR, comparison table. 18 tests passing.
  - `track_a/run.py` — CLI with `--mode smoke|backtest|live`, `--cadence`, `--mu0`, `--new-capital`
  - Smoke test: 7 quarterly periods (2024-09 → 2026-05), A1 10–12 positions/period, all optimal, 0.4–1.6s/period
  - `requirements.txt`: cvxpy>=1.5, highspy>=1.7, scipy>=1.11 now active
  - `config.yaml`: `track_a:` section added (full parameter spec: capital, cadences, μ₀ sweep, optimizer bounds, A2 params)
  - **128/128 tests passing** (Track A + Track B)

  **Phase 5 — Live mode + report:**
  - `track_a/src/live.py` — one-shot current recommendation (A1 + A2 for today's quarter); reads `track_a/holdings.csv`; outputs markdown report to `track_a/output/live_{date}.md`
  - `track_a/src/report.py` — full backtest report: markdown comparison table + matplotlib NAV chart (normalized to 100) + Pareto frontier (CAGR vs max DD across μ₀ sweep)
  - **Live mode confirmed working (2026-05-19):** A1 optimal (11 positions, E[r]=10.9%, CVaR=13.2%, 7.1s), A2 optimal (3 positions, E[r]=1.8% combined, 37.6s), output saved to `track_a/output/live_2026-05-19.md`
  - Two bugs fixed: A2 mu0 constraint changed to per-unit-of-new-capital (prevents infeasibility on sparse/empty portfolio); Windows Unicode issue resolved (`>=` ASCII instead of `≥`, `stdout.reconfigure(encoding="utf-8")`)

- **Next session options (in priority order):**
  1. **Full 2021–2026 backtest sweep** — `uv run python track_a/run.py --mode backtest` — runs all 14 combinations (2 cadences × 7 μ₀ values); generates report + NAV chart + Pareto chart. Takes 1–3 hours (fundamentals cached, optimizer ~10–40s per period per run)
  2. **HTML dashboard output** (BACKLOG P1, Track B) — static HTML + chartjs over the markdown report
  3. **Tear sheet generator** (BACKLOG P1) — one-page PDF/HTML: return chart, drawdown, rolling Sharpe, holdings table

## Now (2026-06-14) — Interface / "next level": Cockpit + automation + brokerage v2

Marcel asked to lift the project to a hosted, impressive level. Confirmed direction via a
4-question check: localStorage holdings · full GitHub Actions cron · unified cockpit (both
tracks) · brokerage as a real v2 study.

**Built this session:**
- **`build_site.py`** — aggregates pipeline output into `web/data/latest.json` (JSON sidecar
  preferred, markdown-parse fallback so it works on today's files) + maintains
  `web/data/track_record.json` (NL-4 realized-performance loop). Writes **no** money figures.
  Verified: parses the real WDC pick (15-row leaderboard) + Track A live rec (11 A1 positions).
- **`web/` cockpit** — static finance terminal (`index.html` + `styles.css` + `app.js`, marked.js
  for markdown). Tabs: Overview · Fast Ideas · Core · Track Record · My Holdings. **Holdings are
  localStorage-only**, with P&L overlay + JSON export/import. Rendered + screenshot-verified, no
  console errors.
- **GitHub Actions** — `monthly-pick.yml` (both pipelines → commit), `daily-stoploss.yml`,
  `deploy-pages.yml` (publish on data change). Anthropic key via Actions secret.
- **`docs/BROKERAGE.md`** — Nordea vs Nordnet vs Saxo for the ASK, with switching cost/effort and
  the Saxo OpenAPI automated-holdings angle. Recommendation: plan Nordea → Saxo as v2.
- **Privacy bug fixed** — `.gitignore` now ignores the real `track_*/holdings.csv` paths (was
  pointing at the wrong subdir; real positions would have been committed).
- **`docs/BACKLOG.md`** — added proposed roadmap NL-1…NL-8 for Marcel's review.

**Cockpit data contract** lives in `web/README.md`. Deploy steps there too.

**Backlog progress (2026-06-14, after the cockpit):**
- **NL-4 DONE** — realized-performance loop. `build_site._fill_realized_returns()` scores every open
  pick vs entry and vs ACWI each run → `track_record.json` → Track Record tab. First result: WDC
  **+24.9%** since pick vs ACWI **+1.4%**.
- **NL-5 DONE** — JSON sidecars. `track_{a,b}/src/export.py` write structured `*_report.json` /
  `live_*.json` next to each report (hooked, best-effort); `build_site` prefers them over markdown
  parsing. NaN→null sanitization added so the browser never chokes. 128/128 tests still pass.
- Frontend: holdings P&L overlay now sources prices from the whole track record, not just the
  current pick.
- **NL-6 DONE** — server-side stop-loss + push. `build_site._write_watch()` emits non-sensitive
  `web/data/watch.json` (ticker + entry/stop only); `stopwatch` resolves local `holdings.csv` →
  `watch.json` fallback, so the daily CI cron is no longer a no-op. `daily-stoploss.yml` pushes via
  ntfy on breach (no-op without `NTFY_TOPIC` secret). `daily_check.py` got a UTF-8 stdout guard so
  the emoji alert doesn't crash on a Windows console. 132/132 tests pass.

**Shipped & live (2026-06-14):**
- Repo pushed (public): https://github.com/Marcipane3/Finance_Project
- Pages enabled (source = GitHub Actions), deploy green. **Cockpit live:**
  https://marcipane3.github.io/Finance_Project/
- Brokerage: decided to **consolidate to one Saxo ASK** (not run two accounts) when the move
  happens — see BROKERAGE.md + DECISIONS.

**Open follow-ups (for Marcel):**
1. **Add `ANTHROPIC_API_KEY` secret** — `gh secret set ANTHROPIC_API_KEY` — or the monthly thesis
   step fails when the 1st-of-month cron fires. (No secrets are set yet.)
2. *(Optional)* arm the breach push: install the ntfy app, pick a topic, `gh secret set NTFY_TOPIC`.
3. Review remaining BACKLOG NL-7 (committed price snapshot) / NL-8 (Track A μ₀ sweep + tear sheets
   in cockpit) — cut / re-rank.
4. Still pending from before: the full 2021–2026 Track A μ₀ sweep (surfaces in cockpit via NL-8).

## Open blockers

See BLOCKERS.md.
