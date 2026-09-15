"""Challenger Calibration Model (0330).

Fits a ridge-regression model on labeled decision_episodes to predict
90-day SPY alpha. Applies a bounded, shrinkage-weighted adjustment to
the base Opportunity Hunter composite score.

Architecture constraints:
- Uses only numpy (sklearn not installed) — ridge regression via normal equations.
- Training requires MIN_TRAINING_N labeled 90d episodes before influencing scores.
- Adjustment is capped at ±MAX_ADJUSTMENT score points regardless of prediction.
- Shrinkage formula: adjustment = (n / (n + SHRINKAGE_LAMBDA)) * raw_adjustment
- Hard risk limits in the risk engine are never modified.
- Validation uses chronological walk-forward split (no random splits — those
  leak future/regime information into training for time-series data).

Usage:
    model = ChallengerModel.train()     # returns None if insufficient data
    if model:
        out = model.score(candidate)    # dict with expected_alpha, learning_adjustment, etc.
        model.save()                    # persist to learning_models table
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING

import numpy as np

import agent_db

MIN_TRAINING_N      = 30        # below this, model has no influence
SHRINKAGE_LAMBDA    = 50.0      # at n=50, factor = 50/100 = 0.5
RIDGE_ALPHA         = 1.0       # L2 regularization strength
MAX_ADJUSTMENT      = 10.0      # ±score points cap
ALPHA_TO_SCORE_SCALE = 100.0   # 1% expected alpha above mean → +1 score point
HORIZON             = "3m"
FEATURES            = ["q_score", "v_score", "pf_score", "c_score", "ec_score"]
FEATURE_SCHEMA_VER  = "v1"


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
    ):
        self.coef               = np.array(coef)
        self.intercept          = intercept
        self.mean_alpha         = mean_alpha
        self.training_n         = training_n
        self.training_cutoff    = training_cutoff
        self.model_version      = model_version
        self.validation_metrics = validation_metrics
        self.feature_schema_hash = feature_schema_hash

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
          p_outperform          float | None  — sigmoid probability of alpha > 0
          reliability           float         — shrinkage weight (0-1)
          learning_adjustment   float         — bounded score delta (±MAX_ADJUSTMENT)
          model_version         str
          active                bool          — False when training_n < MIN_TRAINING_N
        """
        active = self.training_n >= MIN_TRAINING_N
        pred = self.predict_alpha(candidate) if active else None

        if pred is None or not active:
            return {
                "expected_alpha": None,
                "p_outperform": None,
                "reliability": self.reliability,
                "learning_adjustment": 0.0,
                "model_version": self.model_version,
                "active": False,
            }

        # p_outperform from sigmoid on predicted alpha
        p_outperform = float(1.0 / (1.0 + np.exp(-pred * ALPHA_TO_SCORE_SCALE)))

        # Raw adjustment: excess alpha above training mean, converted to score points
        raw_adj = (pred - self.mean_alpha) * ALPHA_TO_SCORE_SCALE

        # Apply shrinkage and cap
        adj = self.reliability * raw_adj
        adj = float(np.clip(adj, -MAX_ADJUSTMENT, MAX_ADJUSTMENT))

        return {
            "expected_alpha": pred,
            "p_outperform": p_outperform,
            "reliability": self.reliability,
            "learning_adjustment": adj,
            "model_version": self.model_version,
            "active": True,
        }

    def save(self) -> None:
        """Persist model to learning_models table."""
        metrics_json = json.dumps(self.validation_metrics)
        conn = agent_db._connect()
        conn.execute(
            """INSERT OR REPLACE INTO learning_models
               (model_version, training_cutoff, feature_schema_hash,
                training_n, validation_metrics, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                self.model_version,
                self.training_cutoff,
                self.feature_schema_hash,
                self.training_n,
                metrics_json,
                time.time(),
            ),
        )
        conn.commit()
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
        )

    @classmethod
    def train(cls, ridge_alpha: float = RIDGE_ALPHA) -> "ChallengerModel | None":
        """Train on all labeled 3m episodes using chronological walk-forward validation.

        Returns None if fewer than MIN_TRAINING_N rows are available.
        """
        conn = agent_db._connect()
        rows = conn.execute(
            f"""
            SELECT e.episode_id, e.captured_at,
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
        conn.close()

        if len(rows) < MIN_TRAINING_N:
            return None

        X = np.array([[r[f] for f in FEATURES] for r in rows], dtype=float)
        y = np.array([r["alpha"] for r in rows], dtype=float)
        n = len(rows)
        training_cutoff = rows[-1]["captured_at"]

        # Chronological walk-forward: train on first ~80%, validate on last ~20%
        split = max(MIN_TRAINING_N, int(n * 0.8))
        X_train, X_val = X[:split], X[split:]
        y_train, y_val = y[:split], y[split:]

        coef, intercept = _ridge_fit(X_train, y_train, ridge_alpha)
        mean_alpha = float(y_train.mean())

        val_metrics: dict = {}
        if len(X_val) > 0:
            y_pred_val = X_val @ coef + intercept
            mae   = float(np.abs(y_val - y_pred_val).mean())
            ss_res = float(np.sum((y_val - y_pred_val) ** 2))
            ss_tot = float(np.sum((y_val - y_val.mean()) ** 2))
            r2    = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            val_metrics = {"val_n": len(X_val), "val_mae": mae, "val_r2": r2}

        # Refit on full data for the deployed model
        coef_full, intercept_full = _ridge_fit(X, y, ridge_alpha)

        feature_schema_hash = _schema_hash()
        model_version = f"edge_v{int(training_cutoff):010d}"

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
    def load_latest(cls) -> "ChallengerModel | None":
        """Load the most recently saved model from learning_models, if any."""
        try:
            conn = agent_db._connect()
            row = conn.execute(
                "SELECT * FROM learning_models ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if not row:
                return None
            metrics = json.loads(row["validation_metrics"] or "{}")
            # The coef/intercept are stored in validation_metrics as a side-channel
            # when the model is saved via save_with_weights(); otherwise unavailable.
            coef = metrics.get("coef")
            intercept = metrics.get("intercept")
            if coef is None:
                return None
            return cls(
                coef=coef,
                intercept=intercept,
                mean_alpha=metrics.get("mean_alpha", 0.0),
                training_n=row["training_n"] or 0,
                training_cutoff=row["training_cutoff"] or "",
                model_version=row["model_version"],
                validation_metrics=metrics,
                feature_schema_hash=row["feature_schema_hash"] or "",
            )
        except Exception:
            return None

    def save_with_weights(self) -> None:
        """Save model including coefficients inside validation_metrics JSON."""
        full_metrics = dict(self.validation_metrics)
        full_metrics["coef"] = self.coef.tolist()
        full_metrics["intercept"] = float(self.intercept)
        full_metrics["mean_alpha"] = float(self.mean_alpha)
        conn = agent_db._connect()
        conn.execute(
            """INSERT OR REPLACE INTO learning_models
               (model_version, training_cutoff, feature_schema_hash,
                training_n, validation_metrics, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                self.model_version,
                self.training_cutoff,
                self.feature_schema_hash,
                self.training_n,
                json.dumps(full_metrics),
                time.time(),
            ),
        )
        conn.commit()
        conn.close()


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
    """Train a new model and save it. Returns summary dict."""
    model = ChallengerModel.train()
    if model is None:
        return {
            "trained": False,
            "reason": f"fewer than {MIN_TRAINING_N} labeled 90d episodes",
        }
    model.save_with_weights()
    return {
        "trained": True,
        "model_version": model.model_version,
        "training_n": model.training_n,
        "reliability": model.reliability,
        "active": model.training_n >= MIN_TRAINING_N,
        "validation_metrics": model.validation_metrics,
    }
