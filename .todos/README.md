# Investment bug-fix backlog

Created October 21, 2026 from the [deep review](../docs/plans/investment-deep-review-20261021.md). All 15 items are **implemented locally and archived as done**. See the [implementation receipt](../docs/plans/investment-backlog-implementation-20261021.md). Evidence covers 17 reproduced scenarios. The inaccessible shared-conversation link supplied no additional readable requirements.

| ID | Priority | Finding | Dependencies |
|---|---|---|---|
| [0745](done/0745-canonical-approved-thesis-status.md) | critical | Approved theses are ignored by policy and invalidation readers | none |
| [0746](done/0746-serialize-fifo-sales-before-inventory-read.md) | critical | Concurrent sells can oversell inventory and corrupt the ledger | none |
| [0747](done/0747-restore-only-undone-sale-allocations.md) | critical | Undoing an earlier sale restores shares that are still sold | 0746 |
| [0748](done/0748-reserve-aggregate-covered-call-obligations.md) | critical | Covered-call checks ignore outstanding calls and order reservations | none |
| [0749](done/0749-preserve-call-coverage-on-equity-sales.md) | critical | Equity sales can remove shares backing an open covered call | 0748 |
| [0750](done/0750-retry-intents-after-transient-quote-failures.md) | high | A temporary quote failure permanently strands an approved intent | none |
| [0751](done/0751-require-session-correct-outcome-prices.md) | high | Stale holding prices silently become horizon outcomes | none |
| [0752](done/0752-aggregate-newsletter-holdings-before-ledger-overrides.md) | high | Multi-lot CSV holdings are double-counted in newsletter valuation | none |
| [0753](done/0753-rebuild-sale-snapshots-without-erasing-history.md) | high | Selling leaves stale snapshots or deletes valid history | 0754 |
| [0754](done/0754-synchronize-portfolio-projections-after-undo-and-lot-delete.md) | high | Undo and lot deletion leave authoritative holdings projections inconsistent | 0746, 0747 |
| [0755](done/0755-recompute-surviving-fifo-cost-basis.md) | high | FIFO sales do not update the surviving position's average cost | 0754 |
| [0756](done/0756-validate-lot-quantity-cost-and-purchase-date.md) | high | Lot-add accepts negative inventory | none |
| [0757](done/0757-include-working-buys-in-new-position-caps.md) | high | New-position sizing caps omit working buy reservations | none |
| [0758](done/0758-use-one-exchange-calendar-for-newsletter-and-dashboard.md) | normal | Newsletter and dashboard use a federal holiday calendar as an exchange calendar | none |
| [0759](done/0759-reconstruct-historical-virtual-books-as-of-session.md) | high | Historical MTM repair includes future trades and current cash | none |

## Implementation order (completed)

1. Thesis safety and inventory protection: 0745, 0756, 0746, 0747.
2. Portfolio projections: 0754, then 0753 and 0755.
3. Execution safety: 0748, 0749, 0750 and 0757.
4. Valuation and learning integrity: 0752, 0758, 0751 and 0759.

All listed items passed local validation. The dependency column records the implementation prerequisites.

## Completion rules

Keep items here while backlog/in-progress. Add regression and validation receipts before marking done and moving them into `done/`. Run `venv/bin/python scripts/check_todo_status.py`. Any protected covered-call behavior change must satisfy the existing release authorization gates. Production-data diagnosis/repair and deployment must be recorded separately from local code completion.

## Coding-agent implementation backlog (0760–0784)

Renumbered after completed task 0759. These are separate from the completed investment fixes above.

