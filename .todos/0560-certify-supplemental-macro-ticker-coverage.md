# Certify Supplemental Macro Ticker Coverage

- **ID:** 0560
- **Status:** backlog
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** 0558, 0559

## Problem

Formal dimension eligibility is currently tied to the eight tickers in the acceptance artifact, so scoring other candidates does not make them eligible. Add immutable supplemental coverage certification under an accepted contract without modifying the original acceptance lifecycle object.

## Proposed approach

- Create an immutable certification record and macro_coverage_validation rows keyed by certification ID, acceptance record, ticker and dimension. Persist stability class, eligible, N, mean, stddev, scorer/config/evidence schema/model identities, frozen input hashes/artifact links and certification completion timestamp.
- Reuse frozen-input formal N=20 repeatability machinery and the exact accepted dimension policy. Runtime stability must never grant certification, and coverage runs must never activate/replace the acceptance pointer or append to its original validation artifact.
- Allow provenance through either an original accepted ticker-dimension row or a supplemental certification tied to the same active acceptance, scorer, config and model. Continue enforcing runtime evidence quality and score freshness.
- Require certification and score availability before the decision timestamp. Freeze the chosen certification identity into episode/cohort provenance; reject stale-contract, incomplete, future, mismatched or failed certification records.
- Pre-certify likely candidates in the inclusive bounded influence envelope. Maintain historical certifications immutably across contract changes; do not certify all candidates blindly or backfill prior cohorts.

## Touches

agent_db.py; scripts/validate_macro_scorer.py; agents/learning/macro_provenance.py; agents/learning/episode_capture.py; scripts/; tests/

## Done when

- [ ] Supplemental certification cannot mutate original acceptance artifacts, original validation rows or the active acceptance pointer.
- [ ] Original and supplemental provenance paths enforce the same accepted policy, runtime evidence requirements and pre-decision timing.
- [ ] Certification lineage is immutable and tests reject runtime-only eligibility, insufficient samples, future certification and mismatched acceptance/config/model/scorer.
- [ ] A pre-certified candidate outside the original eight-ticker universe becomes eligible only on a later valid prospective sweep.
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced.
