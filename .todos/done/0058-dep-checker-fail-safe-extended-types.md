# Dependency Checker: Fail-Safe for Unknown Types + Extended Type Coverage

- **ID:** 0058
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P0
- **Depends:** none

## Problem

`dependency_checker.py` now handles PRICE, THESIS_VERSION, POSITION_WEIGHT, MACRO_STATE, and FINANCIAL_PERIOD — but the `else` branch still does `reason = None`, silently treating any unknown dependency type as perpetually valid. This means:

1. A new agent can emit a dependency type (e.g. `OPTION_IV`, `EARNINGS_DATE`) and it will never expire, leaving stale recommendations permanently open.
2. Adding a new type requires editing the checker — but there is no guardrail that forces that edit. The failure is invisible.

Additionally, five types used (or soon to be used) by agents have no checker at all: `OPTION_QUOTE`, `OPTION_IV`, `OPTION_LIQUIDITY`, `EVENT_CALENDAR`, `EARNINGS_DATE`, `ESTIMATE_REVISION`.

## Proposed approach

### 1. Fail-safe for unknown types

Replace the silent `else: reason = None` with:

```python
else:
    print(f"[DepChecker] WARNING: unknown dependency type {dtype!r} on rec {rec_id} — marking DEPENDENCY_CHECK_FAILED")
    violated_reasons.append(f"Unknown dependency type {dtype!r}: cannot validate, treating as stale")
```

This is a conservative fail-safe: if we can't check a dependency, we supersede and re-evaluate rather than leaving a potentially stale recommendation open forever.

### 2. OPTION_IV and OPTION_QUOTE

Data source: `cc_positions` table already stores premium data. For IV, if no live IV feed exists in the DB, add a `_check_option_iv` stub that checks if the option expired (expiration date passed) and treats that as a violation.

```python
def _check_option_iv(dep, prices): ...  # expiry passed → violated
def _check_option_quote(dep, prices): ... # premium stale by >X days → violated
```

### 3. EARNINGS_DATE

Data source: `company_financials` has `period_end`. Earnings typically follow 30–60 days after period end. Flag as violated if current date is within 14 days of estimated earnings (period_end + 45 days) or if a new period_end has appeared since the dependency was recorded.

```python
def _check_earnings_date(dep, periods): ...
```

### 4. EVENT_CALENDAR, OPTION_LIQUIDITY, ESTIMATE_REVISION

These require data sources that don't yet exist in the DB. Implement as stub handlers that:
- Log a warning that the check is skipped due to missing data source
- Return `None` (leave open) rather than silently passing or falsely superseding

Document in each stub exactly what DB table/field would be needed to make it real.

## Touches

- `agents/dependency_checker.py` — fail-safe else branch, new checker functions, dispatch table
- `agents/covered_call_agent.py` — write EARNINGS_DATE dependency (period_end + 45d estimate)
- `agent_db.py` — no schema changes expected; stubs can use existing tables

## Done when

- [ ] Unknown dependency type supersedes the recommendation with a clear reason string instead of silently passing
- [ ] OPTION_IV checker implemented (at minimum: expiry-date-passed logic)
- [ ] EARNINGS_DATE checker implemented using period_end estimation
- [ ] EVENT_CALENDAR / OPTION_LIQUIDITY / ESTIMATE_REVISION have documented stubs that log and return None
- [ ] Test: write a recommendation with dependency type `BANANA` → verify it gets superseded
- [ ] **Backend QA:** run on optiplex; confirm expected supersessions appear
- [ ] **No service regression:** investment service running; all API routes respond
