# Stop Explaining Structural Score Changes with Current Macro Conditions

- **ID:** 0480
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0464

## Problem

`generate_macro_score_summary()` feeds week-over-week structural exposure score changes to the LLM and asks it to explain "how the macro environment explains it." After 0464 separated structural exposure from regime, this is architecturally inconsistent: structural exposure should only change when the company changes (new earnings data, business model shift, restructuring), not when rates or the dollar move. The existing summary prompt effectively recreates the AI rationalization loop that 0464 was meant to eliminate — the model will invent plausible-sounding macroeconomic explanations for what may simply be LLM score noise or a prompt-version change.

## Proposed approach

- Rewrite the `generate_macro_score_summary()` prompt to treat structural score changes as evidence of one of three things:
  1. **Changed company evidence** — if the evidence hash (from 0475) changed between the two runs, note what changed
  2. **Model or prompt version change** — if `model_version` or `schema_version` changed between runs (from ledger), label the delta as a version artefact
  3. **Unexplained instability** — if neither evidence nor version changed, label the delta as potential scoring noise
- Remove from the prompt: current VIX, yield, CPI, dollar, spread, and any regime/market data. The summary should receive only: ticker, prior score, current score, prior evidence hash, current evidence hash, prior model version, current model version.
- The macro regime context (what rates, inflation, dollar are doing right now) should appear separately in a **Regime Impact Commentary** section that explains how the *unchanged* structural exposure interacts with the *current* regime — not why the exposure score changed.
- If evidence hash is unavailable (pre-0475 history), label the score change as "evidence unverifiable — treat as potential noise."

## Touches

- `portfolio_ai.py` — `generate_macro_score_summary()` prompt and input assembly
- Dashboard macro risk tab (weekly AI summary display, if it surfaces the summary text)

## Done when

- [x] The summary prompt does not receive current macro conditions (VIX, yield, CPI, curve, dollar)
- [x] Score changes are labelled as evidence-driven, version-artefact, or unexplained-instability based on hash comparison
- [x] A separate "Regime Impact Commentary" section (using current macro) is clearly distinguished from the structural score explanation
- [x] An LLM cannot produce a sentence of the form "GRMN's dollar sensitivity rose because the dollar strengthened this week"
