# Balance Prospective Macro Cohort Coverage

- **ID:** 0561
- **Status:** done
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** 0559, 0560

## Problem

The current treatment can observe cohorts where some candidates receive eligible macro adjustments and others receive none, confounding macro value with evidence availability. Require common information coverage for every candidate that can mathematically win under the bounded treatment.

## Proposed approach

- Version the experiment protocol before usable collection starts; verify the live cohort count first. Let the new protocol hash create a new epoch and preserve all prior epochs and excluded cohorts unchanged.
- Among candidates passing the same base/risk eligibility in both arms, compute Bmax and include every candidate with base_score >= Bmax - 2*Mmax. At Mmax=5 this is the inclusive Bmax-10 envelope; derive the bound from the protocol cap rather than hard-coding it.
- An uncertified/unavailable candidate inside the envelope excludes the cohort as coverage_incomplete. For coverage-complete envelope candidates, compute the intersection of their usable dimensions; exclude an empty intersection as no_common_usable_macro_dimensions.
- Calculate every decision-relevant treatment score using exactly that common dimension set and original weights, without renormalization or imputation. Preserve the full original universe and consistent tie-breaking in both arms; outside-envelope candidates cannot block collection or exceed the cap.
- Freeze the envelope, common dimensions, coverage/certification identities, exclusion reasons and both selections in the ledger. Make exploratory ablations respect the cohort's common dimensions so diagnostics do not reintroduce unequal coverage.
- Retain point-in-time guards, epoch separation and stage 0. Show coverage exclusions/common dimensions in Learning Lab.

## Touches

agents/learning/macro_experiment.py; agents/learning/macro_provenance.py; config/macro_experiment_v1.json (successor protocol); agent_db.py; generate_dashboard.py; tests/

## Done when

- [x] Boundary/tie tests prove a candidate strictly below Bmax-2*Mmax cannot win; the exact boundary is included and cap changes update the envelope.
- [x] AAA={rate,inflation,dollar}, BBB={rate,inflation}, CCC={rate,inflation,geo} yields common={rate,inflation} and equal dimension treatment for all three.
- [x] Missing certification inside the envelope and empty common dimensions have distinct exclusions; missing coverage outside the envelope does not block an otherwise valid cohort.
- [x] No weights are renormalized, no historical cohort is rewritten, no after-decision score/certification is attached, and no production influence changes.
- [x] QA evaluation conducted: functionality verified working, no regressions introduced.

## Completion — 2026-09-21

Implemented and verified in production. See [rollout evidence](../docs/macro-value-experiment.md#verified-rollout--2026-09-21) for acceptance, certification, canary and collection records. Full regression: 1,362 passed, 16 skipped. Production remains stage 0; outcome maturation is pending.
