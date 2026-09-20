# Champion/Challenger Experimental Symmetry

- **ID:** 0345
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0337, 0344

## Problem

The current champion and challenger selection paths differ in more than one variable, making it impossible to attribute performance differences to the learned ranking adjustment alone.

Champion path (approximate): base scores → LLM selects from top-3 → executes champion ticker
Challenger path (approximate): challenger-adjusted scores → highest score wins directly → executes variant ticker

The LLM step, the candidate pool used for selection, and the selection rule (LLM choice vs. top-1 by score) all differ simultaneously. If the challenger outperforms, there is no way to know whether that came from the learned Q/V/PF/C/EC adjustment, from bypassing the LLM, from seeing a different candidate ranking, or from some interaction of all three.

## Proposed approach

Decide on one of two well-defined experiments and implement it cleanly:

**Option A — ranking-only (simpler, recommended first):**
- Champion: select the candidate with the highest *base* composite score (no LLM)
- Challenger: select the candidate with the highest *challenger-adjusted* composite score (no LLM)
- Same candidate universe, same sizing, same execution, same candidate set at selection time
- Treatment variable: learned score adjustment only
- LLM selection becomes a separate, future experiment

**Option B — end-to-end selector:**
- Champion: base top-3 → LLM selects winner
- Challenger: challenger-adjusted top-3 → same LLM model/prompt/temperature selects winner
- Treatment variable: candidate ranking fed into the LLM
- Identical LLM invocation parameters; both record `llm_model`, `llm_why`, `llm_conviction`

Either way, document the chosen experiment design in a new `EXPERIMENT_DESIGN.md` (or a comment block in `opportunity_agent.py`) stating: what the treatment is, what is held constant, and what the null hypothesis is.

## Touches

- `agents/opportunity_agent.py` — enforce single treatment variable in champion/challenger selection; document which experiment is active
- `agents/learning/challenger.py` or opportunity_agent — ensure variant selection uses the same candidate pool and the same LLM call structure if Option B
- `.todos/` or a new `EXPERIMENT_DESIGN.md` — record the chosen design
- `tests/` — test that champion and challenger receive the same candidate set and that only the ranking/selection rule differs

## Done when

- [x] Exactly one variable differs between champion and challenger selection paths (either: score adjustment only, or: ranked input to an identical LLM call)
- [x] The experiment design is documented: treatment variable, constant factors, null hypothesis
- [x] If Option A: LLM is not called for either champion or challenger selection (or is called for both)
- [x] If Option B: same LLM model, prompt template, and temperature for both champion and challenger
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

Chose Option A (ranking-only). `opportunity_agent.py`: CHAMPION_BOOK uses `scored[0]` (top-1 by base composite, no LLM); CHALLENGER_BOOK uses top-1 by `_composite_challenger` score. Treatment variable = learned score adjustment only. The live LLM-selected recommendation is unchanged. 847 tests pass.
