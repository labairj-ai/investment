# Automated Test Suite + CI

- **ID:** 0065
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** P1
- **Depends:** 0059, 0060

## Problem

The only test file is `test_cc_ai.py`. There is no `tests/` directory, no pytest suite, and no CI. The project now contains substantial deterministic financial logic — snapshot aggregation, dependency checking, outcome math, confidence scoring, critic veto rules — where a subtle regression is far more damaging than a crash. Without automated tests, every change carries silent risk.

## Proposed approach

### 1. Directory structure

```
tests/
  conftest.py              # shared fixtures: in-memory DB, sample snapshot
  test_snapshot.py         # lot aggregation, as_of timestamps
  test_dependency_checker.py
  test_outcome_evaluator.py
  test_confidence.py
  test_sell_trim_scores.py
  test_agent_db.py
```

### 2. Key test cases (from design notes)

| Test | Expected result |
|------|----------------|
| 2 lots of 60 ANET shares + 70 ANET shares | Snapshot = 120 shares, weighted avg_cost |
| 105% layer targets in config | Config validation fails |
| Unknown dependency type | Never silently considered valid — superseded |
| MACRO_STATE changes 20 points | CC rec superseded |
| New financial quarter available | Opportunity rec superseded |
| Critical thesis pillar violated (T score = 0) | SellStrength ≥ 90, action = EXIT |
| Theoretical CC pricing | Confidence capped (EvidenceBundle.uses_theoretical_pricing=True) |
| CC strike below cost basis | Critic veto |
| Accepted 50% TRIM | `recommended_path_return` ≠ full hold_r |
| Rejected EXIT | `actual_return` = hold_r |
| Accepted EXIT with execution record | Execution ledger controls actual_return |
| No recommendation from agent | NO_ACTION persisted to DB |
| Stale Friday quote evaluated Sunday | `price_as_of` = Friday; freshness penalty applied |

### 3. Test fixtures

- `conftest.py` creates an in-memory SQLite DB with schema from `agent_db.init_db()`
- `sample_snapshot()` fixture returns a deterministic `PortfolioSnapshot` with 3–4 holdings
- `sample_holding(ticker, shares, avg_cost, price)` factory for parameterized tests
- No real network calls in any test — mock `ollama_client.generate_structured`

### 4. CI: GitHub Actions

```yaml
# .github/workflows/test.yml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pytest yfinance
      - run: pytest tests/ -v
```

No external service calls in CI — all financial data mocked.

### 5. Coverage target

Aim for 80%+ coverage on `dependency_checker.py`, `snapshot.py`, `outcome_evaluator.py`, `confidence.py`, and `sell_trim_agent.py` score functions.

## Touches

- `tests/` directory (new)
- `.github/workflows/test.yml` (new)
- `agent_db.py` — verify `init_db()` can operate on in-memory `:memory:` DB
- Minor: may expose edge cases in existing code requiring small fixes

## Done when

- [ ] `pytest tests/` passes with 0 failures on the Mac dev copy
- [ ] All 13 test cases from the table above are implemented
- [ ] GitHub Actions CI runs on push and PRs
- [ ] No test touches real network, real DB, or real LLM endpoint
- [ ] Coverage report shows ≥80% on core deterministic modules
- [ ] **Backend QA:** CI passes on a push to GitHub; green checkmark on main branch
