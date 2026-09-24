# Formalize Subsystem Criticality for Freshness and Brief Health

- **ID:** 0651
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0647

## Problem

All freshness sources currently contribute equally to `freshness.overall` and thus to `brief_health`. This includes `macro_scores` and `learning_sweep`, which the brief itself explicitly marks as observe-only with zero production influence. A stale macro experiment or learning sweep degrades `brief_health` to DEGRADED, which then forbids STABLE — even though those subsystems cannot affect any production decision.

As more observe-only experiments are added, this becomes increasingly conservative: every new experimental subsystem becomes another way to degrade the entire brief health, producing UNKNOWN states on production briefs that are factually reliable for the decision-critical sources.

## Proposed approach

Introduce criticality tiers for freshness sources:

- **REQUIRED** — stale/unavailable → brief_health DEGRADED or ERROR. Examples: Guardian run, producer pipeline, news snapshot.
- **ADVISORY** — stale → note in brief and evidence footer, but does not degrade brief_health. Examples: macro scores (observe-only), learning sweep.
- **EXPERIMENTAL** — stale → silently ignored from health; may appear in context/evidence. Examples: any observe-only subsystem with production influence = 0.

The tier for each source should be defined in a central registry (e.g. a dict constant) rather than scattered across freshness computation. This registry is the authoritative answer to "does this source affect decisions?"

When a REQUIRED source is stale: degrade health as today.
When an ADVISORY source is stale: add a `context_warnings` entry, render in evidence footer, no health impact.
When an EXPERIMENTAL source is stale: no health impact, no warning unless it was previously CURRENT (transition note only).

The decision about which tier each source belongs to must be explicit and deliberate. At minimum, decide: does `macro_scores` staleness affect `brief_health`? Does `learning_sweep` staleness? This todo should settle those questions with a concrete registry.

## Touches

- `portfolio_ai.py` — freshness source criticality registry; `_compute_freshness()` and `_compute_brief_health()` updated to use tiers; `context_warnings` added to brief_state output
- `agents/briefing_agent.py` — `_format_capability_summary()` surfaces `context_warnings` in prompt
- `generate_dashboard.py` — evidence footer distinguishes REQUIRED staleness (red) from ADVISORY staleness (yellow/info)
- `tests/` — stale EXPERIMENTAL source → brief_health HEALTHY; stale REQUIRED source → DEGRADED; advisory stale → `context_warnings` non-empty, health unchanged

## Done when

- [ ] Each freshness source has an explicit criticality tier: REQUIRED, ADVISORY, or EXPERIMENTAL
- [ ] `macro_scores` and `learning_sweep` tier is explicitly decided and recorded in the registry
- [ ] Stale EXPERIMENTAL/ADVISORY source does not degrade `brief_health`
- [ ] Stale REQUIRED source degrades `brief_health` as before
- [ ] ADVISORY staleness populates `context_warnings` in brief_state
- [ ] Evidence footer distinguishes REQUIRED vs. ADVISORY staleness
- [ ] Tests cover each tier independently
