# Replace Calendar Approximations with Session-Exact Maturity Functions

- **ID:** 0397
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

Two independent calendar approximations remain in the codebase: `SESSIONS_V2_CALENDAR_DAYS = 130` in data health and `horizon_days = 91` in readiness. Neither matches the actual contract (63 NYSE trading sessions ≈ 3 calendar months). Because the approximations are looser than reality, a broken or stalled outcome-label pipeline can be hidden for several extra weeks before data health notices missing mature labels. The unit of maturity should be identical everywhere: outcome labeling, data-health eligibility, readiness maturity prediction, and paper-book holding horizon.

## Proposed approach

- Create one shared function, e.g. `maturity_date(start_date, horizon_version, horizon_label)`, backed by the market-calendar abstraction already present in the codebase.
- Replace `SESSIONS_V2_CALENDAR_DAYS = 130` in the data-health module with a call to this function.
- Replace `horizon_days = 91` in the readiness module with a call to this function.
- Compute health eligibility separately per horizon version (calendar_v1 vs sessions_v2) rather than reusing the target-version cutoff for all versions.
- Open question: where does the market-calendar abstraction currently live, and is it already importable from both health and readiness modules without circular imports?

## Touches

- Data health module (wherever `SESSIONS_V2_CALENDAR_DAYS` is defined and used)
- Readiness module (wherever `horizon_days = 91` is set)
- Market-calendar / trading-day utility (shared function to add here)
- Any tests that assert on the 130-day or 91-day cutoffs

## Done when

- [ ] `SESSIONS_V2_CALENDAR_DAYS = 130` constant is removed; eligibility uses exchange-session count
- [ ] `horizon_days = 91` constant is removed; readiness maturity uses exchange-session count
- [ ] A single shared `maturity_date()` (or equivalent) function is the sole source of truth for both
- [ ] Data-health coverage loop computes cutoffs independently for calendar_v1 and sessions_v2
- [ ] Existing tests pass; new test confirms maturity_date("sessions_v2") != a fixed 91- or 130-day offset
