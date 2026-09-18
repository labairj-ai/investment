"""Challenger Calibration Model (0330, 0334).

Fits a ridge-regression model on labeled decision_episodes to predict
90-day SPY alpha. Applies a bounded, shrinkage-weighted adjustment to
the base Opportunity Hunter composite score.

Architecture constraints:
- Uses only numpy (sklearn not installed) — ridge regression via normal equations.
- Training requires MIN_TRAINING_N labeled 90d episodes before influencing scores.
- Adjustment is capped at ±MAX_ADJUSTMENT score points regardless of prediction.
- Shrinkage formula: adjustment = (n / (n + SHRINKAGE_LAMBDA)) * raw_adjustment
- Hard risk limits in the risk engine are never modified.
- Validation uses decision-date cohort walk-forward with 91-day embargo (0334):
  never a random or row-index split. The embargo prevents return-window overlap
  between training and validation sets.
- p_outperform removed (0334): sigmoid(alpha) is not a calibrated probability;
  a future binary-outcome model will replace it with a proper calibration curve.

Usage:
    model = ChallengerModel.train()     # returns None if insufficient data
    if model:
        out = model.score(candidate)    # dict with expected_alpha, learning_adjustment, etc.
        model.save_with_weights()       # persist to learning_models table
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import date as _date, timedelta as _td, timezone, datetime
from typing import TYPE_CHECKING

import numpy as np

import agent_db

MIN_TRAINING_N      = 30        # below this, model has no influence
SHRINKAGE_LAMBDA    = 50.0      # at n=50, factor = 50/100 = 0.5
RIDGE_ALPHA         = 1.0       # L2 regularization strength
MAX_ADJUSTMENT      = 10.0      # ±score points cap
ALPHA_TO_SCORE_SCALE = 100.0   # 1% expected alpha above mean → +1 score point
HORIZON             = "3m"
EMBARGO_DAYS        = 91        # no overlap with 3m return window
MAX_CV_FOLDS        = 10        # cap walk-forward iterations
FEATURES            = ["q_score", "v_score", "pf_score", "c_score", "ec_score"]
FEATURE_SCHEMA_VER  = "v1"
# 0428: Increment this string ONLY when the training algorithm materially changes
# (fold selection, embargo math, feature normalization, the Ridge fit itself).
# Code changes unrelated to model output (dashboard, canary, tests) must NOT change this.
TRAINING_ALGORITHM_VERSION = "ridge_v1"

# 0411: Opportunity Hunter builds candidates with underscore-prefix keys (_q, _v, …).
# This map lets predict_alpha() accept either form without touching opportunity_agent.py.
_FEATURE_ALIASES: dict[str, str] = {
    "q_score":  "_q",
    "v_score":  "_v",
    "pf_score": "_pf",
    "c_score":  "_c",
    "ec_score": "_ec",
}


def candidate_learning_features(candidate: dict) -> dict:
    """Return a normalized feature dict readable by the Ridge model.

    Resolves both canonical names (q_score, …) and OH underscore aliases (_q, …).
    0422: OH underscore keys (_q, _v, …) are authoritative when present — they hold
    the values actually computed by the current sweep.  Canonical q_score/… values
    may carry stale data from a previous DB read and must not silently override the
    freshly-scored alias.  Canonical keys are used only as fallback when no alias exists.
    Returns a flat dict with exactly the five FEATURES keys; missing values are None.
    """
    out: dict = {}
    for canonical, alias in _FEATURE_ALIASES.items():
        alias_val = candidate.get(alias)
        if alias_val is not None:
            out[canonical] = alias_val
        else:
            out[canonical] = candidate.get(canonical)
    return out

# 0343/0347 — uncertainty band thresholds for ranking-spread CI width (precision classification)
ALPHA_CI_HIGH_THRESHOLD   = 0.02   # band width < 2% → HIGH precision
ALPHA_CI_MEDIUM_THRESHOLD = 0.05   # band width < 5% → MEDIUM; else LOW

# Lifecycle states — explicit promotion gates required between each (0335)
LIFECYCLE_TRAINED      = "TRAINED"
LIFECYCLE_OBSERVE      = "OBSERVE"
LIFECYCLE_PAPER_ACTIVE = "PAPER_ACTIVE"
LIFECYCLE_RETIRED      = "RETIRED"
LIFECYCLE_SUSPENDED    = "SUSPENDED"  # 0371: auto-suspended on edge degradation

# Promotion gate thresholds
PROMOTE_MIN_UNIQUE_TICKERS        = 10
PROMOTE_MIN_UNIQUE_DECISION_DATES = 30
PROMOTE_MIN_UNIQUE_WEEKS          = 4
PROMOTE_MIN_CV_FOLDS              = 3   # 0355: raised from 1; single fold is not meaningful evidence
OBSERVE_MIN_DAYS                  = 14  # 0355: minimum calendar days in OBSERVE before PAPER_ACTIVE
OBSERVE_MIN_FRESH_EPISODES        = 5   # 0355: minimum new decision_episodes since entering OBSERVE
OBSERVE_MIN_MATURE_OBS            = 5   # 0360: minimum model_observations with outcome labels
OBSERVE_MIN_COHORT_DAYS           = 10  # 0378: minimum distinct market days for cohort independence
DEGRADATION_MIN_NEW_OUTCOMES      = 15  # 0377: new PAPER_ACTIVE outcomes required between snapshots
DEGRADATION_MIN_NEW_COHORT_DAYS   = 3   # 0384: distinct scored_at_date values between snapshots
DEGRADATION_MIN_DIVERGENT_COHORTS = 5   # 0391: min divergent cohorts before selection delta used as NEGATIVE signal
DEGRADATION_WINDOW_COHORTS        = 30  # 0401: number of complete decision cohorts in the degradation window

# Canonical training target — the horizon the scheduled trainer uses (0379)
LEARNING_TARGET_HORIZON = "sessions_v2"
LEARNING_TARGET_PERIOD  = "3m"

# Gate result states (0381)
GATE_PASS          = "PASS"
GATE_FAIL          = "FAIL"
GATE_NOT_EVALUABLE = "NOT_EVALUABLE"

# 0432/0438: MIGRATION-ONLY fallback. Prefer evidence_contract_version column on learning_models.
# Used only when evidence_contract_version IS NULL (models written before 0438).
# Do NOT extend or rely on this timestamp for new logic; populate evidence_contract_version instead.
LEDGER_ROLLOUT_CUTOFF: float = 1789769915.0


class DataHealthBlockError(Exception):
    """Raised by train_and_save() when compute_data_health() returns overall='block'. (0376)"""


class ChallengerModel:
    """Shrinkage-regularized ridge model predicting 90d SPY alpha."""

    def __init__(
        self,
        coef: list[float],
        intercept: float,
        mean_alpha: float,
        training_n: int,
        training_cutoff: str,
        model_version: str,
        validation_metrics: dict,
        feature_schema_hash: str,
        lifecycle_state: str = LIFECYCLE_TRAINED,
    ):
        self.coef                = np.array(coef)
        self.intercept           = intercept
        self.mean_alpha          = mean_alpha
        self.training_n          = training_n
        self.training_cutoff     = training_cutoff
        self.model_version       = model_version
        self.validation_metrics  = validation_metrics
        self.feature_schema_hash = feature_schema_hash
        self.lifecycle_state     = lifecycle_state

    @property
    def reliability(self) -> float:
        """Shrinkage weight: 0 when n=0, approaches 1 as n → ∞."""
        return self.training_n / (self.training_n + SHRINKAGE_LAMBDA)

    def predict_alpha(self, candidate: dict) -> float | None:
        """Predict 90d alpha for a candidate. Accepts OH _q/_v/… or canonical q_score/… keys."""
        feat = candidate_learning_features(candidate)
        x = [feat.get(f) for f in FEATURES]
        if any(v is None for v in x):
            return None
        return float(np.dot(self.coef, x) + self.intercept)

    def score(self, candidate: dict) -> dict:
        """Return challenger scoring dict for one candidate.

        Keys:
          expected_alpha        float | None  — predicted 90d alpha vs SPY
          reliability           float         — shrinkage weight (0-1)
          learning_adjustment   float         — bounded score delta (±MAX_ADJUSTMENT)
          model_version         str
          active                bool          — False when training_n < MIN_TRAINING_N
        """
        active = (self.lifecycle_state == LIFECYCLE_PAPER_ACTIVE
                  and self.training_n >= MIN_TRAINING_N)
        pred = self.predict_alpha(candidate) if active else None

        if pred is None or not active:
            return {
                "expected_alpha": None,
                "reliability": self.reliability,
                "learning_adjustment": 0.0,
                "model_version": self.model_version,
                "active": False,
            }

        # Raw adjustment: excess alpha above training mean, converted to score points
        raw_adj = (pred - self.mean_alpha) * ALPHA_TO_SCORE_SCALE

        # Apply shrinkage and cap
        adj = self.reliability * raw_adj
        adj = float(np.clip(adj, -MAX_ADJUSTMENT, MAX_ADJUSTMENT))

        return {
            "expected_alpha": pred,
            "reliability": self.reliability,
            "learning_adjustment": adj,
            "model_version": self.model_version,
            "active": True,
        }

    def save(self) -> None:
        """Persist model to learning_models table (weights not included)."""
        self._write(json.dumps(self.validation_metrics))

    def save_with_weights(self) -> None:
        """Save model including coefficients inside validation_metrics JSON."""
        full_metrics = dict(self.validation_metrics)
        full_metrics["coef"] = self.coef.tolist()
        full_metrics["intercept"] = float(self.intercept)
        full_metrics["mean_alpha"] = float(self.mean_alpha)
        self._write(json.dumps(full_metrics))

    def _write(self, metrics_json: str) -> None:
        """INSERT-only write — model rows are immutable after creation (0344).

        Raises sqlite3.IntegrityError if model_version already exists; lifecycle
        state changes must go through promote() only.
        """
        import sqlite3 as _sqlite3
        vm = self.validation_metrics
        conn = agent_db._connect()
        try:
            import uuid as _uuid_mod
            _model_id = vm.get("model_id") or str(_uuid_mod.uuid4())
            conn.execute(
                """INSERT INTO learning_models
                   (model_version, training_cutoff, feature_schema_hash,
                    training_n, validation_metrics, created_at,
                    unique_tickers, unique_decision_dates, unique_weeks, raw_n,
                    lifecycle_state, training_horizon_version,
                    model_id, training_config_hash, code_commit_sha,
                    evidence_contract_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.model_version,
                    self.training_cutoff,
                    self.feature_schema_hash,
                    self.training_n,
                    metrics_json,
                    time.time(),
                    vm.get("unique_tickers"),
                    vm.get("unique_decision_dates"),
                    vm.get("unique_weeks"),
                    vm.get("raw_n"),
                    self.lifecycle_state,
                    vm.get("training_horizon_version", "calendar_v1"),  # 0369
                    _model_id,
                    vm.get("training_config_hash"),
                    vm.get("code_commit_sha"),
                    1,  # 0438: evidence_contract_version=1 for all new models
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def to_dict(self) -> dict:
        return {
            "coef": self.coef.tolist(),
            "intercept": self.intercept,
            "mean_alpha": self.mean_alpha,
            "training_n": self.training_n,
            "training_cutoff": self.training_cutoff,
            "model_version": self.model_version,
            "validation_metrics": self.validation_metrics,
            "feature_schema_hash": self.feature_schema_hash,
            "lifecycle_state": self.lifecycle_state,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChallengerModel":
        return cls(
            coef=d["coef"],
            intercept=d["intercept"],
            mean_alpha=d["mean_alpha"],
            training_n=d["training_n"],
            training_cutoff=d["training_cutoff"],
            model_version=d["model_version"],
            validation_metrics=d["validation_metrics"],
            feature_schema_hash=d["feature_schema_hash"],
            lifecycle_state=d.get("lifecycle_state", LIFECYCLE_TRAINED),
        )

    @classmethod
    def train(
        cls,
        ridge_alpha: float = RIDGE_ALPHA,
        horizon_version: str = "calendar_v1",
    ) -> "ChallengerModel | None":
        """Train on all labeled 3m episodes using decision-date cohort walk-forward (0334).

        horizon_version: 0369 — 'calendar_v1' (91d) or 'sessions_v2' (63 sessions).
        Rows from different versions are never mixed in one training run.
        Returns None if fewer than MIN_TRAINING_N rows are available.
        """
        conn = agent_db._connect()
        try:
            rows = conn.execute(
                """
                SELECT e.episode_id, e.captured_at, e.ticker,
                       e.q_score, e.v_score, e.pf_score, e.c_score, e.ec_score,
                       o.alpha
                FROM decision_episodes e
                JOIN episode_outcomes o ON e.episode_id = o.episode_id
                WHERE o.horizon = ? AND o.alpha IS NOT NULL
                  AND o.horizon_definition_version = ?
                  AND e.q_score IS NOT NULL AND e.v_score IS NOT NULL
                  AND e.pf_score IS NOT NULL AND e.c_score IS NOT NULL
                  AND e.ec_score IS NOT NULL
                ORDER BY e.captured_at ASC
                """,
                (HORIZON, horizon_version),
            ).fetchall()
        except Exception:
            # Older DB without horizon_definition_version column — fall back (backward compat)
            rows = conn.execute(
                f"""
                SELECT e.episode_id, e.captured_at, e.ticker,
                       e.q_score, e.v_score, e.pf_score, e.c_score, e.ec_score,
                       o.alpha
                FROM decision_episodes e
                JOIN episode_outcomes o ON e.episode_id = o.episode_id
                WHERE o.horizon = ? AND o.alpha IS NOT NULL
                  AND e.q_score IS NOT NULL AND e.v_score IS NOT NULL
                  AND e.pf_score IS NOT NULL AND e.c_score IS NOT NULL
                  AND e.ec_score IS NOT NULL
                ORDER BY e.captured_at ASC
                """,
                (HORIZON,),
            ).fetchall()
            horizon_version = "calendar_v1"
        conn.close()

        n = len(rows)
        if n < MIN_TRAINING_N:
            return None

        X = np.array([[r[f] for f in FEATURES] for r in rows], dtype=float)
        y = np.array([r["alpha"] for r in rows], dtype=float)
        training_cutoff = rows[-1]["captured_at"]

        # Unique sample-size metrics (0334)
        dates = [_episode_date(r["captured_at"]) for r in rows]
        tickers = [r["ticker"] for r in rows]
        unique_dates = sorted(set(dates))
        unique_weeks = len(set(_iso_week(d) for d in unique_dates))
        unique_tickers = len(set(tickers))

        # Decision-date cohort walk-forward cross-validation (0334/0414/0421)
        folds = _cv_walk_forward(X, y, dates, ridge_alpha, horizon_version=horizon_version)

        # Bootstrap uncertainty bands for expected alpha (0343)
        ci = _bootstrap_alpha_ci(folds)

        fold_maes      = [f["mae"] for f in folds]
        fold_baselines = [f["baseline_mae"] for f in folds]

        cv_mae_mean      = float(np.mean(fold_maes)) if fold_maes else None
        cv_mae_std       = float(np.std(fold_maes)) if len(fold_maes) > 1 else None
        baseline_mae_mean = float(np.mean(fold_baselines)) if fold_baselines else None
        beats_baseline   = (
            cv_mae_mean < baseline_mae_mean
            if (cv_mae_mean is not None and baseline_mae_mean is not None)
            else None
        )

        # Top-vs-bottom quintile alpha spread (aggregated across folds)
        q_spreads = [f["top_vs_bottom_quintile_alpha"]
                     for f in folds if f.get("top_vs_bottom_quintile_alpha") is not None]
        q_spread = float(np.mean(q_spreads)) if q_spreads else None

        # Directional stability: fraction of folds where each coef is positive
        coef_signs = [f["coef_signs"] for f in folds if "coef_signs" in f]
        if coef_signs:
            signs_arr = np.array(coef_signs, dtype=float)  # (n_folds, n_features)
            coef_positive_rate = (signs_arr > 0).mean(axis=0).tolist()
        else:
            coef_positive_rate = None

        # Refit on full data for the deployed model
        coef_full, intercept_full = _ridge_fit(X, y, ridge_alpha)

        feature_schema_hash = _schema_hash()
        # 0403: include horizon version in model ID to prevent collision between
        # models trained on different horizons against the same episode cutoff.
        # 0409: also include feature_schema_hash prefix so retrains after a schema
        # change with the same cutoff produce a distinct version key.
        # 0420: include training_config_hash prefix so retrains with different
        # hyperparameters (ridge_alpha, MAX_ADJUSTMENT, etc.) produce a distinct PK.
        _schema_short = (feature_schema_hash or "")[:8] or "nohash"
        _config_short = _training_config_hash(horizon_version, ridge_alpha)[:8]
        model_version = f"edge_{horizon_version}_{_schema_short}_{_config_short}_v{int(training_cutoff):010d}"

        val_metrics: dict = {
            "cv_folds":                 len(folds),
            "cv_mae_mean":              cv_mae_mean,
            "cv_mae_std":               cv_mae_std,
            "baseline_mae_mean":        baseline_mae_mean,
            "beats_baseline":           beats_baseline,
            "top_vs_bottom_quintile_alpha": q_spread,
            "coef_positive_rate":       coef_positive_rate,
            "unique_tickers":           unique_tickers,
            "unique_decision_dates":    len(unique_dates),
            "unique_weeks":             unique_weeks,
            "raw_n":                    n,
            # 0343/0347 — ranking-spread uncertainty bands (90% CI = 5th/95th percentile)
            "ranking_spread_ci_low":    ci["ranking_spread_ci_low"],
            "ranking_spread_ci_high":   ci["ranking_spread_ci_high"],
            "alpha_precision":          ci["alpha_precision"],
            "alpha_edge_evidence":      ci["alpha_edge_evidence"],
            # 0369 — version of horizon definition used for training data
            "training_horizon_version": horizon_version,
            # 0416 — immutable artifact identity
            "model_id": str(__import__("uuid").uuid4()),
            "training_config_hash": _training_config_hash(horizon_version, ridge_alpha),
            "code_commit_sha": _code_commit_sha(),
        }

        return cls(
            coef=coef_full.tolist(),
            intercept=float(intercept_full),
            mean_alpha=float(y.mean()),
            training_n=n,
            training_cutoff=str(training_cutoff),
            model_version=model_version,
            validation_metrics=val_metrics,
            feature_schema_hash=feature_schema_hash,
        )

    @classmethod
    def _from_row(cls, row) -> "ChallengerModel | None":
        """Construct from a learning_models DB row, or None if weights missing."""
        if not row:
            return None
        metrics = json.loads(row["validation_metrics"] or "{}")
        coef = metrics.get("coef")
        intercept = metrics.get("intercept")
        if coef is None:
            return None
        keys = row.keys() if hasattr(row, "keys") else []
        return cls(
            coef=coef,
            intercept=intercept,
            mean_alpha=metrics.get("mean_alpha", 0.0),
            training_n=row["training_n"] or 0,
            training_cutoff=row["training_cutoff"] or "",
            model_version=row["model_version"],
            validation_metrics=metrics,
            feature_schema_hash=row["feature_schema_hash"] or "",
            lifecycle_state=row["lifecycle_state"] if "lifecycle_state" in keys else LIFECYCLE_TRAINED,
        )

    @classmethod
    def load_paper_active(cls) -> "ChallengerModel | None":
        """Load the PAPER_ACTIVE model, independent of any newer TRAINED model (0344).

        This is the correct callsite for scoring.  Training a new model never
        shadows an active one because this query filters by lifecycle_state.
        """
        try:
            conn = agent_db._connect()
            row = conn.execute(
                "SELECT * FROM learning_models WHERE lifecycle_state=? ORDER BY created_at DESC LIMIT 1",
                (LIFECYCLE_PAPER_ACTIVE,),
            ).fetchone()
            conn.close()
            return cls._from_row(row)
        except Exception:
            return None

    @classmethod
    def load_latest_trained(cls) -> "ChallengerModel | None":
        """Load the most recently saved model regardless of lifecycle state.

        Use for admin/training workflows only.  Scoring must use load_paper_active().
        """
        try:
            conn = agent_db._connect()
            row = conn.execute(
                "SELECT * FROM learning_models ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            return cls._from_row(row)
        except Exception:
            return None

    @classmethod
    def load_latest(cls) -> "ChallengerModel | None":
        """Deprecated alias for load_latest_trained(). Use load_paper_active() for scoring."""
        return cls.load_latest_trained()


def _episode_date(captured_at: float) -> str:
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo("America/New_York")
    except Exception:
        from datetime import timedelta
        et_tz = timezone(timedelta(hours=-4))
    return datetime.fromtimestamp(captured_at, tz=et_tz).strftime("%Y-%m-%d")


def _iso_week(date_str: str) -> str:
    """Return YYYY-Www ISO week string."""
    d = _date.fromisoformat(date_str)
    iso = d.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def _bootstrap_alpha_ci(
    folds: list[dict],
    n_iter: int = 1000,
    rng_seed: int = 42,
) -> dict:
    """Bootstrap 5th/95th percentile CI over fold-level ranking-alpha spread (0343/0347).

    Metric: top_vs_bottom_quintile_alpha — the alpha spread between top and bottom
    quintile of the model's ranking.  This is *ranking power*, not individual expected
    alpha; the key names and dashboard labels use "ranking_spread" to make that clear.

    Returns ranking_spread_ci_low, ranking_spread_ci_high, alpha_precision
    (HIGH/MEDIUM/LOW by band width), and alpha_edge_evidence
    (POSITIVE/INCONCLUSIVE/NEGATIVE by whether CI crosses zero).
    INSUFFICIENT_DATA returned when < 2 folds have a spread value.
    """
    spreads = [f["top_vs_bottom_quintile_alpha"]
               for f in folds if f.get("top_vs_bottom_quintile_alpha") is not None]
    if len(spreads) < 2:
        return {
            "ranking_spread_ci_low":  None,
            "ranking_spread_ci_high": None,
            "alpha_precision":        "INSUFFICIENT_DATA",
            "alpha_edge_evidence":    "INSUFFICIENT_DATA",
        }

    rng = np.random.default_rng(rng_seed)
    arr = np.array(spreads)
    boot_means = [float(rng.choice(arr, size=len(arr), replace=True).mean())
                  for _ in range(n_iter)]
    ci_low  = float(np.percentile(boot_means, 5))
    ci_high = float(np.percentile(boot_means, 95))
    band_width = ci_high - ci_low

    # Precision: how tight the 90% interval is
    if band_width < ALPHA_CI_HIGH_THRESHOLD:
        precision = "HIGH"
    elif band_width < ALPHA_CI_MEDIUM_THRESHOLD:
        precision = "MEDIUM"
    else:
        precision = "LOW"

    # Edge evidence: does the CI exclude zero?
    if ci_low > 0:
        edge_evidence = "POSITIVE"
    elif ci_high < 0:
        edge_evidence = "NEGATIVE"
    else:
        edge_evidence = "INCONCLUSIVE"

    return {
        "ranking_spread_ci_low":  round(ci_low, 6),
        "ranking_spread_ci_high": round(ci_high, 6),
        "alpha_precision":        precision,
        "alpha_edge_evidence":    edge_evidence,
    }


def _cv_walk_forward(
    X: np.ndarray,
    y: np.ndarray,
    dates: list[str],
    ridge_alpha: float,
    horizon_version: str = "calendar_v1",
) -> list[dict]:
    """Decision-date cohort walk-forward cross-validation with embargo (0334/0414).

    For each cutoff date where train_n >= MIN_TRAINING_N, validates on the
    next available date that is at least one full horizon maturity period after
    the cutoff.  The embargo prevents return-window overlap between training
    and validation.  0414: embargo derived from maturity_date() so sessions_v2
    models use the exact same horizon clock as labeling and eligibility checks.

    Returns list of fold dicts: mae, baseline_mae, train_n, val_n, coef_signs,
    top_vs_bottom_quintile_alpha (None when val_n < 5).
    """
    from trade_engine.market_calendar import maturity_date as _mat_date

    unique_dates = sorted(set(dates))
    folds: list[dict] = []

    for cutoff_str in unique_dates:
        train_mask = np.array([d <= cutoff_str for d in dates])
        if int(train_mask.sum()) < MIN_TRAINING_N:
            continue

        # 0421: fail-closed — a calendar error must skip the fold, not relax the embargo
        try:
            embargo_end = _mat_date(cutoff_str, horizon_version, HORIZON)
        except Exception as _cal_err:
            import logging as _log
            _log.getLogger(__name__).error(
                "[calibration] maturity_date() failed for cutoff %s horizon %s: %s — skipping fold",
                cutoff_str, horizon_version, _cal_err,
            )
            continue  # skip this fold rather than weaken embargo
        val_dates_after = [d for d in unique_dates if d > embargo_end]
        if not val_dates_after:
            break

        first_val_date = val_dates_after[0]
        val_mask = np.array([d == first_val_date for d in dates])
        if not val_mask.any():
            continue

        X_train, y_train = X[train_mask], y[train_mask]
        X_val,   y_val   = X[val_mask],   y[val_mask]

        coef, intercept = _ridge_fit(X_train, y_train, ridge_alpha)
        mean_train = float(y_train.mean())

        y_pred    = X_val @ coef + intercept
        fold_mae  = float(np.abs(y_val - y_pred).mean())
        baseline_mae = float(np.abs(y_val - mean_train).mean())

        # Top-vs-bottom quintile alpha spread
        q_spread: float | None = None
        if len(y_val) >= 5:
            q_size = max(1, len(y_val) // 5)
            ranks = np.argsort(y_pred)
            top_alpha    = float(y_val[ranks[-q_size:]].mean())
            bottom_alpha = float(y_val[ranks[:q_size]].mean())
            q_spread = top_alpha - bottom_alpha

        folds.append({
            "cutoff": cutoff_str,
            "val_date": first_val_date,
            "train_n": int(train_mask.sum()),
            "val_n": int(val_mask.sum()),
            "mae": fold_mae,
            "baseline_mae": baseline_mae,
            "coef_signs": [int(np.sign(c)) for c in coef],
            "top_vs_bottom_quintile_alpha": q_spread,
        })

        if len(folds) >= MAX_CV_FOLDS:
            break

    return folds


def _ridge_fit(
    X: np.ndarray,
    y: np.ndarray,
    alpha: float,
) -> tuple[np.ndarray, float]:
    """Ridge regression via normal equations on zero-centered data.

    Returns (coef, intercept) where coef has shape (n_features,).
    """
    X_mean = X.mean(axis=0)
    y_mean = y.mean()
    Xc = X - X_mean
    yc = y - y_mean

    n_features = Xc.shape[1]
    A = Xc.T @ Xc + alpha * np.eye(n_features)
    b = Xc.T @ yc
    coef = np.linalg.solve(A, b)
    intercept = y_mean - X_mean @ coef
    return coef, intercept


def _schema_hash() -> str:
    return hashlib.md5("|".join(FEATURES).encode()).hexdigest()[:12]


def eligible_learning_cohorts(conn, model_version: str) -> frozenset:
    """Return cohort_ids with verified-complete sweep data (0430).

    COMPLETED status AND scored_candidates == expected_candidates.
    Pre-0424 cohorts with no ledger row are NOT included; callers decide legacy treatment.

    Non-overlap guarantee (0436): learning_sweep_runs has UNIQUE(model_version, cohort_id), so a
    cohort_id appears in exactly one of eligible_learning_cohorts or _ineligible_ledger_cohorts.
    """
    try:
        rows = conn.execute(
            """SELECT cohort_id FROM learning_sweep_runs
               WHERE model_version=? AND status='COMPLETED'
                 AND scored_candidates=expected_candidates""",
            (model_version,),
        ).fetchall()
        return frozenset(r["cohort_id"] for r in rows)
    except Exception:
        return frozenset()


def _ineligible_ledger_cohorts(conn, model_version: str) -> frozenset:
    """Return cohort_ids with a ledger row that is NOT verified-complete (0430).

    Includes: PARTIAL, FAILED, STARTED, and COMPLETED-but-count-mismatch rows.
    Pre-0424 cohorts with NO ledger row are NOT in this set — they are legacy.

    Non-overlap guarantee (0436): UNIQUE(model_version, cohort_id) on learning_sweep_runs ensures
    no cohort_id appears in both this set and eligible_learning_cohorts() simultaneously.
    """
    try:
        rows = conn.execute(
            """SELECT DISTINCT cohort_id FROM learning_sweep_runs
               WHERE model_version=?
                 AND NOT (status='COMPLETED' AND scored_candidates=expected_candidates)""",
            (model_version,),
        ).fetchall()
        return frozenset(r["cohort_id"] for r in rows)
    except Exception:
        return frozenset()


def _summarize_row_subset(rows: list) -> dict:
    """Minimal prospective summary including base-vs-challenger decision edge (0427/0433)."""
    n = len(rows)
    if n < 3:
        return {"n": n, "insufficient_data": True}
    outcomes = [float(r["outcome_alpha_90d"]) for r in rows]
    ch_scores = [float(r["challenger_score"]) for r in rows]
    selected = [r for r in rows if r["would_select"]]
    not_selected = [r for r in rows if not r["would_select"]]
    sel_mean = (sum(float(r["outcome_alpha_90d"]) for r in selected) / len(selected)) if selected else None
    not_mean = (sum(float(r["outcome_alpha_90d"]) for r in not_selected) / len(not_selected)) if not_selected else None
    spread = (sel_mean - not_mean) if sel_mean is not None and not_mean is not None else None
    q_size = max(1, n // 5)
    sorted_ch = sorted(zip(ch_scores, outcomes), key=lambda x: x[0])
    ranking_spread = (sum(o for _, o in sorted_ch[-q_size:]) / q_size
                      - sum(o for _, o in sorted_ch[:q_size]) / q_size)

    # 0433: per-cohort base-vs-challenger decision edge
    from collections import defaultdict as _dd
    cmap: dict = _dd(list)
    for r in rows:
        cid = r["decision_cohort_id"]
        if cid is not None:
            cmap[cid].append(r)

    divergent_cohorts = 0
    wins = losses = ties = 0
    ch_top1_alphas: list = []
    base_top1_alphas: list = []
    divergent_deltas: list = []  # 0437: (ch_out - base_out) for divergent cohorts only
    for crow in cmap.values():
        ch_r = [r for r in crow if r["would_select"]]
        base_r = [r for r in crow if r["base_would_select"] is not None and int(r["base_would_select"])]
        if not ch_r or not base_r:
            continue
        ch_ep = ch_r[0]["episode_id"]
        base_ep = base_r[0]["episode_id"]
        ch_out = float(ch_r[0]["outcome_alpha_90d"])
        base_out = float(base_r[0]["outcome_alpha_90d"])
        ch_top1_alphas.append(ch_out)
        base_top1_alphas.append(base_out)
        if ch_ep != base_ep:
            divergent_cohorts += 1
            divergent_deltas.append(ch_out - base_out)
            if ch_out > base_out:
                wins += 1
            elif ch_out < base_out:
                losses += 1
            else:
                ties += 1

    ch_top1_mean = (sum(ch_top1_alphas) / len(ch_top1_alphas)) if ch_top1_alphas else None
    base_top1_mean = (sum(base_top1_alphas) / len(base_top1_alphas)) if base_top1_alphas else None
    all_cohort_incremental_edge = (
        round(ch_top1_mean - base_top1_mean, 6)
        if ch_top1_mean is not None and base_top1_mean is not None else None
    )

    # 0437: divergent-only metrics (cohorts where challenger and base chose different episodes)
    total_with_both = len(ch_top1_alphas)
    divergent_only_mean_edge = (
        round(sum(divergent_deltas) / len(divergent_deltas), 6) if divergent_deltas else None
    )
    _sorted_div = sorted(divergent_deltas)
    if _sorted_div:
        _m = len(_sorted_div)
        divergent_only_median_edge = round(
            (_sorted_div[_m // 2] if _m % 2 else (_sorted_div[_m // 2 - 1] + _sorted_div[_m // 2]) / 2),
            6,
        )
    else:
        divergent_only_median_edge = None
    divergent_win_rate = round(wins / divergent_cohorts, 6) if divergent_cohorts > 0 else None
    divergence_rate = (
        round(divergent_cohorts / total_with_both, 6) if total_with_both > 0 else None
    )

    return {
        "n": n,
        "mean_alpha": round(sum(outcomes) / n, 6),
        "selection_alpha_spread": round(spread, 6) if spread is not None else None,
        "ranking_spread": round(ranking_spread, 6),
        # 0433: base-vs-challenger decision edge within this population stratum
        "divergent_cohorts": divergent_cohorts,
        "challenger_top1_mean_alpha": round(ch_top1_mean, 6) if ch_top1_mean is not None else None,
        "base_top1_mean_alpha": round(base_top1_mean, 6) if base_top1_mean is not None else None,
        "all_cohort_incremental_edge": all_cohort_incremental_edge,
        # 0437: divergent-only edge (cohorts where challenger/base picked different episodes)
        "divergent_only_mean_edge": divergent_only_mean_edge,
        "divergent_only_median_edge": divergent_only_median_edge,
        "divergent_win_rate": divergent_win_rate,
        "divergence_rate": divergence_rate,
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }


def _build_stratified_metrics(rows: list, eligible_ids: set, ineligible_ids: set) -> dict:
    """Stratified prospective metrics by base_recommendation_eligible (0427).

    eligible_ids: cohort_ids where base_recommendation_eligible=1 (base would have acted)
    ineligible_ids: cohort_ids where base_recommendation_eligible=0 (base would not have acted)
    """
    if not eligible_ids and not ineligible_ids:
        return {}
    known_rows = [r for r in rows if r["decision_cohort_id"] is not None]
    eligible_rows = [r for r in known_rows if r["decision_cohort_id"] in eligible_ids]
    ineligible_rows = [r for r in known_rows if r["decision_cohort_id"] in ineligible_ids]
    e_ids = {r["decision_cohort_id"] for r in eligible_rows}
    i_ids = {r["decision_cohort_id"] for r in ineligible_rows}
    return {
        "eligible_sweeps": _summarize_row_subset(eligible_rows),
        "ineligible_sweeps": _summarize_row_subset(ineligible_rows),
        "eligible_cohort_count": len(e_ids),
        "ineligible_cohort_count": len(i_ids),
    }


def _training_config_hash(horizon_version: str, ridge_alpha: float) -> str:
    """0416/0428: Hash all model-affecting constants so different configs produce different keys."""
    parts = [
        f"features={','.join(FEATURES)}",
        f"ridge_alpha={ridge_alpha}",
        f"max_adj={MAX_ADJUSTMENT}",
        f"alpha_scale={ALPHA_TO_SCORE_SCALE}",
        f"shrinkage_lambda={SHRINKAGE_LAMBDA}",
        f"min_training_n={MIN_TRAINING_N}",
        f"horizon_version={horizon_version}",
        f"horizon_label={HORIZON}",
        f"feature_schema_ver={FEATURE_SCHEMA_VER}",
        f"algorithm_version={TRAINING_ALGORITHM_VERSION}",
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


def _code_commit_sha() -> str | None:
    """0416: Best-effort git commit SHA at train time."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return None


def train_and_save(horizon_version: str = LEARNING_TARGET_HORIZON) -> dict:
    """Train a new model (lifecycle_state=TRAINED). Promotion requires separate promote() call.

    horizon_version: the horizon label version to train on (0379). Defaults to
        LEARNING_TARGET_HORIZON so the scheduled trainer uses the configured target.
    Raises DataHealthBlockError when compute_data_health() returns overall='block'. (0376)
    """
    conn = agent_db._connect()
    try:
        health = compute_data_health(conn, target_horizon_version=horizon_version)
    finally:
        conn.close()
    if health["overall"] == "block":
        blocking = [k for k, v in health["metrics"].items()
                    if isinstance(v, dict) and v.get("status") == "block"]
        raise DataHealthBlockError(
            f"Data health check blocked training: {blocking}"
        )

    model = ChallengerModel.train(horizon_version=horizon_version)
    if model is None:
        return {
            "trained": False,
            "reason": f"fewer than {MIN_TRAINING_N} labeled 90d episodes",
        }
    model.save_with_weights()
    vm = model.validation_metrics
    return {
        "trained": True,
        "lifecycle_state": LIFECYCLE_TRAINED,
        "model_version": model.model_version,
        "training_n": model.training_n,
        "reliability": model.reliability,
        "validation_metrics": vm,
        "unique_tickers": vm.get("unique_tickers"),
        "unique_decision_dates": vm.get("unique_decision_dates"),
        "unique_weeks": vm.get("unique_weeks"),
        "cv_folds": vm.get("cv_folds"),
        "beats_baseline": vm.get("beats_baseline"),
    }


def _check_promotion_gates(model_version: str, target_state: str) -> dict:
    """Evaluate promotion gate checklist, branched by target_state (0348/0355).

    TRAINED → OBSERVE: data sufficiency + ≥3 CV folds + edge not NEGATIVE
    OBSERVE → PAPER_ACTIVE: all TRAINED→OBSERVE gates + min elapsed days + fresh episodes

    Returns dict with keys:
      passed  — bool
      failed  — list of gate names that did not pass
      gates   — rich dict: {gate: {value, minimum|expected, pass}}
      vm      — raw validation_metrics dict for snapshot building
    """
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT * FROM learning_models WHERE model_version=?", (model_version,)
    ).fetchone()
    if not row:
        conn.close()
        return {"passed": False, "failed": ["model_not_found"], "gates": {}, "vm": {}}

    vm = json.loads(row["validation_metrics"] or "{}")
    ut  = row["unique_tickers"] or vm.get("unique_tickers") or 0
    ud  = row["unique_decision_dates"] or vm.get("unique_decision_dates") or 0
    uw  = row["unique_weeks"] or vm.get("unique_weeks") or 0
    cf  = vm.get("cv_folds") or 0
    bb  = vm.get("beats_baseline")
    edge = vm.get("alpha_edge_evidence")

    # Base gates — shared by TRAINED→OBSERVE and OBSERVE→PAPER_ACTIVE
    gates: dict[str, dict] = {
        "unique_tickers": {
            "value": ut, "minimum": PROMOTE_MIN_UNIQUE_TICKERS,
            "pass": ut >= PROMOTE_MIN_UNIQUE_TICKERS,
        },
        "unique_decision_dates": {
            "value": ud, "minimum": PROMOTE_MIN_UNIQUE_DECISION_DATES,
            "pass": ud >= PROMOTE_MIN_UNIQUE_DECISION_DATES,
        },
        "unique_weeks": {
            "value": uw, "minimum": PROMOTE_MIN_UNIQUE_WEEKS,
            "pass": uw >= PROMOTE_MIN_UNIQUE_WEEKS,
        },
        "has_cv_folds": {
            "value": cf, "minimum": PROMOTE_MIN_CV_FOLDS,
            "pass": cf >= PROMOTE_MIN_CV_FOLDS,
        },
        "beats_baseline": {
            "value": bb, "expected": True,
            "pass": bb is True,
        },
        "edge_not_negative": {
            "value": edge, "expected": "not NEGATIVE",
            "pass": edge != "NEGATIVE",
        },
    }

    # OBSERVE → PAPER_ACTIVE: additional time-in-OBSERVE and fresh-episode gates
    if target_state == LIFECYCLE_PAPER_ACTIVE:
        observe_log = conn.execute(
            """SELECT promoted_at FROM model_promotion_log
               WHERE model_version=? AND to_state=?
               ORDER BY promoted_at DESC LIMIT 1""",
            (model_version, LIFECYCLE_OBSERVE),
        ).fetchone()
        promoted_to_observe_at = float(observe_log["promoted_at"]) if observe_log else None

        elapsed_days: float | None = None
        if promoted_to_observe_at is not None:
            elapsed_days = (time.time() - promoted_to_observe_at) / 86400.0

        fresh_episodes: int = 0
        if promoted_to_observe_at is not None:
            fresh_row = conn.execute(
                "SELECT COUNT(*) as n FROM decision_episodes WHERE captured_at > ?",
                (promoted_to_observe_at,),
            ).fetchone()
            fresh_episodes = int(fresh_row["n"]) if fresh_row else 0

        gates["observe_elapsed_days"] = {
            "value": round(elapsed_days, 1) if elapsed_days is not None else None,
            "minimum": OBSERVE_MIN_DAYS,
            "pass": (elapsed_days is not None and elapsed_days >= OBSERVE_MIN_DAYS),
        }
        gates["fresh_episodes_since_observe"] = {
            "value": fresh_episodes,
            "minimum": OBSERVE_MIN_FRESH_EPISODES,
            "pass": fresh_episodes >= OBSERVE_MIN_FRESH_EPISODES,
        }
        # 0360/0365/0429: prospective evidence gates — filter out PARTIAL/FAILED ledger cohorts
        pm = compute_prospective_metrics(model_version, conn, filter_partial_ledger=True)
        prospective_n = int(pm.get("prospective_n", 0))
        prospective_selected_n = int(pm.get("prospective_selected_n", 0))
        ranking_spread = pm.get("prospective_ranking_spread")
        pred_mae = pm.get("prediction_mae")
        base_mae = pm.get("baseline_mae")
        obs_edge = pm.get("prospective_edge_evidence", "")
        incremental_spread = pm.get("incremental_ranking_spread")
        n_cohort_days = pm.get("n_cohort_days", 0)

        gates["mature_observations"] = {
            "value": prospective_n,
            "minimum": OBSERVE_MIN_MATURE_OBS,
            "pass": prospective_n >= OBSERVE_MIN_MATURE_OBS,
        }
        gates["prospective_selected_n"] = {
            "value": prospective_selected_n,
            "minimum": OBSERVE_MIN_MATURE_OBS,
            "pass": prospective_selected_n >= OBSERVE_MIN_MATURE_OBS,
        }
        gates["prospective_ranking_spread"] = {
            "value": ranking_spread,
            "expected": "> 0",
            "pass": ranking_spread is not None and ranking_spread > 0,
        }
        gates["prediction_mae_vs_baseline"] = {
            "value": pred_mae,
            "expected": f"<= baseline ({base_mae})",
            "pass": pred_mae is not None and base_mae is not None and pred_mae <= base_mae,
        }
        # Positive or inconclusive prospective edge required; NEGATIVE blocks promotion
        gates["prospective_edge_not_negative"] = {
            "value": obs_edge,
            "expected": "POSITIVE or INCONCLUSIVE",
            "pass": obs_edge not in ("NEGATIVE", "") and obs_edge is not None,
        }
        # 0375/0381: challenger must not degrade base-strategy ranking
        # NOT_EVALUABLE when incremental_spread is None (no base_score data)
        if incremental_spread is None:
            _ir = GATE_NOT_EVALUABLE
        elif incremental_spread >= 0:
            _ir = GATE_PASS
        else:
            _ir = GATE_FAIL
        gates["incremental_ranking_non_negative"] = {
            "value": incremental_spread,
            "expected": ">= 0",
            "result": _ir,
            "pass": _ir == GATE_PASS,
        }
        # 0378/0381: require cohort day diversity
        # NOT_EVALUABLE when n_cohort_days == 0 (no scored_at_date populated)
        if n_cohort_days == 0:
            _cd = GATE_NOT_EVALUABLE
        elif n_cohort_days >= OBSERVE_MIN_COHORT_DAYS:
            _cd = GATE_PASS
        else:
            _cd = GATE_FAIL
        gates["cohort_day_diversity"] = {
            "value": n_cohort_days,
            "minimum": OBSERVE_MIN_COHORT_DAYS,
            "result": _cd,
            "pass": _cd == GATE_PASS,
        }

        # 0380: data health must not be in block state for the model's training horizon
        thv_for_health = (row["training_horizon_version"]
                          if "training_horizon_version" in row.keys() else None) or "calendar_v1"
        health = compute_data_health(conn, target_horizon_version=thv_for_health)
        _dh = GATE_PASS if health["overall"] != "block" else GATE_FAIL
        gates["data_health_block"] = {
            "value": health["overall"],
            "expected": "ok or warn",
            "result": _dh,
            "pass": _dh == GATE_PASS,
        }

    conn.close()
    failed = [k for k, v in gates.items() if not v["pass"]]
    return {"passed": len(failed) == 0, "failed": failed, "gates": gates, "vm": vm}


def promote(
    model_version: str,
    target_state: str,
    force: bool = False,
    promoted_by: str = "manual",
    promotion_reason: str = "",
    override_reason: str = "",
) -> dict:
    """Advance lifecycle_state with gate validation (0335/0342/0344/0348).

    target_state: OBSERVE | PAPER_ACTIVE | RETIRED
    force=True: only allowed for → RETIRED transitions (0348).  For any other
        target, pass a non-empty override_reason instead; gates_bypassed=True
        will be stored in the snapshot.
    promoted_by: identifier for who/what triggered the promotion (0342).
    promotion_reason: free-text note captured at promotion time (0342).
    override_reason: required when bypassing gates for non-RETIRED targets.
    Returns {"promoted": bool, "new_state": str, "gates": dict}.
    """
    # 0348: restrict force to RETIRED only
    if force and target_state != LIFECYCLE_RETIRED:
        raise ValueError(
            f"force=True is only allowed for → RETIRED transitions; "
            f"got target_state={target_state!r}. "
            f"Pass a non-empty override_reason to bypass gates instead."
        )

    valid_transitions = {
        LIFECYCLE_TRAINED:      (LIFECYCLE_OBSERVE,),
        LIFECYCLE_OBSERVE:      (LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_RETIRED),
        LIFECYCLE_PAPER_ACTIVE: (LIFECYCLE_RETIRED,),
        LIFECYCLE_SUSPENDED:    (LIFECYCLE_OBSERVE,),  # 0371: re-enter observation after suspension
    }

    conn = agent_db._connect()
    row = conn.execute(
        "SELECT lifecycle_state FROM learning_models WHERE model_version=?",
        (model_version,),
    ).fetchone()
    if not row:
        conn.close()
        return {"promoted": False, "error": "model_not_found", "gates": {}}

    current = row["lifecycle_state"] or LIFECYCLE_TRAINED
    allowed = valid_transitions.get(current, ())
    if target_state not in allowed:
        conn.close()
        return {
            "promoted": False,
            "error": f"invalid transition {current} → {target_state}",
            "gates": {},
        }

    gates_bypassed = False
    if force or target_state == LIFECYCLE_RETIRED:
        gate_result = {"gates": {}, "vm": {}, "passed": True, "failed": []}
        gates_bypassed = bool(force)
    elif override_reason:
        # Explicit gate bypass with auditable reason (0348)
        gate_result = _check_promotion_gates(model_version, target_state)
        gates_bypassed = True
    else:
        gate_result = _check_promotion_gates(model_version, target_state)
        if not gate_result["passed"]:
            conn.close()
            return {
                "promoted": False,
                "error": "gate_check_failed",
                "failed_gates": gate_result["failed"],
                "gates": gate_result["gates"],
            }

    # 0348: build rich snapshot with actual metric values, thresholds, and pass/fail
    vm = gate_result.get("vm", {})
    snapshot: dict = {
        "gates_bypassed": gates_bypassed,
    }
    if override_reason:
        snapshot["override_reason"] = override_reason
    for gate_name, gate_info in gate_result.get("gates", {}).items():
        snapshot[gate_name] = gate_info
    # Supplement with raw model metrics for full audit trail
    for key in ("cv_mae_mean", "baseline_mae_mean", "ranking_spread_ci_low",
                "ranking_spread_ci_high", "alpha_precision", "alpha_edge_evidence"):
        if key in vm:
            snapshot[key] = {"value": vm[key]}

    # 0344: auto-retire any existing PAPER_ACTIVE before activating a new one
    if target_state == LIFECYCLE_PAPER_ACTIVE:
        existing_active = conn.execute(
            "SELECT model_version FROM learning_models WHERE lifecycle_state=? AND model_version!=?",
            (LIFECYCLE_PAPER_ACTIVE, model_version),
        ).fetchall()
        for ea in existing_active:
            conn.execute(
                "UPDATE learning_models SET lifecycle_state=? WHERE model_version=?",
                (LIFECYCLE_RETIRED, ea["model_version"]),
            )
            conn.execute(
                """INSERT INTO model_promotion_log
                   (model_version, from_state, to_state, promoted_by, promoted_at,
                    promotion_reason, promotion_metrics_snapshot)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    ea["model_version"], LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_RETIRED,
                    "auto_retire", time.time(),
                    f"Auto-retired when {model_version} promoted to PAPER_ACTIVE",
                    json.dumps({"gates_bypassed": False}),
                ),
            )

    conn.execute(
        "UPDATE learning_models SET lifecycle_state=?, promotion_gates_json=? WHERE model_version=?",
        (target_state, json.dumps(snapshot), model_version),
    )
    # 0342: write promotion log row with full metrics snapshot
    conn.execute(
        """INSERT INTO model_promotion_log
           (model_version, from_state, to_state, promoted_by, promoted_at,
            promotion_reason, promotion_metrics_snapshot)
           VALUES (?,?,?,?,?,?,?)""",
        (
            model_version, current, target_state, promoted_by,
            time.time(), promotion_reason,
            json.dumps(snapshot),
        ),
    )
    conn.commit()
    conn.close()
    return {"promoted": True, "new_state": target_state, "gates": gate_result.get("gates", {})}


def compute_prospective_metrics(model_version: str, conn, *, filter_partial_ledger: bool = False) -> dict:
    """Compute out-of-sample ranking metrics from labeled model_observations (0365).

    Returns a dict with selection_alpha_spread, prediction_mae, baseline_mae,
    prospective_ranking_spread, and prospective_edge_evidence derived purely from
    model_observations (not from retrospective CV metrics).
    Returns {} when fewer than 5 labeled observations exist.

    0373: filters by target_horizon_version matching the model's training_horizon_version.
    0375: adds base_ranking_spread, challenger_ranking_spread, incremental_ranking_spread,
          selection_alpha_delta.
    0378: uses per-row baseline_predicted_alpha for baseline_mae; tracks n_cohort_days.
    0427: adds stratified_metrics — eligible vs ineligible sweeps by base_recommendation_eligible.
    0429: filter_partial_ledger=True excludes cohorts with PARTIAL/FAILED ledger status from all
          gate-relevant counts; pre-0424 cohorts with no ledger row are kept (legacy treatment).
    """
    import math

    # 0373: look up training_horizon_version to filter observations by version
    mv_row = conn.execute(
        "SELECT training_horizon_version FROM learning_models WHERE model_version=?",
        (model_version,),
    ).fetchone()
    thv = ((mv_row["training_horizon_version"] if mv_row else None) or "calendar_v1")

    # 0403: strict horizon isolation — for sessions_v2 and newer versions, exclude legacy
    # NULL target rows whose horizon is ambiguous; keep NULL fallback only for calendar_v1
    if thv == "calendar_v1":
        rows = conn.execute(
            """SELECT episode_id, ticker, challenger_score, base_score, predicted_alpha, would_select,
                      outcome_alpha_90d, baseline_predicted_alpha, scored_at_date,
                      prediction_timestamp, decision_cohort_id, base_would_select
               FROM model_observations
               WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                 AND (target_horizon_version=? OR target_horizon_version IS NULL)""",
            (model_version, thv),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT episode_id, ticker, challenger_score, base_score, predicted_alpha, would_select,
                      outcome_alpha_90d, baseline_predicted_alpha, scored_at_date,
                      prediction_timestamp, decision_cohort_id, base_would_select
               FROM model_observations
               WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                 AND target_horizon_version=?""",
            (model_version, thv),
        ).fetchall()
    # 0430: use centralized eligible/ineligible helpers for consistent gate quality
    _inelig_cids = _ineligible_ledger_cohorts(conn, model_version)
    _elig_cids = eligible_learning_cohorts(conn, model_version)
    _ineligible_cohorts_ledger = len(_inelig_cids)

    # 0432/0438: modern models must have COMPLETED ledger rows (no legacy unledgered cohorts)
    _mv_created_at: float | None = None
    _ev_ver: int | None = None
    try:
        _mcr = conn.execute(
            "SELECT created_at, evidence_contract_version FROM learning_models WHERE model_version=?",
            (model_version,),
        ).fetchone()
        _mv_created_at = float(_mcr["created_at"]) if _mcr else None
        _ev_ver_raw = _mcr["evidence_contract_version"] if _mcr else None
        _ev_ver = int(_ev_ver_raw) if _ev_ver_raw is not None else None
    except Exception:
        pass
    # 0438: prefer evidence_contract_version>=1; ev=0 or NULL falls back to timestamp
    _is_modern_model = (
        (_ev_ver >= 1)
        if _ev_ver
        else (_mv_created_at is not None and _mv_created_at > LEDGER_ROLLOUT_CUTOFF)
    )

    # 0427: build cohort eligibility map for stratified metrics
    _eligible_cohort_ids: set = set()
    _ineligible_eligibility_ids: set = set()
    try:
        _led_rows = conn.execute(
            """SELECT cohort_id, base_recommendation_eligible FROM learning_sweep_runs
               WHERE model_version=? AND status='COMPLETED'
                 AND base_recommendation_eligible IS NOT NULL""",
            (model_version,),
        ).fetchall()
        for _lr in _led_rows:
            if _lr["base_recommendation_eligible"] == 1:
                _eligible_cohort_ids.add(_lr["cohort_id"])
            else:
                _ineligible_eligibility_ids.add(_lr["cohort_id"])
    except Exception:
        pass

    # 0430/0432: exclude ineligible cohorts; modern models also exclude legacy-unledgered
    if filter_partial_ledger:
        if _is_modern_model:
            # 0432: modern models — only verified-complete cohorts (no legacy unledgered)
            rows = [r for r in rows if r["decision_cohort_id"] in _elig_cids]
        elif _inelig_cids:
            # Legacy model — exclude known-bad, allow pre-0424 unledgered
            rows = [r for r in rows if r["decision_cohort_id"] not in _inelig_cids]

    if len(rows) < 5:
        return {
            "ineligible_cohorts_ledger": _ineligible_cohorts_ledger,
            "stratified_metrics": {},
            "population_label": "complete_ledger" if filter_partial_ledger else "all",
        }

    outcomes = [float(r["outcome_alpha_90d"]) for r in rows]
    ch_scores = [float(r["challenger_score"]) for r in rows]
    pred_alphas = [float(r["predicted_alpha"]) if r["predicted_alpha"] is not None else None
                   for r in rows]
    selected = [r for r in rows if r["would_select"]]
    not_selected = [r for r in rows if not r["would_select"]]
    n = len(rows)

    mean_alpha = sum(outcomes) / n

    # 0378: per-row baseline from baseline_predicted_alpha (training-time mean), not hindsight mean
    rows_with_baseline = [(float(r["baseline_predicted_alpha"]), float(r["outcome_alpha_90d"]))
                          for r in rows if r["baseline_predicted_alpha"] is not None]
    if rows_with_baseline:
        baseline_mae = sum(abs(b - o) for b, o in rows_with_baseline) / len(rows_with_baseline)
    else:
        baseline_mae = sum(abs(mean_alpha - o) for o in outcomes) / n

    # MAE: predicted_alpha vs actual; fall back to challenger_score if unavailable
    valid_preds = [(p, o) for p, o in zip(pred_alphas, outcomes) if p is not None]
    if valid_preds:
        prediction_mae = sum(abs(p - o) for p, o in valid_preds) / len(valid_preds)
    else:
        prediction_mae = sum(abs(s - o) for s, o in zip(ch_scores, outcomes)) / n

    scores = ch_scores
    sel_mean = (sum(float(r["outcome_alpha_90d"]) for r in selected) / len(selected)) if selected else None
    not_mean = (sum(float(r["outcome_alpha_90d"]) for r in not_selected) / len(not_selected)) if not_selected else None
    spread = (sel_mean - not_mean) if sel_mean is not None and not_mean is not None else None

    # Challenger quintile ranking spread
    sorted_ch = sorted(zip(scores, outcomes), key=lambda x: x[0])
    q_size = max(1, n // 5)
    ch_bottom_mean = sum(o for _, o in sorted_ch[:q_size]) / q_size
    ch_top_mean = sum(o for _, o in sorted_ch[-q_size:]) / q_size
    challenger_ranking_spread = ch_top_mean - ch_bottom_mean

    # 0375: Base ranking spread and incremental edge
    base_scores_raw = [r["base_score"] for r in rows]
    base_scores = [float(b) for b in base_scores_raw if b is not None]
    base_ranking_spread: float | None = None
    incremental_ranking_spread: float | None = None
    selection_alpha_delta: float | None = None

    if len(base_scores) == n:  # all rows have base_score populated
        sorted_base = sorted(zip([float(b) for b in base_scores_raw], outcomes), key=lambda x: x[0])
        base_bottom_mean = sum(o for _, o in sorted_base[:q_size]) / q_size
        base_top_mean = sum(o for _, o in sorted_base[-q_size:]) / q_size
        base_ranking_spread = base_top_mean - base_bottom_mean
        incremental_ranking_spread = challenger_ranking_spread - base_ranking_spread
        if sel_mean is not None:
            selection_alpha_delta = sel_mean - base_top_mean

    # 0382/0388: cohort-matched selection delta — divergence by episode identity, not outcome equality
    # After 0386, both base and challenger select exactly top-1 per cohort.
    selection_alpha_delta_legacy = selection_alpha_delta  # preserve global-quintile value
    n_divergent_cohorts = 0
    challenger_wins = 0
    base_wins = 0
    ties = 0
    cohort_deltas: list = []
    cohort_delta_weeks: list = []  # parallel: ISO week label per divergent cohort (0408)
    # 0402: initialize before cohort block so return dict is always valid
    selection_delta_ci_low: float | None = None
    selection_delta_ci_high: float | None = None
    selection_delta_evidence: str | None = None
    median_selection_delta: float | None = None
    # 0408: block bootstrap CI (clustered by decision week)
    selection_delta_ci_low_short_block: float | None = None
    selection_delta_ci_high_short_block: float | None = None
    selection_delta_evidence_short_block: str | None = None

    rows_with_cohort = [r for r in rows if r["decision_cohort_id"] is not None]
    if rows_with_cohort:
        from collections import defaultdict
        cohort_map: dict = defaultdict(list)
        for r in rows_with_cohort:
            cohort_map[r["decision_cohort_id"]].append(r)
        cohort_deltas = []
        cohort_delta_weeks = []
        for cohort_rows in cohort_map.values():
            ch_rows = [r for r in cohort_rows if r["would_select"]]
            base_rows = [r for r in cohort_rows
                         if r["base_would_select"] is not None and int(r["base_would_select"])]
            if not ch_rows or not base_rows:
                continue
            ch_row = ch_rows[0]
            base_row = base_rows[0]
            ch_outcome = float(ch_row["outcome_alpha_90d"])
            base_outcome = float(base_row["outcome_alpha_90d"])
            # 0388: divergence = different episode identity
            # 0400: only accumulate delta for divergent cohorts — same-choice cohorts
            # contribute delta=0 and dilute the mean edge without adding signal
            ch_ep = ch_row["episode_id"]
            base_ep = base_row["episode_id"]
            delta = ch_outcome - base_outcome
            if ch_ep != base_ep:
                n_divergent_cohorts += 1
                cohort_deltas.append(delta)
                # 0408: track ISO week of each divergent cohort for block bootstrap
                _sdate = ch_row["scored_at_date"] or ""
                if _sdate and len(_sdate) >= 10:
                    try:
                        from datetime import date as _ddate
                        _week = _ddate.fromisoformat(_sdate[:10]).isocalendar()[:2]  # (year, week)
                        cohort_delta_weeks.append(f"{_week[0]}-W{_week[1]:02d}")
                    except Exception:
                        cohort_delta_weeks.append("unknown")
                else:
                    cohort_delta_weeks.append("unknown")
                if delta > 0:
                    challenger_wins += 1
                elif delta < 0:
                    base_wins += 1
                else:
                    ties += 1
        # 0402: IID bootstrap 90% CI and median over divergent cohort deltas
        if cohort_deltas:
            selection_alpha_delta = sum(cohort_deltas) / len(cohort_deltas)
            sorted_d = sorted(cohort_deltas)
            nd = len(sorted_d)
            median_selection_delta = (sorted_d[nd // 2] if nd % 2 == 1
                                      else (sorted_d[nd // 2 - 1] + sorted_d[nd // 2]) / 2)
            if nd >= 2:
                rng_d = np.random.default_rng(42)
                arr_d = np.array(cohort_deltas)
                boot_d = [float(rng_d.choice(arr_d, size=nd, replace=True).mean())
                          for _ in range(2000)]
                selection_delta_ci_low = round(float(np.percentile(boot_d, 5)), 6)
                selection_delta_ci_high = round(float(np.percentile(boot_d, 95)), 6)
                if selection_delta_ci_low > 0:
                    selection_delta_evidence = "POSITIVE"
                elif selection_delta_ci_high < 0:
                    selection_delta_evidence = "NEGATIVE"
                else:
                    selection_delta_evidence = "INCONCLUSIVE"

            # 0408: block bootstrap — resample by ISO week to account for overlapping 63-session
            # return windows (consecutive daily cohorts share almost all of their outcome period).
            # Requires >= 4 distinct decision weeks; otherwise the clustering has too few groups.
            if cohort_delta_weeks and len(set(cohort_delta_weeks)) >= 4:
                from collections import defaultdict as _dd2
                week_buckets: dict = _dd2(list)
                for d, w in zip(cohort_deltas, cohort_delta_weeks):
                    week_buckets[w].append(d)
                week_means = [float(np.mean(v)) for v in week_buckets.values()]
                nw = len(week_means)
                rng_b = np.random.default_rng(43)
                arr_w = np.array(week_means)
                # Resample whole weeks; each resample mean approximates the overall mean
                boot_b = [float(rng_b.choice(arr_w, size=nw, replace=True).mean())
                          for _ in range(2000)]
                selection_delta_ci_low_short_block = round(float(np.percentile(boot_b, 5)), 6)
                selection_delta_ci_high_short_block = round(float(np.percentile(boot_b, 95)), 6)
                if selection_delta_ci_low_short_block > 0:
                    selection_delta_evidence_short_block = "POSITIVE"
                elif selection_delta_ci_high_short_block < 0:
                    selection_delta_evidence_short_block = "NEGATIVE"
                else:
                    selection_delta_evidence_short_block = "INCONCLUSIVE"

    # Pearson correlation (challenger_score vs outcome)
    corr: float | None = None
    if n >= 2:
        mean_s = sum(scores) / n
        mean_o = mean_alpha
        cov = sum((s - mean_s) * (o - mean_o) for s, o in zip(scores, outcomes)) / n
        std_s = math.sqrt(sum((s - mean_s)**2 for s in scores) / n)
        std_o = math.sqrt(sum((o - mean_o)**2 for o in outcomes) / n)
        if std_s > 0 and std_o > 0:
            corr = cov / (std_s * std_o)

    hit_rate = (sum(1 for r in rows if r["would_select"] and float(r["outcome_alpha_90d"]) > mean_alpha)
                / max(len(selected), 1))

    # 0378: cohort day tracking — use scored_at_date, fall back to date portion of prediction_timestamp
    dates = []
    for r in rows:
        d = r["scored_at_date"]
        if not d and r["prediction_timestamp"]:
            d = str(r["prediction_timestamp"])[:10]
        if d and len(d) >= 10:
            dates.append(d[:10])
    # Only count cohort days when scored_at_date was actually populated
    # (old rows without scored_at_date don't give reliable cohort data)
    rows_with_scored_date = sum(1 for r in rows if r["scored_at_date"])
    if rows_with_scored_date >= n // 2:
        n_cohort_days = len(set(dates))
    else:
        n_cohort_days = 0  # can't evaluate — old rows without scored_at_date
    effective_n = min(n, 3 * n_cohort_days) if n_cohort_days > 0 else n

    # Prospective edge evidence — derived from observations, NOT from CV metrics
    if spread is not None and spread > 0 and prediction_mae <= baseline_mae:
        obs_edge = "POSITIVE"
    elif spread is not None and spread < 0:
        obs_edge = "NEGATIVE"
    else:
        obs_edge = "INCONCLUSIVE"

    return {
        "prospective_n": n,
        "prospective_selected_n": len(selected),
        "prediction_mae": round(prediction_mae, 6),
        "baseline_mae": round(baseline_mae, 6),
        "prediction_vs_actual_corr": round(corr, 4) if corr is not None else None,
        "would_select_mean_alpha": round(sel_mean, 6) if sel_mean is not None else None,
        "nonselected_mean_alpha": round(not_mean, 6) if not_mean is not None else None,
        "selection_alpha_spread": round(spread, 6) if spread is not None else None,
        "top_quintile_mean_alpha": round(ch_top_mean, 6),
        "bottom_quintile_mean_alpha": round(ch_bottom_mean, 6),
        "prospective_ranking_spread": round(challenger_ranking_spread, 6),
        "prospective_hit_rate": round(hit_rate, 4),
        "prospective_edge_evidence": obs_edge,
        # 0375: incremental edge over base strategy
        "base_ranking_spread": round(base_ranking_spread, 6) if base_ranking_spread is not None else None,
        "challenger_ranking_spread": round(challenger_ranking_spread, 6),
        "incremental_ranking_spread": round(incremental_ranking_spread, 6) if incremental_ranking_spread is not None else None,
        "selection_alpha_delta": round(selection_alpha_delta, 6) if selection_alpha_delta is not None else None,
        "selection_alpha_delta_legacy": round(selection_alpha_delta_legacy, 6) if selection_alpha_delta_legacy is not None else None,
        # 0378: cohort independence metrics
        "n_cohort_days": n_cohort_days,
        "effective_n": effective_n,
        # 0382/0388/0400/0402: decision cohort evaluation (divergent cohorts only)
        "n_divergent_cohorts": n_divergent_cohorts,
        "challenger_wins": challenger_wins,
        "base_wins": base_wins,
        "ties": ties,
        "mean_selection_delta": round(selection_alpha_delta, 6) if cohort_deltas else None,
        "median_selection_delta": round(median_selection_delta, 6) if median_selection_delta is not None else None,
        "selection_delta_ci_low": selection_delta_ci_low,
        "selection_delta_ci_high": selection_delta_ci_high,
        "selection_delta_evidence": selection_delta_evidence,
        # 0408: block bootstrap (weekly clusters, accounts for overlapping return windows)
        "selection_delta_ci_low_short_block": selection_delta_ci_low_short_block,
        "selection_delta_ci_high_short_block": selection_delta_ci_high_short_block,
        "selection_delta_evidence_short_block": selection_delta_evidence_short_block,
        # 0427: stratified metrics by base_recommendation_eligible
        "stratified_metrics": _build_stratified_metrics(
            rows, _eligible_cohort_ids, _ineligible_eligibility_ids),
        # 0429: ineligible ledger cohort count; population_label signals filtering state
        "ineligible_cohorts_ledger": _ineligible_cohorts_ledger,
        "population_label": "complete_ledger" if filter_partial_ledger else "all",
    }


def compute_data_health(conn, target_horizon_version: str = None) -> dict:
    """Compute learning dataset health metrics for training/promotion decisions (0370/0380).

    target_horizon_version: when specified, only this version's coverage is a hard gate;
        other versions are informational only (block downgraded to warn). (0380)

    Returns {"overall": "ok"|"warn"|"block", "metrics": {...}, "total_episodes": int,
             "eligible_episodes": int}.
    """
    import time as _time
    findings: dict = {}

    total_episodes = 0
    try:
        total_episodes = conn.execute("SELECT COUNT(*) FROM decision_episodes").fetchone()[0]
    except Exception:
        pass

    # 0397: eligible episodes = those old enough to have matured outcomes.
    # Use exchange-session-exact cutoff via market calendar; never a fixed calendar approximation.
    eligible_episodes = 0
    from datetime import date as _dt_date, datetime as _dt_datetime, timedelta as _dt_td
    _today_str = _dt_date.today().isoformat()
    try:
        from trade_engine.market_calendar import nth_trading_session_before
        if target_horizon_version == "sessions_v2":
            _elig_date = nth_trading_session_before(_today_str, 63)
        else:
            _elig_date = (_dt_date.today() - _dt_td(days=91)).isoformat()
    except Exception:
        _elig_date = (_dt_date.today() - _dt_td(days=91)).isoformat()
    # Use end-of-day timestamp so episodes captured on the cutoff date are included
    eligible_cutoff_ts = _dt_datetime.strptime(_elig_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    ).timestamp()
    try:
        eligible_episodes = conn.execute(
            "SELECT COUNT(*) FROM decision_episodes WHERE captured_at <= ?",
            (eligible_cutoff_ts,),
        ).fetchone()[0]
    except Exception:
        pass

    # Outcome coverage (3m) — 0380: denominator = eligible episodes; use DISTINCT to avoid double-count
    try:
        labeled_3m = conn.execute(
            """SELECT COUNT(DISTINCT eo.episode_id) FROM episode_outcomes eo
               JOIN decision_episodes de ON de.episode_id = eo.episode_id
               WHERE eo.horizon='3m' AND de.captured_at <= ?""",
            (eligible_cutoff_ts,),
        ).fetchone()[0]
        coverage = labeled_3m / eligible_episodes if eligible_episodes else 0.0
        if eligible_episodes == 0:
            cov_status = "warn"  # can't evaluate — no mature episodes yet
        else:
            cov_status = "ok" if coverage >= 0.50 else ("warn" if coverage >= 0.25 else "block")
        findings["outcome_coverage_3m_pct"] = {"value": round(coverage, 3), "status": cov_status}
    except Exception:
        findings["outcome_coverage_3m_pct"] = {"value": None, "status": "warn"}

    # Ticker concentration
    try:
        if total_episodes:
            top = conn.execute(
                """SELECT ticker, COUNT(*) as n FROM decision_episodes
                   GROUP BY ticker ORDER BY n DESC LIMIT 1"""
            ).fetchone()
            conc = top["n"] / total_episodes if top else 0.0
            findings["top_ticker_concentration_pct"] = {
                "value": round(conc, 3),
                "ticker": top["ticker"] if top else None,
                "status": "ok" if conc < 0.25 else ("warn" if conc < 0.40 else "block"),
            }
    except Exception:
        pass

    # MTM completeness
    try:
        total_nav = conn.execute("SELECT COUNT(*) FROM virtual_book_nav").fetchone()[0]
        incomplete = conn.execute(
            "SELECT COUNT(*) FROM virtual_book_nav WHERE is_complete=0"
        ).fetchone()[0]
        incomplete_pct = incomplete / total_nav if total_nav else 0.0
        findings["incomplete_mtm_pct"] = {
            "value": round(incomplete_pct, 3),
            "status": "ok" if incomplete_pct < 0.10 else ("warn" if incomplete_pct < 0.30 else "block"),
        }
    except Exception:
        findings["incomplete_mtm_pct"] = {"value": None, "status": "warn"}

    # OBSERVE observation coverage per model
    try:
        obs_models = conn.execute(
            "SELECT model_version FROM learning_models WHERE lifecycle_state='OBSERVE'"
        ).fetchall()
        for om in obs_models:
            mv = om["model_version"]
            total_obs = conn.execute(
                "SELECT COUNT(*) FROM model_observations WHERE model_version=?", (mv,)
            ).fetchone()[0]
            labeled_obs = conn.execute(
                "SELECT COUNT(*) FROM model_observations WHERE model_version=? AND outcome_alpha_90d IS NOT NULL",
                (mv,),
            ).fetchone()[0]
            findings[f"observe_coverage_{mv}"] = {
                "total": total_obs, "labeled": labeled_obs,
                "status": "ok" if labeled_obs >= 5 else "warn",
            }
    except Exception:
        pass

    # 0397/0380: per-version outcome coverage with version-specific eligible cutoff
    try:
        for ver in ("calendar_v1", "sessions_v2"):
            # Each version gets its own exact eligibility cutoff
            try:
                from trade_engine.market_calendar import nth_trading_session_before
                if ver == "sessions_v2":
                    _ver_elig_date = nth_trading_session_before(_today_str, 63)
                else:
                    _ver_elig_date = (_dt_date.today() - _dt_td(days=91)).isoformat()
            except Exception:
                _ver_elig_date = (_dt_date.today() - _dt_td(days=91)).isoformat()
            _ver_cutoff_ts = _dt_datetime.strptime(_ver_elig_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            ).timestamp()
            ver_eligible = conn.execute(
                "SELECT COUNT(*) FROM decision_episodes WHERE captured_at <= ?",
                (_ver_cutoff_ts,),
            ).fetchone()[0]
            labeled_ver = conn.execute(
                """SELECT COUNT(DISTINCT eo.episode_id) FROM episode_outcomes eo
                   JOIN decision_episodes de ON de.episode_id = eo.episode_id
                   WHERE eo.horizon='3m' AND eo.horizon_definition_version=?
                     AND de.captured_at <= ?""",
                (ver, _ver_cutoff_ts),
            ).fetchone()[0]
            cov_ver = labeled_ver / ver_eligible if ver_eligible else 0.0
            if ver_eligible == 0:
                ver_status = "warn"
            else:
                ver_status = "ok" if cov_ver >= 0.50 else ("warn" if cov_ver >= 0.25 else "block")
            findings[f"outcome_coverage_3m_{ver}_pct"] = {
                "value": round(cov_ver, 3),
                "status": ver_status,
            }
    except Exception:
        pass

    # 0380: if target_horizon_version is specified, downgrade non-target version block → warn
    if target_horizon_version:
        for ver in ("calendar_v1", "sessions_v2"):
            if ver == target_horizon_version:
                continue
            key = f"outcome_coverage_3m_{ver}_pct"
            if key in findings and findings[key].get("status") == "block":
                findings[key]["status"] = "warn"

    # 0376: feature null rates using correct column names (q_score/v_score/pf_score/c_score/ec_score)
    for col in ("q_score", "v_score", "pf_score", "c_score", "ec_score"):
        try:
            null_count = conn.execute(
                f"SELECT COUNT(*) FROM decision_episodes WHERE {col} IS NULL"
            ).fetchone()[0]
            null_rate = null_count / total_episodes if total_episodes else 0.0
            findings[f"feature_null_rate_{col}"] = {
                "value": round(null_rate, 3),
                "status": "ok" if null_rate < 0.05 else ("warn" if null_rate < 0.20 else "block"),
            }
        except Exception:
            pass

    # 0415: learning pipeline health — flag when no shadow scores recorded in 3 trading days
    try:
        pa_row = conn.execute(
            """SELECT model_version, last_shadow_score_at FROM learning_models
               WHERE lifecycle_state='PAPER_ACTIVE' ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        if pa_row is not None:
            from trade_engine.market_calendar import nth_trading_session_before
            _today = __import__("datetime").date.today().isoformat()
            _stale_cutoff = nth_trading_session_before(_today, 3)
            _last = pa_row["last_shadow_score_at"] if hasattr(pa_row, "__getitem__") else None
            if _last is None or _last < _stale_cutoff:
                findings["learning_pipeline_health"] = {
                    "value": _last,
                    "status": "block",
                    "detail": f"PAPER_ACTIVE model has no shadow scores since {_stale_cutoff}",
                }
            else:
                findings["learning_pipeline_health"] = {"value": _last, "status": "ok"}
    except Exception:
        pass

    # 0406: cohort winner-count invariant — exactly one would_select and one base_would_select
    # per (model_version, decision_cohort_id). Violations indicate a bug in score_for_observe.
    try:
        bad_cohort_rows = conn.execute(
            """SELECT model_version, decision_cohort_id,
                      SUM(would_select) AS ch_winners,
                      SUM(COALESCE(base_would_select, 0)) AS base_winners
               FROM model_observations
               WHERE decision_cohort_id IS NOT NULL
               GROUP BY model_version, decision_cohort_id
               HAVING ch_winners != 1 OR base_winners != 1"""
        ).fetchall()
        n_bad = len(bad_cohort_rows)
        if n_bad == 0:
            findings["cohort_winner_invariant"] = {"value": 0, "status": "ok"}
        else:
            findings["cohort_winner_invariant"] = {
                "value": n_bad,
                "status": "block",
                "detail": f"{n_bad} cohort(s) with wrong winner count",
            }
    except Exception:
        findings["cohort_winner_invariant"] = {"value": None, "status": "warn"}

    statuses = [v.get("status") for v in findings.values() if isinstance(v, dict)]
    if "block" in statuses:
        overall = "block"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"

    return {
        "overall": overall,
        "metrics": findings,
        "total_episodes": total_episodes,
        "eligible_episodes": eligible_episodes,
    }


def _check_degradation(model_version: str, conn) -> None:
    """Compute rolling performance snapshot; auto-suspend on 2 consecutive NEGATIVE verdicts (0371).

    0374: evaluates only PAPER_ACTIVE-phase observations (post-promotion evidence).
    0377: non-overlapping cohort hysteresis — requires DEGRADATION_MIN_NEW_OUTCOMES new
          outcomes since the last snapshot before computing a new one.
    0383: uses per-row baseline_predicted_alpha for baseline_mae; stores ranking spreads;
          adds incremental_spread < 0 as a NEGATIVE signal.
    0384: uses last_outcome_labeled_at for hysteresis anchor when available; falls back
          to last_snapshot_max_obs_id for backward compat.
    Called by outcome_labeler after back-filling outcomes for PAPER_ACTIVE models.
    """
    from datetime import date as _d2

    row = conn.execute(
        "SELECT lifecycle_state FROM learning_models WHERE model_version=?",
        (model_version,),
    ).fetchone()
    if not row or row["lifecycle_state"] != LIFECYCLE_PAPER_ACTIVE:
        return

    # 0377/0384: check if enough new outcomes have matured since the last snapshot
    last_snap = conn.execute(
        """SELECT last_outcome_labeled_at, last_snapshot_max_obs_id
           FROM model_performance_snapshots
           WHERE model_version=?
           ORDER BY snapshot_date DESC LIMIT 1""",
        (model_version,),
    ).fetchone()

    if last_snap is not None:
        last_labeled_at = last_snap["last_outcome_labeled_at"]
        last_max_obs_id = last_snap["last_snapshot_max_obs_id"]

        if last_labeled_at is not None:
            # 0384: new approach — count by outcome_labeled_at timestamp
            new_n = conn.execute(
                """SELECT COUNT(*) FROM model_observations
                   WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                     AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)
                     AND outcome_labeled_at > ?""",
                (model_version, last_labeled_at),
            ).fetchone()[0]
            new_cohort_days = conn.execute(
                """SELECT COUNT(DISTINCT scored_at_date) FROM model_observations
                   WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                     AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)
                     AND outcome_labeled_at > ? AND scored_at_date IS NOT NULL""",
                (model_version, last_labeled_at),
            ).fetchone()[0]
            if new_n < DEGRADATION_MIN_NEW_OUTCOMES or new_cohort_days < DEGRADATION_MIN_NEW_COHORT_DAYS:
                return
        elif last_max_obs_id is not None:
            # 0377 legacy: count by observation id
            new_n = conn.execute(
                """SELECT COUNT(*) FROM model_observations
                   WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                     AND id > ?
                     AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)""",
                (model_version, last_max_obs_id),
            ).fetchone()[0]
            if new_n < DEGRADATION_MIN_NEW_OUTCOMES:
                return
        # else: no hysteresis anchor → proceed unconditionally

    # 0401: window by latest N distinct decision cohorts, not N candidate rows.
    # 0407: GROUP BY + MAX(id) ORDER instead of DISTINCT + ORDER BY id — DISTINCT with an
    # unaggregated ORDER BY id is query-planner-dependent and not reproducible.
    _latest_cohorts = conn.execute(
        """SELECT decision_cohort_id, MAX(id) AS max_id
           FROM model_observations
           WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
             AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)
             AND decision_cohort_id IS NOT NULL
           GROUP BY decision_cohort_id
           ORDER BY max_id DESC LIMIT ?""",
        (model_version, DEGRADATION_WINDOW_COHORTS),
    ).fetchall()
    _cohort_ids = [r["decision_cohort_id"] for r in _latest_cohorts]

    # 0430/0432: exclude cohorts with incomplete/failed ledger rows from the rolling window.
    # Legacy cohorts (no ledger row, pre-0424) are allowed through for non-modern models.
    _deg_inelig = _ineligible_ledger_cohorts(conn, model_version)
    if _deg_inelig:
        _deg_mv_created: float | None = None
        _deg_ev_ver: int | None = None
        try:
            _deg_cr = conn.execute(
                "SELECT created_at, evidence_contract_version FROM learning_models WHERE model_version=?",
                (model_version,),
            ).fetchone()
            _deg_mv_created = float(_deg_cr["created_at"]) if _deg_cr else None
            _deg_ev_raw = _deg_cr["evidence_contract_version"] if _deg_cr else None
            _deg_ev_ver = int(_deg_ev_raw) if _deg_ev_raw is not None else None
        except Exception:
            pass
        # 0438: prefer evidence_contract_version>=1; ev=0 or NULL falls back to timestamp
        _deg_is_modern = (
            (_deg_ev_ver >= 1)
            if _deg_ev_ver
            else (_deg_mv_created is not None and _deg_mv_created > LEDGER_ROLLOUT_CUTOFF)
        )
        if _deg_is_modern:
            _deg_elig = eligible_learning_cohorts(conn, model_version)
            _cohort_ids = [cid for cid in _cohort_ids if cid in _deg_elig]
        else:
            _cohort_ids = [cid for cid in _cohort_ids if cid not in _deg_inelig]

    if _cohort_ids:
        _ph = ",".join("?" * len(_cohort_ids))
        obs = conn.execute(
            f"""SELECT id, episode_id, challenger_score, base_score, predicted_alpha, would_select,
                      outcome_alpha_90d, baseline_predicted_alpha, outcome_labeled_at, scored_at_date,
                      decision_cohort_id, base_would_select
               FROM model_observations
               WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                 AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)
                 AND decision_cohort_id IN ({_ph})""",
            [model_version] + _cohort_ids,
        ).fetchall()
    else:
        # Fallback: legacy observations without decision_cohort_id
        obs = conn.execute(
            """SELECT id, episode_id, challenger_score, base_score, predicted_alpha, would_select,
                      outcome_alpha_90d, baseline_predicted_alpha, outcome_labeled_at, scored_at_date,
                      decision_cohort_id, base_would_select
               FROM model_observations
               WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
                 AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)
               ORDER BY id DESC LIMIT 30""",
            (model_version,),
        ).fetchall()
    n_cohorts_in_window = len(_cohort_ids)
    n_candidate_rows_in_window = len(obs)

    if n_candidate_rows_in_window < 5:
        return

    current_max_obs_id = max(int(r["id"]) for r in obs)
    # 0393: query globally for max outcome_labeled_at — LIMIT 30 window may not contain the true max
    current_max_labeled_at = conn.execute(
        """SELECT MAX(outcome_labeled_at) FROM model_observations
           WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
             AND (observation_phase='PAPER_ACTIVE' OR observation_phase IS NULL)""",
        (model_version,),
    ).fetchone()[0]

    outcomes = [float(r["outcome_alpha_90d"]) for r in obs]
    n_obs = len(obs)
    selected = [r for r in obs if r["would_select"]]
    not_selected = [r for r in obs if not r["would_select"]]
    mean_alpha = sum(outcomes) / n_obs
    valid_pred = [(float(r["predicted_alpha"]), float(r["outcome_alpha_90d"]))
                  for r in obs if r["predicted_alpha"] is not None]
    if valid_pred:
        prediction_mae = sum(abs(p - o) for p, o in valid_pred) / len(valid_pred)
    else:
        prediction_mae = sum(abs(float(r["challenger_score"]) - o)
                             for r, o in zip(obs, outcomes)) / n_obs

    # 0383: use per-row baseline_predicted_alpha when available (ex-ante, not hindsight)
    rows_with_baseline = [(float(r["baseline_predicted_alpha"]), float(r["outcome_alpha_90d"]))
                          for r in obs if r["baseline_predicted_alpha"] is not None]
    if rows_with_baseline:
        baseline_mae = sum(abs(b - o) for b, o in rows_with_baseline) / len(rows_with_baseline)
    else:
        baseline_mae = sum(abs(mean_alpha - o) for o in outcomes) / n_obs

    sel_mean = (sum(float(r["outcome_alpha_90d"]) for r in selected) / len(selected)) if selected else None
    not_mean = (sum(float(r["outcome_alpha_90d"]) for r in not_selected) / len(not_selected)) if not_selected else None
    spread = (sel_mean - not_mean) if sel_mean is not None and not_mean is not None else None

    hit_rate = sum(1 for r in obs if r["would_select"] and float(r["outcome_alpha_90d"]) > mean_alpha) / max(len(selected), 1)

    # 0383: compute ranking spreads for the snapshot
    q_size = max(1, n_obs // 5)
    ch_scores_arr = [float(r["challenger_score"]) for r in obs]
    sorted_ch = sorted(zip(ch_scores_arr, outcomes), key=lambda x: x[0])
    snap_challenger_spread = (sum(o for _, o in sorted_ch[-q_size:]) / q_size
                               - sum(o for _, o in sorted_ch[:q_size]) / q_size)
    snap_base_spread: float | None = None
    snap_incremental_spread: float | None = None
    base_scores_raw = [r["base_score"] for r in obs]
    if all(b is not None for b in base_scores_raw):
        sorted_base = sorted(zip([float(b) for b in base_scores_raw], outcomes), key=lambda x: x[0])
        snap_base_spread = (sum(o for _, o in sorted_base[-q_size:]) / q_size
                             - sum(o for _, o in sorted_base[:q_size]) / q_size)
        snap_incremental_spread = snap_challenger_spread - snap_base_spread

    # 0391: cohort-based selection delta over the rolling window
    snap_selection_delta: float | None = None
    n_divergent_window = 0
    obs_with_cohort = [r for r in obs if r["decision_cohort_id"] is not None]
    if obs_with_cohort:
        from collections import defaultdict as _dd
        cmap: dict = _dd(list)
        for r in obs_with_cohort:
            cmap[r["decision_cohort_id"]].append(r)
        _win_deltas = []
        for crow in cmap.values():
            ch_r = [r for r in crow if r["would_select"]]
            base_r = [r for r in crow if r["base_would_select"] is not None
                      and int(r["base_would_select"])]
            if not ch_r or not base_r:
                continue
            ch_ep = ch_r[0]["episode_id"]
            base_ep = base_r[0]["episode_id"]
            ch_out = float(ch_r[0]["outcome_alpha_90d"])
            base_out = float(base_r[0]["outcome_alpha_90d"])
            if ch_ep != base_ep:
                # 0400: only accumulate divergent-cohort deltas (same-choice cohorts
                # contribute delta=0 and dilute the metric — exclude them)
                _win_deltas.append(ch_out - base_out)
                n_divergent_window += 1
        if _win_deltas:
            snap_selection_delta = sum(_win_deltas) / len(_win_deltas)

    # 0383: verdict — incremental_spread < 0 is also a NEGATIVE signal
    # 0391: sustained negative selection_delta with enough divergent cohorts is also NEGATIVE
    if snap_incremental_spread is not None and snap_incremental_spread < 0:
        verdict = "NEGATIVE"
    elif (snap_selection_delta is not None and snap_selection_delta < 0
          and n_divergent_window >= DEGRADATION_MIN_DIVERGENT_COHORTS):
        verdict = "NEGATIVE"
    elif spread is not None and spread > 0 and prediction_mae <= baseline_mae:
        verdict = "POSITIVE"
    elif spread is not None and spread < 0:
        verdict = "NEGATIVE"
    else:
        verdict = "INCONCLUSIVE"

    today = _d2.today().isoformat()
    try:
        # 0394: use INSERT OR REPLACE so a second run on the same day updates the anchor
        # rather than silently ignoring it (which would freeze last_outcome_labeled_at at T1)
        conn.execute(
            """INSERT OR REPLACE INTO model_performance_snapshots
               (model_version, snapshot_date, window_n, selection_alpha_spread,
                prediction_mae, baseline_mae, prospective_hit_rate, edge_verdict,
                last_snapshot_max_obs_id, snapshot_base_ranking_spread,
                snapshot_challenger_ranking_spread, snapshot_incremental_spread,
                last_outcome_labeled_at, snapshot_selection_delta, n_divergent_cohorts_in_window,
                n_cohorts_in_window, n_candidate_rows_in_window)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (model_version, today, n_obs, spread, prediction_mae, baseline_mae,
             hit_rate, verdict, current_max_obs_id,
             snap_base_spread, snap_challenger_spread, snap_incremental_spread,
             current_max_labeled_at, snap_selection_delta, n_divergent_window,
             n_cohorts_in_window, n_candidate_rows_in_window),
        )
        conn.commit()
    except Exception:
        pass

    # Auto-suspend if 2 consecutive NEGATIVE verdicts (from any snapshot, including manual ones)
    recent = conn.execute(
        """SELECT edge_verdict FROM model_performance_snapshots
           WHERE model_version=? ORDER BY snapshot_date DESC LIMIT 2""",
        (model_version,),
    ).fetchall()
    if len(recent) >= 2 and all(r["edge_verdict"] == "NEGATIVE" for r in recent):
        now_ts = time.time()
        conn.execute(
            "UPDATE learning_models SET lifecycle_state=? WHERE model_version=?",
            (LIFECYCLE_SUSPENDED, model_version),
        )
        conn.execute(
            """INSERT INTO model_promotion_log
               (model_version, from_state, to_state, promoted_by, promoted_at,
                promotion_reason, promotion_metrics_snapshot)
               VALUES (?,?,?,?,?,?,?)""",
            (model_version, LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_SUSPENDED,
             "auto_degradation_monitor", now_ts,
             "auto_degradation: 2 consecutive NEGATIVE rolling snapshots",
             json.dumps({"edge_verdict": verdict, "spread": spread, "mae": prediction_mae})),
        )
        conn.commit()


def learning_readiness_report(conn, model_version: str = None) -> dict:
    """Consolidated report on the state of the learning loop (0385).

    Returns a single dict covering: canonical_horizon, eligible_episodes,
    mature_observations, independent_cohort_days, ranking spreads,
    current_lifecycle, promotion_gates, data_health, and next_maturity_date.
    """
    from datetime import date as _d, timedelta as _td

    # Find the model to report on (latest in OBSERVE/PAPER_ACTIVE, then any)
    if model_version is None:
        for state in (LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_OBSERVE, LIFECYCLE_SUSPENDED,
                      LIFECYCLE_TRAINED):
            r = conn.execute(
                "SELECT model_version FROM learning_models WHERE lifecycle_state=? ORDER BY created_at DESC LIMIT 1",
                (state,),
            ).fetchone()
            if r:
                model_version = r["model_version"]
                break

    if model_version is None:
        return {"error": "no models found", "canonical_horizon": LEARNING_TARGET_HORIZON}

    # Model row
    mv_row = conn.execute("SELECT * FROM learning_models WHERE model_version=?", (model_version,)).fetchone()
    lifecycle = mv_row["lifecycle_state"] if mv_row else None
    thv = (mv_row["training_horizon_version"] if mv_row else None) or LEARNING_TARGET_HORIZON
    _mv_ts = float(mv_row["created_at"]) if mv_row and mv_row["created_at"] else 0.0
    _mv_keys = mv_row.keys() if (mv_row and hasattr(mv_row, "keys")) else []
    # 0415: pipeline observability — last successful shadow score
    last_shadow_score_at = mv_row["last_shadow_score_at"] if "last_shadow_score_at" in _mv_keys else None
    last_shadow_cohort_id = mv_row["last_shadow_cohort_id"] if "last_shadow_cohort_id" in _mv_keys else None
    # 0416: artifact identity fields
    model_id = mv_row["model_id"] if "model_id" in _mv_keys else None
    training_config_hash = mv_row["training_config_hash"] if "training_config_hash" in _mv_keys else None
    code_commit_sha_val = mv_row["code_commit_sha"] if "code_commit_sha" in _mv_keys else None
    # 0432/0438: provenance classification — prefer evidence_contract_version, fall back to timestamp
    _ev_contract_raw = mv_row["evidence_contract_version"] if "evidence_contract_version" in _mv_keys else None
    _ev_contract_int = int(_ev_contract_raw) if _ev_contract_raw is not None else None
    # 0438: prefer evidence_contract_version>=1; ev=0 or NULL falls back to timestamp
    _is_modern = (
        (_ev_contract_int >= 1)
        if _ev_contract_int
        else (_mv_ts > LEDGER_ROLLOUT_CUTOFF)
    )

    # Data health (target-aware)
    health = compute_data_health(conn, target_horizon_version=thv)
    eligible_episodes = health.get("eligible_episodes", 0)

    # Prospective metrics — filter PARTIAL/FAILED ledger cohorts consistent with promotion gates
    pm = compute_prospective_metrics(model_version, conn, filter_partial_ledger=True)
    mature_obs = int(pm.get("prospective_n", 0))
    cohort_days = int(pm.get("n_cohort_days", 0))

    # Promotion gates — target depends on lifecycle (0396):
    # OBSERVE → PAPER_ACTIVE gates; SUSPENDED → OBSERVE re-entry gates
    gates_result: dict = {}
    promotion_target_state: str = ""
    if lifecycle == LIFECYCLE_OBSERVE:
        promotion_target_state = LIFECYCLE_PAPER_ACTIVE
        gates_result = _check_promotion_gates(model_version, LIFECYCLE_PAPER_ACTIVE)
    elif lifecycle == LIFECYCLE_SUSPENDED:
        promotion_target_state = LIFECYCLE_OBSERVE
        gates_result = _check_promotion_gates(model_version, LIFECYCLE_OBSERVE)

    # 0397: next maturity date via shared maturity_date() — no calendar approximation
    next_maturity_date: str | None = None
    try:
        min_unmatured = conn.execute(
            """SELECT MIN(scored_at_date) FROM model_observations
               WHERE model_version=? AND outcome_alpha_90d IS NULL AND scored_at_date IS NOT NULL""",
            (model_version,),
        ).fetchone()[0]
        if min_unmatured:
            from trade_engine.market_calendar import maturity_date as _mat_date
            next_maturity_date = _mat_date(min_unmatured, thv, "3m")
    except Exception:
        pass

    n_div = pm.get("n_divergent_cohorts", 0)
    return {
        "canonical_horizon": LEARNING_TARGET_HORIZON,
        "model_version": model_version,
        "current_lifecycle": lifecycle,
        "training_horizon_version": thv,
        "eligible_episodes": eligible_episodes,
        "mature_observations": mature_obs,
        "independent_cohort_days": cohort_days,
        # Ranking evidence (all mature observations)
        "base_ranking_spread": pm.get("base_ranking_spread"),
        "challenger_ranking_spread": pm.get("challenger_ranking_spread"),
        "incremental_ranking_spread": pm.get("incremental_ranking_spread"),
        # Decision evidence (divergent cohorts only) — 0388/0392/0400/0402
        "n_divergent_cohorts": n_div,
        "challenger_wins": pm.get("challenger_wins", 0),
        "base_wins": pm.get("base_wins", 0),
        "ties": pm.get("ties", 0),
        "mean_selection_delta": pm.get("mean_selection_delta"),
        "median_selection_delta": pm.get("median_selection_delta"),
        "selection_delta_ci_low": pm.get("selection_delta_ci_low"),
        "selection_delta_ci_high": pm.get("selection_delta_ci_high"),
        "selection_delta_evidence": pm.get("selection_delta_evidence"),
        # 0408/0417: short-block bootstrap CI (weekly clusters, informational only).
        # Adjacent daily cohorts share ~90% of their 63-session return window so
        # weekly blocks still understate dependence.  NOT used in promotion gates.
        "selection_delta_ci_low_short_block": pm.get("selection_delta_ci_low_short_block"),
        "selection_delta_ci_high_short_block": pm.get("selection_delta_ci_high_short_block"),
        "selection_delta_evidence_short_block": pm.get("selection_delta_evidence_short_block"),
        "block_bootstrap_note": (
            "Weekly blocks; adjacent 63-session cohorts ~90% correlated. "
            "Treat as lower bound on uncertainty. Upgrade to 13-week blocks after "
            "sufficient history accumulates."
        ),
        "selection_alpha_delta": pm.get("selection_alpha_delta"),
        "challenger_win_rate": (pm.get("challenger_wins", 0) / n_div) if n_div > 0 else None,
        "promotion_target_state": promotion_target_state,  # 0396
        "promotion_gates": gates_result.get("gates", {}),
        "promotion_passed": gates_result.get("passed"),
        "promotion_failed": gates_result.get("failed", []),
        "data_health": health["overall"],
        "data_health_metrics": health["metrics"],
        "next_maturity_date": next_maturity_date,
        # 0415: pipeline observability
        "last_shadow_score_at": last_shadow_score_at,
        "last_shadow_cohort_id": last_shadow_cohort_id,
        # 0416: artifact identity
        "model_id": model_id,
        "training_config_hash": training_config_hash,
        "code_commit_sha": code_commit_sha_val,
        # 0427: stratified metrics by base_recommendation_eligible
        "stratified_metrics": pm.get("stratified_metrics", {}),
        "population_label": pm.get("population_label", "all"),
        # 0429: ineligible ledger cohort count (PARTIAL/FAILED sweeps excluded from gates)
        "ineligible_cohorts_ledger": int(pm.get("ineligible_cohorts_ledger", 0)),
        # 0432/0438: provenance classification for this model's cohorts
        "provenance_breakdown": {
            "verified_modern": len(eligible_learning_cohorts(conn, model_version)),
            "ineligible": len(_ineligible_ledger_cohorts(conn, model_version)),
            "is_modern_model": _is_modern,
            "evidence_contract_version": _ev_contract_int,
        },
    }


if __name__ == "__main__":
    import sys
    result = train_and_save()
    print(f"[calibration] {result}")
    sys.exit(0 if result.get("trained") else 1)
