# Ledger Accounting Hard Failure + Separate Supported vs Unsupported Counts

- **ID:** 0515
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0504

## Problem

Two issues. First, the `expected_n == scored_n + failed_n` invariant check currently only prints a warning on mismatch — it was supposed to raise and persist FAILED. Second, funds now increment `scored_n` even though they bypass the LLM, so a run can report 100% "scored" when a significant portion are unsupported fund records. The health dashboard gives a better coverage concept, but the ledger should match it.

## Proposed approach

**Hard failure on accounting mismatch**: restore the invariant as an actual failure:
```python
if scored_n + failed_n != len(to_score):
    msg = f"[MacroScores] FATAL accounting mismatch — expected {len(to_score)}, scored={scored_n}, failed={failed_n}, sum={scored_n+failed_n}"
    print(msg)
    # Persist FAILED status and raise
    try:
        conn_f = sqlite3.connect(str(DB_PATH), timeout=10)
        conn_f.execute(
            "UPDATE macro_scoring_runs SET status='FAILED', errors_json=? WHERE run_id=?",
            (json.dumps([msg]), run_id)
        )
        conn_f.commit()
        conn_f.close()
    except Exception:
        pass
    raise RuntimeError(msg)
```

**Separate ledger counters**: add columns to `macro_scoring_runs`:
- `supported_scored_n INTEGER` — tickers that went through LLM scoring
- `unsupported_n INTEGER` — fund/unsupported tickers that were skipped

Update the INSERT and final UPDATE to populate these:
```python
# In fund-bypass branch:
unsupported_n += 1
# In LLM-scored branch:
supported_scored_n += 1
```

Change `scored_n` semantics to mean "processed" (LLM + unsupported), and add `supported_scored_n` for the LLM-only count. `COMPLETE` still means `processed == expected`, but the health dashboard and coverage reports should use `supported_scored_n` for meaningful coverage %.

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()`, accounting invariant, fund counter
- `_init_ai_tables()` — ALTER TABLE to add `supported_scored_n`, `unsupported_n`

## Done when

- [ ] Accounting mismatch raises and persists `status='FAILED'` (not just a warning)
- [ ] `supported_scored_n` and `unsupported_n` columns added to `macro_scoring_runs`
- [ ] Funds increment `unsupported_n` instead of (or in addition to) `scored_n`
- [ ] Health dashboard coverage % uses `supported_scored_n`, not total `scored_n`
