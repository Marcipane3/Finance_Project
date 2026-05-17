# DECISIONS — Portfolio Optimization Project

Append-only. Newest at top. Format: date, decision, rationale, alternatives rejected, follow-up.

---

## 2026-05-17 — Track B spec locked

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
