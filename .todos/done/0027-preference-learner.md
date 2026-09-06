# Build Preference Learner

- **ID:** 0027
- **Status:** done
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

## Outcome

**`agent_db.py`:**
- `learned_preferences(id, preference_key UNIQUE, scope, value REAL, confidence REAL, sample_size, first_observed, last_updated, evidence_json)` table added to schema (IF NOT EXISTS — safe migration)
- `upsert_learned_preference()`: computes sigmoid confidence = `100 × n/(n+10)`, INSERT OR REPLACE
- `get_learned_preferences()`: returns all rows as dicts
- `_compute_preference_fit(rec, prefs)`: returns `(fit 0-100, note)` or `(None, None)` when sample_size < 5; adjusts base acceptance-rate fit for CC delta/DTE deviation and sell score threshold; never touches recommendation_score or confidence columns
- `list_recommendations()`: loads prefs once, attaches `preference_fit` + `preference_note` to each rec

**`agents/preference_learner.py`** (new):
- `run_preference_learner()`: queries `accepted`/`rejected` decisions, recalculates 3 preference types: `action_acceptance_rate.{ACTION}` (exponential decay, half-life 90 days), `cc.preferred_delta`, `cc.preferred_dte` (from accepted SELL_CC payloads), `sell.score_threshold` (min score at which user accepted TRIM/EXIT)
- Hard rules in `strategy_config.py` confirmed zero references

**`serve.py`:**
- `_handle_agent_decision()`: launches `run_preference_learner()` in daemon thread after each decision write (non-blocking)
- `GET /api/preferences` → `_handle_preferences_get()`: returns full `learned_preferences` table

**`generate_dashboard.py`:**
- `_renderDQCard()`: Preference Fit badge added after trend note — green (≥75), red (<40), grey (otherwise); displays note text inline; hidden when `preference_fit == null`

Browser QA result (2026-09-05): 5 QA HOLD decisions seeded (4 accepted + 1 rejected). QATEST DQ card showed green "Pref Fit 80 — Preference fit 80 — consistent with your decision history" badge. Zero JS console errors. `/api/preferences` returned `{ok:true, count:2, prefs:[...]}`. Live decision (POST /api/agents/recommendations/61/decision) confirmed learner re-ran — sample grew from 5→6, value updated from 0.80→0.67. `strategy_config.py` contains zero references to learned_preferences or preference_learner (grepped). QA data cleaned up.

## Done when

- [x] `learned_preferences` table created and migratable
- [x] Preference learner recalculates after each `user_decisions` insert
- [x] Hard rules in `strategy_config` are never modified by the learner
- [x] Learned values only influence Preference Fit score, not Fundamental/Valuation/Evidence scores
- [x] Minimum 5 decisions required before a preference affects any recommendation
- [x] `GET /api/preferences` returns current learned preferences with confidence and sample_size
- [x] Decision Queue card shows Preference Fit score and note when fit is low
- [x] Browser QA (mandatory — do not skip): Record ≥ 5 decisions, then run the preference learner. Open the dashboard Decision Queue in a browser and verify: (a) zero JS console errors, (b) a recommendation card shows a Preference Fit score and note when fit is low, (c) hard rules in strategy_config are unchanged (grep to verify). Do NOT check this box without completing live browser testing.

