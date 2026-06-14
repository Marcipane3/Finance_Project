# DECISIONS — Portfolio Optimization Project

Append-only. Newest at top. Format: date, decision, rationale, alternatives rejected, follow-up.

---

## 2026-06-14 — Interface: static GitHub Pages "cockpit", private-by-design holdings

**Decision.** Build a unified static web cockpit (`web/`) over a machine-readable `web/data/latest.json` contract, covering both tracks. GitHub Actions automate it: `monthly-pick.yml` runs both pipelines + commits data, `daily-stoploss.yml` runs the stop-loss, `deploy-pages.yml` publishes `web/` to GitHub Pages on data change. `build_site.py` aggregates pipeline output (JSON sidecar preferred, markdown parse fallback) and maintains `track_record.json` (the realized-performance loop, NL-4). **Personal holdings live only in the browser (localStorage), never committed.** Confirmed via four-question check with Marcel (2026-06-14).

**Rationale.**
- **No fake brokerage API.** Nordea exposes no retail brokerage/depot read API (PSD2 = bank accounts only). The honest design is a static research terminal fed by the existing pipeline output, with manual/browser holdings behind an adapter. Saxo OpenAPI is the one real automated-holdings path and is treated as v2 (see BROKERAGE.md).
- **Privacy split.** GitHub Pages is public; research (theses, signals, picks) is shareable, but € positions must not be. localStorage keeps money data client-side only. The public layer carries no holdings — only model allocations on the *configured* sleeve sizes (€23k / €2k assumptions), not real balances.
- **Self-updating > local script.** Actions cron turns the project from a thing Marcel runs into a thing that maintains itself at zero hosting cost; the Anthropic key sits in an Actions secret, never in the public site.

**Alternatives rejected.**
- Private repo + private Pages (needs GitHub Pro; puts money in git) — rejected for the free, browser-private model.
- Committing holdings.csv for the daily job to read — rejected: would publish positions. Consequence: the *server-side* daily stop-loss only fires meaningfully with a non-sensitive watch file; logged as a follow-up.
- Faking/scraping a Nordea integration — rejected as dishonest and fragile.

**Follow-up.**
- Fixed a real privacy bug: `.gitignore` protected `track_*/data/holdings.csv` but the pipelines read `track_*/holdings.csv`. Corrected.
- Server-side stop-loss needs a non-sensitive `watch.json` (ticker + stop only, no €) to be useful in CI — backlog.
- Pipelines should emit JSON sidecars directly (NL-5) so build_site stops parsing markdown.

---

## 2026-06-14 — Brokerage v2: plan ASK move Nordea → Saxo (not blocking)

**Decision.** Treat moving the Aktiesparekonto from Nordea to Saxo as a v2 project, gated on confirming two numbers (Nordea custody fee B4; Saxo ASK commission tier) and prototyping the Saxo OpenAPI read path on a sim account first. Full analysis in `docs/BROKERAGE.md`.

**Rationale.** Saxo is cheapest for small mostly-US tickets ($1 min vs DKK 25–29) and is the **only** option with a personal read API (`PositionsMe()`) — which closes the cockpit's one automation gap. Pure fee saving is modest (~€80–130/yr); the API + best-in-test ASK is the real driver. One ASK per person means the whole account moves at once; transfer takes weeks, may force liquidation to cash, and blocks trading during the move — so timing it after a rebalance matters.

