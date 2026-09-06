# Build 3-Level Notification System with Engagement Tracking

- **ID:** 0023
- **Status:** in-progress
- **Created:** 2026-09-05
- **Priority:** low
- **Depends:** 0016, 0027

## Problem

The system has no mechanism to distinguish what genuinely requires immediate attention from what belongs in the queue from what should simply be recorded. Without tiers, either everything notifies (alert fatigue) or nothing does (missed urgency). Equally important: the system has no way to learn which notifications the user actually cares about vs. ignores — without tracking engagement, notification thresholds can never self-improve.

## Proposed approach

**Three levels:**

| Level | Treatment |
|---|---|
| URGENT | Push notification (Mac notification center or email) |
| ATTENTION | Top of Decision Queue, visually highlighted |
| INFORMATIONAL | Dashboard / Decision Journal only, no interruption |

**Urgency formula (deterministic, all components 0–1):**
`Urgency = TimeSensitivity × FinancialMateriality × DecisionSeverity`

- **TimeSensitivity**: days until decision window closes; 1.0 = action required today, 0.0 = no deadline
- **FinancialMateriality**: recommendation impact as fraction of portfolio value
- **DecisionSeverity**: 1.0 for EXIT/TRIM, 0.7 for CC assignment window, 0.5 for REVIEW, 0.2 for HOLD/RESEARCH

**URGENT threshold** should start high and be adjusted via preference learning (0027). Initial qualifying conditions (all must be true):
- Major position (> configured threshold % of portfolio) with confirmed thesis violation
- OR: CC at or past management DTE window (e.g., 7 DTE) with no recorded action
- OR: Material corporate event (acquisition announcement, dividend suspension, bankruptcy filing)
- OR: High-confidence actionable recommendation with expiry within 24 hours

"Stock down 4%" alone: INFORMATIONAL only, never URGENT.

**Engagement tracking (new table: `notification_events`):**
| Field | Purpose |
|---|---|
| recommendation_id | FK |
| level | URGENT / ATTENTION / INFORMATIONAL |
| sent_at | When notification was issued |
| outcome | `opened` / `ignored` / `dismissed` / `acted_on` |
| time_to_action | Seconds from sent to decision (null if ignored) |

This data feeds the Preference Learner (0027) to improve future thresholds.

**URGENT delivery mechanism:** initially, email via existing Gmail SMTP in the investment project. Long-term: Mac notification center via `osascript` on the optiplex if user is on local network, or email fallback.

## Touches

`notification_events` table (new), `agents/orchestrator.py` (assign urgency level after Critic pass), `serve.py` (notification dispatch), `generate_dashboard.py` (ATTENTION items visually differentiated in Decision Queue), `strategy_config.py` (urgency thresholds)

## Done when

- [ ] Every recommendation assigned URGENT / ATTENTION / INFORMATIONAL before writing to DB
- [ ] ATTENTION items rendered at top of Decision Queue with visual distinction
- [ ] URGENT sends email via existing Gmail SMTP
- [ ] `notification_events` table records outcome and time_to_action when user acts
- [ ] "Stock down 4%" alone does not produce URGENT or ATTENTION level
- [ ] Urgency thresholds readable from `strategy_config` (configurable without code change)
- [ ] Browser QA (mandatory — do not skip): Trigger a recommendation at each urgency level. Open the dashboard in a browser and verify: (a) zero JS console errors, (b) ATTENTION items appear at the top of the Decision Queue with visual distinction, (c) URGENT triggers a Gmail send (check inbox). Confirm a 4% price drop alone does NOT produce URGENT or ATTENTION. Do NOT check this box without completing live browser testing.

