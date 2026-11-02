# Standing task authorization and owner release workflow

An explicit owner task authorizes normal implementation, testing, merging and
deployment within the requested scope. ChatGPT reviews the resulting PR diff, exact
head, risk and current CI. The existing owner connector records the initiating task
authorization against that exact PR and continues automatically when its technical
checks pass. No intermediate Go/No-Go request, SHA copying, structured comments,
script or second deployment approval is required for routine in-scope work.

Pause for a new owner decision when a proposed action is both genuinely high-risk
and outside the task scope, including live-trading activation, changes to financial
safety controls, or secret access/exposure. Preserve all applicable domain canaries,
CI, security controls and GitHub protections in every case.

The isolated owner connector freezes the reviewed context, authenticates the
personal owner's GitHub ID/login, and uses the existing `go_no_go`/continuation
path to record task authorization against the current exact PR head. It generates
nonce and audit metadata internally. The fixed expected-SHA merge runs after
exact-head CI passes. `reconcile_approved` retries while CI is pending. A changed
head requires refreshed technical checks and a new exact-head authorization record
derived from the same task scope; it does not require another user prompt. Technical
certificates, protection evidence and health still expire independently and are
rechecked.
The connector must be installed outside candidate source with credentials that
Builder, Reviewer, Scout and the implementation service cannot access.

The deployment poller consumes that **same review object's ID**, verifies the
latest decision, exact approved head, actual owner merge actor, exact merge SHA,
head CI, merged-main CI, ancestry and current main. It waits automatically while
CI is pending. It does not consume OWNER-DEPLOY or OWNER-AUTONOMY-PROMOTION objects.
The fixed controller still enforces clean source, backup, fixed service controls,
HTTP/API and Advisor health, protected investment state, delayed observation,
rollback and interruption recovery. Owner review, merge and deployment receipts
remain distinct. The owner sees DEPLOYED or FAILED, with diagnostics for failures.
No arbitrary shell, broker function or investment-data rollback is permitted.

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
