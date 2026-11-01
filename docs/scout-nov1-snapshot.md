# November 1 Scout snapshot correction (TODO 0852)

Base: `47e9236d605a6153bbc538b8dd5ceabd4c3b81ac`. Prepared fix; no live
deployment, Scout start, timer change, epoch reset or acceptance write.

## Deployment review first

Production equals current main, so there is no merged source waiting to deploy.
All five open PRs lack recorded exact-head owner reviews/approval objects:

| PR | Exact head | Remaining blocker |
|---|---|---|
| 19 | e6c106d354c80c2326b8b2795a8dcae3bf04c46e | Owner L5 review; its own documented qualification/operational acceptance remains open. |
| 31 | ef6fe7b56d7443cc20fe75cd700bfe9358c6751b | Draft planning stack; owner review. |
| 32 | 9ffd0108a58adb373182b48146e282b08ca9c2e0 | Draft read-only API; owner review and documented live acceptance. |
| 33 | 39498282f2609eb149d0abe55d6f25e2efe33255 | Draft interface; owner review, live rollout/parity and device/connector acceptance. |
| 35 | a62d5eeace2ff3300256fe5f0d9597c31a71809c | Owner L5 review, conflicts against current main, controller rollout. |

Application source deployment with the Control Center feature OFF need not acquire
Scout execution/autonomy authority. These PRs nevertheless have no existing owner
approval to consume, and their own live rollout/parity acceptance is unfinished.
Their CI success is not that approval or acceptance. No unrelated Scout failure
was used to refuse an otherwise approved deployment. No deploy controller
installation, feature enablement, or draft-stack rebase is included in this fix.

## Evidence and diagnosis

The SYSTEM timer actually fired at November 1 16:01:26 EST. PID 1 recorded job
4885289 and invocation `ec64de828d304e608b8113e3fc3d7e59`. The observer consumed
that exact boot/monotonic timer identity before its snapshot failed. Pre exited 1
with `SOURCE_SNAPSHOT_INVALID`; Main did not start. Post's `BOOKEND_INVALID` is
the existing rejection of `Result != success`, a consequence of Pre failing.

The source manifest, Git HEAD, governance controls and holdings match. No pinned
source file has an mtime after the completed transition. The failure is not a
comparison against transition-time database/WAL fingerprints: `snapshot()` does
not read those fingerprints. That baseline belongs to the source transition,
not to a promise that the live application never updates its database afterward.

The installed reader opens SQLite with `mode=ro` on the observer's read-only
mount. A cleanly closed WAL database may have neither WAL nor SHM. SQLite then
tries to create sidecars even for this read-only connection. A synthetic Linux
read-only bind mount reproduces `OperationalError / SQLITE_CANTOPEN` in the old
reader. The new reader hashes the same fixture successfully, leaves its bytes
unchanged and creates no sidecars. This follows SQLite's documented read-only
WAL constraints: https://www.sqlite.org/wal.html#read_only_databases

Historical certainty is limited: the original root exception was intentionally
discarded by `guarded()`. It cannot be recovered from the journal. The current
production WAL/SHM pair was born at 16:15:06, after the failure; the observer
retains an open descriptor to investment.db. These facts support the reproduced
missing-sidecar diagnosis but do not reconstruct the original sidecar inventory
or prove its original SQLite extended error code. Current read-only namespace
snapshot succeeds after sidecars exist. No unrelated speculative fix is included.

## Minimal correction and safety

Keep the existing transactional read for databases with any sidecar. For a
sidecar-free database only, use `mode=ro&immutable=1` while requiring identical
raw SHA-256, device/inode/size/mtime/ctime before and after, and no WAL/SHM/journal
or sidecar symlink afterward. Reject changing state; never ignore an existing
WAL. The logical iterdump SHA and the existing whole-run before/after comparisons
are unchanged. No database write permission, recovery, checkpoint, fingerprint
substitution, receipt generation, or financial-data copy is introduced.

Risk remains elevated because this read-only observer guards source and financial
safety. Required owner review, CI and the existing source-bound rollout remain
mandatory. No new approval gate or validation framework is added.

