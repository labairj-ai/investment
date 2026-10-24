# PR15 internal rollout prerequisites — 0851–0854

Owner experience: ChatGPT reviews the actual PR, exact head and CI, recommends GO
or NO-GO, and the owner replies **Go** or **No-Go**. The same Go authorizes the exact
head to merge after CI and its resulting merge SHA to deploy after merged-main CI
and technical gates. This guide is for internal release tooling/operators; it adds
no owner script, certificate handling, stage transition or second approval.

PR15 prepares source support. It does not install or activate services. All four
TODOs remain open, and all implementation/publication/merge activation settings
remain unchanged. Installation support must use reviewed, merged, clean source;
default installer invocation is plan-only. Existing installations are refused,
not overwritten. Bootstrap failure removes only newly created installation files;
an oracle that cannot be stopped retains its files for diagnosis.

## 0851: bounded static validator

`ops/validator/install.py` verifies canonical origin, exact HEAD and origin/main,
then reads the two fixed installation files from Git blobs. Its explicit apply
path is Linux root only: a dedicated nologin identity, root-controlled source,
private key/configuration, protected bare Git authority and one fixed system unit.
It never downloads a model or changes an MLX/application service. The initial
allowed scope remains `docs/help/` static documentation; it grants no pytest authority.

`scripts/check_l0_validator.py` invokes the installed socket against exact base/head
and reports only a functional probe. PROBE_PASS is **not** live certification.
Acceptance still needs the entire TODO0851 host permission/network/data denial and
adversarial matrix, runtime/source pins and a sanitized non-fixture receipt.
A frozen-plan base must be available through a protected trusted authority update;
no candidate may write that store. The independent pytest-result oracle is still
required by runtime admission. This PR does not replace it with static PASS.

## 0852: read-only discovery

`ops/install_discovery.py` plans the six fixed Scout/observer/collector units from
reviewed merged source. Apply is limited to the OptiPlex application account and
starts only the three timers. It never manually invokes Scout or installs the
supervised loop. A separately provisioned private GitHub reader credential must
show pull=true and push/admin/maintain=false. Do not reuse owner CLI credentials.
The optional HTTP reader keeps tokens out of command lines and rejects cross-origin
redirects. Service sandboxes deny application data and owner credential locations.
These source restrictions still require actual host denial tests.

`scripts/discovery_acceptance_report.py` reads actual ledger observations. Credit
requires three distinct New York timer slots/invocations, exact current source,
complete counts, required signal availability and current observed timer health.
Manual, duplicate, fixture, failed and unknown-source runs cannot qualify.

Root-controlled `/var/lib/investment-development-acceptance/discovery.json` holds
independent host observations outside Scout/Builder writable state. The acceptance
reader does not create this evidence. A trusted host observer must record actual
OS boundary checks and bookended holdings/investment identities without exporting
data or secrets. The schema contains `source_head`, `fixture_only=false`,
`os_boundary_verified=true`, a fresh numeric `observed_at`, and `runs`. Each run
matches the ledger `invocation` and `slot`, has true `no_builder`, `no_worktree`,
`no_source_mutation`, `no_pr`, `no_deploy`, `no_financial_execution`, and matching
64-hex `holdings_before/after` and `investment_before/after`. All three must qualify.
Missing evidence stays NOT READY. Do not construct a receipt from expectations or
fixture results; the actual observation producer/measurements remain live work.

## 0853: genuine supervised pilot

The cycle checks full discovery acceptance and candidate provenance before worktree
creation and admits only L0. Independent Reviewer, protected validation, full CI,
AWAITING_OWNER and the normal exact-head owner decision remain mandatory. No-Go or
a new head invalidates downstream authority. Canonical REST PR facts fix the blank
repository identity returned by the CLI during the prior real release.

An optional operator-configured `DEV_AGENT_BUILDER_ENDPOINT` or
`DEV_AGENT_REVIEWER_ENDPOINT` selects the already-running shared Qwen MLX service
on Mac Studio port8080 (or an explicit localhost8080 tunnel). Only the existing
Qwen3.6-35B-A3B-4bit model is accepted. News port8081, other hosts/models, native tool
calls, redirects, malformed/truncated/oversized responses are rejected. Defaults
retain Ollama. No endpoint is contacted, model loaded or configuration activated
by this PR. The adapter supplies JSON only and confers no host tools or authority.

A genuine discovered improvement, accepted live validator and pytest authority,
Builder/Reviewer identities, real PR, owner decision and merged-main CI are still
required. A seeded candidate or simulated Go cannot close this TODO.

## 0854: deployment controller

The fixed installed preflight checks the dedicated identity, read-only GitHub
capability, safety stop, protected controller location and inability to replace
protected state or read known owner/application credentials. A READY permission
audit grants no deployment authority. The deployment transaction independently
rechecks the one exact-head Go, merge/main/CI, clean source, backup and health.

Installation must resolve fixed checkout privileges without giving the deployment
identity writable holdings/database parents, broad sudo, arbitrary shell or GitHub
write authority. Preflight refuses an unsafe layout rather than adding ACLs. The
existing source layout may therefore remain NOT READY until a reviewed fixed
checkout mechanism is installed. Do not turn the check off to make it deploy.

Protected comparisons and integrity-checked read-only backups include investment.db
and existing buffett.db. Code rollback never restores a database. Append-only
OWNER_MERGE and STATIC_VALIDATION audit events are recognized; unknown event kinds,
modified prefixes/schema or protected-state mutations still fail. The actual
installation, live failure/interruption matrix, delayed observations and three
controller releases remain outstanding. LOW-RISK AUTO-PR readiness is presentation
of existing evidence, never activation or autonomous merge/deploy permission.
