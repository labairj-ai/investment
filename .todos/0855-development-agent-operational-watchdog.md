# TODO 0855 — Development Agent Operational Watchdog

- **ID:** 0855
- **Status:** in-progress
- **Priority:** critical strategic
- **Risk:** L5 — monitoring integration and supervised-admission governance
- **Depends:** 0852 READY on its currently pinned source
- **Blocks:** 0853
- **Stories:** WD-DA-001 through WD-DA-012

## Objective and rollout order

Extend the existing Investment operational watchdog so read-only Development Agent
discovery cannot silently stop, stall, drift or fail. Its only execution model is
**observe → classify → alert**, never observe → repair.

1. Complete 0852 on the currently deployed/observer-pinned source
   `19fd140227a5b9b3cec27e6a2f91e610842e9947` with three distinct genuine accepted
   Eastern-date Scout slots and root-observed host safety.
2. The owner's follow-up authorizes preparing/testing this epic's source now for
   deferred deployment. Do not merge/deploy the watchdog during the current
   three-run sequence. After 0852 is READY, use normal exact-head source review,
   CI and one owner Go/No-Go plus all technical deployment gates.
3. Deploy and live-verify watchdog coverage before any 0853 Builder/worktree/pilot.
   Do not begin 0853 or change activation controls as part of this epic.

Source preparation is authorized; live installation, monitoring acceptance and
source transition remain blocked. No production inspection, timer change or
acceptance completion is claimed from source/tests.

## Existing integration points and authority

Reuse `operational_watchdog.py`, `scripts/macro_health_watchdog.py`,
`systemd/macro-health-watchdog.{service,timer}`, existing watchdog SQLite
projections/incidents/delivery attempts, `/api/watchdog` and existing dashboard.
See [the watchdog architecture](../docs/operational-watchdog.md).
Do not create a second incident, email, retry or dashboard status framework.

Authoritative execution is systemd. Authoritative discovery execution/evidence is
its existing Development Agent ledger plus the root discovery observer. Existing
`dev_agent.scheduler_health.acceptance` and the read-only acceptance report remain
the only acceptance calculation; watchdog HEALTHY grants no implementation or
acceptance authority. Watchdog writes are limited to its own existing operational
projections, incident transitions and notification delivery state. Discovery ledger,
spool, root evidence, source, configuration and investment state remain read-only.

WD-DA-001–009 form the core; WD-DA-010 projects it to the existing dashboard;
WD-DA-011 adds the actual supervised admission prerequisite. WD-DA-012 applies to
all work and must be tested from the start, not added after deployment.

## WD-DA-001 — Discovery scheduling

- [ ] Read `development-scout.timer`: exists, loaded, enabled, active, reviewed
      calendar/delay/accuracy and available next trigger.
- [ ] Bind the reviewed daily **08:15 America/New_York**, Persistent=true,
      RandomizedDelaySec=120 schedule; account for all reviewed completion bounds.
      Use timezone-aware Eastern dates/DST, never fixed UTC offsets.
- [ ] Require LastTrigger after the first due execution, not before it. Account
      for installation time, real persistent catch-up and next expected slot without
      changing timer history or retrospectively inventing executions.
- [ ] HEALTHY when metadata and required execution are on time; YELLOW after the
      permitted completion/grace window while still inside escalation; RED for
      missing/disabled/inactive/drifted timers, repeated failure or missed-run
      escalation. Configurable bounded grace/escalation defaults need review.
- [ ] Disabled timer opens RED; a valid future first slot is not an incident;
      late evidence produces YELLOW before RED. No service-control action exists.

## WD-DA-002 — Collector freshness and availability

- [ ] Read the real private regular nonsymlinked `operational-signals.json`;
      validate owner/mode, bounded `development-signals-1` shape, timestamps,
      observations and required `ci`, `telemetry`, `performance` availability.
