# Enforce Brief-Health Invariant Globally

- **ID:** 0644
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0640

## Problem

The `brief_health != HEALTHY → portfolio_state != STABLE` rule currently only gates the early-return path in `_run_briefing_llm()`. Three other routes to `STABLE` remain unguarded:

1. **LLM path**: when items exist, the model can return `portfolio_state=STABLE` regardless of `brief_health`. There is no postcondition enforcement after `return result`.
2. **LLM failure fallback**: the deterministic fallback produces `"STABLE"` when `attention == []`, even when `brief_health == ERROR` and an opportunity exists.
3. **Top-level exception handler** in `run_briefing_agent()` explicitly returns `"portfolio_state": "STABLE"` paired with `"headline": "Brief generation failed."` — a direct contradiction.

The reliability contract must not depend on the LLM following prompt semantics.

## Proposed approach

Create a single deterministic enforcement function, e.g. `_enforce_brief_health(brief_state, briefing_output) -> dict`, with the invariant:

```
HEALTHY  → STABLE / ATTENTION / URGENT allowed
DEGRADED → STABLE forbidden; UNKNOWN / ATTENTION / URGENT allowed
ERROR    → STABLE forbidden; UNKNOWN / ATTENTION / URGENT allowed
```

Run every `briefing_output` through this function — both LLM returns and fallback returns — before it is used anywhere. The enforcement must be in `portfolio_ai.py` (inside `create_portfolio_brief()` or just before the SAVEPOINT write) so no call site can bypass it, rather than in `agents/briefing_agent.py` where the LLM path already lives.

Note: ATTENTION and URGENT are still permitted even when `brief_health == ERROR`, because deterministic evidence (e.g. a guardian finding) may genuinely warrant action. The invariant only forbids *claiming overall stability* from incomplete evidence.

## Touches

- `portfolio_ai.py` — add `_enforce_brief_health()`, call it in `create_portfolio_brief()` before SAVEPOINT write
- `agents/briefing_agent.py` — fix LLM failure fallback and top-level exception handler to use `"UNKNOWN"` not `"STABLE"`
- `tests/test_portfolio_brief.py` — tests that LLM result `STABLE` is overridden to `UNKNOWN` when `brief_health == ERROR`; fallback path produces `UNKNOWN` not `STABLE` with errored health

## Done when

- [ ] `_enforce_brief_health(brief_state, briefing_output)` exists and enforces the invariant
- [ ] Every `briefing_output` (LLM and fallback) is passed through it before persistence
- [ ] LLM returning `STABLE` with `brief_health=ERROR` is overridden to `UNKNOWN`
- [ ] LLM fallback with `brief_health=ERROR` and no attention items produces `UNKNOWN`, not `STABLE`
- [ ] Top-level exception handler no longer uses `"STABLE"` for failed generation
- [ ] Tests cover LLM-returns-STABLE-but-health-is-ERROR case
