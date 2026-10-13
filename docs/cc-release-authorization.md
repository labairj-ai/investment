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