- [ ] Use the existing approved freshness limit (currently 36 hours in load_spool),
      with a reviewed earlier warning threshold; do not expand validity to hide
      failure. Monitor collector timer loaded/enabled/active and service results.
- [ ] HEALTHY: active collector timer, fresh usable spool, no unavailable required
      source. YELLOW: approaching expiry/delayed collector with still-valid spool.
      RED: missing/disabled timer, missing/stale/invalid spool, unavailable required
      source/public CI access or repeated collector failures.
- [ ] Never run the collector, rewrite/regenerate a spool or rescue stale success.
      Existing public-mode credential-free transport and Scout fail-closed reads
      remain unchanged. Alerts contain no signal payload/credential/portfolio data.

## WD-DA-003 — Scheduler observer

- [ ] Read scheduler-observer timer/service loaded/enabled/active/results and the
      latest real SCHEDULER_OBSERVATION. Use existing approved evidence freshness
      (currently one hour), reviewed warning threshold and actual producer cadence.
- [ ] HEALTHY for fresh real observations; YELLOW approaching stale/delayed;
      RED for missing/disabled observer, repeated failures or expired observations.
- [ ] The scheduler observer remains the producer. Watchdog must never append
      SCHEDULER_OBSERVATION or manually invoke its service.

## WD-DA-004 — Genuine Scout execution

- [ ] Read SCHEDULE_ATTEMPT, SCHEDULE, SCHEDULE_FAILURE and SCHEDULE_DUPLICATE for
      the required Eastern slot, keeping failures/duplicates distinct from success.
- [ ] Validate systemd-observed-timer trigger, real InvocationID, exact expected
      source, Eastern-date slot, finite/bounded start/end/duration, COLLECTED status
      and complete required signal availability. Preserve existing retry semantics;
      monitoring must not add retries or invent a producer retry policy.
- [ ] Match root-observed per-invocation evidence and available systemd/journal
      provenance. A label/regex-valid ID or TriggeredBy relationship alone is not
      proof of timer execution. Handle oneshot garbage collection without inventing
      an InvocationID or relying on an empty live service property as success.
- [ ] HEALTHY only for genuine required-slot success; YELLOW for a late required
      slot inside escalation; RED for failed/missing required execution, wrong
      source, unavailable signals or exhausted producer retry policy.
- [ ] Adversarial manual, fixture/synthetic, duplicate, stale-source and forged
      ledger rows cannot clear an incident. Missing authoritative provenance must
      remain explicit, never silently accepted or repaired.

## WD-DA-005 — Acceptance projection

- [ ] Consume the existing read-only acceptance result: source, successful/required
      runs, accepted Eastern slots, host safety, scheduler health and current state.
- [ ] Display ACCEPTING 0/3, ACCEPTING 1/3, ACCEPTING 2/3, READY 3/3 or BLOCKED.
      READY requires the authoritative result to be READY including host safety;
      a counter of three by itself is insufficient.
- [ ] Healthy progression at 0/3, 1/3 or 2/3 is not an incident. Missing expected
      progression is classified by the underlying late/failed component checks.
- [ ] Never independently grant/count acceptance or change candidate provenance.

## WD-DA-006 — Root host-safety evidence

- [ ] Read discovery.json only if present; validate protected root ownership and
      ancestor permissions, regular/nonsymlinked/bounded file, exact source,
      fixture_only=false and os_boundary_verified=true.
- [ ] Match each successful genuine invocation and Eastern slot to existing root
      evidence: no_builder, no_worktree, no_source_mutation, no_pr, no_deploy,
      no_financial_execution true; valid holdings/investment before==after hashes.
- [ ] Absence before any genuine successful run at 0/3 is normal/PENDING.
      Missing corresponding safety evidence after success is RED, as are malformed,
      mismatched or unsafe records. Missing bookend during a bounded in-flight
      execution is not a completed success.
- [ ] Distinguish latest-run Host Safety PASS from the authoritative three-run
      host_safety_accepted requirement; do not mark 1/3 READY or fail it merely
      because aggregate three-run safety is still pending.
