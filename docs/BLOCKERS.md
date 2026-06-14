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
**Working assumption (placeholder until confirmed):** 0.10% annual on foreign stocks held in ASK. Conservative middle estimate.

---

## B5 — Track B specification incomplete *(RESOLVED 2026-05-17)*
Resolved — Track B monthly 1-pick locked. See DECISIONS.

---

## B6 — Broker decision for Track B *(RESOLVED 2026-05-17)*
Resolved — monthly 1-pick at Nordea has acceptable fee math (~7%/year). Broker switch parked to BACKLOG.
