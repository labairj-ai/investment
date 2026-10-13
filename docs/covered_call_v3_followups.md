# Covered Call V3 follow-ups (0704–0710)

This release implements the source requirements preserved in
`covered_call_v3_followup_todos/`. **V2 stays live; V3 stays observe-only.** Scorer
`cc-v3.2`, simulator `cc-virtual-1`, surface `local-total-variance-2`, duration
utility `duration-utility-2`, paired promotion policy `paired-prospective-gate-2`.
Prior V3 config/model cohorts cannot qualify for this version.

## Prospective virtual book

Decision recording atomically starts one virtual challenger position when V3
selects SELL_CC; NO_CALL creates none. Entries must be captured prospectively
within five minutes of the decision, using the original quote, coverage, execution
parameters, model/config and Git provenance. Retrospective replay has a separate
namespace and cannot masquerade as prospective. Repeated creation is idempotent.

`cc_virtual_chains`, `cc_virtual_positions`, `cc_virtual_actions`,
`cc_virtual_fills`, `cc_virtual_intervals` and `cc_market_snapshots` are append-only
with UPDATE/DELETE rejection triggers. Position rows are immutable state revisions.
The module has no broker-write adapter and never writes `executed_actions`, actual
`cc_positions`, holdings, or recommendations. Virtual chain IDs start `virtual-cc-`.

Management uses the live pure `evaluate_cc_management_state` and
`_suggest_next_call`, which now accepts an explicit as-of date. Live defaults are
unchanged. Snapshot availability, underlying/option observation times, and event
knowledge are bounded by each evaluation time. Future quotes/events are removed;
actual actions/outcomes never enter the simulator's policy inputs. Captured
current drift/HV forecasts can be used only after their availability timestamp.
Assignment permission waits until verified expiry settlement; it does not model
an early exercise merely because assignment is acceptable.

ROLL_UP and ROLL_UP_AND_OUT keep the existing strike/expiry invariants. Virtual
ROLL_OUT additionally excludes the existing/earlier expiries to guarantee a real
extension; the legacy live selector's defaults are unchanged. This restriction is
explicit and will be measured as a contract-selection divergence in certification.

Modeled entry credits, BTC ask fills, two-leg roll fills, fees, intervention labor
and assignment opportunity cost reconcile once. Fill price/alpha are per-share;
cash flows/fees/labor are total USD. Actual fill fractions are never trained on
virtual fills. Frozen model/config mismatch, unavailable quotes, or missed scheduled
intervals create censored evidence rather than later filling gaps with future data.
A cycle's action/fills/state/outcome commit atomically; failures can retry safely.
Duplicate scheduler invocations do not duplicate actions or refetch quotes.

The `cc-virtual-management.timer` runs every half hour at :15/:45 during weekday
market hours and at 16:15 Eastern. Each job refreshes its snapshot first, then
manages the isolated book. It logs `VIRTUAL_CC`; actual observation capture logs
`ACTUAL_CC`. Exchange holiday/early-close coverage that cannot be verified remains
censored. `Persistent=false` prevents delayed timers from pretending to run in the
past. Open state survives restart.

## Explicit outcome provenance

`cc_outcomes` stores versioned source, origin episode, chain, time range, snapshot
lineage, evidence hash, completeness/censoring, coverage, model/config and units:

- `ACTUAL_EXECUTION`: actual execution IDs reconciled in the actual database.
- `PROSPECTIVE_VIRTUAL`: forward-only modeled chain, never broker-reconciled.
- `MARKET_PATH_ONLY`: observed path/reconstructed delta; no realized chain costs.
- `ESTIMATED_COUNTERFACTUAL`: retrospective/formula estimates, never prospective.

Corrections append revisions and preserve the source. Virtual cannot upgrade to
actual; estimated data cannot become prospective. Actual performance aggregation
uses only actual-source outcomes. Virtual economics have their own labeled panel.
Pure path evidence can calibrate touch events, but cannot supply realized roll,
assignment-policy or execution economics. Unknown sources/contract versions fail.

Legacy classification appends typed outcomes without rewriting original decisions,
features or labels. Incomplete legacy evidence is never assumed actual. Cost
annotations lacking actual execution IDs are explicitly unreconciled estimates,
not eligible actual costs. Actual costs require fresh reconciled observation.

Live management now observes only quotes it already fetched; there are no extra
market requests or changes to its policy selection. Snapshot and actual-action
records are separate, and replay receives only the snapshot. Additional actual
roll/BTC fill quotes can be reconciled with `record_actual_fill`, which verifies
execution IDs, the originating actual chain and contemporaneous date/time bounds.

