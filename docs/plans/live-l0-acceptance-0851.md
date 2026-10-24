# Live 0851/0852 acceptance and service-identity regression

Base/deployed source: `05d6cccf734d4604d1a8c10406d9e3d7598e9c6f`.
Risk: L5 (deployment fingerprint/evidence). No financial behavior or activation changes.

The approved validator installer and real installed harness passed all 22 checks
on OptiPlex. The root discovery observer is installed/running. The discovery
installer correctly stopped at the absent dedicated reader credential before any
user units, collector priming or timers were installed/enabled. No Scout runs.

Live daemon reload exposed an unrelated existing fingerprint defect:
Executor.config_hash hashes ExecStart process timestamps/PIDs. systemd cleared
these bookkeeping fields on daemon reload while investment.service retained its
PID/start time and identical unit/drop-in/private environment contents. All
protected state hashes are identical. Preserve the failed old fingerprint and
independent persistent-content comparisons; do not relabel that check PASS.

Small fix: fingerprint complete unit/drop-in text and stable loaded metadata;
require NeedDaemonReload=no and consistent metadata before/after reading the
unit text. Do not read private credentials or add privileges. Detect command,
unit, drop-in, user/environment-path changes, missing/stale metadata and races.
Test those conditions plus stability across differing ExecStart runtime metadata.

Record sanitized live evidence and proposed TODO 0847/0851 closure through this
branch. Keep 0852 open at 0/3, with no discovered candidates or synthetic host
observations. Run focused/full tests and all eight unchanged release gates, open
an exact-head PR and obtain CI evidence. Do not merge or deploy this fix. Leave
production on its approved SHA, all four implementation/publication/merge flags
false, SHADOW and required_human_merge=true. Existing models/app remain untouched.
