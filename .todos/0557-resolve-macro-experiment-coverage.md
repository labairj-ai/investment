# Resolve Macro Experiment Opportunity Coverage

- **ID:** 0557
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0558, 0559, 0560, 0561, 0562

## Finding

The authoritative production universe has 79 unowned Opportunity Hunter candidates
and zero overlap with the eight tickers carrying accepted per-dimension eligibility.
The new experiment therefore records coverage exclusions until valid accepted
macro evidence becomes available for its actual opportunity universe.

The deployed provenance check also finds zero currently usable dimensions across
all eight accepted tickers under runtime evidence-quality requirements. For
example, XOM's current score payload records `none` for every dimension's evidence
quality despite valid acceptance, scorer and run provenance. Formal eligibility
does not override missing runtime evidence. This is a second data-readiness
constraint to resolve before interpreting any experiment result.

## Reviewed diagnosis — 2026-09-21

This umbrella separates two problems. The first is a confirmed evidence-adapter
defect: `_fetch_company_evidence()` requests fields absent from the actual
`company_financials` schema, while ingestion stores debt, cash, gross profit and
revenue from which useful evidence can be derived. The earlier blanket framing
as a data-readiness limitation was incomplete. The canonical prompt includes
these evidence fields, so repairing them is expected to require a versioned v1.8
scorer/evidence contract and formal reacceptance under the real-defect exception.

The second is legitimate architectural coverage: original acceptance validation
is ticker-specific and cannot certify the unrelated opportunity universe simply
by generating scores. Supplemental immutable coverage certification must remain
separate from original acceptance, with runtime evidence quality still required.

## Resolution sequence

1. [0558](0558-repair-macro-evidence-contract.md): repair the canonical evidence adapter, units and point-in-time provenance; revalidate changed scorer inputs.
2. [0559](0559-score-separate-macro-candidate-universe.md): score candidate targets separately using the canonical scorer.
3. [0560](0560-certify-supplemental-macro-ticker-coverage.md): certify supplemental ticker/dimension coverage under the accepted contract.
4. [0561](0561-balance-prospective-macro-cohort-coverage.md): version the protocol for the inclusive bounded envelope and common dimensions.
5. [0562](0562-run-prospective-macro-coverage-canary.md): verify a real prospective stage-0 canary before declaring usable collection started.

0549–0556 remain implemented. Preserve v1.7 artifacts, evidence thresholds,
original opportunity-universe membership and historical cohorts. No runtime-only
certification, retrospective attachment, blanket certification of all 79 stocks,
or production macro influence is permitted. The original review created the implementation backlog; the completion record below supersedes that operational status.

## Done when

- [x] Evidence-adapter repair and required v1.8 reacceptance are complete (0558).
- [x] Separate candidate scoring and supplemental certification provide a compatible coverage path (0559–0560).
- [x] Coverage-balanced prospective enrollment and the real canary pass (0561–0562).
- [x] A real future sweep records usable accepted macro candidates in both arms.
- [x] Prospective collection starts without any production recommendation influence.

Outcome maturation and evidence evaluation follow collection; neither can be
declared complete before the preregistered horizon and uncertainty requirements.

## Completion — 2026-09-21

Implemented and verified in production. See [rollout evidence](../docs/macro-value-experiment.md#verified-rollout--2026-09-21) for acceptance, certification, canary and collection records. Full regression: 1,362 passed, 16 skipped. Production remains stage 0; outcome maturation is pending.
