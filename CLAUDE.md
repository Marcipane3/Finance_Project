# CLAUDE.md — Project Context for Claude Code

Read this file at the start of every session. It tells you what this project is, what's in flight, and how to work in it.

## What this project is

A personal portfolio optimization system. Two tracks, formally separated:

- **Track A — Synapse-style.** Slow, quarterly/yearly rebalancing, fundamental score (Piotroski F-Score) filtering + MILP-CVaR optimization. ~€21k inside Aktiesparekonto (Danish tax-advantaged account). Reproduces and extends Marcel's master thesis. **NOT being built yet** — Track B comes first.

- **Track B — Fast Ideas.** Monthly single-stock recommendation engine. Global universe (S&P 500 + STOXX 600 + Nikkei 225 + FTSE 100 + ASX 200 ≈ 1,500 names). LLM writes a long-form thesis per pick. ~€2k sleeve. **This is what we're building now (v0.1).**

The user is Marcel — has a master's thesis on this topic, technically capable, prefers precision over brevity, uses Python.

## Where the truth lives

Read these in order at the start of every session:

1. **`docs/STATE.md`** — current state, what's working, what's next. The "Now" section is the single source of truth for "what should I work on?"
2. **`docs/DECISIONS.md`** — append-only log of every decision, rationale, and what was rejected. If something seems weird, check here first.
3. **`docs/BACKLOG.md`** — parked items, future improvements, prioritized
4. **`docs/BLOCKERS.md`** — anything stuck

If user instruction conflicts with STATE.md, ask before proceeding — don't silently drift.

## Coding conventions

- **Language:** Python 3.11+
- **Package manager:** `uv` preferred (fast; `uv pip install ...`) — fall back to plain `pip` if `uv` isn't installed
- **Linter / formatter:** `ruff` (does both)
- **Type hints:** yes, but pragmatic — not religion. Public function signatures should have them; internal helpers don't need to.
- **Tests:** `pytest`. Test the optimization math + data parsing carefully. UI / output formatting can be lightly tested.
- **Logging:** use `logging` module, never `print` in library code. CLI scripts may use print for user output.
- **Config:** `config.yaml` at project root. No magic numbers in code.
- **Secrets:** `.env` file (gitignored). Use `python-dotenv` to load. Never commit API keys.

## Code style

- Prefer clear, readable code over clever code. Marcel is in a portfolio optimization context, not a competitive programming one.
- Functions should do one thing. If a function is >50 lines, ask whether to split.
- Comments explain *why*, not *what*. Code explains the *what*.
- When making a non-trivial design decision, propose options to Marcel before committing.
- After completing a non-trivial change, suggest updating `docs/DECISIONS.md` with the rationale.

## Pace and interaction

- Marcel asked for: **"Chat for planning, Code for implementation, Pattern: Chat → agree approach → Code → implement → Chat → review."**
- For each new feature, briefly state the approach in plain language before writing code. Wait for Marcel's nod (or pushback). Then code.
- After substantial changes, run tests + show the user what you ran and the result. Don't claim "tests pass" without showing.
- Don't ask permission for trivial things (formatting, renaming a local variable). Do ask for non-obvious design choices (new dependency, new module, schema change).

## Workflow conventions

- **Every session ends by updating STATE.md "Now" section** with what was done and what's next.
- **Every meaningful decision goes in DECISIONS.md** with date, rationale, alternatives rejected.
- **Every parked item goes in BACKLOG.md** with hypothesis + how we'd test it.
- **Every blocker goes in BLOCKERS.md** with what's needed to resolve.

## Current Track B v0.1 scope (subject to confirmation)

**Monthly, 1 stock at a time variant** (under Marcel's consideration as of 2026-05-17):
- One pick per month, 100% of sleeve in that name
- Stop-loss at -10% triggers exit to cash; wait for next monthly run
- Output: long-form markdown report with the thesis + diff vs. current holding
- Fee math: ~7% annual drag at Nordea, workable

(If Marcel chooses the bi-weekly 5-pick variant instead, the agent layer changes — the data + signal stack is the same.)

## Universe sources

Wikipedia scraping for index constituents (free, decent coverage):
- S&P 500: `https://en.wikipedia.org/wiki/List_of_S%26P_500_companies`
- STOXX 600: `https://en.wikipedia.org/wiki/STOXX_Europe_600`
- Nikkei 225: `https://en.wikipedia.org/wiki/Nikkei_225`
- FTSE 100: `https://en.wikipedia.org/wiki/FTSE_100_Index`
- ASX 200: `https://en.wikipedia.org/wiki/S%26P/ASX_200`

Prices + financials + news: `yfinance` package.

## Things to remember

- ASK (Aktiesparekonto) has lager-beskatning — turnover is tax-neutral inside. Only broker fees matter for trade frequency.
- Nordea fees: DKK 29 min + 0.20% commission + 0.25% FX on non-Nordic stocks.
- Marcel is Danish-based — EUR is the working currency. Convert USD prices to EUR when reporting.
- LLM thesis-writer calls Claude API directly (not Claude Code). Cost is negligible (~$5/year for monthly cadence).
- **Do not commit credentials.** WRDS / Anthropic / any API key goes in `.env`, gitignored.
