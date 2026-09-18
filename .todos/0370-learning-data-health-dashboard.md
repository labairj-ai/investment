# Learning Data Health Dashboard for Training and Promotion Decisions

- **ID:** 0370
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0360, 0365, 0366

## Problem

Before training or promoting a model, there is no single view that surfaces
whether the dataset is trustworthy. Potential issues — stale quotes, missing
outcome labels, ticker concentration, incomplete MTM rows, high feature-null
rates — are visible only by manually querying individual tables. A trainer or
reviewer cannot quickly answer "can I trust this dataset?" without writing
ad-hoc SQL. As the system accumulates data across multiple model versions and
outcome horizons, silent data-quality problems will increasingly distort
learning signals.

## Proposed approach

### Data health metrics to surface

| Category | Metric |
|---|---|
| **Outcome coverage** | % of episodes with each horizon labeled; count/% with NULL outcome |
| **Ticker concentration** | Top-10 tickers by episode count; fraction of total |
| **Label freshness** | Date of most recent outcome label written; age of oldest unlabeled mature episode |
| **Quote quality** | % of intents by `quote_quality` tier (BID_ASK / LAST_ONLY / PAYLOAD_FALLBACK / missing) |
| **MTM completeness** | # of `virtual_book_nav` rows; % with `is_complete=0`; date of most recent complete row |
| **Failed price fetches** | # of MTM rows where any ticker had `is_complete=0` in last 30 days |
| **OBSERVE observation coverage** | # of `model_observations` rows per model_version; % with `outcome_alpha_90d` filled |
| **Feature null rates** | % NULL for each feature column in `decision_episodes` (for active model versions) |
| **Model version coverage** | For each active model, % of live episodes that have a shadow observation |

### Implementation options

**Option A — API endpoint** (`GET /api/agents/learning/health`): returns a
JSON object with all metrics. Dashboard renders a "Learning Lab" card.

**Option B — CLI summary** (`python -m agents.learning.calibration --health`):
prints a table to stdout. Useful for pre-training inspection without the server.

Recommend implementing both: the CLI for training-time inspection, the API for
dashboard visibility.

### Threshold alerts

For each metric, define a `warn` and `block` threshold:

```python
HEALTH_THRESHOLDS = {
    "outcome_coverage_3m_pct":     {"warn": 0.50, "block": 0.25},
    "top_ticker_concentration_pct": {"warn": 0.25, "block": 0.40},
    "incomplete_mtm_pct_30d":      {"warn": 0.10, "block": 0.30},
    "feature_null_rate_max":       {"warn": 0.05, "block": 0.20},
}
```

A `block`-level finding should prevent `calibration.py` from training a new
model until the issue is resolved (or overridden with explicit reason).

## Touches

- `agents/learning/calibration.py` — `check_training_health()` function; call before `fit()`; raise `DataHealthWarning` at warn level, `DataHealthBlock` at block level
- `agents/learning/outcome_labeler.py` — expose helper for coverage stats
- `agent_db.py` — helper queries for each health metric
- `serve.py` — `GET /api/agents/learning/health` endpoint
- `tests/test_calibration.py` — test that block-level metric prevents training; test that warn-level logs but continues

## Done when

- [ ] `check_training_health()` computes all metrics listed above
- [ ] Block-level findings prevent `fit()` from running
- [ ] `GET /api/agents/learning/health` returns structured JSON with per-metric status and value
- [ ] Dashboard "Learning Lab" card (or equivalent) displays health summary
- [ ] Test: seeded DB with high ticker concentration → health returns WARN for concentration metric
- [ ] Test: seeded DB with low outcome coverage → health returns BLOCK and fit() raises
- [ ] `python -m pytest tests/` passes with no regressions
