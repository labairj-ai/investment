# Trusted validation and operator boundaries (0803–0809)

This phase is a supervised security change. It grants no deployment, merge,
production promotion or autonomous execution authority. All seven TODOs remain open
until their environmental QA, reviewed CC migration and exact-head checks pass.

## Trusted tests and evidence

`development-validation-3` reconstructs the test/configuration oracle from exact Git
blobs at the immutable approved base. It rejects missing objects, symlinks, oversized
blobs and incomplete reconstruction. It reads blobs rather than allowing Git
`export-ignore` attributes to omit tests silently. The mandatory workspace combines
candidate application code with base tests, base pytest configuration and base
release-check scripts. Its entire source tree is an OS read-only bind mount.
Candidate root/nested conftests, startup customizations and candidate test directories
are removed from this workspace before the trusted files are installed.

Before each mandatory pytest scope, a separate networkless container collects that
scope against approved-base application code and approved-base tests. Its exact test
identities are cached by base/command and compared with actual JUnit identities.
Candidate-reported counts, declared XML totals and replacement test names cannot
satisfy this comparison. A failed collection is UNAVAILABLE, never PASS.

Every VALIDATION and VALIDATION_BATCH binds `trusted_test_tree_hash` separately from
`candidate_source_tree_hash`, alongside the complete source hash and exact base/head.
Candidate tests run in a fresh supplemental container with a separate artifact
namespace. They cannot replace the mandatory XML or oracle. Supplemental failures
also prevent a green handoff; supplemental successes cannot substitute for any of
the seven mandatory gates. Both inventories remain review evidence.

Python starts with `-I`, plugin autoload disabled, no inherited host environment,
and trusted pytest loaded before adding application paths. Arbitrary application
Python still executes in the same interpreter as regression assertions; a read-only
oracle is not proof against all Python-memory tampering. Independent review and
scope restrictions remain mandatory. The generic Builder cannot modify financial,
execution or governance source. No test-count receipt replaces those controls.

## GitHub Actions threat model and bootstrap

Candidate Python, pytest hooks/configuration, generated reports, filenames and
artifacts are untrusted. Host orchestration, the approved base, reviewed immutable
GitHub Actions commits and the operator-approved validator image are trusted.
The host never imports candidate Python or executes candidate repository scripts.

Workflow permission is explicitly `contents: read`; unspecified permissions are none.
Both checkouts disable persisted credentials. Critical Actions are pinned to full
commits resolved from the official repositories. The runner checks out orchestration
at an operator-managed reviewed SHA independently of candidate head. The workflow
is governance-protected; PR edits to orchestration/permissions require independent
human review and repository protection. No `pull_request_target` or repository
secrets are used to execute candidate source.

An operator must first build/review/publish the image using `ops/validator/build.py`
and a reviewed digest-pinned Python base. The recipe installs Git and the explicitly
version-pinned dependency snapshot; it includes no repository source, production
state or credentials. Review the final image and record its registry digest.
Configure these repository variables out-of-band:

- `DEV_AGENT_VALIDATOR_IMAGE`: `ghcr.io/labairj-ai/investment-validator@sha256:<64 hex>`
- `DEV_AGENT_ORCHESTRATOR_SHA`: the full independently reviewed commit containing
  `scripts/run_contained_ci.py` and the hardened harness.

The orchestration SHA must contain the new code; an old main without these scripts
cannot bootstrap it. Do not point this variable automatically at PR head. The
approved regression base must also include the trusted release gates required by
that harness. Main must first receive the independently reviewed harness baseline;
missing base gates fail closed rather than falling back to candidate scripts.

On ephemeral hosted runners, a trusted provisioning step fetches only the
operator-approved immutable image before candidate execution. Agent validation
itself always uses `--pull=never`; it never builds or fetches images dynamically.
A missing image/ref configuration fails explicitly with UNAVAILABLE. There is no
unrestricted-host fallback. Image provisioning is not claimed complete by committing
this recipe, and no repository variables have been configured by this change.

Containers have no network, host credentials, host Git history, Docker socket or
privileged interfaces. They use non-root UIDs, a read-only root filesystem and source,
dropped capabilities, no-new-privileges, bounded CPU/memory/PIDs and bounded temporary
storage. Only approved, size-bounded, non-symlink, parsed artifacts cross back to the
host. The full mandatory JUnit inventory must match trusted independent collection.
The trusted controller exports only `test-results.xml`, `validation.json` and
`supplemental.json`. The exact GitHub event head/base are checked and bound.

