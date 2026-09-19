# Live Acceptance Rerun Under Amended Contract

- **ID:** 0505
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0503, 0504

## Problem

The first live run (contract v1) produced BLOCK due to the UUP anchor and fund instability. The contract amendment (0503) fixes the anchor; fund exclusion (0504) removes the instability source. This todo is the actual rerun under the corrected contract — a separate, independent run that produces a new immutable acceptance record.

## Proposed approach

Prerequisites before running:
- 0503 committed (v1.1 config, NEE/multinational anchors, original run preserved)
- 0504 committed (funds excluded from repeatability scorer)

Run on optiplex:
```bash
cd ~/investment && LLM_URL=http://100.73.128.40:8080 \
  venv/bin/python scripts/validate_macro_scorer.py \
  --live --n-repeats 20 \
  --out out/macro_validation_acceptance_$(date +%Y%m%d_%H%M%S).json
```

Expected outcome after fixes:
- 0 anchor FAILs (funds excluded; company anchors use independently evidenced tickers)
- UNSTABLE WARNs reduced (funds gone; may still see instability on limited-evidence foreign companies — this is expected and acceptable at engine level, controlled by 0506/0509 at feature level)
- PASS verdict → write `macro_acceptance_state` row and activate ACCEPTED tagging

If result is still BLOCK, document which specific check failed before investigating further.

On PASS:
```python
# Write to macro_acceptance_state table
conn.execute("""
    INSERT OR REPLACE INTO macro_acceptance_state
    (contract, accepted_at, record_id, commit_sha, model_identity, notes)
    VALUES (?,?,?,?,?,?)
""", ("macro_validation_v1", datetime.utcnow().isoformat(),
      acceptance_record_filename, commit_sha, model_identity,
      "Amended from v1: UUP anchor replaced; funds excluded from repeatability"))
```

## Touches

- `scripts/validate_macro_scorer.py` (run only, no code changes)
- `out/macro_validation_acceptance_TIMESTAMP.json` — new immutable record
- `macro_acceptance_state` table — populated on PASS

## Done when

- [ ] 0503 and 0504 both committed before this run starts
- [ ] Full N=20 live run completes on real MLX model with frozen macro context
- [ ] New immutable acceptance record written (does not overwrite prior BLOCK record)
- [ ] PASS: `macro_acceptance_state` populated; future episodes tagged ACCEPTED
- [ ] BLOCK: specific failure documented; new investigation todo created
