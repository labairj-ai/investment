# TODO 0804 — Harden GitHub Actions Against Agent-Generated Code

- **ID:** 0804
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0796, 0798
- **Blocks:** 0800, 0801

## Problem

Although the Builder has no shell or network access on the local host, agent-generated Python is eventually pushed to GitHub where GitHub Actions executes it.

The current workflow executes repository tests directly on a GitHub-hosted runner with network access and without an explicit least-privilege workflow permission contract.

This creates an indirect execution and network path for model-generated code.

## Scope and acceptance

- [ ] Add explicit least-privilege workflow permissions.
- [ ] Default workflow permissions to:
  - `contents: read`
- [ ] Deny write permissions unless explicitly required by a separate trusted workflow.
- [ ] Configure checkout with persisted Git credentials disabled.
- [ ] Pin critical GitHub Actions dependencies to reviewed immutable commit SHAs.
- [ ] Execute agent-generated code only inside an isolated validation container.
- [ ] Use a digest-pinned pre-provisioned validation image.
- [ ] Disable network access inside the test container.
- [ ] Do not mount GitHub credentials, tokens or secrets into the validation container.
- [ ] Do not expose Docker socket or privileged host interfaces.
- [ ] Mount candidate source read-only before copying into disposable container workspace.
- [ ] Export only explicitly approved artifacts such as JUnit results.
- [ ] Validate returned artifacts using trusted host-side logic.
- [ ] Preserve exact-head GitHub CI behavior.
- [ ] Distinguish trusted orchestration from untrusted candidate execution.
- [ ] Document the GitHub Actions threat model.

## QA requirements

- [ ] Agent test attempting outbound HTTP fails.
- [ ] Agent test attempting GitHub API access without credentials fails.
- [ ] Agent test cannot read `GITHUB_TOKEN`.
- [ ] Agent test cannot read repository secrets.
- [ ] Agent test cannot push a branch.
- [ ] Agent test cannot modify the checked-out host source outside the disposable workspace.
- [ ] Test artifacts remain available to trusted baseline checks.
- [ ] Full workflow still produces exact JUnit inventory.
- [ ] CI remains green for legitimate changes.

## Implementation guardrails

- Do not depend solely on GitHub's current default token permissions.
- Do not expose secrets to workflows that execute agent-generated source.
- Do not weaken required CI to solve containment problems.

## Source

User-supplied 2026-10-22 trust-boundary code-review follow-up. Backlog creation does not authorize implementation, promotion, pilot execution or autonomy activation.

## Implementation checkpoint — 2026-10-22

Implementation is on `codex/trust-boundary-0803-0809`; see the
[implementation plan](../docs/plans/development-agent-trust-boundaries-0803-0809.md)
and [trust-boundary contract](../docs/development-agent-trust-boundaries.md).
Source/fixture validation does not close environmental acceptance. This TODO remains
open pending its complete QA, required human decisions and exact-head CI evidence.
