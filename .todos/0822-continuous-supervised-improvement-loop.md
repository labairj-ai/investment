# TODO 0822 — Build the Continuous Supervised Improvement Loop

- **ID:** 0822
- **Status:** backlog
- **Priority:** critical strategic
- **Risk:** L3 — automated software development
- **Depends:** 0816, 0817, 0818, 0819, 0820, 0821
- **Blocks:** 0824

## Problem

The repository has most individual Development Agent components, but they are not yet connected into an always-running improvement pipeline.

The desired workflow is:

observe → discover → prioritize → plan → build → review → correct → validate → PR → owner OK/NO → merge → deploy → observe outcome.

The system should make meaningful progress without requiring the owner to manually initiate each coding session.

## Scope and acceptance

### Candidate progression

- [ ] Automatically identify eligible discovered candidates.
- [ ] Enforce backlog limit.
- [ ] Enforce per-day candidate cap.
- [ ] Enforce dependency ordering.
- [ ] Exclude unresolved duplicates.
- [ ] Re-score when evidence changes.
- [ ] Never automatically approve L3+ work.

### Automatic planning

For eligible L0–L2 candidates:

- [ ] Generate bounded implementation plan.
- [ ] Generate TODO with externally verifiable criteria.
- [ ] Identify affected files.
- [ ] Identify focused tests.
- [ ] Calculate deterministic risk.
- [ ] Freeze scope before build.
- [ ] Prevent Builder from editing the TODO or governance contract.

### Builder

- [ ] Create isolated worktree.
- [ ] Use bounded structured file-write actions only.
- [ ] No shell/tool authority from model.
- [ ] Enforce file allowlist.
- [ ] Enforce line/action/time budgets.
- [ ] Stop if risk increases.
- [ ] Stop if scope expands.

### Reviewer

- [ ] Use a separate provider/model context.
- [ ] Reviewer receives requirements, diff and validation evidence.
- [ ] Reviewer receives no Builder private reasoning.
- [ ] Reviewer cannot mutate files.
- [ ] Findings use stable IDs.
- [ ] Builder must address every unresolved finding.
- [ ] Conflicting findings escalate.

### Correction loop

- [ ] Maximum bounded iterations.
- [ ] Maximum bounded written lines.
- [ ] Maximum bounded elapsed time.
- [ ] Repeated high-severity failure escalates.
- [ ] No endless retry loop.

### Validation

- [ ] Run 0818 trusted validation.
- [ ] Run focused tests.
- [ ] Run full regression suite.
- [ ] Run release baseline.
- [ ] Run CC contract where applicable.
- [ ] Run governance checks.
- [ ] Bind all evidence to exact candidate head.

### PR creation

- [ ] Automatically commit reviewed candidate.
- [ ] Push only scoped agent branch.
- [ ] Open/update one PR per candidate.
- [ ] PR body includes:
  - problem,
  - expected outcome,
  - risk,
  - changed files,
  - test results,
  - reviewer disposition,
  - unresolved limitations,
  - exact head,
  - rollback,
  - deployment expectations.
- [ ] Never merge automatically.
- [ ] Notify owner/ChatGPT workflow that a PR is ready for review.

## State machine

Implement explicit states such as:

`DISCOVERED`
→ `PLANNED`
→ `APPROVED_FOR_BUILD`
→ `BUILDING`
→ `REVIEWING`
→ `VALIDATING`
→ `PR_READY`
→ `AWAITING_OWNER`
→ `MERGED`
→ `DEPLOYMENT_PENDING`
→ `DEPLOYED`
→ `OBSERVING`
→ `CLOSED`

with explicit failure/escalation states.

## Required tests

- [ ] L0 candidate can progress automatically to PR.
- [ ] L1 candidate can progress automatically to PR.
- [ ] L2 candidate can progress automatically to PR.
- [ ] L3 candidate stops for human authorization.
- [ ] L4 candidate cannot enter generic Builder.
- [ ] L5 candidate cannot enter generic Builder.
- [ ] Increased risk mid-build stops progression.
- [ ] Failed reviewer stops PR readiness.
- [ ] Missing validation stops PR readiness.
- [ ] Stale SHA invalidates evidence.
- [ ] Changed PR head invalidates owner approval.
- [ ] Agent cannot merge.
- [ ] Agent cannot deploy.
- [ ] Agent cannot edit main.
- [ ] Agent cannot alter GitHub rulesets.

## Operational QA

Complete at least three real supervised candidate journeys:

1. documentation/cleanup;
2. test or low-risk tooling improvement;
3. low-risk UI/site enhancement.

Each must complete:

discovery → plan → build → reviewer → correction if needed → validation → PR → owner OK → merge → deployment → healthy observation.

## Implementation guardrails

- Auto-merge remains false.
- Autonomous implementation remains false during initial rollout.
- Builder cannot mutate investment state.
- Builder cannot access production secrets.
- Deployment remains outside this component.
- L4/L5 remain owner-controlled.

## Done when

- [ ] Agents can generate a reviewed, tested PR from an observed problem without the owner manually initiating coding.
- [ ] Owner interaction begins at the OK/NO decision unless earlier escalation is genuinely required.
- [ ] Three supervised end-to-end runs succeed.
