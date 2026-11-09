# Development TODO evidence review — November 9, 2026

Review base and deployed Scout source: `6db0b6ccf2494721d024a6e29ecf8fbb55c66bf6`.
Scope is record housekeeping only, under the explicit owner request to review,
close supported criteria, create one PR and merge if green. No production deployment,
Scout trigger, acceptance rewrite, infrastructure or new TODO is authorized here.

## Disposition against original criteria

| TODO | Disposition | Criteria and evidence |
|---|---|---|
| 0868 | Done | PR52, both exact-head and merged-main CI, healthy deployment, live API/page/assets and seven-width rendering checks. Latest discoveries separate from priority; original receipts preserved. |
| 0869 | Done | PR53, both CI summaries, healthy deployment and nine genuine appended outcomes against original IDs. Setup-failure regression and cold-import checks; original events unchanged, no new candidates. Broad deferred scopes remain deferred. |
| 0870 | Done | PR54/55, all required gates, healthy deployments, nine actual outcomes/L5 risks/PR53 delivery and live Chromium at all seven existing widths. Six filters, disposition colors and accessibility checks passed. |
| 0763 | Done | discovery.scout, signals, store and reviewed_source implement evidence-backed bounded read-only proposals; categories and per-category diversity, stable duplicate identity, explicit file scope/UNESTIMATED effort, validation, source context and unavailable inputs. Existing fixtures/adversarial tests plus genuine protected host observations and deployed-main CI satisfy QA. |
| 0782 | Done | scheduler.discover_daily, CLI and systemd units implement Eastern daily slots, lock/idempotency, bounded backlog/proposals, persisted metadata/failures and two-attempt budget. DST/restart/duplicate/backlog/retry fixtures and three genuine current-source runs support completion. On-demand CLI shares code; later safety boundary intentionally disallows production manual execution. |
| 0848 | In progress | Installation, 3/3 and safety satisfied. Original dashboard Discovery: READY criterion remains unsatisfied because scheduler inventory is incomplete. |
| 0852 | In progress | Installation, metadata, 3/3, safety and QA satisfied. Same original owner-facing READY gap; no missing genuine acceptance runs. |
| 0839 | Superseded, archived in done | Already superseded by 0848; historical unchecked checklist retained, no false completion credit. |

Source/fixture mapping: `tests/test_development_agent.py` covers read-only Scout,
all supplied input-source labels, architecture, proposal bounds, duplicates, DST,
backlog and retry budget; `tests/test_continuous_improvement.py` covers validated
signals, recurring identities and source availability; operational producer,
public-reader, reviewed-source, current-job, observer-refresh and system-sandbox
tests cover real-source freshness, network failure, fail-closed provenance,
source isolation and host boundaries. Fixture proof is not operational credit.
Scout has no discovery-model dependency; missing input is unavailable, not an
approved candidate or invented feedback. Production optional user feedback was
unavailable; CI/telemetry/performance were available. All nine proposal categories
are supported, not all are required to appear in each live run.

## Authoritative operational evidence

`current-source-discovery.json` is a verbatim read-only copy of the root-owned
`/var/lib/investment-development-acceptance/epochs/6db0b6ccf2494721d024a6e29ecf8fbb55c66bf6/discovery.json`
on OptiPlex. It records November 7, 8 and 9 genuine slots with authenticated
manager-job provenance, unchanged before/after holdings and investment hashes,
OS boundary verification, and no Builder/worktree/source/PR/deployment/financial
execution. This is existing evidence, not a newly issued certificate.

November 9 invocation: `8fb7e25240dd40f284addfcd6c748980`; activation 16:00:47 EST,
Scout ledger start 16:00:51.065833 EST, end 16:01:06.255365 EST, authenticated
closing receipt 16:01:08.558586 EST; service result success and exit 0. Four new
candidates, one duplicate. SyntaxWarnings and optional user_feedback unavailability
were nonfatal. Read-only integrity/FK checks on development, investment and Buffett
DBs returned ok/zero violations. No source transition occurred during today's run;
the current epoch's existing transition marker dates to November 7.

The authenticated live Control Center API returned HTTP 200 and all four new
candidate IDs. Certification returned successful_runs=3, required_runs=3.
Read-only acceptance calculation returned current_epoch_accepted_runs=3 and
host_safety_accepted=true. Its overall NOT READY label comes from
scheduled_discovery inventory_complete=false (the existing 1,000-record inventory
bound), not from failure of these three accepted runs. That status is preserved;
no bound, safety requirement or acceptance calculation is changed by this PR.

Installed Scout timer is enabled/active, with daily 16:00 America/New_York,
120-second randomized delay and one-minute accuracy. Collector and scheduler
observer timers are active. supervised_loop_enabled, autonomous_implementation,
supervised_publish_pr and auto_merge are all false. Current-source **3/3 milestone
is reached**. Additional runs or source transitions are not needed to establish it.

## Existing release evidence

`existing-evidence-index.json` records retained artifact paths, SHA256 digests and
selected nonsecret verified fields. These artifacts were read, not rewritten.
PR52/53/54/55 merge and deployment identities and exact workflow links are recorded
in the corresponding completed TODO files. CI skips remain explicit (18 existing
skips); no waiver or lowered threshold is introduced. PR55's final suite had
4295 passed, zero failed, 18 skipped. Source remains present in current main.

The bounded PR53 fix does not complete its deferred broad proposal. Closing the
Scout build and scheduling records does not close supervised execution, autonomy,
physical-device testing, technical/admission certification or overall operational
certification. Those records remain untouched. The remaining 0848/0852 gap is
specific to the owner-facing aggregate projection and requires separately scoped
work; this review adds no service, governance or new task to obtain closure.

## Housekeeping verification

Run the existing repository aggregate without modifying gates: TODO consistency,
agent contract, development governance, focused agent tests, full suite, exact
release baseline, unchanged CC contract and summary integrity. Required native
systemd fixture and source-influence checks run in exact-head GitHub CI. The PR
records final exact head, workflow URL and actual results. No production rollout
is part of this housekeeping PR; the accepted deployed SHA must remain pinned.
