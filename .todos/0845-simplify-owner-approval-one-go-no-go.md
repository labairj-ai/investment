# TODO 0845 — Simplify Owner Approval to One Go / No-Go Decision

- **ID:** 0845
- **Status:** backlog
- **Priority:** critical
- **Risk:** L5 — owner authority
- **Depends:** PR #14 current implementation
- **Blocks:** 0849
- **Supersedes:** owner-facing portions of 0838 and 0843

## Objective

Reduce the repository owner's normal workflow to one decision: Go or No-Go. Internal controls may remain separate, but they must not create additional owner actions.

## Required owner workflow

Agent PR → ChatGPT reviews exact code/head/CI → ChatGPT recommends GO or NO-GO → owner says Go or No-Go → system performs permitted downstream actions automatically.

A Go applies only to the exact reviewed PR head. If that head changes, a new review and new Go are required.

## Go authorization semantics

For an ordinary reviewed PR, Go authorizes exact-head owner approval, merge after exact-head CI passes, deployment of the resulting merge SHA after merged-main CI passes, and automatic post-deployment health/state verification.

Go never bypasses a technical gate and never authorizes another SHA or PR.

## Elevated-risk changes

For L4/L5 work, ChatGPT must clearly tell the owner that the PR affects financial, execution, governance or autonomy behavior before recommending GO. The owner response remains Go or No-Go.

Do not require separate financial, execution, promotion or deployment phrases.

## Remove owner-facing promotion ceremony

The owner must not separately issue an autonomy-promotion approval during normal operation. If an internal promotion object remains useful for audit, derive it from the exact owner-approved activation PR without another owner action.

## Deployment authorization

Do not require a second owner interaction after merge. The original exact-head Go may become an internal deployment authorization only after the exact approved head merged, the merge actor is valid, merged-main CI passes, current main contains the merge, and deployment targets that exact merge SHA.

## Required tests

- [ ] Go on head A cannot merge head B.
- [ ] Changed head invalidates Go.
- [ ] No-Go prevents merge.
- [ ] Failed exact-head CI prevents merge despite Go.
- [ ] Failed merged-main CI prevents deployment despite Go.
- [ ] Successful merged-main CI permits deployment without another owner interaction.
- [ ] Go cannot authorize another PR.
- [ ] Go cannot raise autonomy risk.
- [ ] Go cannot bypass investment-state protection.
- [ ] Replay against another SHA fails.
- [ ] Review, merge and deployment remain distinct internal receipts.

## Guardrails

Keep auto_merge=false, exact-SHA enforcement, autonomous merge disabled and autonomous deployment disabled. Builder/Reviewer cannot manufacture owner approval. Do not enable autonomy here.

## Done when

Normal owner operation requires only Go or No-Go.
