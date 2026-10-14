# Portfolio Advisor Decision mode

Explore remains the conversational `/api/ai/chat` interface. Decision uses
`POST /api/ai/decision` and renders a structured, persisted preview. Neither mode
submits orders. ACTIONABLE means decision-grade for user review, never execution
approval. Conversion to a paper intent is disabled.

The versioned pipeline is captured context → typed request → deterministic impact
→ exact tax lots → shared Critic → shared risk preview → deterministic policy →
immutable lineage → explanation. Model output cannot set quantities, policy state,
Critic vetoes, or risk results. A rendering failure leaves the structured result
available. Parsing unresolved quantities returns clarification rather than a guess.

Context reads canonical Decision Brief state, holdings, exact lots, CC coverage,
layer targets, persisted screener enrichment, and the opportunity comparison scorer.
The context builder starts a read snapshot and performs no migrations, writes,
network calls, or model calls. Missing tables or marks remain unavailable. UTC
freshness is shared with the Decision Brief. Full context identity captures advisory
sources; authorization identity excludes observe-only macro/learning values and
freshness. Those sources cannot alter ranking, size, or actionability.

SQLite enforces the read-only boundary, including WITH-backed writes. Advisor HTTP
handlers and the canary use `GuardedConnection`: its nested authorizer scopes deny
DML, schema/database operations and mutating pragmas, compose existing callbacks,
and restore them after success or failure. `query_only` is also preserved/restored;
context capture never commits a caller transaction. A plain caller-supplied
connection keeps its existing authorizer untouched (Python exposes no getter) and
uses SQLite `query_only` for DML/schema denial. Use the tracked factory for full
authorizer operation coverage. External screener access remains `mode=ro`.

Select a risk account explicitly in Decision mode. Its captured positions must match
the portfolio; otherwise account alignment is unavailable. Account NAV includes
captured cash and marked positions. Without a matching account, tracked holdings
value is labeled as such and cash is unknown. Reference prices are simulation
inputs, not executable limits or fill guarantees. Fees and slippage are excluded
explicitly. Missing/stale mark evidence keeps a proposal in review.

`advisor-risk-snapshot-v2` captures only the selected account, ordered positions
(account/symbol identity, excluding surrogate row IDs), open intents ordered by
intent ID, orders working/partially filled or submitted on the captured UTC day
ordered by order ID, and that day's fills ordered by timestamp/fill ID. Today's
fills capture only identity, account, quantity, price, time and realized P&L for
daily turnover/loss checks; unrelated fill audit metadata, historical closed orders and fills do not
affect equity preview. The selected account's resolved policy hash captures global
defaults and account overrides separately. No other global database input is used
by these equity risk rules. Context, commitments, canonical brief execution state
and risk preview use this scope. With no matching account, alignment and risk
remain unavailable; commitments from other books are never combined.

Selected-account positions/marks, relevant orders/fills/open intents, cash/account
policy and UTC risk-day rollover change authorization identity. Unrelated account
activity, unrelated risk/advisor audit rows and collection insertion order do not.
Portfolio holdings, thesis, exact lots and open CC coverage remain canonical shared
portfolio inputs and still invalidate a decision when they change.

Risk preview and execution evaluation share the same rule core. Preview writes no
intent, risk decision, counterfactual, reservation, order, or fill. Execution-only
checks are identified as unknown/skipped. Linked reallocations receive per-leg
checks and remain REVIEW_REQUIRED because aggregate reservations have not been
admitted. Missing Critic/model evidence fails closed. Deterministic vetoes are reused,
not copied. Exact-lot FIFO, long-term-first and minimum-gain scenarios describe
planning alternatives, not broker-supported disposition guarantees. Federal tax
liability is absent unless explicit rate policy is provided.

`critic-review-v1` Advisor inputs carry `origin=advisor`, exact impact, before/after
layers, thesis/context references and explicit `ALLOCATION_CHANGE` semantics.
New BUY, ADD, trim and reallocation proposals receive the shared allocation target
integrity veto without changing option rule categories or producer BUY semantics.
Producer score and confidence are `None`, explicitly unavailable in the prompt,
never invented neutral 50 values. The producer output schema is unchanged.
`advisor-policy-v2` records the stronger governance contract and invalidates old
policy-v1 decisions. Veto, challenge and unavailable Critic behavior remain fail-closed;
approval never overrides other gates or authorizes execution.

