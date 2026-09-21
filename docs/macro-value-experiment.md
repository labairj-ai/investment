# Macro Value Experiment

The v1.7 acceptance remains an immutable historical record. The confirmed financial
adapter defect requires v1.8 acceptance before repaired evidence is usable. This
workstream measures incremental selection value and grants no production influence.

## Prospective protocol

`config/macro_experiment_v2.json` is the current preregistration; v1 is retained.
Before the first episode,
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
model, evidence provenance and completed scoring item contribute. All base-eligible
candidates at or above `Bmax - 2*adjustment_cap` (inclusive, currently Bmax-10)
must carry original or supplemental accepted coverage before the decision. Missing
certification excludes the cohort as `coverage_incomplete`. The treatment uses the
intersection of their usable dimensions; an empty intersection excludes the cohort
as `no_common_usable_macro_dimensions`. Weights are never renormalized, missing
scores are never imputed, and candidates outside the envelope cannot win under the
bounded adjustment. Both arms share base-score
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

## Repaired evidence and supplemental candidate coverage

The defect diagnosis supersedes the earlier description of all missing runtime
evidence as a data-readiness limitation. `macro_evidence.py` reads the real stored
statement schema. It derives `(total_debt-cash)/1e6` in reporting-currency millions
and `100*gross_profit/revenue` in percentage points, selects by financial period
and conservative fetched-at availability, and preserves source values and units.
No USD currency is invented. Same-period quarterly rows take precedence over annual
rows; freshness limits are 185 days for quarters and 550 days for annual statements.
Unknown interest coverage, foreign revenue and unsourced geo data remain unavailable.
The adapter source and evidence schema v3 are part of the scorer contract hash.

Candidate scores, immutable history and run/item ledgers are separate from holding
scores. Supplemental N=20 certification reuses the canonical frozen-input scorer
and accepted stability policy. Immutable coverage records reference the current
acceptance; they never activate acceptance or extend its original artifact. Both
score publication and certification must predate any consuming decision.

```
venv/bin/python scripts/prepare_macro_candidates.py
venv/bin/python scripts/prepare_macro_candidates.py --prepare --out out/coverage_PREPARATION_ID.json
venv/bin/python scripts/run_macro_coverage_canary.py --out out/canary_CANARY_ID.json
```

The first command only plans the bounded target envelope. Preparation fetches
existing financial sources, scores candidates, and certifies previously untested
targets under the current acceptance. A process lock prevents overlapping collectors;
stale interrupted ledgers are reconciled before a new collection. The optional
weekday 04:00 America/New_York timer prepares data ahead of later sweeps. It must
not be enabled until the initial acceptance/coverage rollout has completed.

The real canary invokes Opportunity Hunter and persists prospective episodes,
cohorts and virtual books. It does not publish returned recommendations or invoke
broker execution. An isolated pre-sweep database copy replays the existing production
path with macro observation disabled and the same recorded LLM response. All
recommendation fields must match except distinct episode IDs and wall-clock expiry
timestamps; the seven-day validity duration is independently checked. The canary
also requires unchanged trade-intent counts and fills in both macro virtual books.
Cost-basis placeholders remain incomplete until ordinary nightly mark-to-market.

Only a passing canary establishes `collection_started_at` in Learning Lab. A failed
or uncovered sweep remains excluded and cannot be backfilled. No divergence or
positive outcome is required to begin collecting; no effectiveness or promotion
claim is implied. Freeze protocol v2 while prospective outcomes accumulate.
