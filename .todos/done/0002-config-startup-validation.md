# Add Startup Config Validation with Fail-Fast Checks

- **ID:** 0002
- **Status:** backlog
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

## Done when

- [ ] `validate_config()` raises clearly on sum ≠ 100, missing fields, or invalid ranges
- [ ] `serve.py` fails to start if validation fails (error logged before bind)
- [ ] A deliberately broken config triggers the error and shows a readable message
- [ ] Valid config (all layers sum to 100) passes silently
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