**Alternatives rejected.** Nordnet (clean #2, cheaper than Nordea, but no personal API — nothing for the cockpit to automate against). Lunar (cheap on Danish names, no API, thin foreign coverage). Staying at Nordea (fine short-term; revisit once B4 is known).

**Follow-up.** Confirm B4 + Saxo tier + in-kind transfer support; build `SaxoSync` adapter against sim account behind the existing holdings interface.

---

## 2026-05-19 — Track A: A1/A2 dual-mode optimizer design

**Decision.** Track A runs two optimization modes each rebalance period in parallel:
- **A1 (Full Rebalance):** MILP-CVaR optimizer over all N eligible stocks; buy and sell allowed; proportional TC (0.45%) in objective; new capital dilutes prev_weights by `(1 - new_capital_frac)` before TC decomposition.
- **A2 (Capital Deployment):** All existing positions held unchanged; only new quarterly capital (€3,000 configurable) is allocated to NEW stocks not currently held; no selling; existing portfolio's scenario contribution enters as a constant (S,) vector.

**Rationale.** Marcel's explicit request: he wants to see both "what the optimizer would do if I could sell" (A1) and "what new stocks should I buy with my quarterly injection" (A2). ASK account means turnover is tax-neutral — only broker fees penalize selling — but Marcel may still not want to sell stable winners. A2 gives him the buy-only view without suppressing the full-information A1 view.

**Alternatives rejected.**
- A2 operating on the full (existing + new) portfolio: would require selling to rebalance, defeating the point.
- A2 using combined expected return constraint `E[r_combined] >= mu0`: makes A2 infeasible when new capital is a small fraction of total portfolio, because €3k / €23k = 11.5% of invested capital can't move the combined portfolio return by the full mu0 threshold.

**Follow-up.** mu0 constraint for A2 → see next entry.

---

## 2026-05-19 — Track A: A2 mu0 constraint applied per unit of new capital

**Decision.** In `solve_a2()`, the minimum return constraint is:
```
sum(new_scenarios @ w_new) / (S * new_capital_frac) >= mu0
```
i.e., the expected return on the new positions (expressed per unit of new capital deployed, not per unit of total portfolio) must exceed mu0.

**Rationale.** With combined-portfolio constraint `E[r_combined] >= mu0`, A2 is infeasible on a sparse or empty portfolio because: `E[combined] = E[new] × new_cap_frac ≈ 10% × 11.5% = 1.15% < mu0_quarterly = 2.41%`. The new capital physically cannot move the combined portfolio return enough. The per-unit-of-new-capital formulation asks "does this €3k deployment earn at least mu0 on its own?" — which is the economically meaningful question for a buy-only capital injection.

**Alternatives rejected.**
- Lower mu0 globally for A2: would make A2 a weaker constraint than A1 for no principled reason.
- Set mu0=0 for A2: gives a degenerate "minimize CVaR only" problem — any result is "optimal" including highly concentrated positions.

---

## 2026-05-19 — Track A: backtest period 2021-01-01 → rolling present

**Decision.** Track A backtest runs from 2021-01-01 to today, not the thesis's 2015–2019 window. Price history fetched from 2016-01-01 (5 years before backtest start) to seed the MVN estimation at the first rebalance date. The window advances as time passes.

**Rationale.** Marcel's explicit request: he wants to know how the strategy performs in the real post-thesis environment (2021–2026), not just replicate the in-sample result. The thesis already covers 2015–2019 and out-of-sample 2020–2024. Running 2021–present on live market data gives a more actionable benchmark for his actual portfolio decisions.

**Alternatives rejected.**
- 2015–2019 in-sample replication: would only confirm the thesis, not add new information.
- 2020–present: 2020 is a COVID-crash year with extreme outlier returns — starts the backtest on an atypical period.

---

## 2026-05-18 — thesis.py: prompt caching restructured; max_tokens raised to 3500

**Decision.** `_SYSTEM_PROMPT` trimmed to role-only (~130 tokens). New `_FORMAT_INSTRUCTIONS` constant (~900 tokens) holds the detailed section format guide, data interpretation notes, and quality standards. `_FORMAT_INSTRUCTIONS` is placed as the first content block in the user message with `cache_control: ephemeral`, making the cached prefix (system + format block) well above the 1024-token minimum. `max_tokens_per_pick` raised from 2000 → 3500 in both code default and `config.yaml`. Truncation warning added: logs when `output_tokens ≥ max_tokens - 50`.

**Rationale.**
- Prior system prompt (~380 tokens) was below the 1024-token cache threshold — `cache_read_input_tokens` was always 0.
- Restructuring separates stable format instructions (cached) from volatile pick data (not cached), at the correct granularity.
- 2000 token limit caused truncation ("in=998 out=2000" in log) — thesis was being cut mid-section.

**Alternatives rejected.**
- Padding `_SYSTEM_PROMPT` artificially: inelegant, harder to maintain.
- Raising limit to 5000+: unnecessary; 3500 gives ~1,500 words of thesis with comfortable headroom.

---

## 2026-05-17 — thesis.py: stable system prompt cached, streaming, per-day cache

**Decision.** `thesis.py` sends the analyst persona + section-format instructions as a cached system prompt block (`cache_control: ephemeral`), and puts volatile per-ticker signal data in the user message. Uses `client.messages.stream()` + `get_final_message()` for the ~2,000-token output. Results are cached per ticker per calendar date in `track_b/data/cache/thesis/TICKER_YYYY-MM-DD.md`.

**Rationale.**
- Prompt caching: the system prompt (~350 tokens) is identical across all monthly picks. Marking it ephemeral means the first call writes to cache; subsequent calls (re-runs, testing) pay only the negligible cache-read cost. At ~$2/year total cost this barely matters, but it's the right pattern.
- Streaming: prevents timeout on 2,000 token output.
- Per-day cache: lets the pipeline re-run (e.g. crash + restart) without burning tokens. Dated file name means a new thesis is generated on the next calendar day.

**Alternatives rejected.**
- Non-streaming: fine for 2,000 tokens at this latency, but streaming is the habit for any non-trivial output.
- Cache per ticker only (no date in filename): would serve a stale thesis forever. Monthly cadence means the cached thesis is valid for one calendar day; next day a fresh one is generated.

**Follow-up.** Holdings diff module is next.

---

## 2026-05-17 — Track B monthly 1-pick variant locked

**Decision.** Track B v0.1 is the monthly 1-pick variant. One stock per month, 100% of sleeve in that name. Stop-loss at -10% rotates to cash; wait for next monthly run. Output: long-form markdown report (~1,500 words) per pick. Always fully invested or fully in cash (no partial positions).

**Rationale.** Marcel chose explicitly. Reasons aligned: 
- Fee math: ~7% annual drag at Nordea (monthly 1-pick) vs. 30–74% (bi-weekly multi-pick) — 4–10× cheaper.
- Stays inside Nordea ASK without forcing a broker switch.
- Forces commitment per pick — sharper learning loop, no hiding bad calls inside a portfolio.
- Code is half the size: no position sizing, no rank weighting, no portfolio diff.
- Easy to extend to multi-pick later if Marcel wants diversification — strict subset of the bi-weekly design.

**Alternatives rejected.**
- Bi-weekly 5-pick (original spec): rejected — fee economics defeat the strategy at this account size, broker switch is friction Marcel doesn't want.
- Bi-weekly 1-pick: rejected — adds rotation cost without commensurate signal improvement.
- Quarterly 1-pick: rejected — too slow for "play and learn" goal Marcel articulated.

**Follow-up.** Broker switch question (B6) demoted from blocker to backlog item — not gating Track B anymore.

---

## 2026-05-17 — F-Score sourcing: compute from raw yfinance data, not external API

**Decision.** When Track A starts, we compute the Piotroski F-Score ourselves from raw balance sheet / income statement / cash flow data via yfinance. No paid API for pre-computed scores.

**Rationale.**
- Marcel suggested yfinance might provide pre-computed F-Scores; it does not — only raw financials. Every public example computes the score from those.
- Pre-computed F-Score endpoints exist (FMP, GuruFocus) but cost $15–30/month and lock us to their variant.
- F-Score variants differ slightly (Piotroski original 2000 paper, FMP TTM variant, GuruFocus variant). Computing ourselves lets us pin to the exact thesis variant.
- ~80 lines of code, well-tested logic, no recurring cost.
- Not a Track B concern — Track B uses LLM thesis, no F-Score involved.

**Alternatives rejected.**
- FMP API for pre-computed scores: rejected — paid + variant uncertainty.
- Wait until Track A start to decide: deferred but covered by this decision; if recompute proves too painful, FMP becomes an option then.

**Follow-up.** Added to BACKLOG as a Track A prep item with reference to thesis F-Score definition (Section X of `Master-Thesis_Romeiro_Malbrich.pdf`).

---

**Decision.** Track B is a bi-weekly recommendation engine producing a long-form markdown report with 5 rank-weighted picks (30/25/20/15/10) drawn from a global universe (S&P 500 + STOXX 600 + Nikkei 225 + FTSE 100 + ASX 200, ~1,500 deduped names). Five-stage pipeline: pre-filter → deep-dive → ranked → thesis (Claude API) → report. Holdings diff vs. manual `holdings.csv`. -10% stop loss enforced via daily price check. Aspirational return target 40% annual; honest measured benchmark is S&P 500.

**Rationale.** Marcel wants a learning + fun-money sleeve that produces in-depth analysis he can read. Long-form thesis matters more than mechanical signals — the goal is "understand why something is interesting to invest into." Bi-weekly cadence enforces discipline (not trading on whim). 5-pick rank weighting permits 0% on low-confidence ranks.

**Alternatives rejected.**
- ETFs-only universe: rejected — wouldn't deliver the "play and learn individual stocks" experience Marcel wants.
- Short snippets per pick: rejected — Marcel explicitly chose the long version for learning.
- HTML dashboard for v0.1: deferred to backlog. Markdown first for simplicity and version control.
- Confidential alpha-mining (technicals only, no LLM thesis): rejected — the thesis is the point.

**Follow-up.** Broker decision is the gating dependency (see DECISIONS entry below and BLOCKERS B6). Until that's resolved, Track B can't actually trade — but we can still build the pipeline since the recommendation engine is broker-agnostic.

---

## 2026-05-17 — Broker fee math flagged for Track B; Marcel to decide

**Decision (pending Marcel).** Track B's bi-weekly rotation will not work economically at Nordea. Fee analysis: at €400 average position, full rotation costs ~74% of sleeve in fees per year; even light rotation costs 15%. Three options identified:
1. **Switch ASK to Saxo or Nordnet** (lower min kurtage, no depotgebyr; only one ASK per person, so this means moving Track A too)
2. **Track B inside same Nordea ASK** as Track A (tax-neutral on trades, fees still burdensome)
3. **Track B in regular Nordea handelskonto** (worst tax + worst fees)

**Rationale.** Bi-weekly cadence × ~€400 positions makes Nordea's DKK 29 minimum kurtage punitive. Saxo/Nordnet's cheaper structure is materially better for this size and frequency.

**Alternatives rejected.**
- Accept the fee drag as cost of learning: rejected — 15% drag turns the 40% target into a near-impossible 55% gross. Fees this high distort the strategy itself (you can't trade your signal).
- Cut Track B frequency to monthly: open as Plan B if Marcel doesn't want to move accounts.

**Follow-up.** Marcel to decide between options 1/2/3 (or option 4: monthly cadence instead of bi-weekly). My recommendation: option 1 — open Saxo ASK, move Track A there, run Track B as a separate sub-portfolio inside it. Friction is one-time; the savings recur for life. Documented as BLOCKER B6.

---

## 2026-05-17 — Track A real-world parameters locked

**Decision.** Capital €23k inside ASK (forced by 2026 DKK 174,200 deposit ceiling). Min weight 3.04% (€700). Max weight 10%. Cardinality 10–30. Broker fee model: DKK 29 fixed + 0.20% commission + 0.25% FX margin (Nordea online for non-Nordic stocks). β = 0.10 fixed. μ₀ swept over annualized {0%, 5%, 10%, 15%, 20%, 25%, 30%}. ~€2k capital overflow goes to Track B sleeve.

**Rationale.** 
- €25k → €23k: Marcel can't legally deposit more than the ASK cap in 2026. The overflow into Track B is convenient (it was already planned as a 10% sleeve).
- Min weight €700: Marcel won't manage positions smaller. 3% in absolute terms keeps the optimizer's 10–30 cardinality range feasible (math: at 30 stocks the min weight floor must be ≤ 3.33%).
- 10–30 cardinality preserved despite the FX/fee headwind: matches Marcel's stated manageability ceiling.
- Fees real, not academic: Nordea ASK is ~2× the thesis Revolut assumption for foreign stocks. This further strengthens the case for quarterly/yearly over monthly rebalancing.
- β = 0.10 pinned, μ₀ swept: thesis showed β contributes little, μ₀ dominates. Single-parameter sweeps are easier to interpret.
- ASK lager-beskatning makes turnover tax-neutral inside ASK — only broker fees penalize trading frequency. This is a clean modeling property.

**Alternatives rejected.**
- €1000 min weight: would force max stocks down to 22 — fine, but tighter than Marcel's stated preference. Easier to relax later if he changes his mind.
- Raising max weight to 15–20%: would allow 10–30 cardinality with €1000 min but introduces concentration risk Marcel didn't ask for.
- Sweeping β too: each extra dimension squares the run count. Not worth it given thesis evidence β doesn't dominate.

**Follow-up.** μ₀ on yearly rebal needs reinterpretation as an annual minimum return (sensible range 8–20%); separate sweep for that cadence.

---

## 2026-05-17 — Rebalance cadence: quarterly + yearly (drop monthly)

**Decision.** v0.1 backtests both quarterly and yearly cadence in parallel. Monthly is dropped from v0.1; it remains only as a sanity-check reference point against the thesis.

**Rationale.** 
- Marcel explicitly does not want frequent rebalancing.
- F-Score was designed by Piotroski for annual holding periods on high-BM stocks — yearly cadence matches the underlying philosophy, not monthly.
- Annual reports (10-K) are audited; quarterly reports (10-Q) are not. Data quality is meaningfully higher at yearly cadence.
- Nordea fees are 2× the thesis assumption — turnover cost arithmetic favors infrequent rebal.
- ASK tax is mark-to-market regardless of trading, so trading frequency is neutral from a tax standpoint — the entire trade-off collapses to "fees vs. signal freshness."

**Alternatives rejected.**
- Monthly as a third arm: would run 12× the rebalance count for no expected gain at this fee level.
- Event-triggered rebal: deferred to backlog; promising but unnecessary complexity for v0.1.

**Follow-up.** If yearly dominates quarterly on net return after fees, it becomes the default. The signal-freshness loss from yearly may show up in higher drawdowns, in which case we look at a hybrid (yearly buys, mid-year sells if F-Score drops below threshold).

---

## 2026-05-17 — Broker and account: Nordea Aktiesparekonto

**Decision.** Track A runs entirely inside an existing Nordea Aktiesparekonto. Track B uses a regular Nordea handelskonto for the ~€2k overflow.

**Rationale.** Marcel already uses Nordea; switching brokers is friction he doesn't want. ASK 17% lager-tax vs. 27/42% normal is a material advantage. Fee comparison vs. Saxo/Nordnet not worth doing in v0.1 — we model real costs and Marcel can switch later if results justify it.

**Alternatives rejected.**
- Saxo or Nordnet (cheaper kurtage, no depotgebyr, also offer ASK): defer to backlog as a "switch broker?" item. Worth revisiting after v0.1 if fees prove to be a major drag.

**Follow-up.** Quantify Nordea's depot-gebyr for foreign stocks (the Nordea page mentions a fee for foreign holdings storage but didn't give a rate). Marcel to check his last statement.

---

## 2026-05-16 — MVP scope locked

**Decision.** v0.1 will be: S&P 500 universe (current snapshot) → F-Score threshold 8 → MVN return simulator (historical mean, 5-year lookback, 5000 sims of 21-day terminal returns) → MILP-CVaR with TC, μ₀=0.0375, β=0.15, 10–30 stocks, 1–10% weights → 60-month backtest 2015–2019 → compare against thesis baseline.

**Rationale.** Marcel asked to "start easy" and "drop all" of the alternative return models (#8, #9 in his answers). One return model, one score, fixed thesis-best params lets us get an end-to-end working pipeline fast; everything else gets added on top once the loop runs.

**Alternatives rejected.**
- Multi-score / multi-return-model parity from day one — rejected: too much surface area, won't ship.
- Quarterly rebal in MVP — deferred to the realistic-parameters review; we keep monthly first so the backtest comparison to the thesis is apples-to-apples.

**Follow-up.** Backlog every dropped item (G-Score, QMJ, EWMA, Student-t, GARCH, regime switching) with a one-line hypothesis and how we'd test it.

---

## 2026-05-16 — Single-language Python rebuild

**Decision.** Drop Julia (JuMP + Gurobi) and R (rugarch + rmgarch). Rebuild the full pipeline in Python.

**Rationale.** Marcel no longer has DTU HPC access or Gurobi license, runs on laptop, is comfortable iterating fast in Python with Claude Code, and overnight runs are acceptable.

**Alternatives rejected.**
- Keep Julia + open-source HiGHS in Julia — rejected: polyglot codebase adds friction with no benefit for laptop-scale problems.
- Port only the optimizer — rejected: data + scoring + simulation are also Julia/R; partial port leaves orchestration glue brittle.

**Follow-up.** Choose between cvxpy and pulp+pyomo for the MILP layer when we get to optimizer implementation. Both are fine; cvxpy is more readable, pulp is more flexible for advanced MIP modeling.

---

## 2026-05-16 — Drop WRDS dependency, plan for yfinance + SimFin

**Decision (pending Marcel's approval).** Use yfinance for prices + financials in v0.1. If F-Score field coverage proves insufficient, layer SimFin community plan underneath. SEC EDGAR XBRL stays as the eventual gold standard but is not done upfront.

**Rationale.** WRDS subscription likely lapsed post-graduation. yfinance bundles prices + quarterly statements in one API, gets us to a working pipeline within days. SimFin gives us better coverage if needed. EDGAR is the source-of-truth but takes 1+ week to wire up cleanly — not worth blocking v0.1.

**Alternatives rejected.**
- EDGAR XBRL upfront — rejected: too slow to ship.
- Paid APIs (EODHD, Polygon, FMP paid) — rejected: free tier suffices for laptop-scale R&D.

**Follow-up.** Marcel to approve or push back. If approved, first coding task is the data pipeline.

---

## 2026-05-16 — Two-track architecture

**Decision.** Track A (Synapse) and Track B (Fast Ideas) live in separate code trees with separate eval frameworks. Capital split: ~90% A / ~10% B (revisitable). Track B will not auto-execute trades; it produces a watchlist Marcel reviews and trades manually.

**Rationale.** Marcel's two use cases have fundamentally different cadences (monthly vs bi-weekly), universes (S&P 500 vs global), holding periods (months vs weeks-to-months), and risk budgets. Mixing them in one optimizer would force trade-offs that obscure attribution.

**Alternatives rejected.**
- Unified optimizer with two risk-aversion regimes — rejected: too clever, harder to diagnose.

**Follow-up.** Track B work is deferred until Track A v0.1 reproduces a backtest. No code written for B until then.

---

## 2026-05-16 — Project bootstrap

**Decision.** Created STATE.md, DECISIONS.md, BACKLOG.md, BLOCKERS.md as living docs. Every session begins by re-reading STATE.md "Now" section.

**Rationale.** Marcel explicitly asked for clear decision tracking and "every session starts with understanding current state."

**Alternatives rejected.**
- Single combined doc — rejected: append-only decision log + state snapshot serve different purposes.
- Issue tracker (GitHub issues, etc.) — fine if Marcel wants it later; markdown works now.

**Follow-up.** Flag security issue: plaintext WRDS credentials in Jupyter notebooks. Rotate password and move secrets to .env. *Reported 2026-05-16; awaiting confirmation it's done.*

---

## Decision-log conventions

- **One decision per entry.** If a decision implies sub-decisions, link them rather than nesting.
- **Always record alternatives rejected.** That's the part future-Marcel will care about.
- **Mark reversed decisions explicitly** by adding a new entry that supersedes the old, and editing the old entry to say "SUPERSEDED by YYYY-MM-DD."
- **Date format: ISO 8601.** No ambiguity.
