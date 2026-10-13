# Covered Call V3

The evidence, simulator, surface and duration follow-ups are documented in
[Covered Call V3 follow-ups](covered_call_v3_followups.md); that contract supersedes
the original V1 descriptions below where noted.

The source requirements are preserved in `covered_call_v3_todos/` (0690–0703).
Deployment starts in **observe_only** mode. Corrected V2 remains the live entry
champion; management and roll-selection rules are unchanged. No broker orders are
created by this feature. V3 may recommend different coverage or NO_CALL but those
outputs are diagnostic until prospective promotion.

## Entry and models

- Hard gates run on every captured entry alternative before top five: strategy,
  DTE band, OTM, delta, events, assignment policy/floor, live valid bid/ask, and
  minimum liquidity. No fallback. Rejections and NO_CALL are persisted.
- V2 uses annualized yield in its relative score and absolute `opp_score` ordering.
  The LLM receives only eligible IDs. Floating-point metrics remain unrounded in
  evidence and action payloads; display formatting rounds only for readers.
- Drift is a market-prior posterior with an annual volatility uncertainty floor
  of 20%, bounded annual return observation, and a 5% bounded momentum adjustment.
  Raw returns, raw/bounded estimate, uncertainty and model version are persisted.
  Historical-volatility forecasting remains intact. Both center and upper-bound
  physical ITM, regret and alpha are captured. V3 risk limits use the upper bound.
- GBM first-passage strike and premium barrier probabilities supplement terminal
  risk. Daily deterministic Monte Carlo estimates moving delta thresholds and
  conditional time to first strike touch. Production seed is 6902; path count is
  configured. Delta estimates are daily-grid estimates, not intraday forecasts.
  Analytical strike touch is validated against Brownian-bridge MC within 0.02
  absolute probability on 20,000-path synthetic tests. The bounded management
  proxy is **not** a calibrated probability of a roll.
- The local surface uses same-snapshot ATM/ITM/OTM quotes. Interpolation requires
  three valid points and delta support; no extrapolation. Broken/stale quotes and
  large IV outliers are unusable. Term comparisons use neighboring expiries
  within 35 days. Earnings variance, when estimable, uses a shorter event-free ATM
  baseline and is explicitly an estimate. Missing event/surface measurements are
  null. Historical IV percentile needs 30 independent comparable-delta/DTE days.
  Provider bid/ask timestamps are unavailable from the current feed: capture time
  is identified as capture time, not a verified exchange quote timestamp.
- Utility units are USD per share. Mid premium minus conservative upside
  surrender, intervention cost, execution cost and expected FIFO tax friction
  exactly reconciles to adjusted alpha. Slippage is subtracted once. Management
  includes configured labor plus two-leg execution friction, not option payoff
  loss. Missing tax/execution inputs block V3. Surface gaps block V3 selection.
  The absolute hurdle is 2% annualized spot value, duration prorated; ranking
  uses utility margin per day. Nonpositive margin returns NO_CALL.
- Duration diagnostics include premium/alpha per day, theta efficiency, risk per
  day and an observed shorter-cycle benchmark. Its second cycle assumes 50%
  availability and 50% alpha retention; it does not repeat current IV or assume
  writing is always available. It is a benchmark, not another utility deduction.
- V3 policy coverage caps are INCOME 100%, UPSIDE_PRESERVATION 50%, NONE 0%.
  High conviction/strong uptrend cap coverage at 50%. Round lots round down:
  300 shares at a 50% cap recommends one call, actual overwrite 33.3%.
  V2's original coverage is stored separately for actual outcome attribution.
  Actual entry recording cannot exceed recommendation-authorized contracts.
- Equity regime uses bounded momentum, trend persistence, breakout and 52-week
  distance. Strong-uptrend challenger adjustments bound coverage, delta, OTM
  and hurdle. Configuration can disable those adjustments. Regime cannot create
  a trade without eligibility and positive utility.
- Tax calculations reuse `_lot_tax_friction` and FIFO lot schedules at expiry.
  Raw projected gain and ST/LT differential are visible, missing lots are explicit.
  QCC status remains UNASSESSED with review warnings; no tax qualification is
  inferred from incomplete information. Ex-dividend state is exposed separately.
- Execution uses a conservative 15%-of-spread fill prior. Empirical tight/wide
  buckets require 30 **actual** fills and shrink toward 50 prior observations.
  Estimated fills never train the model. Zero/crossed quotes are handled explicitly.

## Evidence, outcomes and dashboard

