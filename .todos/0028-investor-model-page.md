# Build Investor Model Page

- **ID:** 0028
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** low
- **Depends:** 0027

## Problem

The Preference Learner (0027) builds a model of investor behavior, but that model is invisible — it silently influences recommendation presentation without the user being able to see, validate, or correct it. An opaque preference model is dangerous: it could drift toward wrong conclusions or reinforce bad habits without the user realizing it. The Investor Model page makes the learned preferences explicit, legible, and correctable.

## Proposed approach

A dedicated dashboard section or tab: **"Investor Model"**

**Layout — tiered by confidence:**

```
LEARNED INVESTMENT PREFERENCES

HIGH CONFIDENCE (≥ 80%)

  You strongly favor holding high-conviction compounders
  rather than monetizing upside through covered calls.
  Evidence: 18 decisions · Confidence: 91%

  [Correct]  [Incorrect]  [Don't use this]


MODERATE CONFIDENCE (50–79%)

  You prefer adding to existing positions over initiating
  new positions when portfolio fit scores are similar.
  Evidence: 11 decisions · Confidence: 73%

  [Correct]  [Incorrect]  [Don't use this]


EARLY OBSERVATION (< 50%)

  You appear reluctant to sell positions for valuation alone.
  Evidence: 5 decisions · Confidence: 48%

  [Correct]  [Incorrect]  [Don't use this]
```

**Three feedback actions per preference:**
- **[Correct]** — confirms the inference; increases weight in future learning, logs a `preference_feedback` event with `outcome=confirmed`
- **[Incorrect]** — rejects the inference; resets this preference's influence to neutral, logs `outcome=rejected`
- **[Don't use this]** — suppresses this preference from influencing recommendations permanently (user may have a reason the system can't detect), sets a `suppressed` flag on the `learned_preferences` row

**Hard rules section (read-only, beneath learned preferences):**
Shows all hard strategy rules from `strategy_config` with current values. No edit capability here — these require intentional config file changes. Label: "These rules are fixed and require manual configuration to change."

**New table: `preference_feedback`**
| Field | Purpose |
|---|---|
| preference_id | FK to learned_preferences |
| outcome | `confirmed` / `rejected` |
| suppressed | Boolean |
| feedback_at | Timestamp |

**API:**
- `GET /api/preferences` — all preferences with confidence/sample_size (from 0027)
- `POST /api/preferences/{id}/feedback` — body: `{outcome}` or `{suppressed: true}`

## Touches

`preference_feedback` table (new), `learned_preferences` table (add `suppressed` column), `agent_db.py`, `serve.py` (feedback endpoint), `generate_dashboard.py` (Investor Model section)

## Done when

- [ ] Investor Model section renders with preferences tiered by confidence
- [ ] Each preference shows evidence count and confidence level
- [ ] [Correct] / [Incorrect] / [Don't use this] buttons work and write to `preference_feedback`
- [ ] Suppressed preferences no longer influence any recommendation presentation
- [ ] Hard rules section renders current `strategy_config` values as read-only
- [ ] Page handles empty state gracefully: "Not enough decisions yet to infer preferences. Keep using the Decision Queue."
- [ ] Browser QA (mandatory — do not skip): Open the Investor Model page in a browser and verify: (a) zero JS console errors, (b) preferences render tiered by confidence with evidence counts, (c) [Correct] / [Incorrect] / [Don't use this] buttons call the API and update state without page reload, (d) suppressing a preference removes it from subsequent recommendation scoring (verify via a new rec), (e) empty state shows the correct 'Not enough decisions yet' message. Do NOT check this box without completing live browser testing.

