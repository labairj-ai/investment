# OptiPlex 0851/0852 live rollout — 2026-10-24

Approved/current production release:
`05d6cccf734d4604d1a8c10406d9e3d7598e9c6f` (PR15).
The rollout used only its unchanged reviewed installers. No source fix was
installed, no application restart performed, and no model service accessed/changed.

## L0 Validator: READY

The actual oracle service is active as investment-oracle (UID996/GID987), nologin,
no supplementary groups. Source is root-controlled under
`/opt/investment-static-oracle`; the protected Git authority is root:oracle0750,
key oracle0600 and socket/private runtime directory oracle0700. Other identities
cannot access key/socket or write source/authority. Loaded sandbox facts are in
`oracle-loaded-boundaries.txt`: empty capabilities, NoNewPrivileges, AF_UNIX only,
PrivateNetwork, ProtectHome, strict filesystem protection and inaccessible app/
Docker paths. No network, credentials or production DB access is granted.

The real installed acceptance unit completed at 2026-10-24 18:01:37 UTC, invocation
`6ee0af3f6fe0459db2cf5b4100931d72`. Its host-generated
[l0-live-acceptance.json](l0-live-acceptance.json) is copied without alteration from
`/var/lib/investment-static-oracle-acceptance/live-acceptance.json`. SHA256 sidecars
preserve identity. All **22 checks PASS**, including actual installed socket
validation, off-identity denial and real worker failure processes. Generated
hostile inputs are explicitly identified; these are real host-boundary probes,
not pytest fixtures or a genuine discovered pilot.

The receipt binds exact application/source/runtime/harness identities, service,
timestamps and complete matrix. fixture_only=false; scope=L0_STATIC_TEXT;
grants_pytest_authority=false; grants_activation=false; grants_implementation=false.
Both installed root services are currently running; the unchanged bootstrap
installers start them but do not enable them at boot. No stronger reboot-persistence
claim is made. Independent pytest authority and protected pilot-base updates remain
separate 0853 prerequisites; this receipt cannot activate implementation.

## Discovery: NOT READY — dedicated reader credential unavailable

The reviewed root-owned observer installed successfully and is active. See
`discovery-loaded-boundaries.txt`. The real discovery installer then rejected
absence of `/home/optiplex/.config/investment-development/github-read.token` before
writing any user unit, collecting a spool or enabling any timer. The only located
GitHub credential belonged to existing backup infrastructure; it was not read,
reused or copied. No dedicated reader permissions were claimed or fabricated.

Scout/timer, signal collector/timer and scheduler observer/timer are not installed
or enabled. The control ledger already existed; no migration was needed/run by
the failed installer. No primed spool or accepted source availability exists.
Genuine runs: **0/3**; first actual timer: none; generated ideas: none. There are no
run slots/invocations, durations/counts, candidates, dedup/suppression counts or
host-safety results to report. No manual Scout or synthetic run was performed and
no discovery.json exists. The reviewed calendar remains daily08:15 New York plus
0–120 seconds jitter; an uninstalled timer has no actual scheduled fire time.

## Protected state and the retained fingerprint failure

[rollout-verification.json](rollout-verification.json) is an independent operator
reconciliation, explicitly **not a discovery run**. Before/after identities match
for holdings, investment.db, buffett.db and the full empty control ledger. The
private service environment digest is unchanged (not exported). Current unit and
all drop-in contents exactly match the PR15 deployment's preserved configuration;
its SHA256 is recorded. Investment MainPID1611800 and start/active times remain
2026-10-24 13:50:08 EDT, before this rollout. Source remains exact/clean; existing
untracked overlays match the approved deployment inventory. All activation flags
remain false, stageSHADOW, maximum riskL2 and required_human_merge=true.

The old Executor.config_hash check **failed** and is retained verbatim. It hashes
systemctl's ExecStart execution bookkeeping: daemon-reload cleared those PID/start
fields to pid=0/start_time=[n/a] without restarting the process or changing the
configuration. Independent persistent-content, private-environment and process
checks establish actual configuration stability; the failed old hash is not
relabelled PASS. A minimal source fix with regressions is proposed on this branch
for review only. It hashes complete unit/drop-in text and stable loaded metadata,
rejects NeedDaemonReload and checks for read races. No private credential access,
extra privilege, sandbox exception or authority gate is added.

The original private pre/post observations remain on OptiPlex under
`/home/optiplex/.local/share/investment-rollout/0851-0852-05d6ccc/`.
No database contents, credentials, signing material or raw investment data were
copied from the host. 0852 remains open until credential provisioning, successful
priming and three distinct actual timer runs with automatic bookends. 0853/0854
were not started. Proposed TODO0847/0851 closure concerns this actual L0 acceptance
only and follows normal evidence-PR review; production files remain untouched.
