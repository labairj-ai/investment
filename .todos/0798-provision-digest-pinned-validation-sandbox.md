# Provision Digest-Pinned Development-Agent Sandbox Runtime

- **ID:** 0798
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0796

## Problem

The validation architecture requires an isolated, digest-pinned runtime, but operational validation currently reports the sandbox unavailable because Docker is not provisioned on the execution host.

Fixture validation is not sufficient for supervised pilot certification.

## Scope and acceptance

- [ ] Select the dedicated execution host for development-agent validation.
- [ ] Prefer an environment isolated from authoritative production state.
- [ ] Install and configure the approved container runtime.
- [ ] Build/provision the approved validator image out-of-band.
- [ ] Pin the image by SHA-256 digest.
- [ ] Confirm the harness uses `--pull=never`.
- [ ] Confirm validation containers run with:
  - no network
  - read-only source bind
  - no Docker socket
  - no host credentials
  - no privileged mode
  - dropped Linux capabilities
  - no privilege escalation
  - bounded memory
  - bounded CPU
  - bounded PID count
  - non-root user
- [ ] Execute the real development-agent focused validation suite through the sandbox.
- [ ] Verify generated JUnit evidence is readable and SHA-bound.
- [ ] Confirm candidate validation cannot modify the source worktree or production data.

## QA requirements

- [ ] Network access attempt fails.
- [ ] Production filesystem path is unavailable.
- [ ] Docker/host socket access is unavailable.
- [ ] Secret/environment leakage test fails closed.
- [ ] Source worktree hash remains identical before/after validation.
- [ ] Container timeout/termination cleans up correctly.
- [ ] Missing sandbox runtime returns `UNAVAILABLE`, never PASS.
- [ ] Operational sandbox component reports PASS.

## Implementation guardrails

- Do not replace sandbox validation with unrestricted host subprocess execution.
- Do not mount production databases or secrets into the container.
- Do not dynamically pull an unreviewed image during an agent run.

## Source

User-supplied 2026-10-22 development-agent operational acceptance phase. Requirements and dependencies preserved; backlog creation does not authorize implementation or activation.
