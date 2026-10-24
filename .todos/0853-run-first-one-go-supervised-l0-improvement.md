# TODO 0853 — Run the First One-Go Supervised L0 Improvement

- **ID:** 0853
- **Status:** backlog
- **Priority:** critical strategic
- **Risk:** L3
- **Parent:** 0849
- **Depends:** 0851, 0852
- **Blocks:** 0854

## Objective

Run the first genuine Development Agent improvement through the simplified solo-owner workflow.

The owner experience must be:

ChatGPT reviews the actual PR and CI → recommends GO or NO-GO → owner replies Go or No-Go.

No second approval ceremony.

## Candidate requirements

Use a real L0 improvement discovered from an accepted live signal.

Eligible examples:

- stale documentation;
- missing or incorrect help text;
- harmless static documentation metadata;
- user-facing documentation drift.

Do not use a fixture-only task as the final acceptance candidate.

## Required flow

- [ ] Real discovery signal accepted.
- [ ] Candidate scope frozen.
- [ ] L0 risk classification confirmed.
- [ ] Disposable isolated worktree created.
- [ ] Builder receives only bounded context and write-action authority.
- [ ] Builder produces only allowed L0 edits.
- [ ] Independent Reviewer runs separately.
- [ ] Live L0 validator PASS.
- [ ] Full required repository CI/gates PASS.
- [ ] PR created with exact candidate head.
- [ ] Pipeline stops at AWAITING_OWNER.
- [ ] ChatGPT reviews actual PR/code/CI.
- [ ] ChatGPT recommends GO or NO-GO in plain English.
- [ ] Owner replies Go or No-Go.
- [ ] Exact owner decision is bound to the reviewed head.
- [ ] Stale/new head invalidates the decision.
- [ ] If Go: exact reviewed head merges only after CI.
- [ ] Merged-main CI runs and must PASS.
- [ ] If No-Go: no merge and no deployment eligibility.

## One-Go requirement

The owner must not be asked to:

- copy a SHA;
- manually post a structured GitHub comment;
- separately approve deployment;
- separately approve promotion;
- understand certificate/protocol details;
- run a command-line script.

Internal receipts may be created automatically from the one exact-head Go.

## Safety acceptance

Verify the journey does not:

- modify investment data;
- modify holdings;
- alter financial/execution logic;
- change governance policy;
- enable autonomous implementation;
- enable auto-merge;
- grant Builder production credentials;
- deploy before 0854.

## Required evidence

Preserve:

- discovery receipt;
- frozen plan/scope;
- Builder model/provider identity;
- Reviewer identity/result;
- L0 validator result;
- full CI/gate result;
- PR number and exact head;
- ChatGPT GO/NO-GO recommendation;
- owner decision;
- merge SHA if Go;
- merged-main CI result.

## QA

Exercise at least one negative/stale-head path in non-production acceptance and prove it fails closed.

## Done when

One real L0 candidate reaches successful merged-main CI through a single owner Go, or a real No-Go correctly stops the flow, and 0849 can be closed on actual evidence.