| ID | Task | Status |
|---|---|---|
| [0760](0760-establish-repository-coding-agent-contract.md) | Establish Repository Coding-Agent Contract | in-progress |
| [0761](0761-classify-coding-agent-change-risk.md) | Classify Coding-Agent Change Risk | in-progress |
| [0762](0762-add-improvement-candidate-schema-and-ledger.md) | Add Improvement Candidate Schema and Ledger | in-progress |
| [0763](0763-build-improvement-scout.md) | Build Improvement Scout | in-progress |
| [0764](0764-score-improvement-candidate-value-and-risk.md) | Score Improvement Candidate Value and Risk | in-progress |
| [0765](0765-build-todo-planner-for-approved-candidates.md) | Build TODO Planner for Approved Candidates | in-progress |
| [0766](0766-add-isolated-git-worktree-manager.md) | Add Isolated Git Worktree Manager | in-progress |
| [0767](0767-build-bounded-coding-agent-runner.md) | Build Bounded Coding-Agent Runner | in-progress |
| [0768](0768-add-independent-coding-agent-reviewer.md) | Add Independent Coding-Agent Reviewer | in-progress |
| [0769](0769-build-builder-reviewer-correction-loop.md) | Build Builder-Reviewer Correction Loop | in-progress |
| [0770](0770-collect-coding-agent-test-and-evidence-receipts.md) | Collect Coding-Agent Test and Evidence Receipts | in-progress |
| [0771](0771-create-coding-agent-pull-requests-with-evidence.md) | Create Coding-Agent Pull Requests with Evidence | in-progress |
| [0772](0772-enforce-github-branch-and-ruleset-protection-for-agent-changes.md) | Enforce GitHub Branch and Ruleset Protection for Agent Changes | in-progress |
| [0773](0773-add-production-mutability-guard-for-development-agents.md) | Add Production-Mutability Guard for Development Agents | in-progress |
| [0774](0774-detect-financial-logic-changes-in-agent-diffs.md) | Detect Financial-Logic Changes in Agent Diffs | in-progress |
| [0775](0775-persist-coding-agent-run-ledger-and-audit-history.md) | Persist Coding-Agent Run Ledger and Audit History | in-progress |
| [0776](0776-add-development-agent-dashboard.md) | Add Development Agent Dashboard | in-progress |
| [0777](0777-make-development-agent-review-mobile-friendly.md) | Make Development Agent Review Mobile Friendly | in-progress |
| [0778](0778-capture-deployment-outcomes-for-agent-changes.md) | Capture Deployment Outcomes for Agent Changes | in-progress |
| [0779](0779-score-coding-agent-improvement-effectiveness.md) | Score Coding-Agent Improvement Effectiveness | in-progress |
| [0780](0780-scan-architecture-and-technical-debt-for-improvement-candidates.md) | Scan Architecture and Technical Debt for Improvement Candidates | in-progress |
| [0781](0781-enforce-coding-agent-golden-engineering-principles.md) | Enforce Coding-Agent Golden Engineering Principles | in-progress |
| [0782](0782-schedule-daily-improvement-agent-discovery.md) | Schedule Daily Improvement-Agent Discovery | in-progress |
| [0783](0783-add-human-approval-and-escalation-workflow.md) | Add Human Approval and Escalation Workflow | in-progress |
| [0784](0784-certify-the-coding-agent-harness-with-canary-and-adversarial-qa.md) | Certify the Coding-Agent Harness with Canary and Adversarial QA | in-progress |

## Coding-agent hardening and rollout (0785–0794)

Captured from the [shared conversation](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). These are backlog entries only. Complete trust-chain hardening (0785–0790), then readiness/adversarial work (0791–0792), then prospective supervised pilots (0793). Task 0794 remains dependent on successful pilots and the required observation period; creating these tasks grants no autonomy, merge or deployment authority.

| ID | Task | Depends |
|---|---|---|
| [0785](0785-trusted-validation-evidence.md) | Make Validation Evidence Harness-Generated and Non-Spoofable | 0770, 0784 |
| [0786](0786-authenticate-production-snapshot-provenance.md) | Bind Production Snapshot Certification to Authentic Backup Provenance | 0784 |
| [0787](0787-separate-supervised-autonomous-execution.md) | Separate Supervised and Autonomous Coding-Agent Execution Modes | 0767, 0783, 0784, 0785 |
| [0788](0788-authenticate-supervised-operational-evidence.md) | Replace Synthetic Supervision with Authenticated Operational Run Evidence | 0775, 0783, 0787 |
| [0789](0789-verify-sealed-pr-head-sha.md) | Bind GitHub Pull Requests to the Exact Sealed Head SHA | 0771, 0785 |
| [0790](0790-verify-effective-github-protection.md) | Verify Effective GitHub Protection Across Branch Protection and Rulesets | 0772 |
| [0791](0791-display-agent-certification-readiness.md) | Surface Real Coding-Agent Certification and Readiness in the Dashboard | 0776, 0777, 0785, 0786, 0787, 0788, 0790 |
| [0792](0792-expand-agent-authority-adversarial-certification.md) | Expand Development-Agent Adversarial Certification for Evidence and Authority Bypasses | 0785, 0786, 0787, 0788, 0789, 0790, 0791 |
| [0793](0793-run-three-supervised-low-risk-pilots.md) | Run and Evaluate Three Supervised Low-Risk Development-Agent Pilots | 0785, 0786, 0787, 0788, 0789, 0790, 0791, 0792 |
| [0794](0794-enable-bounded-low-risk-autonomy.md) | Enable Bounded L0–L2 Autonomous Implementation-to-PR | 0793 |

