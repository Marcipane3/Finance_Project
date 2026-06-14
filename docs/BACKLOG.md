# BACKLOG — Portfolio Optimization Project

Items deferred from MVP. Format: hypothesis + how we'd test it + priority.

Priorities: **P0** = next thing after v0.1 ships; **P1** = high value, next quarter; **P2** = nice to have; **P3** = research curiosity.

---

## Return modeling

### P1 — Block bootstrap return simulator
**Hypothesis.** Non-parametric block bootstrap (10–20 day blocks) of historical residuals preserves serial dependence and tail behavior without assuming a distribution, and outperforms MVN in stress periods.
**How we'd test.** Drop in as a fourth return-model option, run the same backtest with same params, compare 2015–2024 cumulative return, Sharpe, max DD, and tail-period CVaR vs. MVN baseline.

### P1 — Regime-switching MVN ↔ MV Student-t (vol-scaled)
**Hypothesis.** Thesis Table 30 hinted MVN dominates on average but Student-t(21) does better in stress. A simple 2-regime indicator (e.g. VIX > threshold, or 30-day realized vol > rolling 95th percentile) that flips between models would Pareto-dominate either alone.
**How we'd test.** Implement both samplers, define a deterministic regime indicator on lagged data (no look-ahead), run backtest, compare on full-period and stress-period sub-samples.

### P2 — Add Student-t and EWMA as parametric options
**Hypothesis.** Fat-tailed sampling reduces tail CVaR underestimation enough to improve drawdown control in 2020 / 2022.
**How we'd test.** Same backtest harness, swap return generator.

### P2 — Fix GARCH implementation properly
**Hypothesis.** Thesis GARCH underperformed in part because of implementation choices: `variance.targeting=TRUE`, normal innovations on a t-distributed residual world, post-truncation to `max_dim=350` assets. A clean DCC-gjrGARCH with t innovations and proper convergence handling may actually beat MVN.
**How we'd test.** Reimplement in Python (`arch` package + custom DCC), run head-to-head on 2015–2019 with F-Score 8 at μ₀=0 (the only point where thesis GARCH was feasible).

### P3 — ML-based joint return distribution
**Hypothesis.** A conditional VAE or normalizing flow over standardized residuals captures joint tail dependence better than DCC.
**How we'd test.** Treat carefully — easy to overfit; needs aggressive walk-forward validation.

---

## Filtering / scoring

### P0 — G-Score and QMJ-Score as parallel branches *(Marcel flagged explicitly)*
**Hypothesis.** F-Score performed best in-sample, G-Score best out-of-sample (158% vs 130% on 2020–2024 validation). Marcel had cool results from both — wants them available, not committed to one. Running them as separate portfolios and ensembling weights (or picking the best trailing-12m one) could be more robust than committing to one score.
**How we'd test.** Compute G and QMJ alongside F using the same pipeline, run three independent backtests (F8, G7, QMJ-top), evaluate each plus a 1/3-1/3-1/3 ensemble vs. single-score on Sharpe and drawdown.
**Note from Marcel (2026-05-17):** add to memory so he can pick it up later — both G and QMJ showed cool results in the thesis and are not to be lost.

### P2 — Sector caps
**Hypothesis.** Thesis portfolios concentrated in tech during 2020–2024. A 25% sector cap would reduce drawdowns at modest return cost.
**How we'd test.** Add `sum(x[j] for j in sector_s) <= 0.25` constraint per sector, rerun backtest.

### P2 — Momentum tilt as a tie-breaker among F-Score=8 names
**Hypothesis.** Among the small set of stocks passing the F-Score 8 filter, prior-12m-minus-1m momentum is a marginal positive signal.
**How we'd test.** Modify the score-filter step to weight pre-optimization scores by momentum rank; backtest.

### P3 — Peter Lynch screening principles
Thesis mentions this in future work. Low-priority; non-academic, harder to make rigorous.

### P3 — EUR-denominated universe variant
**Hypothesis.** Trading EUR-listed names (DAX, CAC, Euronext) eliminates the 0.25% FX margin on every trade — that's a ~50bps round-trip improvement. Would test whether a STOXX 600 version of the F-Score strategy is feasible and competitive.
**How we'd test.** Replace S&P 500 universe with STOXX 600, recompute F-Score on European fundamentals (FactSet/yfinance coverage permitting), backtest.

