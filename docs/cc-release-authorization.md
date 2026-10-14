# CC release authorization

CI uses `pull_request.base.sha` or `push.before` from the runner event payload.
Checkout must include full Git history. The checker reads the prior baseline from
that exact immutable commit and computes current identity from the checkout.
Missing history/baseline, malformed data, unsupported events and zero before SHAs
fail closed. Initialize the repository baseline locally before enabling CI; there
is no CI bootstrap fallback and no automatic write.

For offline review use `--trusted-prior-file PATH` or `--prior-ref FULL_SHA`.
CI event authority cannot be overridden by either input. Files are an explicit
local trust input; they are never a replacement for CI event authority.
Candidate promotion must exactly match the computed state, including schema.

Manifest booleans accept only literal `true` and `false`. Behavioral changes
require reset and operator acknowledgment. The only implemented 0712 open-chain
policy is `VERSION_CENSORED`. Every protected identity field is bound in both
prior and proposed state. Existing front matter remains readable; incomplete
historical manifests cannot authorize new transitions. Copy the updated template
and fill every field when proposing a new transition.

Canonical version forms are `cc-vMAJOR.MINOR`, `cc-virtual-N`,
`simulator-contract-N`, `shared-live-management-asof-N`, and `cadence-vN`.
Numeric tuples must increase. Engine changes require the model version to
increase; simulator changes require simulator contract version to increase.
Policy and cadence updates require a corresponding simulator identity change,
its contract bump, and exact manifest. Metadata-only behavioral version changes
are rejected; there is no implicit migration exception.

## Mandatory CI event authority (0731)

When either CI guard flag is true, GITHUB_EVENT_PATH and a supported
GITHUB_EVENT_NAME are mandatory. Missing/unreadable/malformed/non-object events,
unsupported event types, missing/invalid prior SHA and zero prior SHA reject.
All explicit --prior-ref and --trusted-prior-file inputs reject in CI, including
an equal ref. Offline inputs are usable only outside CI. Fixture subprocesses in
CI use isolated genuine temporary Git commits/event payloads and retain CI flags.

The fingerprint-definition migration and inventories are documented in
[cc-behavior-fingerprints.md](cc-behavior-fingerprints.md). Diagnostics identify the
required model_version or simulator_contract_version; simulator_version alone
cannot satisfy a required simulator contract bump.