`advisor-decision-v1` snapshots have a 15-minute TTL. Stored request, context,
trade math, lot scenarios, Critic, risk, policy and explanation are immutable.
Lifecycle may move to STALE, SUPERSEDED or EXPIRED and cannot reactivate. Reusing an
ID is idempotent; conflicting requests fail. Reads revalidate dependency identity.
Advisor history is excluded from producer-agent learning.

Endpoints:

- `POST /api/ai/decision`: request, optional risk account ID and UUID retry ID.
- `GET /api/ai/decision/{id}`: revalidated immutable decision.
- `GET /api/ai/advisor-health`: decision/lifecycle counts, gate/render failures and
  available risk accounts. Empty history is unavailable until lineage schema exists.

Run `python scripts/canary_advisor_decision.py --db /path/to/investment.db` for
read-only production checks. `advisor-canary-v2` opens SQLite in read-only mode,
uses the tracked authorizer, disables models/network use and never persists
decisions. Programmatic `run_canary()` requires the tracked factory to record denied
attempts even when helpers catch exceptions. It reports `mutation_safety` and
`functional_contract`; overall PASS requires both. Mutation safety checks counts
and canonical contents/schema of every existing table, including trading/account,
advisor, recommendation and learning state. A denied mutation attempt fails safety
even when no rows change.

Functional checks choose the first alphabetically ordered holding with finite,
nonnegative shares and a finite positive mark. The whole-share target is
`floor(captured_shares) + 17`; the independently calculated delta preserves any
fractional holding remainder. Target and equivalent explicit-delta requests must
parse correctly and produce the expected same ticker/side/quantity and trade legs.
Checks also cover supported contracts, captured identities, structured governance
stages, policy/evidence consistency and disabled execution/learning. No usable
scenario, wrong math, missing fields/legs or unexpected exceptions fails health.
Failed invariant names and scenario/observed quantities are machine-readable.

PASS proves basic deterministic functionality and mutation safety, not evidence
readiness or execution permission. `source_health` and each policy outcome report
that distinction separately. Critic UNKNOWN is expected with models disabled and
risk UNKNOWN is expected without an explicitly selected matching account. Legitimate
REVIEW_REQUIRED, RESEARCH_ONLY and BLOCKED outcomes can pass functional checks;
policy requirements are never lowered to obtain PASS.

Regression coverage lives in `tests/test_advisor_decision.py` and
`tests/test_advisor_adversarial.py`, including executable JavaScript rendering checks.

Initial v1 acceptance verification (2026-10-14): all 55 focused advisor tests passed. The
read-only canary ran against a consistent SQLite backup of the production
Optiplex database, with all protected row counts unchanged. Both “Get IGV to
100 shares” and “Buy 17 IGV” produced +17 shares; the linked STZ/IGV request
produced -10 STZ and +17 IGV. Source health was DEGRADED, and these proposals
remained REVIEW_REQUIRED. The BP sell was BLOCKED by covered-call coverage.
That v1 canary measured mutation safety; v2 adds the functional contract above.

Decision IDs are immutable at the database layer alongside their stored contents.
The identity trigger is additive, so rerunning the migration also protects databases
that already have the advisor tables and earlier immutability triggers.

The initial local suite passed: 2,529 passed, 16 skipped, no failures. The existing
exact baseline inventory and covered-call behavioral contract gates also pass.
Two legacy covered-call surface tests now use the fixed fixture's capture time
instead of wall-clock freshness; production freshness behavior is unchanged.

GitHub Actions passed the full test job, TODO consistency check, exact baseline
inventory gate and covered-call behavioral contract gate on the implementation
commit: https://github.com/labairj-ai/investment/actions/runs/38552153244.
TODOs 0732–0741 are complete and archived under `.todos/done/`.

Hardening evidence for 0742–0744 is recorded in `docs/advisor-hardening-qa.md`
and `docs/evidence/advisor-canary-v2-20261014.json`.
