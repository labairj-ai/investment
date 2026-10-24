# TODO 0849 — Prove the One-Step Supervised Development Flow

- **ID:** 0849
- **Status:** backlog
- **Priority:** critical strategic
- **Risk:** L3
- **Depends:** 0845, 0847, 0848
- **Blocks:** 0850
- **Supersedes:** 0838 and 0841

## Objective

Prove the real owner experience:

1. Agent creates a harmless PR.
2. ChatGPT reviews actual code and CI.
3. ChatGPT says GO or NO-GO.
4. Owner says Go.
5. System handles the rest.

## Candidate

Use a real L0 change generated from an actual discovery signal. Do not use a manufactured fixture as the final pilot.

## Required path

DISCOVERED → PLANNED → BUILDING → REVIEWING → VALIDATING → PR_READY → AWAITING_OWNER.

Then ChatGPT review → owner Go → exact-head merge after CI → merged-main CI → internal downstream deployment authorization.

## Required evidence

- [ ] real discovery signal;
- [ ] frozen scope;
- [ ] Builder output;
- [ ] independent Reviewer result;
- [ ] L0 validator result;
- [ ] full repository CI;
- [ ] exact PR head;
- [ ] ChatGPT recommendation;
- [ ] owner's Go;
- [ ] exact merge SHA.

## Negative pilot

Exercise one No-Go case and confirm no merge, deployment or reinterpretation of No-Go.

## Owner experience acceptance

Owner must not copy SHAs, create GitHub comments, issue deployment/promotion approvals, run scripts or understand certificate status.

## Done when

A real agent-generated PR reaches merge eligibility using only one owner Go.
