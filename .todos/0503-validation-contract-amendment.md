# Validation Contract Amendment v1.1

- **ID:** 0503
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0498

## Problem

The original live run (contract v1) produced BLOCK with 1 FAIL (UUP anchor) and 15 WARN. The UUP anchor was invalid: UUP is classified as an ETF in SECURITY_MASTER and would never receive a live production score. The first result must be preserved as-is; the amendment must document why the anchor was invalid before seeing the replacement result.

## Proposed approach

- **Preserve** `out/macro_validation_acceptance_20260919_134153.json` — never delete or overwrite
- Create `validation_config_v1.1.json` that:
  - Documents the UUP anchor as invalid (ETF, never receives production score, wrong test subject)
  - References the original run ID as the prior BLOCK
  - Replaces UUP with a supported-company dollar anchor using relative ordering rather than a narrow bracket:
    - LOW: a domestic US company with independently established low foreign-revenue % (e.g. NEE — domestic utility, <5% foreign revenue per `company_financials`) → expected `[1, 4]`
    - HIGH: a large multinational with >50% foreign revenue → expected `[6, 10]`
    - Relative invariant: `low_ticker_score < high_ticker_score` (more robust than absolute bracket)
  - Do NOT choose the anchor ticker because "we expect the LLM to score it low/high" — choose it because the evidence source independently establishes its exposure level
- Add `amendment_note` field to config: `"Replaces v1: UUP invalid anchor (ETF, unsupported in production). NEE chosen based on company_financials foreign_rev_pct <5%, not based on expected LLM output."`
- Bump `config_version` to `"v1.1"`

## Touches

- `validation_config.json` → versioned to v1.1
- `scripts/validate_macro_scorer.py` — update ANCHORS dict to use NEE + multinational relative pair

## Done when

- [ ] Original `macro_validation_acceptance_20260919_134153.json` preserved unmodified
- [ ] `validation_config.json` versioned to v1.1 with UUP removal rationale documented
- [ ] Replacement anchor uses independently-evidenced company, not LLM-expectation-based selection
- [ ] Relative ordering test added (low < high domestic-vs-multinational pair)
- [ ] Amendment committed before 0505 rerun executes
