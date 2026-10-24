# TODO 0847 — Make the Bounded L0 Validator Operational

- **ID:** 0847
- **Status:** backlog
- **Priority:** critical
- **Risk:** L5 — validation trust boundary
- **Depends:** PR #14 bounded static oracle implementation
- **Blocks:** 0849
- **Supersedes:** 0836 and 0837 for the initial rollout

## Objective

Finish and install only the bounded L0 static validator needed for the first useful workflow. Do not build a universal hostile-code validation platform.

## Supported scope

Permit only clearly non-executable L0 work such as Markdown documentation, plain text and approved static documentation metadata.

Reject Python, JavaScript/TypeScript, active HTML, executable configuration, authentication, application logic, financial logic, deployment logic and governance changes. Unsupported work remains supervised/manual.

## Installation

- [ ] Install reviewed validator outside candidate worktrees.
- [ ] Dedicated service identity.
- [ ] Private Unix socket and signing material.
- [ ] Protected Git authority store.
- [ ] Network disabled.
- [ ] Docker socket denied.
- [ ] Production DB denied.
- [ ] SSH/user credentials denied.

## Live acceptance

- [ ] valid static document change;
- [ ] active markup rejection;
- [ ] executable candidate rejection;
- [ ] trusted-test deletion/rewrite rejection;
- [ ] fake PASS/JUnit rejection;
- [ ] symlink rejection;
- [ ] timeout and crash;
- [ ] duplicate/truncated result;
- [ ] runtime binary mismatch;
- [ ] validator-source mismatch;
- [ ] key/socket permission attack;
- [ ] candidate socket/key access denial;
- [ ] network denial;
- [ ] production DB denial.

## Owner-facing health

Expose only L0 validator: READY / NOT READY.

## Guardrails

Static PASS never replaces full repository CI and never authorizes executable code. Do not claim L1/L2 support. Do not enable autonomous implementation.

## Done when

A real non-fixture L0 validator is installed, healthy and usable for the first low-risk pilot.
