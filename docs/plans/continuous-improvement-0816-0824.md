# Continuous improvement implementation plan

Base main: 3b497914270fe53beaecba9c8d2fdd0b80f427fe, verified against origin on 2026-10-23. Task branch starts with TODO-only commit 4be150e. Highest risk L5: authority, validation and deployment admission. No financial recommendation, broker, authoritative database or release-baseline changes.

1. Reconcile owner authority from merged PR #9 with PR #7 containment, exact-head protection lineage, oracle and Git wrappers. Restore tests before extending authority.
2. Add independent CI gate execution and a complete exact-SHA aggregate receipt. Preserve existing check semantics and fail on missing mandatory evidence.
3. Remove candidate filesystem authority over normalized results. Treat in-process pytest evidence as hostile; fail closed where independent oracle/result integrity cannot be established. Do not label an untrusted event stream authoritative merely because a host process serializes it.
4. Consume structured owner-authenticated GitHub decisions read-only; keep writing decisions and owner credentials outside the development-agent process. Exact-head decisions never enable auto-merge.
5. Add observed discovery scheduling and bounded read-only operational signals. Keep scout networkless and implementation-free; network-capable signal gathering belongs to a separate trusted collector.
6. Connect bounded supervised progression to PR only; allow policy-based L0–L2 progression only under separately authenticated frozen policy and fresh certification. Never synthesize a human approval event.
7. Build fixed-command deployment admission/execution/rollback as a separate component, with a pinned operator trust root, explicit deployment authorization and no arbitrary command strings. No live rollout until review/admission gates pass.
8. Add shadow/build-only/PR stage control, bounded caps and pause conditions. Keep autonomous_implementation=false. Real three-run/seven-day evidence and separate owner governance approval are required to activate.

Validation: focused boundary/adversarial tests, all existing Development Agent tests, TODO/repository/development governance, full pytest, release baseline and exact-prior CC contract, and exact-head GitHub CI. Record fixture versus operational evidence explicitly. Real scheduler runs, identity/app/runner provisioning, supervised journeys and observation time cannot be manufactured; those acceptance boxes remain open until observed. All nine TODOs remain in-progress until their full acceptance is met.
