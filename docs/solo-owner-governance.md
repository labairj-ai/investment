# Standing task authorization and owner release workflow

An explicit owner task authorizes routine implementation, testing, merge, and
deployment within its scope. Carry that authorization through the release. The
owner does not need to repeat it after CI, after merge, or before deployment.

## Routine release

User-requested dashboard presentation fixes can use the [direct UI workflow](../AGENTS.md#direct-ui-fixes).
Review the diff and run focused tests before a fast-forward push to main.
Wait for required CI on the resulting main commit, then follow the deployment
and verification steps below.

1. Review the complete diff, verify the exact PR head, and confirm that its
   required CI and domain checks pass. Merge through the existing protected PR
   path using the reviewed head SHA.
2. Confirm the merge commit is current main and passes its own required CI.
   Recheck the diff and tests if the head changes. Ask for a new decision only
   if the change goes beyond the authorized scope.
3. Use the installed release tooling. For an explicitly authorized manual
   OptiPlex release, use the existing SSH access and source synchronization
   tooling. Verify the tracked production worktree and source influence, back
   up protected state, deploy the exact tested main SHA, and verify the
   service, application, protected data, and trading and autonomy settings.
   Follow the existing observation and rollback checks. Roll back code if a
   health or state-integrity check fails.
4. Report the deployed SHA, CI, backup and health evidence, and any rollback.

The manual release uses the initiating task authorization. It does not require
a second owner decision or an approval object from the optional automated
controller. The manual release must pass the same applicable technical checks.
Keep GitHub protections, financial safety controls, and autonomous execution
settings intact. An owner No-Go stops the release.

## Automated release

Where an isolated owner connector and deployment poller are already installed
and accepted, they can carry the same task authorization through their existing
exact-head checks and receipts. Their authentication, replay, and admission
checks continue to apply to automated releases. A manual release must never
fabricate their records. Connector provisioning is separate work and is not a
prerequisite for an explicitly authorized manual release.

Pause for a new owner decision when a proposed action is both genuinely high-risk
and outside the task scope, including live-trading activation, changes to financial
safety controls, or secret access/exposure. Preserve all applicable domain canaries,
CI, security controls and GitHub protections in every case.

An activation PR cannot result from routine code task authorization. Runtime re-verifies
its installed source, deterministic reviewed risk, owner, current GitHub decision and CI; it does not
request a promotion object. Its configuration and technical evidence must still
admit. Owner-facing modes are Supervised and, after proven acceptance and a
reviewed activation change, Low-risk Auto-PR. Both retain the existing explicit
authorization requirement before main.
Internal SHADOW/BUILD_ONLY/PR observations are diagnostics, not manual steps.

The dashboard shows Development Agent: READY or NOT READY with a plain reason.
READY uses the real supervised runtime entry gate; candidate scope, daily limits,
independent review, validation and release gates remain mandatory afterward.
Detailed blockers and evidence remain under Diagnostics.

## Installation and acceptance remain pending

This PR installs nothing and creates no owner approval. All execution flags remain
disabled and stage remains SHADOW. Provisioning belongs to a later reviewed rollout,
not normal owner operation. External owner bindings, non-bypass agent credentials,
branch protection and isolated connector lifecycle must be accepted on real hosts.
Shared dashboard tokens, commit authorship, model recommendations and ledger JSON
are never owner identity. Approved connector app ID/slug, unedited GitHub objects,
latest-decision visibility, nonce replay checks and stale-head rejection remain
mandatory. Unavailable GitHub evidence fails closed.

The L0 static service accepts only bounded non-executable documentation and cannot
certify pytest or executable code. Its installation and real acceptance remain
0847. Three genuine timer runs remain 0848; a real discovered L0 journey remains
0849; installed controller and three genuine releases remain 0850. Tests provide
source evidence only. See [bounded validator](independent-static-oracle.md).
