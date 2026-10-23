# TODO 0817 — Restore Exact-SHA CI and Aggregate Release Validation

- **ID:** 0817
- **Status:** backlog
- **Priority:** critical
- **Risk:** L3 — CI / release tooling
- **Depends:** 0816
- **Blocks:** 0822, 0823, 0824

## Problem

Current `main` CI fails before the regression suite runs because `scripts/check_agent_contract.py` expects the solo-owner governance section that was overwritten in `AGENTS.md`.

The workflow then attempts release-baseline validation without `test-results.xml`, creating a secondary error that obscures the root failure.

A continuous-improvement system needs CI to produce complete diagnostic evidence even when one independent gate fails.

## Scope and acceptance

- [ ] Restore `scripts/check_agent_contract.py` PASS after 0816.
- [ ] Run TODO consistency regardless of other independent gate results.
- [ ] Run repository governance validation.
- [ ] Run Development Agent governance validation.
- [ ] Run the complete pytest suite.
- [ ] Always generate `test-results.xml` if pytest starts.
- [ ] Run release-baseline validation only when the JUnit artifact exists.
- [ ] Run CC behavioral-contract validation independently where safe.
- [ ] Preserve individual gate failures rather than masking them.
- [ ] End the workflow in FAIL if any mandatory gate fails.
- [ ] Produce a single human-readable validation summary.
- [ ] Bind summary to exact commit SHA.
- [ ] Include pass/fail/not-run status for every mandatory gate.
- [ ] Include pytest pass/fail/skip counts.
- [ ] Include reason when a gate was legitimately not run.
- [ ] Upload JUnit and aggregate validation summary as artifacts.
- [ ] Ensure a missing artifact cannot accidentally result in PASS.
- [ ] Preserve release-baseline semantics.
- [ ] Preserve CC contract semantics.
- [ ] Preserve governance checker semantics.
- [ ] Do not add `continue-on-error` behavior that causes overall workflow PASS after mandatory failures.

## Required gates

The exact-head validation inventory must include:

- TODO consistency
- repository agent contract
- Development Agent governance
- focused Development Agent tests
- complete pytest regression suite
- release baseline
- covered-call behavioral contract
- validation summary integrity

## Required tests

- [ ] Governance failure still allows pytest diagnostics to run.
- [ ] Pytest failure still runs applicable post-test validation.
- [ ] Missing `test-results.xml` is represented as NOT_RUN/FAIL, never PASS.
- [ ] CC contract failure independently fails CI.
- [ ] Release-baseline drift independently fails CI.
- [ ] Successful run produces complete gate inventory.
- [ ] Aggregate summary SHA equals GitHub Actions head SHA.
- [ ] Summary cannot claim PASS with a missing mandatory gate.

## QA requirements

- [ ] Run against a deliberately broken `AGENTS.md`.
- [ ] Run against one deliberately failing pytest.
- [ ] Run against a deliberately changed CC contract.
- [ ] Run against clean expected source.
- [ ] Verify final clean run is completely green.
- [ ] Confirm full suite actually executes rather than being skipped after an earlier failure.

## Implementation guardrails

- Do not weaken any gate to make CI green.
- Do not rewrite release baselines automatically.
- Do not reduce CC thresholds.
- Do not silently ignore missing test artifacts.
- Do not introduce candidate-controlled CI configuration into trusted evidence.

## Done when

- [ ] Exact current candidate SHA has green CI.
- [ ] Full regression suite is represented in the receipt.
- [ ] Complete gate inventory is available from one artifact.
- [ ] Current production stack has a release-acceptance result rather than deployment-only evidence.
