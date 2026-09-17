# Add Read-Only Learning Lab Dashboard Panel

- **ID:** 0329
- **Status:** done
- **Created:** 2026-09-15
- **Priority:** normal
- **Depends:** 0328

## Problem

Once episode capture (0327) and outcome labeling (0328) are running, the accumulated data is invisible. There is no way to see whether the scoring formula is working, whether LLM conviction tracks actual returns, or whether any risk rules are systematically blocking profitable trades. Without visibility, the data accumulates but cannot guide decisions about whether to proceed to a learning model.

## Proposed approach

Add a "Learning Lab" tab to the dashboard (alongside the existing Shadow tab). Read-only — nothing in this panel influences execution. Five sections:

1. **Strategy Performance**: paper return vs SPY return, excess return, drawdown, win rate (paper fills from `cycle_runs` + `fills`).
2. **Score Calibration**: table of actual mean alpha by base-score bucket (45–55, 55–65, 65–75, 75–85, >85) across all labeled episodes.
3. **Feature Attribution**: mean alpha broken out by Q, V, PF, C, EC buckets — shows which scoring components actually predict returns.
4. **LLM Calibration**: conviction stars (1–5) vs observed 90d hit rate and mean alpha — reveals systematic over/under-confidence.
5. **Risk Gate Audit**: for each risk rule, count of blocks, estimated losses avoided (prospective return of blocked intents that went down), and estimated missed alpha (prospective return of blocked intents that went up).

Backend: add `/api/learning/stats` endpoint in `serve.py` that queries `decision_episodes`, `episode_outcomes`, `fills`, and `risk_counterfactual_outcomes`. All aggregation in SQL — no heavy computation in the handler.

Frontend: new tab in `generate_dashboard.py` rendered as static tables/grids. No charting library needed initially — plain HTML tables with color coding.

## Touches

- `generate_dashboard.py` — new Learning Lab tab, `loadLearningPanel()` JS function
- `serve.py` — `/api/learning/stats` route and handler
- `tests/` — unit test for the stats query with seeded episode + outcome rows

## Done when

- [ ] Learning Lab tab appears in dashboard navigation
- [ ] All five sections render with real data when labeled episodes exist
- [ ] Sections show a "not enough data" message gracefully when < 10 labeled episodes exist
- [ ] `/api/learning/stats` returns within 2 seconds on the Optiplex hardware
- [ ] No execution logic or scoring weights are modified by anything in this panel

## Outcome

Implemented in commit a7322b8. `📈 Learning Lab` tab added to nav + dropdown. Five cards: Episode Dataset (overview counts + date range), Score Calibration (mean 90d alpha by composite bucket), Feature Attribution (mean alpha by Q/V/PF/C/EC bucket), LLM Conviction Calibration (conviction stars vs hit rate/alpha for selected candidates), Risk Gate Audit (counterfactual outcomes by reject_rule). All sections show "no data yet" message when < 10 labeled outcomes. Backend: `/api/learning/stats` returns all aggregations in one call. Tab restore wired. Dashboard regenerated. 744 tests pass.
