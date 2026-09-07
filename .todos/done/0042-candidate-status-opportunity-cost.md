# Fix Candidate Status Mismatch in Opportunity-Cost Score

- **ID:** 0042
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The Sell/Trim agent's O-score (`_score_O()`) queries `candidate_universe WHERE status = 'tracking'`. But the candidate system uses statuses `active`, `watch`, `owned`, `rejected` — not `tracking`. The opportunity comparison in the Opportunity Hunter (and the candidate comparison UI) explicitly evaluates `active` and `watch` rows. So `_score_O()` almost always finds zero candidates, making the O component of `SellStrength` (10% weight) permanently near-zero and meaningless. There is no canonical enum for candidate status defined anywhere.

## Proposed approach

- Define a canonical status enum (as a constant or small class) in a shared location: `ACTIVE`, `WATCH`, `OWNED`, `REJECTED`, `ARCHIVED`.
- Update `_score_O()` in `sell_trim_agent.py` to query `WHERE status IN ('active', 'watch')`.
- Audit `candidate_universe` rows in the live DB to confirm actual status values in use; migrate any `'tracking'` rows to `'active'` or `'watch'` as appropriate.
- Update any other code that sets or queries `candidate_universe.status` to use the canonical values.
- Open question: is `ARCHIVED` needed or does `REJECTED` cover retired candidates?

## Touches

- `agents/sell_trim_agent.py` (`_score_O`)
- `agents/opportunity_agent.py` (confirm status values used there)
- `serve.py` (any route that inserts into `candidate_universe`)
- DB migration: update existing `status='tracking'` rows

## Done when

- [x] `_score_O()` queries `status IN ('active', 'watch')`
- [x] No `status = 'tracking'` remains anywhere in Python code
- [x] Canonical status constants are defined in one place and imported where needed
- [x] Running `_score_O()` against the live DB returns at least the expected Buffett-winner candidates (5 returned: BZ 88, MSGM 85, NTES 84, FHI 83, DDI 83)
- [x] O-score is non-zero for a holding when strong candidates exist in the universe
- [x] **Backend QA:** deployed to optiplex; service active, API responding
- [x] **Frontend QA:** no API surface change
- [x] **No service regression:** clean restart confirmed

## Outcome

Two files changed:

- **`agent_db.py`**: Added `CAND_ACTIVE`, `CAND_WATCH`, `CAND_OWNED`, `CAND_REJECTED`, `CAND_OPPORTUNITY_STATUSES = ("active", "watch")` as module-level constants immediately after `DB_PATH`.
- **`agents/sell_trim_agent.py`**: Imported `CAND_OPPORTUNITY_STATUSES`; fixed `_score_O()` to query `WHERE status IN ('active','watch')` using parameterized placeholders. No DB migration needed — live DB had zero `tracking` rows (76 `active`, 1 `owned`, 3 `rejected`). O-score now sees all 76 active candidates. 0048 (merge manual candidates into hunter universe) is now unblocked.
