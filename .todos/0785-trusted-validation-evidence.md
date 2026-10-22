# Make Validation Evidence Harness-Generated and Non-Spoofable

- **ID:** 0785
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0770, 0784

## Problem

Development evidence receipts can currently accept validation records supplied through operator input during the sealing step. Although the coding model cannot directly exploit this path, the evidence chain does not prove that every claimed PASS result was actually produced by the trusted validation harness.

A coding-agent PR must never become PR-ready based on caller-supplied PASS metadata.

## Scope and acceptance

- [ ] Remove externally supplied validation result objects from the `seal` workflow.
- [ ] Define one canonical validation manifest containing every mandatory development-agent gate.
- [ ] Execute all mandatory validation commands through trusted harness code.
- [ ] Mandatory validations must include at minimum:
  - focused tests
  - full test suite
  - exact release-baseline check
  - CC behavioral-contract check
  - coding-agent contract check
  - TODO consistency check
  - development-agent governance check
- [ ] Persist validation results immediately after execution as immutable ledger events.
- [ ] Bind every validation result to:
  - candidate ID
  - TODO ID
  - base SHA
  - exact candidate head SHA
  - complete source hash
  - command contract/version
  - sandbox image digest
  - start/end timestamps
  - exit code
  - test inventory where applicable
- [ ] `seal` must reconstruct the receipt exclusively from trusted persisted validation events.
- [ ] Reject sealing when any mandatory result is missing, stale, duplicated, associated with another candidate, or bound to another SHA.
- [ ] Reject operator/model claims such as `{"full_suite":"PASS"}` unless corresponding trusted execution evidence exists.
- [ ] Re-running validation after a code change must invalidate earlier evidence automatically.
- [ ] Preserve explicit `UNAVAILABLE`, `PARTIAL`, `FAIL`, and `NOT_RUN`; none may be converted to PASS by caller input.

## QA requirements

- [ ] Inject forged PASS JSON for every required validation and prove sealing rejects it.
- [ ] Run valid tests, modify one tracked file, and prove all prior evidence becomes stale.
- [ ] Mix validation results from two candidates and prove sealing rejects them.
- [ ] Mix validation results from two commits of the same candidate and prove sealing rejects them.
- [ ] Simulate missing JUnit output and prove the test gate cannot PASS.
- [ ] Simulate successful process exit with failing JUnit inventory and prove the gate fails.
- [ ] Full repository suite passes.
- [ ] Existing release-baseline and CC behavioral gates remain unchanged.

## Implementation guardrails

- The Builder and Reviewer cannot create validation PASS records.
- Do not trust model-generated test counts.
- Do not infer success from stdout.
- Do not weaken required validation inventory to support the agent.
- Validation evidence must be produced by trusted application code only.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
