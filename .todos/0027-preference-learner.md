# Build Preference Learner

- **ID:** 0027
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** low
- **Depends:** 0018, 0024, 0026

## Problem

The system accumulates decision history but does not learn from it. Without preference learning, the same recommendations keep being surfaced in the same way regardless of demonstrated user behavior patterns. But two failure modes must be avoided: (1) learning nothing and repeating the same presentation forever, and (2) learning to agree with the user — optimizing for acceptance rather than investment quality. Preference learning must affect presentation priority, not evidence scores.

## Proposed approach

**Hard boundary (never learned, only user-set via `strategy_config`):**
- Layer allocation limits
- Maximum single position size
- Minimum option return threshold
- Minimum liquidity requirements
- Prohibited investment types
- Tax policy (ST vs LT preference)
- Risk limits

These are policy. The system observes that the user consistently accepts something that would exceed a hard rule — it still does not change the rule. It may surface an observation in the Investor Model (0028) that the user wants to revisit the rule.

**Soft preferences (learned automatically):**
- `covered_calls.max_preferred_delta` — learned from accepted/rejected CC deltas
- `covered_calls.preferred_dte_range` — from accepted CC expirations
- `growth.high_conviction_upside_preference` — willingness to forgo CC income on high-conviction compounders
- `opportunity.preference_for_existing_positions` — tendency to add to existing vs. initiate new
- `sell.valuation_tolerance` — reluctance to exit on valuation alone
- `sell.drawdown_hold_preference` — tendency to hold through drawdowns vs trim
- `thesis.conviction_threshold_for_action` — minimum conviction to act on a recommendation

**New table: `learned_preferences`**

| Field | Purpose |
|---|---|
| id | PK |
| preference_key | e.g., `covered_calls.max_preferred_delta` |
| scope | Portfolio-wide or per ticker |
| value | Learned value (float, string, or JSON) |
| confidence | 0–100 (grows with sample size) |
| sample_size | Number of decisions this is based on |
| first_observed | Date first inferred |
| last_updated | Date last recalculated |
| evidence_json | Summary of which decisions produced this inference |

**Learning mechanism:**
- After each user decision (Accept/Reject/Defer + reason_code), the preference learner recalculates relevant soft preferences
- Uses a simple weighted inference: recent decisions weighted higher than older ones (exponential decay, half-life ~90 days)
- Confidence grows with sample_size using a sigmoid curve: `confidence = 100 × sample_size / (sample_size + 10)`
- Minimum sample_size for any preference to influence recommendations: 5 decisions

**How preferences influence the system (presentation only):**
- Preference Fit score (0–100) added to each recommendation card in the Decision Queue
- Preference Fit does NOT modify Fundamental, Valuation, Portfolio Fit, or Evidence Confidence scores
- High preference fit → recommendation shown with positive framing ("consistent with your historical behavior")
- Low preference fit → recommendation shown with explicit note ("this conflicts with your historical tendency to avoid X — consider whether circumstances are different")
- Priority formula (from 0016) can include Preference Fit as a tie-breaker but not a primary input

## Touches

`learned_preferences` table (new), `agent_db.py` (preference read/write), `agents/orchestrator.py` (run learner after each decision recorded), `serve.py` (`GET /api/preferences` endpoint for Investor Model UI), `generate_dashboard.py` (Preference Fit score on Decision Queue cards)

## Done when

- [ ] `learned_preferences` table created and migratable
- [ ] Preference learner recalculates after each `user_decisions` insert
- [ ] Hard rules in `strategy_config` are never modified by the learner
- [ ] Learned values only influence Preference Fit score, not Fundamental/Valuation/Evidence scores
- [ ] Minimum 5 decisions required before a preference affects any recommendation
- [ ] `GET /api/preferences` returns current learned preferences with confidence and sample_size
- [ ] Decision Queue card shows Preference Fit score and note when fit is low
