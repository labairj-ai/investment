# End-to-End Time Contract Acceptance Test

- **ID:** 0680
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0668, 0669, 0670, 0671, 0672, 0673, 0674, 0675, 0676, 0677, 0678, 0679

## Problem

Individual subsystem fixes (persistence, API, dashboard, email, learning, market schedules) can each be correct in isolation while still failing end-to-end if a single event's instant drifts between creation, storage, learning, API response, and display. A single authoritative acceptance test proves the contract holds across the full lifecycle and across DST boundaries.

## Proposed approach

Create a synthetic event at a known UTC timestamp. Trace it through:

1. Persisted in UTC (storage layer)
2. Provenance references the same instant
3. Learning episode references the same instant
4. API exposes the same canonical UTC value
5. API/dashboard presentation converts to Eastern
6. UTC → Eastern → UTC round-trip produces the original instant
7. Run in an EST date (e.g. 2026-01-15)
8. Run in an EDT date (e.g. 2026-07-15)
9. Run around spring-forward (2026-03-08 02:00 ET)
10. Run around fall-back (2026-11-01 02:00 ET, ambiguous hour)

Test both that UTC identity is preserved end-to-end and that Eastern rendering is correct for each scenario. Fall-back ambiguity must be handled (not silently produce the wrong instant). Spring-forward nonexistent local times must not corrupt persisted data.

## Touches

- `tests/test_time_contract_e2e.py` — new test file
- All layers touched by 0668–0679

## Done when

- [x] UTC identity preserved end to end
- [x] Eastern rendering is correct
- [x] Calendar date conversion correct around midnight UTC
- [x] Fall-back ambiguity handled correctly
- [x] Spring-forward nonexistent local times cannot corrupt persisted data
- [x] Full test suite passes
- [x] Production canaries remain clean
## Outcome

Implemented as part of 0668-0680 batch commit.