- [ ] Never create/edit discovery.json or call an observer producer/bookend API.

## WD-DA-007 — Source/observer drift

- [ ] Compare deployed HEAD/clean tracked source, observer pin, latest scheduled
      source and authoritative acceptance source. Observe cached origin/main where
      appropriate; never fetch/pull/redeploy from monitoring. Handle any separately
      reviewed relationship to a newer remote/ref without silently accepting drift.
- [ ] RED for unexpected source/pin disagreement, Scout evidence on an untrusted
      source, mismatched acceptance source or source changes during qualification
      without the required reviewed transition.
- [ ] Never automatically refresh observer pins, reset/rewrite acceptance or deploy.

### Required reviewed transition after current 0852 completion

The existing config-only pin refresh explicitly refuses any scheduled history or
root acceptance artifacts. It is a zero-run bootstrap transition, not an upgrade
path after 0852 is READY. Deploying watchdog code changes the exact application SHA.

- [ ] Design and review the necessary post-acceptance source/observer transition
      before deployment. Retain genuine historical evidence; do not delete it to
      bypass the zero-run guard or manually edit root configuration.
- [ ] Preserve current exact-source acceptance and candidate admission rules. Do
      not carry old-head run credit/candidates onto a new head, call source changes
      exempt or silently waive a new genuine qualification if those rules require
      it. Record the current-source readiness requirement before 0853 may proceed.
- [ ] Keep this transition separate from automatic watchdog behavior. One normal
      exact-head owner Go remains the human decision; no additional promotion or
      deployment ceremony is introduced.

## WD-DA-008 — Unauthorized authority

- [ ] Immediately RED on supervised_loop_enabled, autonomous_implementation,
      supervised_publish_pr or auto_merge becoming true; non-SHADOW stage or
      required_human_merge != true. Retain the rollout's L2 configured ceiling and
      existing L0-only supervised eligibility.
- [ ] During discovery-only phase inspect authoritative unexpected Builder activity,
      new implementation worktree, automatic PR/merge or Development Agent deploy.
      Preserve known historical release/QA worktrees; distinguish new/active
      implementation from old registrations without deleting either.
- [ ] This alarm is immediate, independent of daily Scout deadlines. Unknown or
      unavailable authority evidence must not become HEALTHY by default.

## WD-DA-009 — Existing incident and notification framework

- [ ] Feed component/severity/expected slot/last valid run/current source/reason to
      existing incident transitions and transport. Example: "Development discovery
      RED — expected Scout run for 2026-10-25 has not completed."
- [ ] Preserve existing incident deduplication, severity transitions, RED delivery,
      YELLOW digest and delivery retry policy. Delivery retries never retry Scout.
- [ ] YELLOW: delayed run, nearing-stale spool/observations. RED: missing/disabled
      timer, failed run, unavailable/stale/invalid required signals, source/pin drift,
      missing/unsafe bookend or unexpected implementation/activation.
- [ ] Exclude portfolio contents, credentials, raw evidence and sensitive paths from
      alerts; project only bounded sanitized diagnostic metadata. Tests use fake
      transport; no invented production incident/test notification is required.

## WD-DA-010 — Existing read-only dashboard

- [ ] Add compact Development Discovery: HEALTHY/YELLOW/RED; acceptance count/state;
      abbreviated source; last/next Scout; Signals HEALTHY/DEGRADED; Host Safety
      PASS/PENDING/FAIL; Builder DISABLED in the intended phase.
- [ ] Expandable invocation/slot/freshness/unavailable/candidate-count/incident
      details reuse the same projection. Unsafe authority must show RED and actual
      unexpected activity, never a hardcoded DISABLED label.
- [ ] No Run Scout, Retry, Repair, Enable Builder or Reset Acceptance controls,
      mutation endpoints or alternate manual evidence inputs.

## WD-DA-011 — Hard prerequisite before 0853

