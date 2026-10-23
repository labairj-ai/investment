# TODO 0816 — Reconcile Development-Agent Hardening with Solo-Owner Governance

- **ID:** 0816
- **Status:** backlog
- **Priority:** critical
- **Risk:** L5 — governance / development-agent authority
- **Depends:** 0810, 0811, 0812, 0815
- **Blocks:** 0817, 0819, 0822, 0823, 0824

## Problem

Current production at `3b497914270fe53beaecba9c8d2fdd0b80f427fe` contains a split governance implementation.

The selective incorporation of PR #7 restored important trust-boundary hardening but also overwrote parts of the solo-owner governance introduced by PR #9.

Current examples:

- `AGENTS.md` matches the older PR #7 governance contract.
- `dev_agent/cli.py` matches the older PR #7 implementation.
- `dev_agent/dashboard.py` matches the older PR #7 implementation.
- `dev_agent/github.py` matches the older PR #7 implementation.
- `dev_agent/operations.py` matches the older PR #7 implementation.
- `dev_agent/store.py` matches the older PR #7 implementation.
- `config/development_agent.json` still declares `governance_model=solo-owner-1`.
- `scripts/check_agent_contract.py` expects the solo-owner governance section.
- `dev_agent/owner_review.py` and `dev_agent/solo_protection.py` remain present from PR #9.

The repository therefore has different definitions of approval authority depending on which code path is executed.

This must be reconciled before enabling autonomous implementation or treating the Development Agent as a reliable continuous-improvement control plane.

## Scope and acceptance

- [ ] Restore `AGENTS.md` contract version `solo-owner-1`.
- [ ] Restore the explicit `## Solo-owner governance` section.
- [ ] State unambiguously that the repository owner may review and approve AI-assisted changes authored through the owner's GitHub account.
- [ ] State that a second human reviewer is optional unless explicitly requested by the owner.
- [ ] Preserve the requirement that Builder and Reviewer models remain independent.
- [ ] Preserve the prohibition against model, CI, agent or automation self-approval.
- [ ] Preserve `auto_merge=false`.
- [ ] Preserve `required_human_merge=true`.
- [ ] Preserve explicit L4 financial acknowledgment requirements.
- [ ] Preserve explicit L5 execution/account-mutation acknowledgment requirements.
- [ ] Reconcile `dev_agent/github.py` so merge recording requires a fresh exact-head owner attestation rather than GitHub `reviewDecision == APPROVED`.
- [ ] Preserve PR #7's exact-head verification and GitHub protection evidence.
- [ ] Preserve PR #7's separation between agent identity and repository-owner authority.
- [ ] Reconcile `dev_agent/operations.py` so supervised success requires both:
  - exact-head owner approval, and
  - complete protection/evidence lifecycle.
- [ ] Restore `OWNER_REVIEW` as a protected append-only event in `dev_agent/store.py`.
- [ ] Restore owner-review CLI operations from PR #9.
- [ ] Restore owner-review dashboard/API functionality from PR #9.
- [ ] Preserve PR #7's hardened dashboard identity boundary.
- [ ] Preserve Tailscale Serve / loopback identity validation.
- [ ] Preserve owner-binding configuration outside candidate-controlled source.
- [ ] Ensure candidate/build agents cannot construct a valid `HumanIdentity`.
- [ ] Ensure an owner review becomes stale immediately when the PR head SHA changes.
- [ ] Ensure an owner review cannot be reused for another repository, PR, SHA, risk level or decision.
- [ ] Ensure a candidate cannot lower its own deterministic risk classification.
- [ ] Ensure governance files remain outside generic Builder authority.
- [ ] Document the final authority flow in `docs/solo-owner-governance.md`.
- [ ] Update `docs/development-agent.md` so no text still requires a second human reviewer.
- [ ] Remove conflicting references to "independent human review" where model independence is what is intended.

## Required tests

- [ ] Owner may approve their own GitHub-authored AI-assisted PR.
- [ ] Owner authorship alone does not constitute approval.
- [ ] Reviewer-model PASS does not constitute owner approval.
- [ ] Builder-model output cannot produce an owner approval.
- [ ] Agent GitHub identity cannot be interpreted as owner identity.
- [ ] Owner approval for SHA A is invalid for SHA B.
- [ ] Owner approval for PR A is invalid for PR B.
- [ ] Owner approval for repository A is invalid for repository B.
- [ ] Replayed owner-review nonce fails.
- [ ] Missing owner binding fails closed.
- [ ] Ambiguous owner identity fails closed.
- [ ] L3 approval without rationale fails.
- [ ] L4 approval without financial acknowledgment fails.
- [ ] L5 approval without execution acknowledgment fails.
- [ ] Auto-merge remains impossible.
- [ ] Agent-triggered merge remains impossible.
- [ ] Merge recording succeeds after a valid exact-head owner-authorized merge.
- [ ] Merge recording fails if GitHub reports a different merged head.
- [ ] Merge recording fails if `merged_by` is not the configured repository owner.
- [ ] Existing PR #7 containment/protection tests remain green.

## Adversarial QA

Attempt to:

- forge `OWNER_REVIEW` directly in the development ledger;
- inject owner identity through request JSON;
- spoof Tailscale headers from a non-loopback request;
- reuse an approval nonce;
- approve SHA A and push SHA B;
- change risk from L5 to L2 after approval;
- substitute an agent GitHub account for the owner;
- satisfy owner approval using reviewer-model output;
- satisfy owner approval using a GitHub CI status;
- merge using auto-merge;
- create a synthetic GitHub merge event.

Every attempt must fail closed.

## Implementation guardrails

- Do not weaken PR #7 containment, test-oracle or Git-execution hardening.
- Do not restore a required second human reviewer.
- Do not give agents access to owner credentials.
- Do not grant agents GitHub administrative authority.
- Do not enable autonomous implementation as part of this task.
- Do not enable automatic merge.
- Do not change investment recommendation behavior.
- Do not modify production financial data.
- Make the smallest reconciliation necessary rather than replacing either PR wholesale.

## Done when

- [ ] Governance code has one consistent owner-authority model.
- [ ] Static governance check passes.
- [ ] Owner-review tests pass.
- [ ] Development-agent focused tests pass.
- [ ] Complete regression suite passes.
- [ ] Exact-head GitHub CI passes.
- [ ] Implementation SHA and evidence are recorded.
