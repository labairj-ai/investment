# Enforce Deterministic Severity Floor on portfolio_state

- **ID:** 0650
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0648, 0649

## Problem

`_enforce_brief_health()` only gates against the health ERROR/DEGRADED → STABLE contradiction. It does not prevent a second class of contradiction: the LLM returning STABLE or ATTENTION when deterministic `attention_items` mandate a higher state.

The deterministic fallback in `_run_briefing_llm()` already establishes the intended semantics:
- High-severity attention item present → URGENT
- Any attention item present → ATTENTION
- No attention + healthy inputs → STABLE permitted

But the LLM path and the fallback path currently have different policies. An LLM can return `portfolio_state = STABLE` with several high-severity items in `attention_items` and `_enforce_brief_health()` will not catch it (because health may be HEALTHY). This means the persisted output can claim STABLE while `attention_items` contains urgent risks.

## Proposed approach

Rename/evolve `_enforce_brief_health()` to `_apply_brief_policy(brief_state, briefing_output)` and add severity-floor rules:

- If any `attention_items` has `severity >= HIGH_THRESHOLD` → `portfolio_state` minimum = `URGENT`
- If any `attention_items` present (any severity) → `portfolio_state` minimum = `ATTENTION`
- If no `attention_items` and brief_health is HEALTHY → `STABLE` permitted
- Existing health-based STABLE prohibition continues unchanged (ERROR/DEGRADED → STABLE forbidden)

Open semantic question to resolve explicitly before implementing: does `portfolio_state` mean **portfolio risk state** or **decision/action required state**? This matters for opportunities: a BUY opportunity with no attention items could coexist with STABLE under risk semantics, but might warrant ATTENTION under action semantics. An outstanding Critic-approved recommendation probably means at least ATTENTION under either interpretation. **Settle this in the implementation PR description before merging.**

When the severity floor fires, apply the same narrative correction as 0649 (deterministic headline replacement + `policy_overrides` entry).

## Touches

- `portfolio_ai.py` — rename `_enforce_brief_health` → `_apply_brief_policy`; add severity-floor rules; apply narrative correction on floor trigger
- `tests/` — adversarial LLM tests: LLM returns STABLE with high-severity attention → URGENT; LLM returns STABLE with ordinary attention → ATTENTION; no attention + healthy → STABLE passes; each severity floor case adds a `policy_overrides` entry

## Done when

- [ ] `_enforce_brief_health` is renamed/evolved to `_apply_brief_policy(brief_state, briefing_output)`
- [ ] High-severity attention items present → `portfolio_state` minimum is `URGENT`
- [ ] Any attention items present → `portfolio_state` minimum is `ATTENTION`
- [ ] Semantic definition of `portfolio_state` (risk state vs. action state) is settled and documented in the function docstring
- [ ] Severity floor triggers the same narrative correction path as 0649 (deterministic headline + `policy_overrides`)
- [ ] Adversarial LLM tests: STABLE + high-severity attention → URGENT; STABLE + any attention → ATTENTION
- [ ] No regression: no attention + HEALTHY brief → STABLE still permitted
