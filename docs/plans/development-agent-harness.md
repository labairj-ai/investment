# Development-agent harness implementation

Base: 468cb64. Tasks: 0760–0784 (previous coding-agent IDs +15).

Build isolated development-control storage, deterministic risk/dependency analysis,
evidence-backed discovery and atomic TODO planning; pinned worktrees; provider-neutral
structured-action builder and independent reviewer; bounded correction; SHA-bound
receipts and PR handoff; GitHub protection verification; immutable run/approval/outcome
history; separate mobile dashboard and explicit authenticated approvals; daily discovery
units (not enabled); versioned engineering principles and adversarial certification.

Risk: governance/execution tooling is conservative L5. No investment calculation,
broker call, live account write, production generation or deployment is included.
Existing domain fingerprints and release thresholds remain unchanged.

Validation: deterministic fixture tests for lifecycle/approval/replay, ID concurrency,
path escapes/symlinks, import reachability, stale/tampered evidence, worktrees,
provider/reviewer failure, bounded loops, dashboard escaping/auth, scheduling/DST,
protection/certification failure. Run focused tests and full CI suite, exact baseline,
TODO consistency, agent-contract and CC gates. Live GitHub settings and physical
mobile acceptance must be observed; unavailable evidence is never marked PASS.

Do not enable autonomous implementation/scheduling or merge this branch on agent
self-approval. Missing external acceptance remains recorded per task.

## Implementation coverage

| Task | Implementation |
|---|---|
| 0760 | `AGENTS.md; scripts/check_agent_contract.py` |
| 0761 | `dev_agent/policy.py` |
| 0762 | `dev_agent/store.py` |
| 0763 | `dev_agent/discovery.py: scout` |
| 0764 | `dev_agent/discovery.py: score` |
| 0765 | `dev_agent/discovery.py: plan/refresh_plan` |
| 0766 | `dev_agent/worktrees.py` |
| 0767 | `dev_agent/providers.py; dev_agent/runner.py` |
| 0768 | `dev_agent/runner.py: review` |
| 0769 | `dev_agent/runner.py: Runner` |
| 0770 | `dev_agent/evidence.py` |
| 0771 | `dev_agent/github.py: prepare_pr/GitHub.handoff` |
| 0772 | `dev_agent/github.py: protections/verify_protections; docs/development-agent.md` |
| 0773 | `dev_agent/guard.py; dev_agent/runner.py: ContainerValidator` |
| 0774 | `dev_agent/policy.py: protected_graph/whole_diff` |
| 0775 | `dev_agent/store.py: run_event/query_runs` |
| 0776 | `dev_agent/dashboard.py; serve.py; generate_dashboard.py` |
| 0777 | `dev_agent/dashboard.py; scripts/check_development_agent_browser.mjs` |
| 0778 | `dev_agent/outcomes.py: observe` |
| 0779 | `dev_agent/outcomes.py: effectiveness/aggregate` |
| 0780 | `dev_agent/discovery.py: architecture_signals` |
| 0781 | `dev_agent/policy.py: PRINCIPLES; scripts/check_development_agent.py` |
| 0782 | `dev_agent/scheduler.py; systemd/development-scout.*` |
| 0783 | `dev_agent/store.py: decide/review_decision; dev_agent/dashboard.py` |
| 0784 | `dev_agent/certification.py; dev_agent/snapshot.py` |

## Validation and remaining acceptance

Local full-suite checkpoints passed (2,748 and subsequently 2,753 passed, 18 skipped).
Final focused checkpoint: 94 passed including timezone guards. A final refreshed
full-suite run and exact-head GitHub CI are recorded in PR checks/evidence. Existing
TODO, agent-contract, exact baseline and CC gates are retained. No waiver, threshold,
financial source, model version or behavioral baseline was changed.

Exact viewport checks pass at 360/390/430/1280px: no overflow, no injected HTML,
44px controls and a confirmation dialog. Run the checked-in Node browser script
against a separate headless browser on localhost:9237; it writes only synthetic
fixtures and screenshots to the requested temporary artifact directory.

The snapshot canary ran on OptiPlex against an isolated copy of the saved pre-deploy
backup. All 123 tables remained unchanged; SQL and runner writes were denied. No
live database was opened and no investment service was changed.

Open operational acceptance: GitHub main is unprotected (API 404); Docker validation
runtime/image unavailable; physical iPhone/Android observation absent; supervised
certification period (three successful runs over seven days) not met. The code
reports FAIL/UNAVAILABLE/PARTIAL accordingly. Configuration keeps autonomous
implementation and auto-merge disabled; supplied systemd units are not enabled.
Human review is required before merge, especially for governance, API and runner
changes. All tasks remain in-progress pending their full independent acceptance;
no unobserved QA checkbox is marked done. This PR does not deploy the harness.

Implementation evidence: [validation receipt](../evidence/development-agent-20261021/validation.json). Final local checkpoint: 2,756 passed and 18 skipped; final focused checks: 96 passed. Exact-head CI remains the final full-suite authority.
