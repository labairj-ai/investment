# Replace Synthetic Supervision with Authenticated Operational Run Evidence

- **ID:** 0788
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0775, 0783, 0787

## Problem

`certify()` currently marks `supervised_observation=PASS` when called with a non-empty actor string. This does not prove that a human supervised a real coding-agent lifecycle.

Autonomy eligibility must be based on actual governed development outcomes, not synthetic certification invocations.

## Scope and acceptance

- [ ] Separate `technical_certification` from `supervised_operational_run`.
- [ ] Technical certification validates harness invariants only.
- [ ] A supervised operational success must require real lineage:
  - candidate discovered
  - plan frozen
  - explicit human approval
  - supervised Builder run
  - independent Reviewer
  - complete trusted validation
  - evidence sealed
  - PR created
  - PR head verified
  - human review disposition recorded
- [ ] Bind supervising human identity to an authenticated application/CLI identity rather than free-form model input.
- [ ] Preserve actor, authentication source, decision timestamp and nonce in the immutable ledger.
- [ ] Prevent the same run from satisfying multiple required supervised-success slots.
- [ ] Only completed qualifying runs count toward `minimum_supervised_successes`.
- [ ] Failed, partial, abandoned, stale, reverted or scope-changed runs cannot count.
- [ ] Harness/config/contract hash changes invalidate prior supervised eligibility as defined by policy.
- [ ] Surface qualifying and non-qualifying supervised runs in the dashboard.

## QA requirements

- [ ] `actor="RJ"` passed in arbitrary JSON cannot establish supervised PASS by itself.
- [ ] Technical canary PASS alone does not increment supervised count.
- [ ] Fixture/replay runs cannot count as real supervised runs.
- [ ] Duplicate/replayed human decision cannot create another success.
- [ ] Successful qualifying real run counts exactly once.
- [ ] Changed harness hash excludes older evidence from current eligibility.
- [ ] Full suite passes.

## Implementation guardrails

- Do not store authentication secrets in the ledger.
- Do not make human identity an LLM-generated field.
- Supervised run evidence must remain separate from model/provider claims.
- Certification never grants merge authority.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
