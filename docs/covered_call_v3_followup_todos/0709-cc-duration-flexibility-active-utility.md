# Activate Covered Call Duration and Flexibility Economics in V3 Utility

- **ID:** 0709
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0695, 0708

## Problem

The current V3 computes a `sequential_short_cycle_benchmark`, but the benchmark is diagnostic only. V3 ranking still primarily uses:

`utility_margin / DTE`

This improves on nominal premium ranking but does not explicitly charge longer-dated calls for the lost opportunity to reprice strike, IV, thesis state, and market regime.

## Proposed approach

Introduce a bounded `flexibility_cost` into V3 utility.

Compare each candidate's expected adjusted alpha to a conservative short-cycle alternative.

Possible formulation:

`flexibility_cost = max(0, benchmark_short_cycle_value - candidate_adjusted_alpha) * lambda`

where:

- benchmark uses only currently observed shorter-cycle candidates;
- future second-cycle availability is discounted;
- future alpha retention is conservative;
- `lambda` is explicit/versioned and initially <= 1.

Then:

`duration_adjusted_alpha = adjusted_cc_alpha - flexibility_cost`

and:

`duration_adjusted_utility_margin = duration_adjusted_alpha - utility_hurdle`

Use this value for V3 challenger ranking only after tests pass.

Persist:

- benchmark candidate/reference
- benchmark assumptions
- availability discount
- alpha-retention assumption
- flexibility cost
- duration utility version

## Guardrails

- Do not assume a future call can always be sold.
- Do not assume today's IV persists.
- Do not count the same expected roll/management cost twice.
- No universal 30-DTE preference.
- Long DTE can still win when its economics genuinely dominate.
- Missing shorter-cycle alternatives => no fabricated flexibility penalty; mark benchmark unavailable.
- Any change to duration utility increments scorer version and restarts prospective evidence eligibility.

## Acceptance tests

### Flat environment
- [ ] If 30-DTE and 60-DTE economics are proportional and future availability is heavily discounted, long DTE is not unfairly penalized.
- [ ] If two sequential shorter cycles clearly dominate, 60-DTE receives positive flexibility cost.

### Term structure
- [ ] Upward IV term structure can make longer DTE win if premium/alpha sufficiently compensates.
- [ ] Inverted term structure can favor shorter DTE.
- [ ] Event-loaded near-term IV does not create a false short-cycle benchmark if policy blocks earnings exposure.

### Ranking
- [ ] Candidate ranking changes only through explicit duration-adjusted margin.
- [ ] Long-DTE candidate with larger nominal premium but lower duration-adjusted value loses to superior shorter candidate.
- [ ] Long-DTE candidate with genuinely higher total expected value can still rank first.

### Accounting
- [ ] Utility decomposition reconciles expected premium, upside cost, management cost, execution cost, tax cost, flexibility cost, and duration-adjusted alpha.
- [ ] No component is subtracted twice.

## QA requirements

### Backend QA
- [ ] Run V3 challenger rankings side-by-side before/after duration adjustment for current portfolio.
- [ ] Produce a report of changed V3 winners and why.
- [ ] Verify V2 champion is unchanged.
- [ ] Verify prior prospective V3 evidence is excluded after scorer-version change.

### Dashboard QA
- [ ] Learning Lab shows flexibility cost and benchmark assumption.
- [ ] Changed-winner cases are auditable.
- [ ] Missing benchmark is shown as unavailable, not zero-value superiority.

### Promotion guard
- [ ] New duration-utility scorer version cannot inherit promotion eligibility from the prior V3 scorer.