## Development-agent operational acceptance — 0795–0802

Created 2026-10-22. This phase proves the environment and controls; it is not an
additional agent-feature phase. 0795 is **in-progress**; 0796–0802 remain **backlog**.

| ID | Task | Priority | Dependencies |
|---|---|---|---|
| [0795](0795-resolve-covered-call-ci-and-behavioral-contract-failures.md) | Resolve Existing Covered-Call CI and Behavioral-Contract Failures | critical | none |
| [0796](0796-restore-exact-head-green-repository-ci.md) | Restore Exact-Head Green Repository CI | critical | 0795 |
| [0797](0797-configure-non-bypass-github-protection.md) | Configure and Verify Non-Bypass GitHub Protection for Development-Agent Changes | critical | 0790, 0796 |
| [0798](0798-provision-digest-pinned-validation-sandbox.md) | Provision Digest-Pinned Development-Agent Sandbox Runtime | critical | 0796 |
| [0799](0799-certify-authentic-production-backup-snapshot.md) | Produce and Certify an Authentic Production Backup Snapshot | critical | 0786, 0796 |
| [0800](0800-complete-development-agent-technical-certification-v2.md) | Complete Development-Agent Technical Certification v2 | critical | 0796, 0797, 0798, 0799, 0792, 0803, 0804 |
| [0801](0801-execute-prospective-supervised-development-agent-pilots.md) | Execute Three Prospective Supervised Development-Agent Pilots | high | 0800, 0805, 0807, 0808, 0809 |
| [0802](0802-authorize-bounded-low-risk-autonomous-operation.md) | Review and Explicitly Authorize Bounded L0–L2 Autonomous Operation | critical | 0801, 0794 |

Critical path: **0795 CC failures → 0796 green CI → 0797 GitHub protection +
0798 sandbox + 0799 authentic snapshot → 0800 technical certification →
0801 three real supervised pilots over ≥7 America/New_York calendar days →
0802 explicit autonomy decision**.

Do not start 0801 until 0795–0800 are truly PASS. 0801 completes the operational
portion of 0793; 0802 also retains dependency on the disabled controls in 0794.
Existing hardening dependencies 0786, 0790 and 0792 remain required; deployed code
is not a substitute for their independent acceptance evidence. Protection changes
belong to a human administrator; autonomy activation requires a separate reviewed
human decision. Creating these files grants neither authority.

## Trust-boundary review follow-up — 0803–0809

All seven items are in-progress; none is operationally accepted yet. 0803/0804 additionally block 0800; 0805/0807/0808/0809 block qualifying 0801 evidence. 0806 is a parallel CC workstream that blocks production promotion of cc-v3.4.

| ID | Task | Depends | Blocks |
|---|---|---|---|
| [0803](0803-isolate-trusted-regression-tests.md) | Isolate Trusted Regression Tests from Agent-Modified Test Code | 0785, 0798 | 0800, 0801 |
| [0804](0804-harden-github-actions-agent-code.md) | Harden GitHub Actions Against Agent-Generated Code | 0796, 0798 | 0800, 0801 |
| [0805](0805-revalidate-protection-through-pilot-success.md) | Revalidate GitHub Protection Through Merge and Pilot Success | 0797 | 0801 |
| [0806](0806-reject-non-finite-covered-call-decision-inputs.md) | Fail Closed on Non-Finite Covered-Call Decision Inputs Before Recommendation Math | 0795 | production promotion of cc-v3.4 |
| [0807](0807-classify-active-html-svg-risk.md) | Tighten Risk Classification for Active HTML and SVG Content | 0746, 0794 | future autonomous L2 presentation work |
| [0808](0808-disable-hooks-ambient-agent-git-config.md) | Disable Git Hooks and Ambient Git Configuration for Agent Git Operations | 0751, 0771 | 0801 |
| [0809](0809-bind-dashboard-decisions-operator-identity.md) | Bind Dashboard Human Decisions to a Unique Authenticated Operator Identity | 0768 | strong 0801 supervision evidence |

Requested workstream order: **0803 → 0804 → 0805 → 0808 → 0797/0798/0799 → 0800 → 0801 → 0802**. Run 0806 in parallel; complete 0807/0809 before pilots count.

Dependency review required before execution: the explicit prerequisites remain authoritative. 0803 and 0804 require 0798, and 0805 requires 0797, so those environmental prerequisites must precede their completion despite the requested workstream order. 0807 retains the supplied dependency on 0794, while 0794 requires the pilots that 0807 must precede; this sequencing conflict must be resolved explicitly before certification/pilot progression. No dependencies were silently removed.
