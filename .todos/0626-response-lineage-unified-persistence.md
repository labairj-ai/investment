# Complete Response Lineage and Unify Brief Persistence

- **ID:** 0626
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0623, 0625

## Problem

There are two separate persistence paths: the pipeline agent writes a `portfolio_brief_provenance` row, but `generate_daily_insight()` (called on manual refresh) writes only `ai_insights` without a provenance row. `/api/ai/daily` retrieves the cached `ai_insight` and separately fetches the latest `portfolio_brief_provenance` to get `brief_id`. After a manual refresh these can represent different briefing generations — meaning the user sees Brief B but clicks DISMISS with Brief A's `brief_id`.

Additionally, the ACT button currently only writes to `portfolio_brief_responses` ("record that the user clicked ACT") rather than actually routing the decision. Until episode linkage exists, this is misleading. An ACT on `rec:123` should find recommendation 123 and create/link a Decision Episode — not just log a click.

## Proposed approach

- **Single `create_portfolio_brief()` function:** One path for both pipeline and on-demand refresh: build state → run synthesis → generate `brief_id` → persist `ai_insight` → persist `portfolio_brief_provenance` → return `{brief, brief_id}`. Both `run_briefing_agent()` in the pipeline and `/api/ai/daily?force=1` call this same function.
- **`brief_id` integrity on POST:** `/api/brief/respond` validates that the `brief_id` + `item_key` exist in `portfolio_brief_provenance` before writing a response. Reject stale or mismatched IDs.
- **ACT routing:** ACT on `rec:<id>` finds the recommendation and calls the existing decision episode creation path (create or link episode). ACT on other item types (guardian finding, news signal) creates an episode in "review" state with the item as context. The user is not automatically committed to a trade — ACT means "I accept this into the decision workflow."
- **Rename until complete:** Until the ACT → episode path is implemented, rename the button label to `REVIEW` in the UI so it accurately reflects "route to decision workflow" rather than implying execution.
- **DISMISS/DEFER:** Attach to the exact `item_key` in `portfolio_brief_responses`. Previously-dismissed items (3+ times without ACT) get a "previously dismissed" label and lower ranking in `build_portfolio_brief_state()`.

## Touches

- `portfolio_ai.py` — new `create_portfolio_brief()` function; retire dual persistence paths; brief_id validation helper
- `serve.py` — `generate_daily_insight()` shim calls `create_portfolio_brief()`; `_handle_brief_respond()` validates brief_id + item_key; ACT routing logic
- `agents/learning/episode_capture.py` — link brief response to decision episode
- `generate_dashboard.py` — rename ACT → REVIEW until routing complete; previously-dismissed label
- `tests/` — unified persistence test; stale brief_id rejection test; ACT → episode creation test

## Done when

- [ ] `create_portfolio_brief()` is the single function called by both pipeline and manual refresh
- [ ] Every displayed brief has a matching `portfolio_brief_provenance` row with the same `brief_id`
- [ ] `/api/brief/respond` validates `brief_id` + `item_key` exist before writing
- [ ] ACT on `rec:<id>` creates or links a Decision Episode referencing the brief and item
- [ ] ACT button is labeled `REVIEW` until episode routing is fully wired
- [ ] Items dismissed 3+ times without ACT render with "previously dismissed" label and lower ranking
- [ ] No scenario where the displayed brief and the stored `brief_id` represent different generations
