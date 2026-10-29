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
No GET calls a scheduler producer, approval writer, host command, merge or deploy.
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
