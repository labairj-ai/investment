# Repair the Macro Evidence Contract

- **ID:** 0558
- **Status:** backlog
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** none

## Problem

The macro evidence reader requests columns that financial ingestion does not populate, so stored quantitative financials can incorrectly yield evidence quality `none`. This is an evidence-plumbing defect, distinct from candidate certification coverage, and qualifies for the defect exception to the acceptance freeze.

## Proposed approach

- Introduce one canonical adapter over the actual company_financials schema. Derive net debt from total_debt minus cash and gross margin from gross_profit divided by revenue; obtain sector from the canonical ticker metadata source.
- Select the latest valid financial period available by the decision timestamp, with deterministic quarterly/annual precedence. Use compatible periods, currencies and units; preserve source columns, period_end, period_type, fetched/available timestamps, derivations and evidence-schema version.
- Specify units explicitly: the current prompt formats gross margin as percent and net debt as millions. Normalize at the adapter/prompt boundary and test the rendered values; do not silently pass a fraction as a percentage or raw currency as millions. Do not label a single-period revenue value as TTM.
- Missing, nonfinite, zero-denominator, stale or incompatible sources fail closed under a documented freshness policy. Preserve legitimate zero values and negative net debt. Do not invent interest coverage, foreign revenue percentages or geo evidence.
- Keep existing dimension evidence thresholds unchanged. Measure the actual improvement in holding evidence coverage; dollar and geo may remain unavailable.
- Compare canonical prompts before and after the repair. Expected path: version the evidence/scorer contract and validation configuration as v1.8, run formal N=20 acceptance and current-contract refresh/verification, retain v1.7 artifacts, and start a separate experiment epoch. Omit reacceptance only if tests prove prompt inputs and scorer behavior are unchanged.

## Touches

portfolio_ai.py; financials_fetcher.py; scripts/validate_macro_scorer.py; config/; tests/

## Done when

- [ ] Real-schema fixtures derive net debt and gross margin from compatible latest available rows, with unit-correct prompt output.
- [ ] Missing values, zero revenue, out-of-order ingestion, mixed periods, stale periods and future availability are tested; an XOM-like fixture with valid stored financials no longer incorrectly yields all none.
- [ ] Before/after evidence coverage is reported without relaxing thresholds; dollar/geo gaps remain explicit.
- [ ] Prompt impact is documented and, if changed, v1.8 formal acceptance and production verification pass without overwriting v1.7; production macro influence remains zero.
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced.