## Simulator validation and paired promotion

Validation reconstructs a champion from the original quote, steps through archived
as-of snapshots without actual actions as policy inputs, and then compares actual
and simulated fills, policy actions, intervention timing, roll type/contracts,
fees, P&L, alpha and measured execution/management costs. Human overrides are
identified separately. Missing historical snapshots/leg quote evidence are explicit
exclusions. Legacy manually logged completed positions are enumerated for review;
they are not fabricated into usable replay cases.

The committed simulator gate requires 20 usable chains, entry spread MAE <=20%,
policy action agreement >=80%, median intervention timing error <=1 session,
roll-type agreement >=75%, bounded median alpha error, and zero lookahead/state
contamination. Runs and certifications are immutable; certification is an explicit
operator command and rechecks the raw case metrics and current versions/config.
Below N, status is INSUFFICIENT_EVIDENCE. Threshold tuning needs a new simulator
version and fresh out-of-sample validation.

Paired promotion requires actual champion + prospective virtual challenger on the
same decision lineage, or a zero-alpha/zero-cost NO_CALL arm. Both arms must be
complete on a compatible comparison horizon. The first forward opportunity per
ticker/Eastern session is canonical, preventing cherry-picking a later successful
or uncensored duplicate. Reports include every exclusion and exact cohort IDs.

The existing 100-pair, 30-divergence, 90-day gate now additionally requires a
certified simulator and no execution-cost regression. It retains positive paired
alpha improvement, bounded roll/management cost, assignment safety and calibration
requirements. Changing model/config/simulator invalidates evidence. Mode alone
is excluded from the feature config hash. Promotion remains explicit, records
Git/config/model/simulator/certification/cohort provenance, and fails closed to V2
when activation provenance changes. One explicit rollback restores V2.

```sh
venv/bin/python scripts/cc_evidence.py migrate
venv/bin/python scripts/cc_evidence.py validate
venv/bin/python scripts/cc_evidence.py certify --run-id <passing-validation-run>
venv/bin/python scripts/cc_evidence.py promotion
venv/bin/python scripts/cc_evidence.py promote  # requires evidence_gated + passing evidence
venv/bin/python scripts/cc_evidence.py rollback
venv/bin/python scripts/cc_virtual_job.py
```

Python reconciliation helpers `record_actual_evaluation` and `record_actual_fill`
are in `covered_call_validation.py`. Actual comparison economics remain in the
normal actual evaluator, using `record_chain_costs` for measured costs.

## Surface and active flexibility economics

V1 diagnostics remain alongside V2. V2 leaves a contract out of its own reference
fit, interpolates within observed delta support, and interpolates **total variance**
between bracketing maturities. It never extrapolates unsupported delta/maturity.
Raw reference points, candidate expected IV, residuals and quality are persisted.

Event dates must be known. Pre/post-expiry total variance determines incremental
variance above a bounded non-event forward-variance baseline. With only one
pre-event expiry, a conservative 150% forward-variance bound is explicit. Raw
negative variance is retained diagnostically and the estimate floors to zero.
Unknown event dates or insufficient peers give unavailable values, not fake zero
richness. Event policy still controls eligibility; event premium is not free alpha.

Flexibility cost is explicit: max(0, discounted short-cycle benchmark minus
adjusted alpha) times a bounded lambda (initially 0.5). Second-cycle availability
and alpha retention are each 0.5. Only currently observed, fully V3-eligible shorter
calls can form the benchmark. Missing alternatives mean unavailable benchmark and
zero penalty, not assumed future availability. Duration-adjusted alpha/margin now
ranks the challenger; V2 is unchanged. Each decomposition reconciles all original
costs plus flexibility once. Long DTE can still win when its net economics dominate.

The Learning Lab displays actual vs virtual source, certification status, paired
N/divergence/duration, exclusions/cohort IDs, virtual state/actions/errors, surface
expected IV/quality, and flexibility reference/cost/assumptions. Low-N and censored
data remain visible.

## Release baseline debt

The exact inventory and remediation decisions are in
`config/release_baseline_failures.json` and `release_baseline_failures.md`.
Baseline `dfc011d`: four known failures, reproduced unchanged; temporary waivers
expire 2026-11-12. CI runs the whole suite, then matches exact test IDs and normalized
assertion/error signatures. New/changed failures, expired waivers or stale resolved
inventory fail. No covered-call failures can be waived by this inventory.
