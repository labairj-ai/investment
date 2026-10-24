# TODO 0836 — Select and Implement Independent Validation Oracle Backend

- **ID:** 0836
- **Status:** superseded
- **Priority:** critical
- **Risk:** L5 — validation trust boundary
- **Parent:** 0826
- **Depends:** 0835
- **Blocks:** 0837, 0841

## Objective

Replace the current oracle protocol boundary with a real independent validator whose PASS result cannot be manufactured by candidate-controlled code.

## Architecture requirements

Candidate-controlled Python must not be capable of deciding whether trusted validation passed.

The selected design must independently establish:

- repository identity;
- approved base SHA;
- candidate SHA;
- candidate source-tree digest;
- trusted test-tree digest;
- expected trusted test inventory;
- command class;
- validator runtime/image identity;
- process exit result;
- timeout result;
- containment result;
- oracle protocol version.

## Recommended initial scope

Support trusted autonomous/supervised validation only for bounded low-risk classes.

**L0:** documentation, metadata, static text and non-executable configuration explicitly classified L0. Use trusted static checks with no candidate code execution.

**L1:** tests/tooling that cannot replace mandatory trusted tests. Candidate tests may run as supplemental evidence only. Trusted mandatory tests come from approved base authority.

**L2:** passive CSS/static UI. Use trusted browser/static/accessibility validation.

**Executable application code:** Python, JavaScript, active HTML, routing, authentication and similar executable changes remain L3+ and outside early autonomous eligibility.

## Required design

- [ ] Independent oracle process.
- [ ] Candidate cannot write oracle result.
- [ ] Candidate cannot access signing secret.
- [ ] Candidate cannot modify trusted tests.
- [ ] Candidate cannot modify expected inventory.
- [ ] Oracle independently observes process exit.
- [ ] Oracle independently observes timeout.
- [ ] Network disabled where not explicitly required.
- [ ] No production DB access.
- [ ] No GitHub write credentials.
- [ ] No SSH credentials.
- [ ] No Docker socket exposure to candidate.
- [ ] Results cryptographically/integrity bound to exact candidate/base.

## Required adversarial tests

Attempt each attack:

- [ ] fake JUnit;
- [ ] fake PASS file;
- [ ] artifact deletion;
- [ ] artifact replacement;
- [ ] symlink substitution;
- [ ] pytest monkeypatch;
- [ ] pytest plugin injection;
- [ ] `conftest.py`;
- [ ] `sitecustomize.py`;
- [ ] module shadowing;
- [ ] `os._exit(0)`;
- [ ] timeout;
- [ ] crash;
- [ ] test inventory truncation;
- [ ] duplicate test IDs;
- [ ] trusted-test rewrite;
- [ ] network call;
- [ ] credential access;
- [ ] production DB access.

Every attack must fail closed.

## Done when

A reviewed oracle implementation exists but is not yet considered live certified.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.


## Superseded

Superseded by TODO 0847 under the simplified solo-owner workflow. Internal safety controls remain, but owner-facing operation is reduced to Go / No-Go. Preserve this file as historical design context.
