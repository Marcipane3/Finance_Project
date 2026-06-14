# BROKERAGE — switch analysis & v2 roadmap

*Created 2026-06-14. Decision-support for "should the Aktiesparekonto move off Nordea, and where to?"
Ties to BACKLOG P2 "Switch broker" and the cockpit's one automation gap (no Nordea read API).*

> **Numbers below are from public price lists (June 2026) and need a final confirmation
> before any move** — especially Nordea's foreign-stock custody fee (BLOCKER B4) and Saxo's
> exact ASK commission tier. Flagged inline as ⚠️.

---

## TL;DR

**Recommendation: plan a one-time move of the ASK from Nordea to Saxo Bank, treated as a v2 project (not blocking the cockpit).**

Two reasons, in order of weight:
1. **It's the only path to automated holdings.** Saxo has a real OpenAPI (`PositionsMe()` read endpoint, OAuth). Nordea and Nordnet expose **no** personal brokerage read API. The cockpit's single unsolved gap — knowing your live position server-side for the daily stop-loss — closes only with Saxo.
2. **It's the cheapest for your trade profile** (small, mostly-US tickets), and its ASK was *Best in Test 2025* (Forbrugerrådet Tænk). Nordnet is a clean #2 but adds nothing the cockpit can automate against.

The pure fee saving is modest (~€80–130/year on a €25k book). The decisive factor is the **API + future-proofing**, not the courtage.

---

## Two accounts, or consolidate? (added 2026-06-14)

**Verdict: consolidate to a single Saxo ASK and close Nordea. Running both makes no sense — for a structural reason, not a soft one.** Because there's only one ASK per person (below), "two accounts" can only mean one of two worse options:

1. **Nordea ASK + a Saxo *taxable* depot** — keeps the €23k tax-advantaged book at the API-blind, pricier broker and moves only the small Track B sleeve to Saxo. But a taxable depot loses the lager-beskatning wrapper, so you'd put the *small* money where the API is while the *real* book stays unreachable. Backwards.
2. **Two relationships "just in case"** — double the statements, FX relationships, and admin for zero benefit. Nordea brokerage offers nothing Saxo doesn't do cheaper.

The whole point of touching Saxo is the read API + lower min-commission; both only pay off if the actual positions live there. **Sequencing caveat:** don't *close* Nordea until the Saxo transfer is fully settled (open → transfer → confirm settled → close). The only thing that would justify keeping Nordea is using it as a plain *retail bank* (salary/cash) — a banking decision, not a portfolio one.

## The hard constraint

- **One ASK per person, full stop.** You cannot run Nordea and Saxo ASKs in parallel. Switching = moving the *entire* account. Track A and Track B both move together.
- **2026 deposit ceiling: DKK 174,200** (~€23.3k). 17% lager-beskatning, annual mark-to-market.
- Because ASK is marked to market every year regardless of trades, **selling inside the ASK is not an extra tax event** — which matters for the switch mechanics below.