## Existing rollout correction

The prior one-shot adapter only admitted the legacy a27 source, so it could not
install this correction from the now-committed 47e source. Reuse that same
transaction with one additional explicit supported old source:
`--old-head 47e9236d605a6153bbc538b8dd5ceabd4c3b81ac`. Other old sources remain
rejected. The current exact config/source, sealed historical archive and COMMITTED
marker must verify; its epoch directory must contain only transition.json. Any
acceptance receipt or unexpected member blocks this zero-credit correction.

Preserve the complete old epoch and reuse the existing sealed a27 history without
rewriting or duplicating it. Retain the November 1 failure's sanitized manager
identity and root observer failure codes in the existing durable transaction plan.
The new source receives its own COMMITTED marker at zero credit; the prior source
stays at zero and the historical a27 source stays at 1/3. No receipt is fabricated,
accepted slot transferred or existing qualification reset.

The same existing fresh, authenticated, exact-head owner capability and merged-main
CI checks apply. The new capability has a target-specific protected filename so
the consumed bootstrap capability remains intact. There is no second owner decision:
one explicit OK authorizes the reviewed head's merge and resulting exact merged
SHA's staging/installation once existing technical gates pass. The existing lock,
quiet-window checks, source/config backups, observer-only stop/start, financial and
candidate preservation, rollback and failure journal remain in use. Scout and its
timer are never started, stopped or edited by this transaction.

Deployment sequence after that one decision: merge this reviewed head; verify
resulting merged-main CI; stage its exact reviewed source under the existing
protected source directory; run PLAN_ONLY with the explicit old head; issue the
existing source-bound capability through the owner-authorized process; APPLY once;
verify source/observer/config, unchanged timer/history/candidates/financial state,
and application HTTP health. If a technical check fails, preserve its evidence and
stop; do not run Scout or manufacture a replacement acceptance.

## Financial and retained-state checks

Both live financial databases pass `integrity_check`; investment.db has zero
foreign-key violations. Holdings and all SHADOW/autonomy controls match the
transition. Against the retained November 1 00:42 backup, orders, fills, position
snapshots, sell transactions, CC positions/fills, virtual positions/fills, actual
fill evidence and execution leases are identical. Differences are in application
findings/runs, recommendations, news, valuation/learning marks and related derived
records; normal application refresh/agent work is independently present in the
journal. The backup is earlier than the transition and is not an exact logical
transition snapshot. No complete row-level comparison to that instant is possible
from its retained byte hashes alone. The earlier FINANCIAL_INTEGRITY=FAIL report
overstated what a later database/WAL byte mismatch establishes.

All five candidate rows match their archived digest. Ledger integrity and its
historical prefix match; only scheduler observations were appended. New-source
acceptance remains 0/3 with only transition.json and no acceptance receipt.
The dashboard service is active and its HTTP root redirects normally (302).
The observer process is active; Scout qualification remains blocked by the failed
run. No runtime financial state, candidate, ledger, archive or evidence is edited.

## Validation and next natural run

Reuse the existing Scout failure tests and release aggregate. Regressions cover
no sidecar creation, real committed WAL inclusion, concurrent database writes,
replacement, symlinks, every sidecar appearing during the read and corrupt input.
Existing epoch-transaction regressions cover the second supported source's
zero-credit admission, unchanged sealed history and prior marker, replay rejection,
capability separation and rollback at each existing mutation stage.
Linux reproduction uses synthetic data under a private read-only bind mount;
no real Scout/certification/timer unit is started.

If this exact fix passes existing CI, receives owner approval and is installed
through the existing source-bound rollout before the next natural firing, it
removes the reproduced no-sidecar failure. A successful natural run still must
pass every existing provenance, collection, bookend and acceptance check. Tests
grant no qualification credit. Latest manager reading is November 2 16:01:26 EST;
the prior 16:00:45 estimate is superseded. Calendar remains 16:00 Eastern with
120 seconds randomized delay; no timer changes were made.
