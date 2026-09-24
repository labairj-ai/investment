# Final-State Narrative Policy

- **ID:** 0654
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0649, 0653

## Problem

After 0649, `_record_override()` uses the same deterministic template regardless of which policy fired:

```
"Portfolio assessment incomplete — <reason>; stability cannot be confirmed."
```

This template is appropriate for a health degradation override (the assessment is genuinely incomplete) but wrong for an attention floor override (the assessment is complete and found something urgent). A STABLE → URGENT override triggered by a high-severity Guardian finding currently produces:

```
"Portfolio assessment incomplete — high-severity attention item present; stability cannot be confirmed."
```

That's a false claim. The assessment is complete. The problem is that there is something urgent.

A second sequencing issue: if health first overrides STABLE → UNKNOWN and then severity overrides UNKNOWN → URGENT, the first health narrative remains as the headline. The final state is URGENT but the user reads "assessment incomplete."

The rule should be: **the final `portfolio_state` drives the final deterministic narrative.** Health degradation becomes a secondary clause when both conditions exist.

## Proposed approach

After all policy evaluation is complete, generate a single deterministic headline/key_question based on the *final* `portfolio_state` and the *primary* reason that determined it:

```
URGENT  (severity floor):
  headline:     "Urgent portfolio attention required — <first high-severity item summary>."
  key_question: "Review <ticker/finding_type> before making any allocation changes."

ATTENTION (attention floor):
  headline:     "Portfolio needs attention — <reason>."
  key_question: "Review open attention items before the next trading session."

UNKNOWN (health gate, no attention):
  headline:     "Portfolio assessment incomplete — <health problem>; stability cannot be confirmed."
  key_question: "Resolve <health problem> before relying on today's brief."

URGENT + health degraded (both conditions):
  headline:     "Urgent portfolio attention required — <first high-severity item>. (Note: <health problem> also active.)"
  key_question: "Review <ticker/finding_type>. Resolve <health problem> for full assessment."

STABLE:
  No override — use LLM headline (it is consistent with the state).
```

Replace intermediate `policy_overrides` narrative entries with a single final narrative generation step at the end of `_apply_brief_policy()`. `policy_overrides` still records each individual override as a structured audit entry — just the headline/key_question is set once at the end, not incrementally.

## Touches

- `portfolio_ai.py` — `_apply_brief_policy()`: replace incremental narrative writes with a single final-state narrative pass; distinct templates per final state; combined URGENT+UNKNOWN template
- `tests/` — test: STABLE→URGENT severity override → URGENT headline not incomplete-assessment headline; test: health UNKNOWN + high-severity → URGENT headline with health note as secondary clause; test: STABLE final state → LLM headline preserved unchanged; test: ATTENTION floor → attention headline not incomplete-assessment

## Done when

- [ ] URGENT final state (from severity floor) produces "Urgent portfolio attention required — ..." headline
- [ ] UNKNOWN final state (from health gate only) produces "Portfolio assessment incomplete — ..." headline
- [ ] URGENT final state with health degradation also active produces combined headline with health note as secondary clause
- [ ] STABLE final state preserves original LLM headline (no override)
- [ ] `policy_overrides` still records each individual policy step as a structured audit entry
- [ ] Headline/key_question are set once after all policy evaluation, not incrementally per override
- [ ] Tests cover URGENT-only, UNKNOWN-only, URGENT+UNKNOWN, ATTENTION, and STABLE paths
