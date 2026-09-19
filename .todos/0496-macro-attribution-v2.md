# Fix Macro Attribution Query, Horizon, and Missing-Data Contamination

- **ID:** 0496
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0495

## Problem

`macro_attribution.py` has three concrete bugs. First, it queries `o.outcome_alpha` but the outcome labeler writes the field as `alpha`, so the join silently returns empty data (caught by exception, looks like "no episodes yet"). Second, it joins all `episode_outcomes` rows without filtering on horizon, so one episode appears up to 5 times (1w/1m/3m/6m/12m), inflating N and averaging incompatible horizons. Third, missing `rate_sensitivity` values use `(e["macro"].get("rate_sensitivity") or 0)` which converts None → 0 and places unsupported holdings into the "low sensitivity" bucket — exactly the contamination 0487 eliminated.

## Proposed approach

- Fix column name: `o.alpha` not `o.outcome_alpha`
- Add `WHERE o.horizon = '3m'` (match the current Learning Lab experiment horizon — Ridge model is focused on 3m alpha)
- Replace `(value or 0)` bucket assignments with explicit None exclusion:
  ```python
  rs = e["macro"].get("rate_sensitivity")
  if rs is None:
      unknown_count += 1
      continue
  ```
  Report `n_unknown` per bucket so coverage gaps are visible, not hidden.
- Make DB/query errors raise visibly instead of returning empty dataset. Add a `--debug` flag that prints the SQL error.
- Add MFE and MAE alongside alpha in bucket summaries (already available in episode_outcomes).
- Include `n_unknown` in output so coverage gaps are explicit.

## Touches

- `scripts/macro_attribution.py`

## Done when

- [ ] `o.alpha` used (not `o.outcome_alpha`); query runs without exception on a real DB
- [ ] Explicitly filters to `horizon = '3m'`
- [ ] None macro values excluded from buckets and counted separately as `n_unknown`
- [ ] MFE and MAE included in bucket summaries
- [ ] DB/query error fails loudly (not silently returns empty data)
