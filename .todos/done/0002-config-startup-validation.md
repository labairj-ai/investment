# Add Startup Config Validation with Fail-Fast Checks

- **ID:** 0002
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** 0001

## Problem

The system silently accepted layer targets that summed to 105% for an extended period. No code checked this invariant. Once agents start making rebalancing recommendations from misconfigured targets, the errors will be harder to trace and potentially acted upon. Validation must happen at startup, before any agent or scheduler runs.

## Proposed approach

- Add a `validate_config()` function in `strategy_config.py` called at import time (or explicitly at `serve.py` startup and in `generate_dashboard.py`).
- Checks to include: layer targets sum to 100 ± 0.01; all required fields present; CC min_dte < max_dte; min_profit_pct is a reasonable float (0 < x < 1); layer drift warning > 0.
- Raise `ConfigurationError` (custom exception) with a clear message on failure — don't silently default.
- Add a CLI flag or env var `SKIP_CONFIG_VALIDATION=1` as an escape hatch for dev/test environments where partial config is intentional.

## Touches

`strategy_config.py`, `serve.py`, `generate_dashboard.py`

## Outcome

Added `ConfigurationError(RuntimeError)` and `validate_config()` to `strategy_config.py`. Validation runs automatically at import time unless `SKIP_CONFIG_VALIDATION=1` is set. Checks enforced:
- Layer targets sum to 100 ± 0.01%
- All 5 layers present with positive targets
- `CC_MIN_DTE < CC_MAX_DTE < CC_MAX_DTE_EXTENDED`
- `CC_R_MIN` in (0, 1)
- `DRIFT_THRESHOLD`, `LAYER_GROSS_DOM`, `HOLDING_GROSS_DOM` all positive

All errors accumulate and are reported together in one message with bullet points.

Added `import strategy_config` to `serve.py` at line 36 (before `ThreadingHTTPServer` at line 4926), so a bad config kills the server process before it binds. `generate_dashboard.py` already imported from `strategy_config` at the top level, so it gets validation for free.

QA: valid config passes silently; sum=105% raises with exact values; inverted DTE + bad r_min raises with 3 bullets; `SKIP_CONFIG_VALIDATION=1` bypasses all checks.

## Done when

- [x] `validate_config()` raises clearly on sum ≠ 100, missing fields, or invalid ranges
- [x] `serve.py` fails to start if validation fails (error logged before bind)
- [x] A deliberately broken config triggers the error and shows a readable message
- [x] Valid config (all layers sum to 100) passes silently
- [x] QA evaluation conducted: functionality verified working, no regressions introduced

