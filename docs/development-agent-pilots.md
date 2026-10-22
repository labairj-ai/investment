# Prospective supervised pilot protocol — TODO 0793

No real pilot has been claimed or completed by the hardening implementation.
Three qualifying successes under the same harness/config/contracts hash must span
at least seven America/New_York calendar days. Failed, abandoned, partial and
rolled-back runs remain visible and do not count. Never backdate evidence.

Proposed real L0–L2 tasks (human approval remains pending):

| Pilot | Proposed scope | Verifiable result |
|---|---|---|
| Documentation | Add a concise operator troubleshooting guide under `docs/` | Explain unavailable sandbox, stale head and missing provenance, with working command examples verified against the CLI parser |
| Regression coverage | Add read-only tests for long and missing readiness metadata | New tests cover unavailable/stale readiness without altering existing tests or financial code |
| Mobile/accessibility | Improve only static presentation of the readiness evidence panel | No horizontal overflow at 360/390/430px, readable focus order and persistent blocker text |

Once technical certification, authentic backup provenance, a provisioned digest-pinned
sandbox image and a non-bypass GitHub identity are available, use the existing Scout,
Planner and explicit candidate approval flow for each task. Freeze `--mode SUPERVISED`
and explicit `focused_tests` in the plan. Commit and bind the plan, approve as an
interactive human, create its isolated worktree, and explicitly invoke `build`.

The operator commits the bounded implementation, then runs `validate` with the
independent reviewer model and `seal` with no input JSON. Push only the scoped agent
branch and invoke `pr`; remote identity is checked after creation/update. Record
human PR disposition at the exact sealed SHA. Merge and deploy remain separate
human actions. `sync-merge` reads and records the independently approved GitHub merge
without performing it. Follow this with an exact deployed-SHA HEALTHY observation. Finally,
`pilot-success --candidate ID` verifies GitHub review, merge SHA and complete ledger
lineage before appending a single operational-success event. It never merges or deploys.

`readiness` reports progress and explicit blockers. A technical canary, a replay,
a free-form actor string or successful test fixtures cannot satisfy a pilot slot.
The autonomous flag remains false. After prospective evidence satisfies TODO 0793,
enabling TODO 0794 still requires a separately reviewed configuration change;
`DEV_AGENT_KILL_SWITCH=1` immediately blocks new starts without changing credentials.

## Solo-owner review authority

Independent human review may be performed by the repository owner, including for their own GitHub-authored changes. It requires a separate authenticated exact-head owner attestation; authorship, Builder/Reviewer PASS and CI are insufficient. New commits invalidate approval. The owner performs the final merge. All financial/execution evidence and prospective pilot requirements remain unchanged. See [owner workflow](solo-owner-governance.md).
