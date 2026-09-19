# Deterministic Validation Universe in Precommitted Config

- **ID:** 0514
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0510

## Problem

The live repeatability test selects tickers using `list({...holdings...})[:8]`. Python sets are unordered, so the 8 tickers chosen for a future validation run are not deterministic — the repeatability universe can differ between runs without any deliberate amendment. Per-ticker×dimension stability conclusions are only comparable across runs when the same population is tested each time.

## Proposed approach

Add `repeatability_universe` to `validation_config.json`:
```json
{
  "version": "v1.1",
  "repeatability_universe": ["XOM", "NFLX", "GRMN", "DSGX", "BRK-B", "UNP", "JOBY", "SNA"],
  ...
}
```

Rules:
- Only company tickers (no funds per SECURITY_MASTER)
- At least 6 tickers; 8 recommended
- Universe changes require a config version bump and amendment note

In `scripts/validate_macro_scorer.py`, replace the dynamic set-based selection with:
```python
universe = config.get("repeatability_universe")
if not universe:
    raise ValueError("repeatability_universe missing from validation_config.json — cannot run deterministic validation")
# Exclude any funds that may have been added to config by mistake
from portfolio_ai import is_fund
tickers = [t for t in universe if not is_fund(t)]
if len(tickers) < 6:
    raise ValueError(f"repeatability_universe has only {len(tickers)} non-fund tickers — need ≥6")
```

The tickers should represent the range of evidence quality and sector types in the portfolio, not just the largest positions.

## Touches

- `validation_config.json` — add `repeatability_universe` list
- `scripts/validate_macro_scorer.py` — read universe from config; raise if missing

## Done when

- [ ] `repeatability_universe` in `validation_config.json` with ≥6 company tickers
- [ ] Validation script reads universe from config; raises if missing or < 6 tickers
- [ ] Funds in universe list are excluded with a warning (not a hard failure)
- [ ] Config version bump required to change the universe
