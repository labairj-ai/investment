# Complete Experiment Capital Contract in Baseline

- **ID:** 0444
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0442

## Problem

`config/experiment_baseline.json` records a single `initial_capital: 10000`, which
comes from the shadow brokerage policy account (`trading_policy.json`). But the
champion/challenger virtual books use `_STARTING_CASH = 100_000`. A reader reviewing
performance months later cannot tell which capital base the "frozen baseline" refers
to, nor whether the $10k vs $100k difference is intentional. Both figures need to be
recorded separately with unambiguous labels.

## Proposed approach

- Locate the authoritative source of `_STARTING_CASH` (likely `calibration.py` or
  the trade engine's virtual-book initialization) and import it in `freeze_baseline.py`
  rather than hard-coding.
- Add two explicit fields to the baseline JSON:
  - `shadow_account_initial_capital` (from `trading_policy.json` → `starting_capital`)
  - `champion_book_initial_capital` and `challenger_book_initial_capital` (from
    `_STARTING_CASH` or equivalent constant)
- Remove the ambiguous single `initial_capital` field.
- Confirm (and document in the baseline) whether the $10k/$100k split is intentional:
  shadow brokerage = real-money risk limit; virtual books = larger notional for
  statistical sensitivity. If not intentional, fix one of the two values first.
- Regenerate `config/experiment_baseline.json` with the corrected fields and recommit.

## Touches

- `scripts/freeze_baseline.py`
- `config/experiment_baseline.json` (regenerated)
- `agents/learning/calibration.py` or wherever `_STARTING_CASH` is defined

## Done when

- [ ] `experiment_baseline.json` contains `shadow_account_initial_capital` and `champion_book_initial_capital` / `challenger_book_initial_capital` as distinct fields
- [ ] Ambiguous single `initial_capital` field is removed
- [ ] `freeze_baseline.py` derives virtual-book capital from the authoritative constant, not a hard-coded literal
- [ ] A comment or `_note` field in the JSON explains the intended relationship between the two capital figures
