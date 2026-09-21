# Macro Value Experiment

Acceptance is frozen at v1.7. This workstream measures incremental selection value;
it neither changes the accepted scorer nor grants it production influence.

## Prospective protocol

`config/macro_experiment_v1.json` is the preregistration. Before the first episode,
the accepted artifact, protocol, ranking source and risk constants are hashed into
an immutable epoch. Changing any of these starts a separate population. Reporting
defaults to the current epoch and never pools older epochs. Historical episodes
are retained but cannot be enrolled retrospectively.

Opportunity Hunter freezes the same candidate universe, base scores, financial
evidence, portfolio snapshot and timestamp for both arms. The control is the
existing deterministic composite. The treatment adds a fixed structural
defensiveness term, bounded to five composite points:

```
adjustment = 5 * sum(weight[d] * (accepted_score[d] - 5.5) / 4.5)
weights: rates -0.25, inflation +0.25, dollar -0.25, geopolitics -0.25
```

Only formally eligible dimensions with the exact accepted scorer, configuration,
model, evidence provenance and completed scoring item contribute. Missing or
ineligible dimensions contribute no incremental adjustment; weights are never
renormalized and missing scores are never imputed. Both arms share base-score
eligibility and deterministic ticker tie-breaking. Existing AI conviction remains
in the common base; this isolates **accepted macro score influence**, not all
possible macro information latent in earlier analysis. Neither arm adds an LLM
selection step or a learned challenger adjustment. This tests one fixed treatment,
not the proposition that every use of macro helps.

The cohort ledger records every original candidate, both selected episode IDs,
universe hash, dimensions and the cached decision-time regime. Cohorts with no
usable macro dimensions are explicitly excluded. Nothing writes a production
recommendation, trade intent or production weight.

## Outcomes and uncertainty

The primary endpoint is mean macro-minus-control SPY-relative alpha among
divergent cohorts at `sessions_v2` / `3m`: 63 trading sessions, approximately
90 calendar days. The existing daily outcome labeler freezes paired experiment
labels only after maturity and valid outcomes for both original episodes.
Calendar-horizon labels, missing benchmark returns, future labels and failed
labels cannot substitute. Missing MFE/MAE remains missing.

The experimental unit is a decision cohort. Bootstrap intervals resample whole
decision dates (2,000 reproducible replicates); multiple candidates or sweeps on
one date do not become independent evidence. One date cannot produce a confidence
interval. Reported secondary metrics include median delta, wins/ties, 1w/1m
diagnostics, MFE/MAE, concentration, recommendation churn and virtual-book metrics.

Two isolated macro books reuse the existing position sizing, slippage and nightly
mark-to-market system. Trade-time cost-basis NAV placeholders are marked incomplete.
Performance uses only complete marks; volatility excludes gaps between trading
sessions. Graduation requires paired date coverage across at least the primary
horizon and complete risk evidence. Book turnover is gross traded notional divided
by starting capital. It is distinct from recommendation churn.

Dimension subsets and regime summaries are exploratory, based solely on frozen
prospective evidence. They cannot promote a model or replace the primary endpoint.

## Evidence and influence

Evidence states are INSUFFICIENT, INCONCLUSIVE, POSITIVE and NEGATIVE. The protocol
requires diversity across dates, tickers, sectors and regimes, sufficient actual
divergence and a sufficiently narrow date-clustered interval. A preliminary
25-cohort reporting milestone is not proof. A POSITIVE alpha interval does not
override drawdown, MAE, concentration or book-coverage blockers.

Production stays at stage 0. A pure policy helper specifies capped future stages
(near ties, bounded adjustment, learned bounded adjustment, broader bounded
influence). It has no production caller. Any future promotion requires positive
prospective evidence and a separate explicit production change. Returning to
stage 0 yields the unchanged base score. No model fitting or live learned-weight
promotion is performed by this experiment.

## Operation

Run only against the authoritative Optiplex database. Startup migrations create
the ledger; ordinary Opportunity Hunter sweeps register and capture prospectively,
and the ordinary outcome labeler synchronizes mature labels. Learning Lab reads
the report through `/api/learning/readiness`.

```
venv/bin/python scripts/macro_experiment.py out/investment.db
venv/bin/python scripts/macro_experiment.py out/investment.db --register
venv/bin/python scripts/macro_experiment.py out/investment.db --sync-labels
venv/bin/python scripts/macro_experiment.py out/investment.db --epoch EPOCH_ID
```

The default CLI opens SQLite read-only. Registration never backfills cohorts.

As of the implementation review on September 20, 2026, the eight stocks with
accepted dimension eligibility do not overlap the active/watch candidate list.
Usable observation collection therefore depends on accepted coverage reaching
the actual Opportunity Hunter universe. The implementation reports exclusions;
it does not loosen eligibility, score candidates with future information or claim
that empty cohorts establish effectiveness. Resolving that coverage limitation
is a separate scope decision under the frozen acceptance policy.

Deployment verification also found zero currently usable dimensions across the
eight accepted tickers under runtime evidence-quality checks (XOM, for example,
has `none` in all four current evidence-quality fields). Formal acceptance alone
does not make those snapshots usable. This data-readiness limitation is also
tracked in 0557; the experiment correctly excludes these scores.