`cc_decisions` and `cc_candidates` are append-only; UPDATE/DELETE triggers enforce
immutability. Full alternatives, champion/challenger flags, policy/config, model
versions and git SHA are captured. Each new SELL_CC uses its originating episode
in a unique trade-chain ID, inherited by management descendants. `cc_labels` and
`cc_fills` are separate immutable evidence with append-only label revisions.

The existing `outcome-labeler` timer invokes the CC forward labeler after its
other jobs. Daily OHLC provides observed high/low/touch; delta is reconstructed
at daily closes using entry IV. Decision-day highs are excluded because they may
precede the recommendation. SPY sessions validate provider session coverage;
missing paths, incomplete chains, and unreconciled economics stay censored.
Expiry counterfactual returns are explicitly **estimated**. Actual economics join
executions through the originating trade_chain_id, including both roll legs.
Assignment opportunity cost and actual management/slippage measurements must be
reconciled before those economic labels can qualify for promotion; absent data
cannot silently become zero cost. Neither future bars nor execution refreshes
modify decision-time features.

The dashboard's Learning panel includes **Covered Call Learning Lab** backed by
`GET /api/learning/covered-calls`: candidate audit details, decomposed utility,
coverage, terminal/path predictions, observed/reconstructed/censored outcomes,
DTE/delta/OTM/coverage/VRP/strategy/regime/divergence cohorts and calibration bins.
Every cohort shows N, eligibility/censoring, and separate roll/alpha sample N.
Probability metrics report Brier score, reliability error and low-N bands.
The latest decision per ticker/session is the independent evaluation unit.

## Actual execution quotes

The existing recommendation execution API accepts optional `execution_quote`:

```json
{
  "bid": 1.80,
  "ask": 2.00,
  "quote_timestamp": "2026-10-13T17:00:00+00:00",
  "execution_timestamp": "2026-10-13T17:01:00+00:00",
  "underlying_price": 100.25
}
```

For an episode-linked SELL_CC, the execution premium/fees and contemporaneous
quote are recorded atomically with executed_actions/cc_positions. Timestamps must
be timezone-aware and no more than five minutes apart. Invalid quotes roll back
the entire transaction. Without contemporaneous quotes, ordinary executions still
record normally but cannot train fill-fraction calibration. Python `record_fill`
also supports reconciled actual fill imports, using stable fill IDs.

## Promotion and rollback

The committed gate predates outcome collection: at least 100 independent paired
prospective decisions, 30 divergences, 90 calendar days, positive incremental alpha
improvement, no increase in roll frequency or management cost, zero assignment
policy violations, and strike-touch Brier <= 0.25 on at least 100 observations.
Retrospective or missing/unreconciled evidence cannot satisfy it. Actual comparison
costs and assignment policy compliance must be labeled explicitly. Weak results
remain observe-only. All promotion cohorts must match the current config/model.

```sh
venv/bin/python covered_call_ledger.py report
venv/bin/python covered_call_ledger.py label --dry-run
venv/bin/python covered_call_ledger.py promotion
```

Promotion requires changing config `mode` to `evidence_gated` and explicitly
running `covered_call_ledger.py promote`; it rechecks evidence and records a
versioned immutable snapshot with cohort IDs/sample counts/config hash/git SHA.
Changing code/config invalidates activation until recertification. The config
hash excludes only `mode`, so observation can qualify for later activation.
Rollback is either setting mode back to `observe_only` or running
`covered_call_ledger.py rollback`. There is no automatic model/weight mutation.

## Validation

New deterministic tests cover all entry gates, filtering before truncation,
no-fallback NO_CALL, full probability precision, drift regimes and perturbations,
first passage/MC, delta thresholds, flat/upward/inverted/event surfaces,
utility reconciliation, sizing/regime disabling, FIFO reuse, actual fill shrinkage,
immutable episodes/labels, path and chain censoring, calibration, divergence and
promotion rejection. Integration tests verify actual-fill recording is atomic
with execution/position writes. Existing management/roll tests remain unchanged.

Reconciled chain costs can be captured with Python
`record_chain_costs(episode_id, trade_chain_id, management_cost, execution_cost,
assignment_cost, assignment_policy_violation, shares, terminal_underlying_price,
source)`. Costs are total USD, require an explicit source and matching originating
chain, and are immutable in `cc_chain_costs`. A later correction creates new
observation evidence and a new outcome revision. Unknown costs are rejected.
The forward labeler normalizes measured costs per share for comparison and uses
terminal underlying price for the chain's hold-return horizon. Actual option
cash flows already include slippage and fees; those costs are reported, not
subtracted twice. Intervention labor is an additional economic deduction.
