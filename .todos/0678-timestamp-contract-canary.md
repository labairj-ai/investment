# Timestamp Contract Canary

- **ID:** 0678
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0669, 0670

## Problem

Once the timestamp contract is established (0668–0670), future development could silently reintroduce ambiguous or local-time timestamps without any automated detection. A runtime canary that sweeps persisted records for timestamp-contract violations provides a continuous safety net.

## Proposed approach

Extend (or create a separate) production canary that checks all timestamped tables. For each new/current-version record verify:
- Timestamp is parseable
- UTC persistence (no unexpected local-time format)
- Timezone awareness where serialization supports it
- Valid chronological ordering (no impossible future timestamps outside clock-skew tolerance)
- Required timestamp fields are present

Classification: new malformed timestamp → violation; unexpected local-time format on new record → violation; recognized legacy format → warning or compatibility classification; canary never rewrites data. Output identifies table, row, field, and malformed value.

## Touches

- `scripts/canary_production_state.py` — add timestamp-contract sweep, or new `scripts/canary_timestamps.py`
- `tests/` — canary catches malformed new timestamp; legacy format → warning

## Done when

- [x] New malformed timestamp → violation
- [x] Current record using unexpected local-time format → violation
- [x] Existing recognized legacy timestamp → warning or compatibility classification
- [x] Canary does not rewrite data
- [x] Canary output identifies table, row, field, and malformed value
## Outcome

Implemented as part of 0668-0680 batch commit.
