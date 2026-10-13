# Store Briefing Provenance and Connect User Responses to Episodes

- **ID:** 0623
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0621, 0622

## Problem

Each briefing currently has no memory of what it cited. If the user acts on a recommendation, dismisses a risk, or defers a decision, there is no path connecting that response back to the specific findings, news events, or thesis signals that generated the item. Over time this means: (a) the briefing cannot learn that certain signal types are consistently dismissed, (b) dismissed items reappear identically the next day, and (c) there is no audit trail connecting a user action to the intelligence that prompted it.

## Proposed approach

- **Briefing provenance record:** When a brief is generated, store a `portfolio_brief_provenance` row that records: `brief_id` (UUID), `captured_at`, `brief_snapshot_json` (the full Portfolio Brief State), `briefing_output_json` (the Briefing Agent result), and a `source_refs` array — each ref carries `source_type` (news_event / recommendation / guardian_finding / thesis_pillar / macro_score), `source_id`, and `item_key` (which attention/opportunity/watch item it contributed to).
- **User response capture:** Add lightweight response actions to Needs Attention and Opportunities items in the UI: ACT / DISMISS / DEFER with an optional note. Store responses in `portfolio_brief_responses` (brief_id, item_key, action, note, responded_at).
- **Connect to decision episodes:** When a user acts on a recommendation item, create or link a `decision_episode` row (already exists in schema) referencing the brief_id and item_key. This ties the briefing → decision → outcome chain together for future calibration.
- **Presentation-layer learning (conservative):** Use response history only to affect presentation order and labeling — not to suppress or modify underlying evidence. Examples: an item dismissed 3+ times without acting gets a lower ranking and a "previously dismissed" label; an item type the user consistently acts on gets a higher ranking. Evidence itself is never filtered.
- **Scope limit:** Do not attempt outcome prediction or signal weighting in this todo. That belongs in the learning lab once enough episodes exist. This todo only connects the briefing to the response record and the decision episode.

## Touches

- `portfolio_ai.py` — new `portfolio_brief_provenance` and `portfolio_brief_responses` tables in `_init_ai_tables()`; provenance write in briefing pipeline; response write endpoint
- `serve.py` — POST endpoint for user response (ACT / DISMISS / DEFER)
- `generate_dashboard.py` — ACT / DISMISS / DEFER buttons on Needs Attention and Opportunities items; "previously dismissed" label
- `agents/learning/episode_capture.py` — link briefing response to decision episode
- `tests/` — provenance write test; response record test

## Done when

- [ ] Each briefing stores a `portfolio_brief_provenance` row with full `brief_snapshot_json`, `briefing_output_json`, and `source_refs`
- [ ] `source_refs` correctly identifies which news events, findings, and recommendations contributed to each item
- [ ] Dashboard renders ACT / DISMISS / DEFER on each Needs Attention and Opportunities item
- [ ] User responses are persisted in `portfolio_brief_responses`
- [ ] An ACT response creates or links a `decision_episode` referencing the brief and item
- [ ] Items dismissed 3+ times without acting render with a "previously dismissed" label and lower ranking
- [ ] Underlying evidence is never suppressed — only presentation order and labels are affected by response history
