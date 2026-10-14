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

Select a risk account explicitly in Decision mode. Its captured positions must match
the portfolio; otherwise account alignment is unavailable. Account NAV includes
captured cash and marked positions. Without a matching account, tracked holdings
value is labeled as such and cash is unknown. Reference prices are simulation
inputs, not executable limits or fill guarantees. Fees and slippage are excluded
explicitly. Missing/stale mark evidence keeps a proposal in review.

Risk preview and execution evaluation share the same rule core. Preview writes no
intent, risk decision, counterfactual, reservation, order, or fill. Execution-only
checks are identified as unknown/skipped. Linked reallocations receive per-leg
checks and remain REVIEW_REQUIRED because aggregate reservations have not been
admitted. Missing Critic/model evidence fails closed. Deterministic vetoes are reused,
not copied. Exact-lot FIFO, long-term-first and minimum-gain scenarios describe
planning alternatives, not broker-supported disposition guarantees. Federal tax
liability is absent unless explicit rate policy is provided.

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
read-only production checks. It opens SQLite in read-only mode, denies mutations,
disables model/network use and never persists decisions. Canary PASS proves the
pipeline ran without changing protected state; `source_health` and each proposal's
state separately report evidence readiness. A missing pipeline receipt or risk
account must not appear healthy merely because the canary itself ran.

Regression coverage lives in `tests/test_advisor_decision.py` and
`tests/test_advisor_adversarial.py`, including executable JavaScript rendering checks.

Acceptance verification (2026-10-14): all 55 focused advisor tests pass. The
read-only canary ran against a consistent SQLite backup of the production
Optiplex database, with all protected row counts unchanged. Both “Get IGV to
100 shares” and “Buy 17 IGV” produced +17 shares; the linked STZ/IGV request
produced -10 STZ and +17 IGV. Source health was DEGRADED, and these proposals
remained REVIEW_REQUIRED. The BP sell was BLOCKED by covered-call coverage.
Canary PASS describes mutation safety, not production evidence readiness.

Decision IDs are immutable at the database layer alongside their stored contents.
The identity trigger is additive, so rerunning the migration also protects databases
that already have the advisor tables and earlier immutability triggers.
