# Remove "Ground Truth" Language from AI Macro Score Labels

- **ID:** 0472
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

The README describes the weekly AI macro scores as "the ground-truth baseline used by all downstream AI systems." This is inaccurate and potentially harmful: the scores are LLM-estimated macro exposures generated from ticker names and dimension descriptions, not measured facts. Calling them ground truth could lead future contributors or automated systems to treat them with unwarranted confidence, particularly if they are ever wired into the Learning Lab or Risk Engine. The mislabeling should be corrected immediately, independently of the longer-term work to replace LLM estimates with deterministic factors.

## Proposed approach

- Remove the phrase "ground-truth baseline" from README and replace with accurate language such as "AI-estimated structural macro exposure scores" or "LLM macro exposure estimates (v1)"
- Audit the dashboard UI for any labels that imply the scores are measured or authoritative (e.g. tooltip text, card headers, score column labels) and update to reflect their estimated nature
- Add a visible caveat in the Macro Risk tab (e.g. a small note under the score cards): "Scores are LLM estimates — not derived from measured company data"
- In the DB, add or update a `score_source` column value (or metadata field) on `holding_macro_scores` rows to `llm_estimate_v1` so any query or consumer can identify the provenance
- This is a labeling/documentation task only — no scoring logic changes

## Touches

- `README.md` (Weekly Macro Scorer section)
- Dashboard macro risk tab (score card labels, tooltips)
- `holding_macro_scores` schema (optional `score_source` column)

## Done when

- [ ] The phrase "ground-truth" no longer appears in README in reference to AI macro scores
- [ ] README describes scores as LLM estimates with explicit acknowledgment of their limitations
- [ ] Dashboard macro risk section includes a visible caveat that scores are LLM-estimated, not measured
