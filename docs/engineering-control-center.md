# Investment Engineering Control Center implementation

Requirements: PR #31, TODOs 0856–0864 and
[the v2 contract](plans/engineering-control-center-investment-v2.md).
Risk is provisionally L5: this is a presentation layer over governance evidence.
No rollout, merge, host acceptance or independent review is implied by source tests.

## API foundation (0856)

`dev_agent/control_center.py` exposes Investment-only GET projections through
`serve.py`. `DEV_AGENT_ECC_ENABLED=1` is required; unset, empty and every other
value leave all new routes unavailable. This change provisions no flag.
The existing `/development-agent` and `/api/development-agent` are unchanged.

A reader uses the existing authenticated loopback Tailscale Serve operator
identity. Existing programmatic readers may supply the existing development API
token in its header. The UI receives no service/owner token. Cross-origin and
cross-site requests are denied, responses are no-store, and all new mutation
routes refuse before reaching legacy financial handlers. Only the dedicated
`development-control.sqlite3` can be read, with SQLite query-only and query budgets.
No GET calls a scheduler producer, approval writer, service-control command, merge or deploy. Fixed Git metadata reads and existing read-only GitHub adapters may use subprocesses.
Existing readiness may perform its existing read-only GitHub checks.

Endpoints under `/api/engineering/v1/projects/investment/`:

| Endpoint | Read contract |
| --- | --- |
| `overview` | Existing supervised admission, ranked blockers, candidate priority queue, separate committed configuration |
| `candidates` | Literal search; state/risk/category/source filters; newest/oldest/risk/value sorting |
| `candidates/{id}` | Bounded proposal, frozen plan and historical timeline; no Build or approval operation |
| `prs` | Historical recorded PR links; never a current owner-decision count |
| `prs/{number}` | Current GitHub head/base/files, separate CI, protection and owner disposition; head recheck |
| `validations/{candidate_id}` | Existing `trusted_receipt` reconstruction, all seven canonical trusted gates and the separate eight-gate repository diagnostics inventory |
| `certification` | Separate existing technical, genuine Scout, supervised calendar-window and autonomy projections |
| `audit` | Sequence-paged historical observations with explicit unverified actor claims |

List queries accept `limit` 1–50 and an opaque next cursor. Cursors bind resource,
filters, ordering and the upper event sequence; a later append cannot move a row
between those pages. Candidate detail exposes its latest 100 events and explicitly
marks incomplete timelines. Audit supports kind/candidate/actor/PR/status and epoch
`since`/`until`; `format=csv` exports that bounded page and returns `X-Next-Cursor`.
CSV cells neutralize formula prefixes. Exports are views, never attestations.
Arbitrary payload fields, prompts, credentials and raw logs are excluded.

Readiness adapters that require complete history fail unavailable above explicit
inventory budgets (500 candidates, 10,000 events, four MB per table, 32 KB records).
Paged candidate/audit inspection remains available within the SQLite query budget;
no incomplete inventory is used to infer operational acceptance.
Every judgment has source, policy, observation/expiry, source SHA, receipt and
verifier fields. Missing, future, stale, unknown or unverified proof cannot become
PASS. Committed SHADOW flags are labeled as configuration rather than host state.
No sample queue, green test total or owner actor is fabricated.

## Owner and deployment boundary

PR previews are read-only. The existing isolated owner connector remains the only
Go/No-Go path; no owner gateway implementation or credential provisioning changes.
The preview explicitly disables both actions pending separate live connector UI
acceptance. CI success is distinct from independent Oracle proof, owner disposition
and deployed health. A Go receipt cannot establish a successful deployment.
No Scout unit, timer, acceptance state, release threshold or autonomy flag changes.
PR #19 and operational tasks 0852–0854 remain separate.

## Verification and remaining acceptance

`tests/test_engineering_control_center.py` uses disposable synthetic repositories
and dedicated ledgers. It covers access/origin denial, mutation refusal, pagination
with concurrent appends, bounds, injection/redaction, stale/forged evidence and
read-only database fingerprints. Existing governance/owner suites remain required.
Record exact-head aggregate results and the real CI workflow URL in the PR.

UI/browser, independent reviewer, real Oracle/host provenance, physical iPhone and
Android, legacy/live parity and post-deploy health remain separate evidence. The
TODOs stay open until their actual required observations exist. Deployment is not
authorized by the implementation request.

## Interface and source acceptance (0857–0864)

