# Store Contract-Specific Evidence References on Recommendations

- **ID:** 0129
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

The orchestrator currently stores `option_snapshot_id` in the audit run manifest, but this is the ID of the most recently captured option snapshot at the time the run manifest was written — not necessarily the snapshot for the specific strike/expiry the CC agent selected. If a chain capture and a rec-writing happen in the same run but in slightly different order, the manifest ID may point to the wrong option. There is also no way to reconstruct which alternative contracts the agent considered (and why it rejected them) from the stored data alone.

## Proposed approach

After the CC agent selects a contract and writes the recommendation, enrich `action_payload_json` on the `recommendations` row with:

```json
{
  "selected_option_snapshot_id": <int>,
  "alternative_snapshot_ids": [<int>, ...],
  "earnings_event_id": <int | null>,
  "strategy_config_hash": "<12-char>",
  "financial_snapshot_hash": "<12-char | null>",
  "thesis_version": "<string>"
}
```

- `selected_option_snapshot_id`: the `id` of the `option_quote_snapshots` row for the chosen contract (strike + expiry + side).
- `alternative_snapshot_ids`: IDs for the other contracts the agent priced before selecting.
- `earnings_event_id`: FK to `earnings_events` if an upcoming event influenced the selection.
- `strategy_config_hash` and `financial_snapshot_hash`: already computed in 0120; move from manifest to per-rec payload.
- Write a helper in `agent_db.py` or `agents/cc_agent.py` to enrich the payload at rec-write time.
- The run manifest can retain a coarse reference for correlation, but the authoritative IDs live on the recommendation.

## Touches

- `agents/cc_agent.py` (or wherever CC recs are written) — enrich `action_payload_json` at write time
- `agents/orchestrator.py` — pass snapshot IDs through from CC agent to rec writer
- `agent_db.py` — helper to fetch selected/alternative snapshot IDs
- `tests/test_lifecycle.py` — assert evidence fields present in `action_payload_json` after a CC rec

## Done when

- [ ] `action_payload_json` on a CC recommendation includes `selected_option_snapshot_id`
- [ ] `alternative_snapshot_ids` list populated with at least the other considered contracts
- [ ] `earnings_event_id` set when an earnings event was in the decision window
- [ ] `strategy_config_hash` moved from run manifest into per-rec payload (manifest may keep a copy)
- [ ] Lifecycle test verifies these fields survive round-trip through `recommendations` table