- [ ] Enforce in actual supervised admission before worktree/Builder, not only UI:
      authoritative current-source 0852 READY, 3/3 genuine accepted slots and host
      safety accepted; installed independent watchdog component and active watchdog
      timer; at least one successful real Development Agent inspection; no unresolved
      Development Agent RED incident; controls valid for the approved 0853 phase.
- [ ] Coverage evidence must be trusted/current, unavailable/stale/mismatched
      coverage fails closed. A caller-supplied HEALTHY flag cannot admit a pilot.
- [ ] Watchdog health is necessary but never sufficient. Preserve independent
      Reviewer, live bounded L0 validator, all CI/release gates, exact-head owner Go,
      stale-head invalidation, human merge and all investment/credential boundaries.
- [ ] Prove every missing prerequisite blocks before any Builder/worktree side
      effect. Do not enable supervised execution or begin the pilot in this epic.

## WD-DA-012 — Non-remediating architectural gate

- [ ] Observation code receives only read-only evidence adapters/handles and
      sanitized data plus the existing watchdog projection/incident output. Do not
      pass service-control, producer, ledger writer, Builder, GitHub write, worktree,
      deployment, configuration-write or financial-write interfaces into it.
- [ ] Systemd adapter allows only bounded read queries for fixed reviewed units;
      no shell/command-string fallback or start/restart/enable/disable/clean path.
- [ ] Negative/adversarial tests trap every prohibited side effect: Scout/collector
      execution, timer mutation, discovery-ledger/SCHEDULER_OBSERVATION/evidence
      writes, candidate creation/state change, Builder/worktree, PR/publication,
      merge/deploy, holdings/investment DB write and activation edits.
- [ ] Before/after tests prove inspection leaves authoritative source, discovery
      state and investment identities untouched. Watchdog may write only its own
      existing incident/projection/delivery state. It cannot impersonate root
      observer evidence or award acceptance.

## Validation and live acceptance

- [ ] Test disabled/drifted/missing timers; first-future-slot vs overdue slots;
      grace/escalation boundaries, DST and Eastern dates; natural persistent
      catch-up; successful, failed, duplicate, manual and forged/synthetic runs.
- [ ] Test fresh/nearing-expiry/stale/private-invalid/bounded-invalid spools;
      unavailable public CI and required sources; missing/stale scheduler evidence;
      root permission/symlink/source/unsafe/missing bookends; source/pin drift.
- [ ] Test healthy 0/1/2 progression, authoritative 3/3 READY, BLOCKED, missing
      coverage/admission and dashboard/alert redaction/deduplication/retry unchanged.
- [ ] Run focused watchdog/Development Agent tests, complete repository suite with
      unchanged skips and all eight release gates; verify exact-head real CI and
      unchanged financial fingerprints/activation. Never weaken guardrails/tests.
- [ ] After current 0852 completion and reviewed deployment/transition only: verify
      actual watchdog timer active, successful independent inspection, genuine
      projections and existing read-only dashboard; preserve real evidence with
      no producer invocation or synthetic acceptance. Do not trigger a production
      failure solely to demonstrate an alert.

## Prepared source progress

Read-only adapter, pure classification, existing incident/delivery integration,
read-only dashboard projection and fail-closed supervised admission are prepared.
Negative tests cover producer/financial writes, forged/manual execution, source and
control drift, deadlines/freshness and missing independent coverage before worktree
or Builder. Exact validation/CI evidence belongs to the review PR. No production
installation, deployment, notification or accepted-run credit is claimed. The
post-acceptance observer/source transition above remains a deployment blocker, not
a watchdog remediation capability. All existing controls and activation flags stay
unchanged.

## Done when

All twelve stories and non-remediation tests pass, reviewed monitoring is deployed
and independently live-verified, required source/observer/acceptance continuity is
resolved without fabricated/migrated credit, and 0853 admission fails closed unless
all monitoring and existing safety prerequisites hold. 0853 itself has not started.
