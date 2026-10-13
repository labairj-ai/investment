# Build Prospective Covered Call Challenger Virtual Book

- **ID:** 0704
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0700, 0701, 0702

## Problem

V3 is currently observe-only, which is correct, but the challenger cannot accumulate complete prospective economic outcomes for SELL_CC decisions because only the V2 champion is actually executed.

This creates a promotion dead end:

- V2 has actual fills, actual roll chains, actual management actions, and reconciled economics.
- V3 has only decision-time features and market-path labels.
- `promotion_evidence()` requires complete challenger outcomes such as `cc_incremental_alpha`, realized management cost, realized execution cost, and assignment-policy state.
- A hypothetical V3 SELL_CC therefore remains chain-censored and cannot participate in a true paired promotion comparison.

The system needs a prospective, deterministic virtual execution and management path for challenger decisions.

## Proposed approach

Create a **virtual challenger covered-call book** that runs prospectively from decision time forward using only information available at each simulated timestamp.

For every V3 challenger SELL_CC decision:

1. Create a virtual position at the original decision timestamp.
2. Generate a modeled entry fill from the precommitted execution model.
3. Persist the virtual position separately from actual brokerage/execution records.
4. On each scheduled CC management cycle:
   - load only data available as of that cycle;
   - run the same deterministic CC management policy used for live positions;
   - persist the virtual management decision;
   - if policy calls for BTC / ROLL_UP / ROLL_OUT / ROLL_UP_AND_OUT / ALLOW_ASSIGNMENT, create the corresponding virtual transition.
5. Continue until terminal close, expiry, or assignment.
6. Compute virtual chain economics using the same units and attribution definitions as the actual CC outcome evaluator.

Add virtual-book tables or equivalent append-only structures such as:

- `cc_virtual_positions`
- `cc_virtual_actions`
- `cc_virtual_fills`
- `cc_virtual_chains`

Required position state:

- episode_id
- candidate_id
- ticker
- strike
- expiration
- contracts
- entry timestamp
- modeled entry fill
- current virtual state
- trade_chain_id / virtual_chain_id
- scorer/model/config version
- origin decision git SHA

Required action state:

- evaluation timestamp
- market snapshot reference
- policy snapshot
- action
- reason
- modeled fill inputs
- resulting strike / expiration for rolls
- state before / after
- provenance/version fields

## Guardrails

- Virtual positions MUST NEVER write to `executed_actions`, actual `cc_positions`, broker adapters, or real execution paths.
- All virtual outcomes must be explicitly marked `PROSPECTIVE_VIRTUAL`.
- No future market data may be used in a decision before its timestamp.
- Do not reuse actual V2 management decisions as V3 decisions.
- Virtual management must call the same deterministic policy function as live management where possible; do not create a second divergent rule engine.
- If required market data is unavailable at a management timestamp, mark that interval unavailable/censored rather than interpolating future information.
- Virtual fills must use the versioned execution model that was active at the time of the virtual action.
- Model/config versions must be immutable for an already-open virtual chain.
- No LLM is allowed to make virtual roll/management decisions.

## Implementation notes

Prefer reusing:

- `evaluate_cc_management_state`
- `_suggest_next_call`
- V3 execution/slippage primitives
- existing trade-chain economics
- existing time utilities
- existing event/thesis policy snapshots

Do not duplicate core CC math if an existing deterministic function can be called safely with an explicit as-of snapshot.

## Acceptance tests

### Initial virtual entry
- [ ] V3 challenger SELL_CC creates one virtual position.
- [ ] V3 challenger NO_CALL creates no virtual position.
- [ ] V2 execution records are untouched.
- [ ] Entry fill uses the configured execution-model version and decision-time quote.
- [ ] Running the same creation twice is idempotent.

### Management lifecycle
- [ ] OTM HOLD_CALL path remains open.
- [ ] >=80% premium captured causes virtual BTC when live policy would do so.
- [ ] Delta/ITM threshold causes the same virtual management action as the deterministic live policy for the same snapshot.
- [ ] ROLL_UP produces a new virtual contract and closes the prior leg.
- [ ] ROLL_OUT produces later expiry.
- [ ] ROLL_UP_AND_OUT changes both strike and expiry according to existing invariants.
- [ ] Assignment path closes the chain.
- [ ] Expiry OTM closes the chain.
- [ ] No virtual action occurs when required quote data is unavailable.

### No-lookahead
- [ ] A market move occurring after a scheduled decision timestamp cannot affect that earlier virtual decision.
- [ ] Event knowledge appears only when event data existed by the virtual decision timestamp.
- [ ] Virtual roll candidate selection uses only option-chain data available at that timestamp.

### Isolation
- [ ] Running the virtual book changes no actual `executed_actions`.
- [ ] Running the virtual book changes no actual `cc_positions`.
- [ ] Running the virtual book invokes no broker API write.
- [ ] Actual and virtual trade-chain IDs cannot collide.

### Economics
- [ ] Single-entry expiry OTM economics reconcile exactly.
- [ ] Assigned virtual call economics reconcile exactly.
- [ ] Multi-hop virtual roll economics reconcile exactly.
- [ ] Fees/slippage are included once and only once.
- [ ] Per-share and total-dollar units are explicit and tested.

## QA requirements

### Backend QA
- [ ] Run virtual-book migration against a backup/copy of production DB.
- [ ] Confirm current holdings, actual CC positions, recommendations, and executions are unchanged.
- [ ] Run one real current V3 challenger through virtual entry on Optiplex.
- [ ] Verify virtual position is queryable and actual position tables are unchanged.
- [ ] Exercise one synthetic full lifecycle in production-like DB.
- [ ] Verify service restart preserves open virtual positions.

### Operational QA
- [ ] Scheduled virtual-management job runs after market-data refresh and uses explicit Eastern/UTC time contract correctly.
- [ ] Duplicate scheduler invocation does not duplicate actions.
- [ ] Failure mid-cycle can be retried idempotently.
- [ ] Logs clearly distinguish `ACTUAL_CC` from `VIRTUAL_CC`.
- [ ] Metrics expose open virtual chains, completed virtual chains, errors, and censored intervals.

### Regression QA
- [ ] Existing covered-call management tests remain green.
- [ ] Existing actual execution behavior is unchanged.
- [ ] Existing V2 recommendation path is unchanged.
- [ ] Existing release checks still pass or any delta is explicitly explained.
