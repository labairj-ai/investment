# Build Deterministic Confidence Scoring System

- **ID:** 0007
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005

## Problem

Currently the system has no formal confidence metric — recommendations carry qualitative language but no numeric confidence that the dashboard can surface or filter by. Asking the LLM to self-report confidence is unreliable. Confidence must be calculated deterministically from measurable properties of the input data, then capped based on known data quality limits.

## Proposed approach

Implement `calculate_confidence(evidence: EvidenceBundle) → int` in `agents/confidence.py`.

Formula: `Confidence = 0.30*D + 0.20*F + 0.20*S + 0.15*A + 0.15*R` (all components 0–100).

**D — Data completeness (max 100):**
- Price present: 15 pts
- Financial history (≥4 quarters): 20 pts
- Macro scores: 15 pts
- Relevant news (≤6h): 15 pts
- Event calendar: 10 pts
- Cost basis: 10 pts
- Strategy metadata (thesis, layer assignment): 15 pts

**F — Freshness (exponential decay per source):**
`Freshness = e^(-ln(2) * age / half_life)`
Half-lives: option quote 5min, market quote (session) 15min, news 6h, macro market 1h, macro classification 7 days, financial statement → until next filing.

**S — Source quality:**
Official filing (100) > primary corporate release (85) > reputable news (65) > secondary commentary (40).

**A — Agreement (0–100):**
Fraction of evidence signals pointing the same direction as the recommendation.

**R — Rule support (0–100):**
What fraction of the conclusion is supported by deterministic rules vs. qualitative judgment. CC rec with live cc_alpha, IV richness, liquidity scores → high R. Geopolitical thesis → low R.

**Confidence caps (applied after formula):**
- Live option quote + good liquidity: max 95
- Ask proxy: max 70
- Theoretical option pricing: max 45
- Single news source: max 60
- Missing recent fundamentals: max 65
- Critic verdict = CHALLENGE: max 60
- Missing cost basis (tax rec): max 40

## Touches

`agents/confidence.py`, `agents/contracts.py` (EvidenceBundle type), all agent files (pass evidence in)

## Done when

- [ ] `calculate_confidence()` accepts an `EvidenceBundle` and returns int 0–100
- [ ] All 5 components (D, F, S, A, R) implemented
- [ ] All 7 confidence caps applied correctly (caps are applied after formula)
- [ ] Unit test with a fully-populated bundle returns > 80; sparse bundle with theoretical option data returns ≤ 45
- [ ] No LLM calls in `confidence.py`
- [ ] QA (backend): Call `calculate_confidence()` with (a) a fully-populated EvidenceBundle and confirm score > 80, and (b) a sparse bundle with theoretical option data and confirm score ≤ 45. Verify all 7 caps apply correctly with a test case that hits each cap. Log actual computed scores before checking this box — do NOT check based on reading the code.

