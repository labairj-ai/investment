# TODO 0818 — Make Trusted Validation Results Candidate-Nonwritable

- **ID:** 0818
- **Status:** in-progress
- **Priority:** critical before autonomy
- **Risk:** L5 — Development Agent trust boundary
- **Depends:** 0816, 0817
- **Blocks:** 0822 autonomous progression, 0824

## Problem

The current hardened validator correctly protects approved-base tests and test-runner configuration, but candidate application code executes inside the same validation process that writes `/artifacts/results.xml`.

The artifact directory is writable by the UID running candidate code.

A malicious candidate may therefore be able to attempt to forge, replace, truncate or pre-create the validation artifact.

Expected test-inventory comparison substantially reduces the attack surface but does not make the candidate process fully non-authoritative over its own PASS evidence.

## Scope and acceptance

- [ ] Treat candidate application code as hostile during validation.
- [ ] Candidate code must not control the authoritative validation-result channel.
- [ ] Separate test execution from trusted receipt generation.
- [ ] Trusted host/orchestrator must determine process exit state.
- [ ] Trusted collector must determine expected test inventory.
- [ ] Candidate must not be able to replace final JUnit evidence.
- [ ] Candidate must not be able to pre-create a valid PASS artifact.
- [ ] Candidate must not be able to modify trusted oracle metadata.
- [ ] Candidate must not be able to modify trusted test configuration.
- [ ] Candidate must not be able to modify validation scripts.
- [ ] Candidate must not be able to modify the validator bootstrap.
- [ ] Candidate must not be able to inject pytest plugins.
- [ ] Candidate must not gain host networking.
- [ ] Candidate must not gain Docker socket access.
- [ ] Candidate must not gain GitHub credentials.
- [ ] Candidate must not gain access to the production database.
- [ ] Candidate must not gain access to SSH credentials.
- [ ] Preserve digest-pinned validator image requirement.
- [ ] Preserve `--network=none`.
- [ ] Preserve read-only source mount.
- [ ] Preserve no-new-privileges and capability drop.
- [ ] Preserve approved-base regression test oracle.
- [ ] Preserve exact expected test inventory comparison.

## Preferred design

Implement one of the following, preferring the strongest design that remains maintainable:

### Option A — External collector

Run candidate tests in one constrained process/container and send bounded structured events through a trusted FD/pipe owned by an external collector.

The candidate process must not have filesystem write access to the final receipt location.

### Option B — Two-stage container execution

Run pytest in the isolated candidate container.

After termination, run a separate trusted collector process/container with:

- read-only access to raw test output;
- no candidate code execution;
- sole write access to the final normalized validation artifact.

### Option C — Immutable raw event stream

Capture pytest output/events into a channel that candidate Python code cannot open or replace and construct the final JUnit/receipt outside the candidate interpreter.

Do not treat merely changing file ownership as sufficient unless the candidate process provably lacks a write path.

## Adversarial tests

Create deliberate candidate changes that attempt:

- [ ] writing `/artifacts/results.xml`;
- [ ] replacing `/artifacts/results.xml`;
- [ ] deleting the JUnit result;
- [ ] pre-creating a fake PASS JUnit;
- [ ] calling `os._exit(0)` during a failing test;
- [ ] monkeypatching pytest JUnit classes;
- [ ] monkeypatching test result hooks;
- [ ] injecting `pytest_plugins`;
- [ ] creating `conftest.py`;
- [ ] creating `sitecustomize.py`;
- [ ] modifying `sys.modules`;
- [ ] shadowing pytest;
- [ ] shadowing a trusted application import;
- [ ] changing current working directory to escape source constraints;
- [ ] symlink-based artifact replacement;
- [ ] hard-link attempts;
- [ ] fork/subprocess manipulation;
- [ ] test inventory truncation;
- [ ] duplicate test identity generation;
- [ ] SIGTERM/timeout behavior;
- [ ] process crash;
- [ ] excessive output;
- [ ] oversized artifacts.

Every attack must result in FAIL or UNAVAILABLE, never PASS.

## QA requirements

- [ ] Clean candidate validation passes.
- [ ] Candidate-written tests cannot influence mandatory regression evidence.
- [ ] Existing trusted-base regression tests continue to work.
- [ ] Timeout cleanup leaves no container behind.
- [ ] Host source hash remains unchanged.
- [ ] Candidate tree hash is independently recorded.
- [ ] Trusted test-tree hash is independently recorded.
- [ ] Final receipt includes validator image digest.
- [ ] Final receipt includes approved base SHA and candidate head SHA.

## Implementation guardrails

- Do not rely on candidate stdout claims.
- Do not let candidate code create authoritative PASS JSON.
- Do not weaken expected-test inventory comparison.
- Do not enable autonomous implementation until this task is complete and certified.

## Done when

- [ ] Adversarial validation suite passes.
- [ ] Technical certification explicitly covers artifact integrity.
- [ ] Exact-head CI passes.
- [ ] New containment receipt is recorded.
