# Add Hard EXIT Trigger for Critical Pillar Violation

- **ID:** 0143
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** none

## Problem

When a critical pillar is violated, `_score_T()` inflates T to `max(T, 90)`, giving a minimum SellStrength of 36 (0.40 × 90). Combined with average other components (F=30, V=35, P=20, O=20), this produces ss ≈ 36 + 6 + 5 + 3 + 2 = 52 → TRIM, not EXIT. A TRIM response to a broken critical investment thesis understates urgency: the original reason for owning the position no longer holds.

A critical pillar is defined as one of the 2–3 reasons the position exists. Its violation means "the investment case is structurally broken" — that is an EXIT scenario, not a TRIM. The current soft inflation is not sufficient.

## Proposed approach

Add a `_hard_exit` flag in `_run()` when a critical pillar is violated:

```python
critical_violated = any(
    d.get("critical") or d.get("status") == "VIOLATED" and d.get("critical")
    for d in t_detail
)
```

Or better: have `_score_T()` return a third value (`critical_violated: bool`) alongside `(T, t_detail)`.

When `critical_violated = True`:
- Force `action = "EXIT"` regardless of ss (bypass `_action_from_strength()`)
- Set `priority = "urgent"`
- Include a note in `action_payload`: `"critical_pillar_violated": True`
- The LLM prompt should be updated to mention the hard exit trigger

This preserves the composite score for display and logging (so the user can see why other components are) but ensures the action is EXIT, not TRIM.

## Touches

- `agents/sell_trim_agent.py` — `_score_T()` to return `critical_violated` flag; `_run()` to apply hard EXIT
- LLM prompt builder — add hard exit context to prompt

## Done when

- [ ] A position with a violated critical pillar always receives EXIT, not TRIM
- [ ] The critical_violated flag is stored in action_payload
- [ ] A position with warnings only (no violations) still follows composite scoring
- [ ] Existing tests pass
