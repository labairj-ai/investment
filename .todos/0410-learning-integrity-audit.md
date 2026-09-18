# Full Regression and Learning Integrity Audit

- **ID:** 0410
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0404, 0406, 0407

## Problem

The 170/170 test count covers only the targeted learning tests in `test_calibration.py`. The full test suite was larger in earlier versions, and it is not clear how many tests were removed or never migrated. More importantly, there is no single command or report that validates the end-to-end learning integrity of the live database: duplicate cohorts, horizon contamination, winner-count violations, orphaned observations, and shadow/paper disagreement are silent failure modes that accumulate over time without any operational alarm.

## Proposed approach

Two workstreams:

**1. Full test discovery pass**
- Run `pytest --collect-only` across all test files; confirm nothing is unintentionally skipped or excluded.
- Verify that all test classes from before 0379 are still present and passing.

**2. Integrity check command / report**
Add a standalone script or CLI command (e.g. `python check_integrity.py`) that queries the live DB and reports:

| Check | Severity |
|---|---|
| Duplicate/fragmented cohorts (multiple UUIDs for same sweep) | WARN |
| Winner-count violations: SUM(would_select) != 1 per cohort | BLOCK |
| Horizon-version contamination: sessions_v2 obs with NULL target | WARN |
| Orphan episode IDs: model_observations without a decision_episode | WARN |
| Mature observations without outcomes (outcome_alpha_90d IS NULL, past maturity) | WARN |
| PAPER_ACTIVE model trained on wrong horizon for current calendar config | BLOCK |
| Shadow vs paper selection disagreement: would_select episode != paper recommended episode for same cohort date | BLOCK |

The report should be runnable manually and also callable from the readiness API as `data_health.integrity`.

## Touches

- New script `check_integrity.py` or function in `agents/learning/calibration.py`
- Readiness/health API — surface integrity check result
- `tests/` — run `--collect-only` and fix any missing test modules
- Possible new test file `tests/test_integrity.py`

## Done when

- [ ] `pytest --collect-only` across all test files shows no unintended exclusions
- [ ] All test classes from pre-0379 commits are present and passing
- [ ] `check_integrity.py` (or equivalent) runs without error against the live DB
- [ ] Each integrity check has a test that injects a violation and confirms it is detected
- [ ] Shadow vs paper selection disagreement check is implemented and tested
