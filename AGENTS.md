# Repository Coding-Agent Contract

Contract version: 2 (solo-owner-1). This contract applies equally to Codex, Claude and every other
approved model, tool or runner working in this repository. It grants no execution,
production or deployment authority by itself.

## Mission

Implement approved, evidence-backed repository improvements with the smallest
necessary change. Inspect existing architecture, relevant TODOs, tests and domain
contracts before proposing changes. Development-agent evidence and learning must
remain separate from investment recommendations and portfolio learning cohorts.

## Source of record

The OptiPlex production database is authoritative for investment state.
Development tasks must not write authoritative production data.
Do not write investment data to a Mac development database or generate production
artifacts (including dashboard.html) locally. Tests may use disposable synthetic
fixtures and temporary databases; an explicitly authorized read-only snapshot must
remain read-only and isolated from runtime paths. Never substitute a local copy
for the production source of record. Existing documented production generation
procedures require separate explicit authorization outside development work.

## Required workflow

1. Start from verified current main in an isolated task branch or worktree; inspect
   working-tree state and preserve unrelated work. Record the base SHA and TODO.
2. Plan before code for non-trivial work: state the problem, acceptance criteria,
   scope, risk, tests and required human decisions. Implement the smallest scope.
3. Run focused tests and required regression tests. Review the complete candidate
   diff, including generated/configuration files and all commits, for scope,
   safety, test integrity and secret exposure.
4. Run the existing TODO consistency, exact release-baseline and CC behavioral
   contract gates unchanged, plus the full suite used in CI:
   `pytest tests/ -v --tb=short --junitxml=test-results.xml`.
5. Record exact implementation SHA, commands, results, skip/waiver inventory and
   real CI workflow URL before claiming PR readiness. Evidence is valid only for
   the tested source/configuration; changed code requires refreshed evidence.
6. Use PR-based changes; satisfy required owner/human review and existing
   branch protections. Move a TODO to `.todos/done/` only after every acceptance
   and QA requirement is met with implementation and CI evidence. Incomplete or
   unavailable checks remain explicitly open, never silently marked PASS.

## Authority boundaries

The coding agent may inspect source and prepare reversible development changes
and PRs within the approved task. It may run isolated fixture tests. This is not
permission to deploy, schedule autonomous execution, access secrets, call external
brokers, mutate accounts or alter live trading state.

## Forbidden actions

- Do not implement directly on main or push implementation directly to main.
- Do not self-approve or bypass independent review or required human approval.
- Do not delete or weaken tests to obtain PASS.
- Do not silently rewrite baselines or reduce acceptance thresholds.
- Do not modify secrets or log credentials.
- Do not call brokers or change live trading state.
- Do not deploy or mutate authoritative production data from development work.
- Do not treat missing evidence, user silence or model judgment as approval.

Existing release, CI, production, canary and investment safety controls remain
mandatory. This contract cannot authorize exceptions to those controls.

## Solo-owner governance

For this personal repository, the repository owner may serve as the human reviewer
and approver, including for changes authored through the owner's GitHub account.
Independent review separates human authority from AI and automation authority.
A second human reviewer is optional unless explicitly required by the owner for a
specific change. Coding agents cannot approve their own work. Reviewer models, CI
and autonomous workflows cannot grant merge authority. The human repository owner
retains final merge authority and must explicitly review and approve the exact
current PR head before merge. Authorship is not approval; a new head invalidates
prior approval. This is an intentional permanent owner governance decision, not a
PR #6 exemption. The existing rule against agent self-approval remains in force.

- L0–L2: owner review plus required CI/evidence.
- L3: explicit owner review and rationale.
- L4: explicit owner financial-domain review, financial canaries, behavioral-contract
  evidence and applicable observation gates.
- L5: explicit owner approval, execution/account-mutation safeguards and required
  technical deployment gates; financial risk must be surfaced in the review.

Owner review must be an authenticated deliberate action, separate from Builder and
Reviewer evidence, bound to repository, PR, exact head, reviewed risk, timestamp
and nonce. Agents must never manufacture that action. auto_merge=false and
required_human_merge=true remain mandatory. The owner performs the final merge.
The owner may authorize the isolated owner connector to perform that exact merge
by saying Go after ChatGPT reviews the actual PR and CI. That same Go authorizes
the resulting exact merge SHA to deploy after merged-main CI and all technical
safety gates pass. A No-Go blocks both merge and deployment. A changed head
requires a fresh review and Go. No additional deployment, financial, execution or
autonomy-promotion phrase is required. Elevated financial, execution, deployment,
governance and autonomy risks must be clearly surfaced before Go. Internal review,
merge and deployment receipts remain separate; none bypasses technical controls.
Builder/Reviewer and discovery have no owner credentials, merge or deployment
capability. Internal staging is automatic safety evidence, not owner ceremony.

## Investment-sensitive changes

Recommendations, risk policy, position sizing, covered calls, learning/promotion,
order/fill generation and account mutation are elevated-risk domains.
Investment-sensitive changes require explicit human review before merge.
Evaluate the whole change and its indirect effects; file names, small diffs and
splitting changes across commits do not make financial behavior low risk. Unknown
or mixed scope receives the highest applicable controls pending human review.
Existing Advisor, Critic, CC, execution and release canaries remain mandatory when
applicable. Neither this contract nor a passing test grants execution authority.

## Precedence and escalation

Follow applicable system/user authority and preserve existing mandatory safety
controls. AGENTS.md supplies repository-wide agent boundaries; architecture and
domain documents supply behavioral invariants; TODOs supply task-specific scope
and acceptance criteria. A TODO cannot silently override this contract or domain
safety constraints. Legacy helper instructions cannot authorize a weaker workflow
or keeping completed TODOs outside `.todos/done/`.
On safety-relevant conflicts, fail closed and escalate to the human.
Stop the affected operation, preserve the safer existing behavior, and report the
conflicting documents, concrete requirement, impact and decision needed. Do not
choose a permissive interpretation. Independent safe inspection may continue.
Unexpected scope expansion, unavailable mandatory evidence, ambiguous authority or
repeated validation failure must be reported with an explicit unresolved state.
Changes to this contract or its validation require human review; an agent cannot
relax its own authority or self-authorize an exception.

## Representative applications

A CSS-only mobile layout fix uses a task branch, a scoped plan, viewport checks,
focused and required regression tests, diff review, SHA-bound evidence and a PR.
It grants no database-write or deployment permission. If a UI edit also changes a
recommendation calculation, apply investment-sensitive controls to the full diff.

A covered-call sizing or risk-policy change requires explicit human review,
existing financial behavioral contracts and applicable canaries in addition to the
normal workflow. A conflicting TODO requesting weaker thresholds is blocked and
escalated; preserve the existing thresholds. Never merge it on self-approval.
