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
        """Predict 90d alpha for a candidate feature dict. Returns None if any feature missing."""
        x = [candidate.get(f) for f in FEATURES]
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
            conn.execute(
                """INSERT INTO learning_models
                   (model_version, training_cutoff, feature_schema_hash,
                    training_n, validation_metrics, created_at,
                    unique_tickers, unique_decision_dates, unique_weeks, raw_n,
                    lifecycle_state, training_horizon_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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

        # Decision-date cohort walk-forward cross-validation (0334)
        folds = _cv_walk_forward(X, y, dates, ridge_alpha)

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
        model_version = f"edge_v{int(training_cutoff):010d}"

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
) -> list[dict]:
    """Decision-date cohort walk-forward cross-validation with embargo (0334).

    For each cutoff date where train_n >= MIN_TRAINING_N, validates on the
    next available date that is at least EMBARGO_DAYS after the cutoff.
    The embargo prevents return-window overlap between training and validation.

    Returns list of fold dicts: mae, baseline_mae, train_n, val_n, coef_signs,
    top_vs_bottom_quintile_alpha (None when val_n < 5).
    """
    unique_dates = sorted(set(dates))
    folds: list[dict] = []

    for cutoff_str in unique_dates:
        train_mask = np.array([d <= cutoff_str for d in dates])
        if int(train_mask.sum()) < MIN_TRAINING_N:
            continue

        embargo_end = (_date.fromisoformat(cutoff_str) + _td(days=EMBARGO_DAYS)).isoformat()
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


def train_and_save() -> dict:
    """Train a new model (lifecycle_state=TRAINED). Promotion requires separate promote() call."""
    model = ChallengerModel.train()
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
        # 0360/0365: prospective evidence gates — must come from model_observations
        pm = compute_prospective_metrics(model_version, conn)
        prospective_n = int(pm.get("prospective_n", 0))
        prospective_selected_n = int(pm.get("prospective_selected_n", 0))
        ranking_spread = pm.get("prospective_ranking_spread")
        pred_mae = pm.get("prediction_mae")
        base_mae = pm.get("baseline_mae")
        obs_edge = pm.get("prospective_edge_evidence", "")

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


def compute_prospective_metrics(model_version: str, conn) -> dict:
    """Compute out-of-sample ranking metrics from labeled model_observations (0365).

    Returns a dict with selection_alpha_spread, prediction_mae, baseline_mae,
    prospective_ranking_spread, and prospective_edge_evidence derived purely from
    model_observations (not from retrospective CV metrics).
    Returns {} when fewer than 5 labeled observations exist.
    """
    import math

    rows = conn.execute(
        """SELECT challenger_score, predicted_alpha, would_select, outcome_alpha_90d
           FROM model_observations
           WHERE model_version=? AND outcome_alpha_90d IS NOT NULL""",
        (model_version,),
    ).fetchall()
    if len(rows) < 5:
        return {}

    # Use predicted_alpha for MAE — challenger_score is a composite, not an alpha prediction
    outcomes = [float(r["outcome_alpha_90d"]) for r in rows]
    ch_scores = [float(r["challenger_score"]) for r in rows]
    pred_alphas = [float(r["predicted_alpha"]) if r["predicted_alpha"] is not None else None
                   for r in rows]
    selected = [r for r in rows if r["would_select"]]
    not_selected = [r for r in rows if not r["would_select"]]
    n = len(rows)

    mean_alpha = sum(outcomes) / n
    # MAE: compare predicted_alpha to actual alpha; fall back to challenger_score if unavailable
    valid_preds = [(p, o) for p, o in zip(pred_alphas, outcomes) if p is not None]
    if valid_preds:
        prediction_mae = sum(abs(p - o) for p, o in valid_preds) / len(valid_preds)
    else:
        prediction_mae = sum(abs(s - o) for s, o in zip(ch_scores, outcomes)) / n
    baseline_mae = sum(abs(mean_alpha - o) for o in outcomes) / n
    # Use challenger_score for quintile ranking spread (ranking quality, not alpha accuracy)
    scores = ch_scores

    sel_mean = (sum(float(r["outcome_alpha_90d"]) for r in selected) / len(selected)) if selected else None
    not_mean = (sum(float(r["outcome_alpha_90d"]) for r in not_selected) / len(not_selected)) if not_selected else None
    spread = (sel_mean - not_mean) if sel_mean is not None and not_mean is not None else None

    # Quintile ranking spread
    sorted_pairs = sorted(zip(scores, outcomes), key=lambda x: x[0])
    q_size = max(1, n // 5)
    bottom_mean = sum(o for _, o in sorted_pairs[:q_size]) / q_size
    top_mean = sum(o for _, o in sorted_pairs[-q_size:]) / q_size
    quintile_spread = top_mean - bottom_mean

    # Pearson correlation
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
        "top_quintile_mean_alpha": round(top_mean, 6),
        "bottom_quintile_mean_alpha": round(bottom_mean, 6),
        "prospective_ranking_spread": round(quintile_spread, 6),
        "prospective_hit_rate": round(hit_rate, 4),
        "prospective_edge_evidence": obs_edge,
    }


def compute_data_health(conn) -> dict:
    """Compute learning dataset health metrics for training/promotion decisions (0370).

    Returns {"overall": "ok"|"warn"|"block", "metrics": {...}, "total_episodes": int}.
    """
    findings: dict = {}

    total_episodes = 0
    try:
        total_episodes = conn.execute("SELECT COUNT(*) FROM decision_episodes").fetchone()[0]
    except Exception:
        pass

    # Outcome coverage (3m)
    try:
        labeled_3m = conn.execute(
            """SELECT COUNT(*) FROM episode_outcomes
               WHERE horizon='3m'"""
        ).fetchone()[0]
        coverage = labeled_3m / total_episodes if total_episodes else 0.0
        findings["outcome_coverage_3m_pct"] = {
            "value": round(coverage, 3),
            "status": "ok" if coverage >= 0.50 else ("warn" if coverage >= 0.25 else "block"),
        }
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

    # Feature null rates for key score columns
    for col in ("composite_score", "quality_score", "portfolio_fit_score"):
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

    statuses = [v.get("status") for v in findings.values() if isinstance(v, dict)]
    if "block" in statuses:
        overall = "block"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"

    return {"overall": overall, "metrics": findings, "total_episodes": total_episodes}


def _check_degradation(model_version: str, conn) -> None:
    """Compute rolling performance snapshot; auto-suspend on 2 consecutive NEGATIVE verdicts (0371).

    Called by outcome_labeler after back-filling outcomes for PAPER_ACTIVE models.
    """
    from datetime import date as _d2

    row = conn.execute(
        "SELECT lifecycle_state FROM learning_models WHERE model_version=?",
        (model_version,),
    ).fetchone()
    if not row or row["lifecycle_state"] != LIFECYCLE_PAPER_ACTIVE:
        return

    obs = conn.execute(
        """SELECT challenger_score, predicted_alpha, would_select, outcome_alpha_90d
           FROM model_observations
           WHERE model_version=? AND outcome_alpha_90d IS NOT NULL
           ORDER BY prediction_timestamp DESC LIMIT 30""",
        (model_version,),
    ).fetchall()
    if len(obs) < 5:
        return

    outcomes = [float(r["outcome_alpha_90d"]) for r in obs]
    selected = [r for r in obs if r["would_select"]]
    not_selected = [r for r in obs if not r["would_select"]]
    mean_alpha = sum(outcomes) / len(outcomes)
    # Use predicted_alpha for MAE (challenger_score is composite, not an alpha prediction)
    valid_pred = [(float(r["predicted_alpha"]), float(r["outcome_alpha_90d"]))
                  for r in obs if r["predicted_alpha"] is not None]
    if valid_pred:
        prediction_mae = sum(abs(p - o) for p, o in valid_pred) / len(valid_pred)
    else:
        prediction_mae = sum(abs(float(r["challenger_score"]) - float(r["outcome_alpha_90d"])) for r in obs) / len(obs)
    baseline_mae = sum(abs(mean_alpha - o) for o in outcomes) / len(outcomes)

    sel_mean = (sum(float(r["outcome_alpha_90d"]) for r in selected) / len(selected)) if selected else None
    not_mean = (sum(float(r["outcome_alpha_90d"]) for r in not_selected) / len(not_selected)) if not_selected else None
    spread = (sel_mean - not_mean) if sel_mean is not None and not_mean is not None else None

    hit_rate = sum(1 for r in obs if r["would_select"] and float(r["outcome_alpha_90d"]) > mean_alpha) / max(len(selected), 1)

    if spread is not None and spread > 0 and prediction_mae <= baseline_mae:
        verdict = "POSITIVE"
    elif spread is not None and spread < 0:
        verdict = "NEGATIVE"
    else:
        verdict = "INCONCLUSIVE"

    today = _d2.today().isoformat()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO model_performance_snapshots
               (model_version, snapshot_date, window_n, selection_alpha_spread,
                prediction_mae, baseline_mae, prospective_hit_rate, edge_verdict)
               VALUES (?,?,?,?,?,?,?,?)""",
            (model_version, today, len(obs), spread, prediction_mae, baseline_mae, hit_rate, verdict),
        )
        conn.commit()
    except Exception:
        pass

    # Auto-suspend if 2 consecutive NEGATIVE verdicts
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


if __name__ == "__main__":
    import sys
    result = train_and_save()
    print(f"[calibration] {result}")
    sys.exit(0 if result.get("trained") else 1)