The dependent interface commit adds six destinations at
`/engineering/projects/investment`: Overview, Candidates, Pull requests,
Validation, Certification and Audit. Desktop uses a sidebar. At phone widths the
five-item navigation exposes Certification and Audit under More. Candidate and
PR inspection use native dialogs with explicit keyboard containment, Escape,
focus restoration and address-bar inspection links. Untrusted text uses DOM text
nodes only. Assets are same-origin under a strict CSP, gated like the API; direct
static-source URLs are blocked from the legacy static fallback.

Overview delegates the owner-facing supervised admission judgment to existing
readiness code. Active backlog excludes terminal states; historical candidates
remain searchable. Current owner-decision count stays **Not observed** until a
complete current inventory exists. Historical PR links are not that count. CI is
shown separately from Oracle, effective protection, owner disposition and health.
The PR preview rechecks GitHub head after its read. Both owner actions remain
disabled with an explanation: the existing connector has no accepted live UI
handoff, and this implementation does not create a competing action endpoint.

Read projections cannot display affirmative evidence against dirty tracked source.
Configuration comes from the recorded Git commit, not a mutable host config file.
The view lifetime is capped by the earliest available proof deadline. Expired or
unauthorized refreshes clear prior readiness. Navigation/filter generations reject
late responses. Detail previews expire too. Scope truncation is explicit; latest
frozen plans are fetched independently of the bounded timeline page. Audit JSON
and CSV exports can share the same exact snapshot/page cursor even during appends.
Actor identity strings in historical events are labeled claims; current owner
verification remains in the existing owner-governance adapter.

The validator view invokes the existing receipt reconstruction against the
reader's current source. A different candidate source or unavailable isolated
Oracle stays STALE/UNAVAILABLE. It does not load executable code from arbitrary
candidate/worktree paths, open signing keys, or promote a digest/JUnit claim into
independent proof. A later trusted remote-receipt presentation bridge, if needed,
requires a separately reviewed provenance boundary; there is no permissive
fallback in this page.

`node scripts/check_development_agent_browser.mjs OUTSIDE_SOURCE_DIRECTORY`
launches its own temporary headless Chromium profile and a synthetic localhost
fixture server. `DEV_AGENT_BROWSER_EXECUTABLE` can select the installed Chromium
binary. It never connects to Investment production or posts owner actions. The
script requires committed clean source, records the exact head, checks all seven
required widths (320/360/390/430/768/1280/1440), literal malicious text, modal
keyboard behavior, disabled Go/No-Go, deep links, lost/stale evidence, late-response
races, 44px controls and the retained legacy page. Screenshots/results are fixture
QA, not host/Oracle/physical-device acceptance. The former script's selectors for
retired legacy decision dialogs were replaced with assertions against the current
legacy read-only view; all existing owner/governance backend tests remain required.

## Prepared parity and rollback matrix

| Surface | Compare against | Required real observation before rollout |
| --- | --- | --- |
| Owner READY / reason | Legacy `readiness.owner` / real supervised admission | Same live source, time and identity; differences block release |
| Candidate / frozen plan | Dedicated ledger IDs, scope/base and original events | Matching count/filter/timeline and no read mutations |
| PR / CI / owner | Current GitHub head, complete checks and existing owner verifier | Head drift, missing Oracle, replay/revocation and concurrent decisions fail closed |
| Validation | Current trusted receipt reconstruction and complete gate manifest | Real independently verified source/test-tree/image identity |
| Technical / operation / autonomy | Existing three independent backend projections | Real Scout slots, supervised releases and calendar window; no synthetic credit |
| History / export | Original sequence, UTC timestamp, redacted fields and snapshot | No lost failure/denial history; unchanged dedicated and financial state |
| Mobile | Seven browser widths plus actual iPhone/Android | Touch, VoiceOver/TalkBack, keyboard, focus and contrast observations |

This work prepares source and QA only. Nothing is installed, enabled, merged,
restarted or deployed. A later authorized rollout must use the existing fixed
controller and one owner decision on the exact reviewed source. Keep the feature
off initially, preserve the legacy interface, and collect its normal canaries,
protected-state checks and delayed health evidence. Never create a second owner
approval protocol to make this UI work. Do not mark 0864 shipped without actual
host and physical-device acceptance.

Rollback preparation is limited to removing/withholding the optional route gate
or reverting reviewed UI/API source through the existing release path. It must
preserve investment databases, holdings, append-only development/acceptance
history, Scout timers, current autonomy configuration and owner receipts. No
rollback command is executed by this change or by the browser test.