Sources: [Skat — Aktiesparekonto](https://skat.dk/borger/aktier-og-andre-vaerdipapirer/aktiesparekonto), [Expat Finance ASK Guide 2026](https://expatfinance.dk/investing/the-aktiesparekonto-ask-guide-2026/).

---

## Fee comparison (foreign / US stocks inside ASK)

| | **Nordea** (current) | **Nordnet** (Standard) | **Saxo** (Classic) |
|---|---|---|---|
| Min commission | DKK 29 (~€3.90) | DKK 25 (~€3.35) | **$1 (~€0.92)** |
| Variable commission | 0.20% | 0.10% | ~0.08% ⚠️ tier-dependent |
| FX margin (non-DKK) | 0.25% | 0.25% | ~0.25% ⚠️ |
| Custody / depot fee | ⚠️ unknown (B4) | none | none |
| Personal read API | ❌ | ❌ | ✅ OpenAPI |
| Intro offer | — | DKK 10 commission, first 3 months | — |
| ASK award | — | — | Best in Test 2025 (Tænk) |

Sources: [Nordnet ASK](https://www.nordnet.dk/tjenester/kontotyper/aktiesparekonto), [Nordnet prisliste](https://www.nordnet.dk/kundeservice/prisliste/standard-bonus-pro), [Saxo ASK FAQ](https://www.help.saxo/hc/en-us/articles/360035642351-Aktiesparekontoen-Frequently-Asked-Questions), [kurtage.dk ASK comparison](https://kurtage.dk/guider/bedste-aktiesparekonto).

### What this means for *your* trades

The min-commission floor is what bites at your position sizes, not the percentage.

| Trade | Nordea | Nordnet | Saxo |
|---|---|---|---|
| Buy €700 (Track A min position) | ~€3.90 | ~€3.35 | **~€0.92** |
| Buy €2,600 (Track A max position) | ~€5.20 | ~€2.60 | ~€2.08 |
| Buy €2,000 (Track B monthly pick) | ~€4.00 | ~€2.00 | ~€1.60 |

*(commission only; add ~0.25% FX = the dominant US-stock cost across all three, ~€1.75 per €700 leg.)*

- On **small tickets** (Track A's €700 floors, ~10–30 of them) Saxo's $1 min is materially cheaper — roughly **€3/trade saved vs Nordea**.
- On **larger tickets** the FX margin dominates and the three converge.
- **The recurring 0.25% FX is the real cost of a US universe** — none of the three escape it. The only structural fix is the parked P3 "EUR-denominated universe" idea (trade STOXX/Euronext names, no FX leg).

**Rough annual saving Nordea → Saxo:** Track A yearly rebalance (~15–30 small trades) + Track B (12 trades) ≈ **€80–130/year** on a €25k book (~0.3–0.5%). Real but not decisive on its own.

---

## What switching actually costs (money, effort, time, risk)

| Dimension | Reality |
|---|---|
| **Tax** | None extra. ASK is mark-to-market yearly; realizing positions to move is not a new taxable event. |
| **Money** | Possible exit/transfer fee from Nordea (⚠️ confirm). Re-buy commission + FX at Saxo if positions are liquidated rather than transferred in-kind. |
| **In-kind vs cash** | Many providers **cannot transfer ASK securities in-kind** — they require selling to cash, transferring cash, re-buying. That means crystallizing spreads + paying re-entry fees + FX again. |
| **Time out of market** | Transfers take **several weeks**, and you're typically **blocked from trading during the move**. Pick a low-activity window (e.g. right after a rebalance, not before one). |
| **Effort** | One-time: open Saxo ASK → instruct transfer → close Nordea ASK. A few forms, a few weeks of waiting, one careful timing decision. |

Sources: [Nordnet — closing an ASK at another bank](https://www.nordnet.dk/faq/aktiesparekonto/hvordan-lukker-jeg-min-aktiesparekonto-hos-anden-bank), [Danske — flyt værdipapirer](https://danskebank.dk/privat/find-hjaelp/investering/flyt-vaerdipapirer).

**Verdict on effort:** it's a one-time annoyance of a few weeks, best done in a quiet portfolio window. Not hard, just slow — and the out-of-market gap is the only real risk.

---

## The API payoff (why Saxo specifically)

Saxo OpenAPI gives the cockpit what no Danish bank otherwise offers:

- **`PositionsMe()`** — read your own live positions (OAuth-scoped, read-only).
- **24-hour developer token** — lets us prototype the sync with zero app-registration friction before committing to a full OAuth app key.
- Mature ecosystem: an `saxo_openapi` Python package already wraps it.

This turns the cockpit's daily stop-loss from "only works if you hand-record the position" into "knows your real position automatically" — and it does so **read-only**, so the bot can never trade. (Consistent with the standing rule: the system suggests, you execute.)

Sources: [Saxo Developer Portal — security/auth](https://www.developer.saxo/openapi/learn/security), [Saxo — live access token](https://openapi.help.saxo/hc/en-us/articles/4416636625041-How-can-I-get-an-access-token-for-the-live-environment), [hootnot/saxo_openapi](https://github.com/hootnot/saxo_openapi).

---

## Recommended v2 roadmap (phased, low-regret)

1. **Confirm the two ⚠️ numbers first** (cheap, no commitment): Nordea foreign-stock custody fee (B4) and Saxo's exact ASK commission tier. If Nordea charges a custody fee, the case for moving strengthens sharply.
2. **Prototype the Saxo API read path against a free/sim account** — no money moved. Build a `SaxoSync` adapter behind the existing holdings interface; prove `PositionsMe()` returns what we need. This validates the payoff before any switch.
3. **Decide the move** with both confirmed: if the API works and the custody fee is non-trivial, schedule the transfer for a quiet window (just after a rebalance).
4. **Execute the transfer**, then flip the cockpit's holdings source from manual/localStorage to `SaxoSync` (manual entry stays as the offline fallback).

**Design rule already in place:** holdings sit behind an adapter, so this is a drop-in — no rewrite of the cockpit or pipelines.

---

## Open items to confirm

- ⚠️ **B4** — Nordea foreign-stock custody fee (this is the swing factor; chase it).
- ⚠️ Saxo exact ASK commission % and FX margin at your expected volume (Classic tier).
- ⚠️ Whether Saxo supports **in-kind** ASK transfer or forces liquidation (drives switching cost).
- Lunar also offers an ASK and showed up in the kurtage.dk comparison — cheaper still on Danish names, but **no public API** and thinner foreign-stock support, so out of scope for the automation goal. Note and move on.

---

## Sources

- [Skat — Aktiesparekonto](https://skat.dk/borger/aktier-og-andre-vaerdipapirer/aktiesparekonto)
- [Expat Finance — The Aktiesparekonto (ASK) Guide 2026](https://expatfinance.dk/investing/the-aktiesparekonto-ask-guide-2026/)
- [Nordnet — Aktiesparekonto](https://www.nordnet.dk/tjenester/kontotyper/aktiesparekonto) · [Nordnet prisliste](https://www.nordnet.dk/kundeservice/prisliste/standard-bonus-pro) · [Nordnet — closing an ASK at another bank](https://www.nordnet.dk/faq/aktiesparekonto/hvordan-lukker-jeg-min-aktiesparekonto-hos-anden-bank)
- [Saxo — Aktiesparekonto FAQ](https://www.help.saxo/hc/en-us/articles/360035642351-Aktiesparekontoen-Frequently-Asked-Questions) · [Saxo Developer Portal](https://www.developer.saxo/openapi/learn/security) · [Saxo — live access token](https://openapi.help.saxo/hc/en-us/articles/4416636625041-How-can-I-get-an-access-token-for-the-live-environment) · [hootnot/saxo_openapi](https://github.com/hootnot/saxo_openapi)
- [kurtage.dk — Bedste aktiesparekonto 2026](https://kurtage.dk/guider/bedste-aktiesparekonto)
- [Danske Bank — flyt værdipapirer](https://danskebank.dk/privat/find-hjaelp/investering/flyt-vaerdipapirer)
