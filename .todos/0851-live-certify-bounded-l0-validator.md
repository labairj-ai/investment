# TODO 0851 — Live-Certify the Bounded L0 Validator

- **ID:** 0851
- **Status:** backlog
- **Priority:** critical
- **Risk:** L5 — validation trust boundary
- **Parent:** 0847
- **Depends:** merged PR #14 source foundation
- **Blocks:** 0853

## Objective

Install and prove the already-designed bounded L0 validator on the actual model/application host without expanding its scope.

This is an operational acceptance task, not a new validator-design task.

## Required scope

Support only the current approved L0 surfaces:

- Markdown documentation;
- plain text;
- explicitly approved static documentation metadata.

Continue to reject executable code, active HTML, application logic, financial logic, authentication, deployment code and governance changes.

## Installation acceptance

- [ ] Install reviewed validator outside all candidate worktrees.
- [ ] Use the dedicated validator service identity.
- [ ] Validator source is root/operator controlled and nonwritable by Builder.
- [ ] Private Unix socket permissions verified.
- [ ] Signing material permissions verified.
- [ ] Protected Git authority store is nonwritable by candidate/Builder.
- [ ] Network access denied.
- [ ] Docker socket access denied.
- [ ] Production investment DB access denied.
- [ ] SSH/user credential access denied.
- [ ] Service starts cleanly and reports healthy.
- [ ] No existing Qwen/MLX or investment services are changed.

## Live adversarial acceptance

Exercise the installed service against:

- [ ] valid L0 document edit;
- [ ] active-markup injection;
- [ ] executable-file change;
- [ ] trusted-test deletion;
- [ ] trusted-test rewrite;
- [ ] fake PASS artifact;
- [ ] fake JUnit artifact;
- [ ] symlink substitution;
- [ ] timeout;
- [ ] crash;
- [ ] duplicate/truncated result inventory;
- [ ] runtime binary mismatch;
- [ ] validator-source mismatch;
- [ ] key/socket permission attack;
- [ ] candidate socket/key access attempt;
- [ ] network access attempt;
- [ ] production DB access attempt.

Every unsupported/hostile case must fail closed.

## Required evidence

Preserve a sanitized live acceptance receipt containing:

- exact application SHA;
- validator source digest;
- runtime identity;
- service identity;
- test matrix and results;
- created/observed timestamps;
- scope = L0 static only;
- fixture_only = false;
- no secrets or production data.

## Owner-facing result

Expose only:

L0 Validator: READY

or

L0 Validator: NOT READY — <plain-English reason>

Detailed evidence remains diagnostic.

## Guardrails

- Do not add L1/L2 support.
- Do not enable Builder execution.
- Do not enable supervised loop.
- Do not enable autonomous implementation.
- Do not change investment logic or state.
- Do not deploy any model.
- Do not alter existing MLX services.

## QA

Run focused Development Agent tests, full repository tests, TODO consistency, Development Agent governance and all existing release gates after any source/config changes needed for host installation support.

## Done when

The installed live L0 validator is independently verified READY and 0847 can be closed on real evidence.