Run real containment acceptance with:

```sh
python scripts/check_validation_containment.py --image ghcr.io/labairj-ai/investment-validator@sha256:<digest>
```

It tests outbound denial, absence of credentials/production paths/sockets, non-root
execution, dropped capabilities, read-only source/oracle, source identity and timeout
cleanup. Missing Docker returns UNAVAILABLE and nonzero, with no skipped test waiver.
Technical certification now requires this actual probe as well as the focused suite.

## Protection continuity

Start, publication, PR handoff/update, disposition, merge recording, deployment
observation and pilot success each require a fresh effective-protection API result.
Each observation binds identity, repository, timestamp, normalized policy, raw evidence
hash, frozen context and exact head. The configured age may tighten the 300-second
ceiling. Identity or material normalized-policy drift creates a FAIL audit observation
and NEEDS_HUMAN. Missing visibility fails closed.

Pilot success requires all lifecycle stages and an exact-head, protection-bound
GitHub-verified MERGE event. A fresh PASS at the end cannot erase a recorded failure
or replace missing lifecycle evidence. The agent never changes GitHub protections.
The dashboard exposes the full PROTECTION history through its existing audit view.

## Human dashboard identity

Shared-token possession alone cannot authorize supervised decisions. For Tailscale
Serve identity, an operator must set `INVESTMENT_BIND_HOST=127.0.0.1` (or loopback IPv6),
`DEV_AGENT_IDENTITY_SOURCE=tailscale-serve`, and a comma-separated allowlist in
`DEV_AGENT_OPERATORS`. The trusted Serve proxy must be the sole ingress to that
loopback-only backend and must strip/repopulate Tailscale identity headers. Local
host processes remain inside the trusted operator boundary.

Mutations require both a loopback peer and loopback-only server listener, exactly one
valid `Tailscale-User-Login`, an allowlisted human identity, the existing API token,
same-origin request, JSON Content-Type and an unused decision nonce bound to current
candidate context. Wildcard listeners, direct tailnet requests, absent/duplicate
headers, unknown operators and shared tokens without identity fail closed. Read-only
access does not require operator mutation identity and never creates evidence.

The actor comes from the authenticated boundary, never request JSON. Audit records
include the user, authentication source, time, decision nonce and exact context;
tokens and raw credentials are never stored. CLI OS/TTY identity remains unchanged.
No production listener, service configuration or secret has been modified here.

## Risk and host Git

Protected runner/configuration files and executable plugin declarations are at least
L3 and human-started. Whole-content review raises risk after Builder edits too.
CSS typography may remain L2; active CSS resource behavior escalates. HTML/SVG is L3
unless both prior and resulting contents are inspected as passive. Script tags,
events, script URLs, forms, embedded objects, resource loads, SVG animation/foreign
content, unknown tags and ambiguous content escalate deterministically. Direct
JavaScript/TypeScript is human-started regardless of its directory.

All host Git calls in dev_agent use a process-local wrapper. Hooks, executable filters,
signing helpers, ambient global/system configuration, external diff/text conversion,
and unsafe transports are disabled or rejected. Candidate writes cannot reach Git
metadata. Publishing checks both fetch and push URLs against the expected repository.
The wrapper uses an explicit agent commit identity rather than unrelated global
settings. Human Git hooks/configuration are never modified. Commit/publication intent
is recorded without credentials. Disposable canaries use the same hardened wrapper.

## CC input validity

0806 separately proposes cc-v3.4 → cc-v3.5. Required numeric values are checked before
candidate preparation/comparison, financial summary/score/priority math and chain
construction. Invalid inputs create an INSUFFICIENT_DATA finding and no recommendation,
with explicit reason codes and no zero replacement. Derived non-finite calculations
also fail closed. Optional evidence can still use JSON null, including NumPy/Pandas
scalars. Valid finite recommendations are compared directly with immutable deployed
cc-v3.4 source. Scoring/promotion thresholds, simulator and observe-only policy remain
unchanged. The proposed contract requires separate acknowledgment and financial review;
no promotion or deployment is performed as part of implementation.

Sources: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use),
[workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[checkout credential behavior](https://github.com/actions/checkout/blob/main/README.md),
[pytest plugin loading](https://pytest.org/en/latest/how-to/writing_plugins.html),
[Tailscale Serve identity headers](https://tailscale.com/docs/features/tailscale-serve),
[Git configuration](https://git-scm.com/docs/git-config).
