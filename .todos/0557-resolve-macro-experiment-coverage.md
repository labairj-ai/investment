# Resolve Macro Experiment Opportunity Coverage

- **ID:** 0557
- **Status:** blocked
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0549, 0550, 0553

## Finding

The authoritative production universe has 79 unowned Opportunity Hunter candidates
and zero overlap with the eight tickers carrying accepted per-dimension eligibility.
The new experiment therefore records coverage exclusions until valid accepted
macro evidence becomes available for its actual opportunity universe.

## Constraint

The user explicitly froze acceptance unless a real defect is discovered. This is
a coverage/scope limitation, not evidence of a scorer defect. Do not loosen
eligibility, reopen acceptance, insert holdings into the opportunity universe,
or retrospectively populate prospective cohorts to make the count increase.

## Done when

- [ ] A compatible coverage path exists under the frozen acceptance policy, or
      the user changes the experiment/coverage scope explicitly.
- [ ] A real future sweep records usable accepted macro candidates in both arms.
- [ ] Prospective collection starts without any production recommendation influence.

Outcome maturation and evidence evaluation follow collection; neither can be
declared complete before the preregistered horizon and uncertainty requirements.