---

## Rebalancing & frequency

### P1 — Hybrid yearly buy + intra-year sell trigger
**Hypothesis.** Yearly buys minimize fees, but holding a name for 12 months when its F-Score drops to 4 is wasteful. A "yearly buys, sell-only triggers mid-year on F-Score deterioration" hybrid may dominate pure yearly.
**How we'd test.** Pure yearly vs. hybrid (sell-only triggers at quarterly check-ins if score < 6). Compare on net return, max DD, turnover.

### P2 — Event-driven rebalance
**Hypothesis.** Rebalance only when (a) a new 10-Q/10-K drops on a held name, or (b) F-Score of a held name drops below threshold mid-year, or (c) the score-eligible set changes by more than X%.
**How we'd test.** Implement event triggers, count rebalance events, compare turnover and net return vs. fixed cadence.

### P3 — Monthly cadence as thesis-comparison reference
Not for production; only useful as a "did we reproduce the thesis?" sanity check. Run once on v0.1, archive result, don't optimize.

---

## Track A — prep items (when we start Track A)

### P0 — F-Score implementation from raw yfinance data
**Reference.** Thesis defines the exact 9 conditions used. Pre-computed APIs (FMP, GuruFocus) exist but cost money + use slightly different variants. Decision: compute ourselves. ~80 lines of code.
**Dependencies.** yfinance `balance_sheet`, `income_stmt`, `cashflow` for current + prior year per ticker.

---

## Broker

### P2 — Switch broker (Saxo Bank / Nordnet)
**Hypothesis.** Saxo/Nordnet have lower kurtage and no depotgebyr on foreign stocks. Switching could save ~30–50bps/year. Demoted from blocker after Track B locked to monthly 1-pick (fee math now acceptable).
**How we'd test.** Get Marcel's Nordea depotgebyr (B4), simulate same trades on competitor price lists, decide if savings justify one-time switch friction (only one ASK allowed per person, so switch means moving Track A too).

---

## Optimizer

### P1 — Solver-time benchmarking
**Hypothesis.** HiGHS is fast enough for our scale; we don't need Gurobi.
**How we'd test.** Wall-clock on representative monthly problem, both HiGHS and (free) commercial trial.

### P2 — Warm starts between consecutive months
**Hypothesis.** Solver can warm-start from the previous month's solution; on a monthly cadence with stable filters, 70%+ of binaries don't flip.
**How we'd test.** Implement warm start, measure solver time improvement.

### P3 — Distributionally robust CVaR
**Thesis future work.** Hedge against estimation error in μ and Σ.
**How we'd test.** Solver overhead is steep — only worth it if we have evidence that input-sensitivity is hurting us.

---

## Universe & data

### ~~P1 — Nikkei 225 scraper~~ DONE (2026-05-18)
**Implemented.** Wikipedia Nikkei 225 article (`<ul>/<li>` list format, not `<table>`) parsed with BeautifulSoup + regex `TYO:\s*(\d{4,5})`. Returns 223 tickers, all suffixed `.T`. Known anchors confirmed: 7203.T (Toyota), 9984.T (SoftBank), 6857.T (Advantest).
**Note:** The original Wikidata SPARQL approach was dead — wrong QID in backlog (Q193068 = "particle-wave duality"; correct is Q507338), and P249 (ticker symbol) is 0.04% populated for Japanese stocks in Wikidata.
**Universe now:** ~1,492 unique tickers (was ~1,269).

### P1 — Point-in-time S&P 500 membership
**Hypothesis.** Using current S&P 500 membership in a 2015–2019 backtest is mild survivorship bias. Point-in-time membership is honest.
**How we'd test.** Source historical membership (Wikipedia scrape or fja05680/sp500 dataset), rerun, see if results change materially.

### P2 — Broader universe (Russell 1000 / global)
**Thesis future work.** Replicate on mid/small caps and ex-US benchmarks.

