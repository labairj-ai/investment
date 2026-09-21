# Run a Prospective Macro Coverage Canary

- **ID:** 0562
- **Status:** backlog
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** 0558, 0559, 0560, 0561

## Problem

Installed experiment infrastructure does not establish that usable prospective collection has begun. Require one real, fully coverage-balanced Opportunity Hunter sweep under the accepted repaired contract, with an auditable stage-0 result, before starting the experiment clock.

## Proposed approach

- Prepare evidence, candidate scores and supplemental certifications for likely envelope candidates before a later real sweep. If that sweep's envelope changes or coverage is incomplete, retain the exclusion and prepare for another future sweep; do not repair it retrospectively.
- Verify current accepted scorer identity, pre-decision score and certification completion, passing runtime evidence quality, full envelope certification and nonempty common dimensions.
- Verify control/macro winners, frozen universe and lineage, cohort status OBSERVED, both isolated virtual books and the rendered Learning Lab report. Selection divergence is not required for the first usable cohort.
- Compare production output with the macro-disabled existing production path using the same frozen inputs and identical recorded LLM response where applicable. The deterministic experimental control winner is not necessarily the existing production LLM winner; do not change production selection to force equality.
- Confirm stage=0, no production macro weights or macro-origin live trade intents. Use shadow books only; do not execute real trades as part of this canary.
- Persist canary evidence (IDs, timestamps, hashes, coverage, selections, book/API/UI checks and production parity). Start the prospective clock at the first qualifying observed decision timestamp, then freeze the protocol while outcomes mature.

## Touches

agents/opportunity_agent.py; agents/learning/macro_experiment.py; scripts/; Learning Lab; production canary artifacts; tests/

## Done when

- [ ] A real later sweep is OBSERVED with all accepted/current, point-in-time, envelope and common-dimension conditions proven from persisted records.
- [ ] Both virtual books and Learning Lab are checked; missing prices or incomplete marks are reported and never presented as complete MTM.
- [ ] Production parity against the existing macro-disabled path is demonstrated; stage remains zero and no production macro influence or canary live trade is introduced.
- [ ] A durable canary artifact establishes the first usable prospective timestamp; no backfill, automatic promotion or early-horizon effectiveness claim occurs.
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced.
