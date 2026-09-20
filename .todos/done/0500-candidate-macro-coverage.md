# Measure Candidate Macro Coverage Across Opportunity Hunter Episodes

- **ID:** 0500
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0494, 0497

## Problem

The weekly Macro Risk scorer was built for current holdings. Opportunity Hunter evaluates securities that may not be current holdings and therefore may have no structural macro score. Before treating macro context as a meaningful Learning Lab signal, we need to know what fraction of Decision Episodes actually have valid macro data — and why the rest don't. Candidates with missing scores silently get `macro_supported = false`, but the reason matters for deciding what to fix.

## Proposed approach

Add a coverage breakdown to `compute_macro_health()` and the health card:

Five distinct coverage states (never collapsed into a single boolean):
1. `company_supported` — ticker is a company with structural scores scored within last 14 days
2. `fund_unsupported` — ticker is in SECURITY_MASTER as etf/mutual_fund
3. `no_score_available` — company ticker but no row in `holding_macro_scores`
4. `stale_score` — has a score but `scored_at` > 14 days old
5. `macro_context_unavailable` — macro context fetch itself failed

For each Decision Episode in the last 30 days, classify into one of the five states. Report:
- Count and % of episodes per state
- % of episode-weighted coverage (if position values available, weight by value)

Do NOT expand scoring scope to cover the full Opportunity Hunter candidate universe yet. First measure the gap, then decide whether to close it. This todo is measurement only.

## Touches

- `portfolio_ai.py` — `compute_macro_health()`, `_build_macro_snapshot()` (add reason field)
- `generate_dashboard.py` — health card coverage breakdown
- `scripts/macro_attribution.py` — add coverage summary section

## Done when

- [ ] Five coverage states enumerated (not collapsed to boolean)
- [ ] `macro_snapshot` reason field populated for non-supported cases
- [ ] Health card shows count + % per coverage state for last 30 days of episodes
- [ ] Attribution script reports coverage breakdown before analysis section
- [ ] No change to scoring scope — measurement only
