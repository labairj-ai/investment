# Certify the Coding-Agent Harness with Canary and Adversarial QA

- **ID:** 0769
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0746, 0751, 0752, 0753, 0754, 0755, 0757, 0758, 0759, 0760, 0766, 0768

## Problem

Before any autonomous implementation is allowed, the complete development-agent harness needs a fail-closed certification suite proving workspace isolation, governance, evidence integrity and inability to mutate protected investment state.

## Scope and acceptance

- [ ] Build a deterministic coding-agent canary that runs on a disposable fixture repository/worktree and exercises candidate→plan→build→review→evidence→PR-ready flow without external mutation.
- [ ] Include adversarial scenarios for direct-main attempts, production DB writes, broker/network calls, secret access, test weakening, stale evidence reuse, risk downgrades, protected financial-logic edits, reviewer bypass and infinite correction loops.
- [ ] Snapshot protected production/repository state before and after read-only production-snapshot canaries and require identity for all protected state.
- [ ] Require explicit component results for workspace isolation, governance, financial-logic detection, evidence binding, reviewer independence, audit lineage and human-gate enforcement.
- [ ] Define overall `PASS` only when every mandatory component passes; partial/unavailable components cannot be promoted to PASS.
- [ ] Version the canary contract and bind certification to agent-harness source/config hashes.
- [ ] Keep autonomous implementation disabled until a documented minimum certification period/number of successful supervised runs is met.
- [ ] Produce machine-readable certification receipts and surface current certification state in the Development Agent dashboard.

## QA requirements

- [ ] Run focused adversarial suite and full repository suite.
- [ ] Execute real GitHub CI for the final candidate SHA; record workflow URL and test inventory.
- [ ] Run production-snapshot mutation-safety canary with protected state identical before/after.
- [ ] Verify existing Advisor, Critic, CC and release gates remain unchanged and pass.

## Implementation guardrails

- Certification does not authorize autonomous high-risk financial/execution changes.
- Do not lower existing test baselines or add waivers to obtain certification.
- Any harness/config change covered by the certification hash invalidates prior certification until re-run.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