### P2 — Filing-date alignment
**Hypothesis.** Quarter-end ≠ filing date. F-Score for Q1 isn't actionable until ~45 days later. Live system must lag fundamentals by filing-date offset to avoid look-ahead.
**How we'd test.** Get filing dates from EDGAR submissions index; add as a column in the score table.

---

## Risk management

### P2 — Drawdown brake
**Hypothesis.** Adding a max-drawdown-triggered cash sleeve (e.g. when trailing-12m DD > 25%, allocate 50% to cash for 2 months) could improve Sharpe at modest CAGR cost.
**How we'd test.** Add as a post-optimizer overlay, backtest with brake on/off.

### P3 — Tail-risk hedges (long volatility, OTM puts)
Too complex for personal portfolio scale; flag and move on.

---

## Live / production

### P1 — Live recommendation generator
**Hypothesis.** Monthly cron that pulls latest data, runs the pipeline, and emits a portfolio recommendation + diff vs. current holdings.
**How we'd test.** Build it, run it parallel with backtest for 3 months before trusting any output.

### P1 — Tear sheet generator
**Hypothesis.** A standard one-page PDF/HTML tear sheet (return chart, drawdown, rolling Sharpe, sector breakdown, current holdings table) makes monthly review trivial.
**How we'd test.** Build it; check it reads in 60 seconds.

### P2 — Tax-loss harvesting overlay
**Hypothesis.** For real-money use in DK (taxable account), pairing losers in December reduces tax drag.
**How we'd test.** Out of MVP scope. Probably need a Danish tax accountant input.

---

## Track B — Fast Ideas

Track B v0.1 spec is locked (see STATE.md). The items below are post-v0.1 improvements.

### P1 — HTML dashboard output
**Hypothesis.** A clickable HTML dashboard with charts per pick is nicer than markdown for at-a-glance review. Markdown first; dashboard once v0.1 is stable.
**How we'd test.** Build a static HTML generator that takes the same report data and renders chartjs/plotly visuals + the long-form text.

### ~~P1 — Daily stop-loss alert~~ DONE (2026-05-18)
**Implemented.** `track_b/src/stopwatch.py` + `track_b/daily_check.py`. Exit code 0/1/2 for cron. Writes dated alert to `track_b/output/alerts/`. 13 tests passing.

### P2 — Performance retrospective
**Hypothesis.** Every quarter, the agent reviews its own past picks and writes a retrospective: which thesis was right, which was wrong, what signals correlated with winners, what we got fooled by. This is the actual learning loop.
**How we'd test.** Build a `retrospective.py` that pulls all past reports + price evolution + final P&L per pick, then Claude API call to write the post-mortem.

### P2 — Personal "watchlist" overrides
**Hypothesis.** Sometimes Marcel will be following a name not in the agent's pre-filter top 50. Allow a manual watchlist that bypasses the pre-filter and goes straight to deep-dive.
**How we'd test.** Add `watchlist.csv` reader; tickers in it skip pre-filter.

### P3 — Sentiment via paid news API
yfinance + free RSS may give thin news coverage. Paid news APIs (NewsAPI, Marketaux) cost $20–50/month and could improve thesis quality. Skip until v0.1 proves the framework is worth investing in.

### P3 — Confidence calibration
**Hypothesis.** The agent's confidence assessments (which drive whether a pick gets a non-zero weight) can be calibrated against actual outcomes over time.
**How we'd test.** Track confidence-vs-realized-return per pick over ~50 picks; fit a calibration curve.

---

## Roadmap — proposed "next level" (added 2026-06-14, for Marcel's review)

*These are the points I'd add to lift the project from "local scripts that work" to "a hosted, self-updating, private-by-design portfolio cockpit." Read, cut, re-prioritise. Nothing here is committed until you nod.*

