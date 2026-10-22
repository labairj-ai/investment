# Approved theses are ignored by policy and invalidation readers

- **ID:** 0745
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** none
- **Review finding:** 01

## Problem and reproduced behavior

Locations: [approval writer](../../agent_db.py:2665), [CC policy reader](../../agents/covered_call_agent.py:137), [dashboard management reader](../../covered_call_rec.py:1625), [dependency reader](../../agents/dependency_checker.py:45), [policy hash reader](../../agent_db.py:2208), [thesis version hash](../../agent_db.py:1719).

`approve_thesis()` writes `status='ACTIVE'`; these readers query `status='active'` on an ordinary case-sensitive TEXT column. They miss the approved record and silently use defaults or an empty version map. Reproduction approved a thesis with `strategy='NONE'` and assignment forbidden: the CC reader returned `INCOME` and assignment allowed; dependency versions were `{}`. Policy changes also fail to change relevant invalidation hashes.

## Touches

- `agent_db.py`
- `agents/covered_call_agent.py`
- `covered_call_rec.py`
- `agents/dependency_checker.py`

## Acceptance criteria

- [x] Choose one canonical thesis status representation and audit every investment_theses status writer and reader; preserve candidate-universe status semantics.
- [x] Approve a real DRAFT carrying strategy NONE and assignment_policy.allowed=false; agent and dashboard readers must return those exact restrictions.
- [x] Approved thesis version and policy changes must invalidate recommendation dependencies, no-action input hashes and covered-call policy hashes.
- [x] Handle legacy lowercase thesis records explicitly and idempotently; ambiguous multiple-active records must not silently select a permissive policy.
- [x] Add end-to-end approval-to-reader regressions; satisfy the existing covered-call behavioral release checks for any protected behavior change.

## Evidence and validation

- [Review finding 1](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Canonical/legacy thesis status readers, fail-closed ambiguous CC policies, assignment-policy hash coverage and approval regressions.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
