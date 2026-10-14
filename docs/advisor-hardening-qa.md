# Advisor hardening verification — 0742–0744

The 2026-10-14 feedback created three TODOs: functional canary v2, Critic semantic
parity, and SQLite/account-scoped context hardening. The decision/economic scorer
and execution risk-rule core are unchanged. Advisor policy identity advances to v2.

The focused Advisor command (`pytest tests/test_advisor_decision.py
tests/test_advisor_adversarial.py -v`) passes 121 tests. Existing producer schema,
confidence and persistence fixtures remain unchanged. Added cases inject incorrect
target/delta math, absent legs/fields, wrong contracts, unexpected research state,
pipeline exceptions and raised execution flags; all produce functional FAIL with
mutation safety PASS. INSERT, UPDATE, DELETE, DDL/index, ATTACH, CTE-backed UPDATE
and guard-disabling attempts are denied and produce mutation safety FAIL even
when caught, including inside nested context scopes.

The deterministic fixture also tests zero/fractional holdings under a ticker other
than IGV/STZ. Captured fractional shares are preserved; the generated whole-share
target and equivalent fractional buy delta reconcile exactly. Missing holdings,
marks and NAV cannot silently pass. Before/after hashes detect same-count content
changes as well as row count changes. Every existing table is protected, including
learning/account state; the canary never persists advisor decisions.

Production evidence is the complete `advisor-canary-v2-20261014.json` receipt in
`docs/evidence/`, produced from a fresh consistent read-only SQLite backup of
Optiplex production. Both dimensions and overall health PASS; all 122 existing
table content identities plus schema identity are unchanged. Selection chose BP
at 100 shares: target 117 and explicit BUY 17 both return +17. Both remain BLOCKED
by existing thesis/source governance. Production source health remains separately
DEGRADED; this receipt does not certify execution readiness or change trading.

Critic parity examples corrupt layer targets to `{1: 50, 2: 40}`. Canonical ALLOCATE
and Advisor new BUY, existing ADD, trim and multi-leg reallocation return the same
deterministic veto reason: targets sum to 90.0%, allocation invalid until corrected.
The model is never called afterward. Valid target fixtures cover all LLM verdicts
and missing Critic; approval/caution do not override source/risk blocks. Captured
Advisor input/prompt carries exact trade impact/thesis/context but producer score
and confidence are unavailable (`None`), while producer 77/81 fixtures retain their
observed values and unchanged output schema. No recommendation/trading rows are
created by Advisor review.

The two-account fixture uses overlapping IGV positions in A/B. B-only position,
order, fill, intent and risk-audit mutations leave A's risk/authorization identity
and persisted decision validity unchanged. A's relevant position, order, current-day
fill, open intent and cash changes change identity and invalidate stored decisions.
An A SELL commitment blocks overselling; B's commitment does not. Reinserted rows
in reversed order (with new position surrogate IDs) retain identical risk and
authorization hashes. Old closed fills/orders/intents do not affect equity preview.
Risk preview returns the captured selected-account hash, executes shared rules and
writes no risk/trading rows; absent selected accounts remain unavailable.
Current fill identity includes only `fill_id`, `account_id`, `qty`, `price`,
`filled_at` and `realized_pnl`; changing unrelated fill audit metadata preserves
identity because it is not an input to the active equity risk rules.

Canonical snapshot fields: `snapshot_version`, `account_id`, `risk_day_utc`,
`trading_accounts`, `position_snapshots`, `orders`, `fills`, `trade_intents`, and
`global_inputs`. Ordering and active equity-rule dependencies are documented in
`advisor-decision.md`; resolved policy/defaults are separately captured by policy
version/hash. Nested guards restore authorizers and query_only on success/error,
and leave caller-owned transactions uncommitted. External screener access is
explicitly mode=ro.