### The honest API reality (read first — it shapes everything below)
- **Nordea has no retail brokerage/depot read API.** Nordea's PSD2/Open Banking APIs expose *bank account* balances and payments, **not** securities held in an Aktiesparekonto. There is no supported way to programmatically pull your ASK holdings from Nordea as a private customer. Aggregators (Tink, GoCardless/Nordigen, Plaid) inherit the same limit — they read bank accounts, not Danish brokerage depots.
- **Saxo Bank is the one real exception.** Saxo has a proper OpenAPI (OAuth, read-only `port/v1/positions` etc.). If you ever move the ASK to Saxo (already parked as P2 "Switch broker"), genuine read-only position sync becomes possible. So: the broker-switch question now has a *second* payoff beyond fees — it's the only path to automated holdings.
- **Therefore the design rule:** treat holdings behind an adapter interface. Manual entry now (`holdings.csv` / paste / browser), a `SaxoSync` adapter later. Do **not** fake or scrape a Nordea integration.

### NL-1 (P0) — Static GitHub Pages "cockpit"
**Hypothesis.** The pipeline already emits everything a good dashboard needs (theses, rankings, alerts). A static site over a machine-readable `latest.json` turns it into a research terminal you actually open weekly — no server, no cost.
**How we'd test.** Build a single static app that loads committed JSON + markdown and renders: current pick + thesis, candidate leaderboard, stop-loss status, Track A live recommendation. Ship to GitHub Pages.

### NL-2 (P0) — Private-by-design holdings (localStorage split)
**Hypothesis.** Research (signals, theses, picks) can be public/shareable; your actual € positions must never be. Keep the public layer in committed JSON and the private layer (tickers + amounts + entry prices) in **browser localStorage only** — never committed, never leaves the machine. The app merges them at render time (public thesis + your private P&L overlay). Export/import JSON for backup/second device.
**How we'd test.** Enter holdings in the browser; confirm nothing touches git; reload persists; P&L overlay renders against public prices.

### NL-3 (P1) — GitHub Actions automation (the "self-updating" part)
**Hypothesis.** A monthly cron (`run.py` for both tracks → commit report + `latest.json`) and a daily cron (`daily_check.py` stop-loss → commit alert, email on breach) make the cockpit update itself. Anthropic key lives in an Actions secret, never in the public site.
**How we'd test.** Schedule both workflows; confirm a clean monthly commit + a daily green/red alert; verify the key never appears in build output.

### ~~NL-4 (P1) — Realized-performance / benchmark tracking~~ DONE (2026-06-14)
**Implemented.** `build_site._fill_realized_returns()` recomputes every open Track B pick's
return vs entry and vs benchmark (ACWI) over the same window on each run; written to
`web/data/track_record.json` and rendered in the cockpit's Track Record tab. First real result:
WDC +24.9% since pick vs ACWI +1.4%. *Still TODO:* Track A live NAV vs S&P 500; cumulative chart.

### ~~NL-5 (P1) — JSON sidecar / unified contract~~ DONE (2026-06-14)
**Implemented.** `track_b/src/export.py` + `track_a/src/export.py` write a `*_report.json` /
`live_*.json` sidecar next to each markdown report (hooked into `report.py::run_pipeline` and
`track_a/run.py` live mode, best-effort). `build_site` prefers the sidecar over markdown parsing.
NaN floats sanitized to null (`_json_safe` + `allow_nan=False`) so the browser's JSON.parse never
chokes. *Still TODO:* a true single `portfolio.json` superset if the two shapes ever need merging.

### NL-6 (P2) — Stop-loss push notification
**Hypothesis.** A daily breach should reach your phone, not just a committed markdown file. GitHub Actions can email on failure exit code, or POST to a webhook (ntfy/Pushover/Telegram bot).
**How we'd test.** Force a breach in a test holding; confirm notification arrives.

### NL-7 (P2) — Committed price snapshot for reproducible builds
**Hypothesis.** Pages builds shouldn't depend on a live yfinance fetch succeeding in CI. Commit a small parquet/JSON price snapshot per run so the site is reproducible and fast.
**How we'd test.** Build the site offline from the committed snapshot.

### NL-8 (P2) — Surface Track A tear sheets + the full μ₀ backtest sweep in the cockpit
**Hypothesis.** The pending 2021–2026 sweep (14 combinations) produces NAV + Pareto charts. The cockpit should host them as an interactive tab, not leave them as local PNGs.
**How we'd test.** Run the sweep once, export chart data as JSON, render with a JS chart lib.
