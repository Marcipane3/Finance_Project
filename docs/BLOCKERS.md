# BLOCKERS — Portfolio Optimization Project

Anything stuck waiting on a decision, data, compute, or external action.
Resolved blockers move to DECISIONS.md and are deleted from here.

---

## B3 — WRDS credentials in plaintext (security)

**Status.** Open.
**What's needed.** Marcel rotates the WRDS password (since the old credentials are visible in `1_scores_final_code_2015_2019.ipynb` and `Just_Scores.ipynb`) and confirms the notebooks are not in any public repo.
**Why blocking.** Not blocking work on this project, but a real-world security item to close.
**Proposed resolution.** Marcel confirms done; we then strip credentials from the notebooks before they go in any future repo.
**Opened.** 2026-05-16.

---

## B4 — Nordea depotgebyr (foreign stocks) — exact rate unknown

**Status.** Open.
**What's needed.** Marcel checks his last Nordea statement for the depotgebyr (custody fee) charged on foreign stocks held in the Aktiesparekonto.
**Why blocking.** Not blocking v0.1 — we'll use 0% as a placeholder. But the real number determines whether a broker switch to Saxo/Nordnet (both 0% depotgebyr) is worth the effort.
**Proposed resolution.** Marcel pastes the number; we add it to the fee model.
**Opened.** 2026-05-17.
**Working assumption (placeholder until confirmed):** 0.10% annual on foreign stocks held in ASK. Conservative middle estimate — Nordea's general schedule mentions a fee exists but the rate isn't publicly listed. If the real number is materially higher, fee impact on Track A worsens proportionally.

---

## B6 — Broker decision for Track B

**Status.** Open. **This is now the top priority blocker — gates Track B from going live.**
**What's needed.** Marcel decides among:
1. Switch ASK to Saxo Bank or Nordnet (one-time friction, recurring savings; closes Nordea ASK)
2. Keep Track B inside Nordea ASK (tax-neutral on trades; fees stay high)
3. Track B in regular Nordea handelskonto (worst tax + worst fees — not recommended)
4. Accept Plan B: keep at Nordea, reduce Track B cadence to monthly (~10% fee drag instead of 30–74%)
**Why blocking.** Track B's economics depend on this. We can build the recommendation engine without it (broker-agnostic code), but Marcel can't actually trade Track B until decided.
**Proposed resolution.** Marcel reflects, makes call. Recommendation: option 1.
**Opened.** 2026-05-17.

---

## B5 — Track B specification incomplete *(RESOLVED 2026-05-17)*

Resolved — moved to DECISIONS log.
