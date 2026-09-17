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

# 0343 — uncertainty band thresholds for alpha CI width classification
ALPHA_CI_HIGH_THRESHOLD   = 0.02   # band width < 2% → HIGH reliability
ALPHA_CI_MEDIUM_THRESHOLD = 0.05   # band width < 5% → MEDIUM; else LOW

# Lifecycle states — explicit promotion gates required between each (0335)
LIFECYCLE_TRAINED      = "TRAINED"
LIFECYCLE_OBSERVE      = "OBSERVE"
LIFECYCLE_PAPER_ACTIVE = "PAPER_ACTIVE"
LIFECYCLE_RETIRED      = "RETIRED"

# Promotion gate thresholds for TRAINED → OBSERVE
PROMOTE_MIN_UNIQUE_TICKERS        = 10
PROMOTE_MIN_UNIQUE_DECISION_DATES = 30
PROMOTE_MIN_UNIQUE_WEEKS          = 4
# beats_baseline == True and cv_folds >= 1 also required for OBSERVE


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
        vm = self.validation_metrics
        conn = agent_db._connect()
        conn.execute(
            """INSERT OR REPLACE INTO learning_models
               (model_version, training_cutoff, feature_schema_hash,
                training_n, validation_metrics, created_at,
                unique_tickers, unique_decision_dates, unique_weeks, raw_n,
                lifecycle_state)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
    def train(cls, ridge_alpha: float = RIDGE_ALPHA) -> "ChallengerModel | None":
        """Train on all labeled 3m episodes using decision-date cohort walk-forward (0334).

        Returns None if fewer than MIN_TRAINING_N rows are available.
        """
        conn = agent_db._connect()
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
            # 0343 — uncertainty bands
            "alpha_ci_low":             ci["alpha_ci_low"],
            "alpha_ci_high":            ci["alpha_ci_high"],
            "alpha_reliability":        ci["alpha_reliability"],
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
        except Exception:
            return None


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
    """Bootstrap 10th/90th percentile CI over fold-level mean alphas (0343).

    Resamples fold Q/B spread values (top_vs_bottom_quintile_alpha) with
    replacement. Returns alpha_ci_low, alpha_ci_high, alpha_reliability.
    INSUFFICIENT_DATA returned when < 2 folds have a spread value.
    """
    spreads = [f["top_vs_bottom_quintile_alpha"]
               for f in folds if f.get("top_vs_bottom_quintile_alpha") is not None]
    if len(spreads) < 2:
        return {
            "alpha_ci_low": None,
            "alpha_ci_high": None,
            "alpha_reliability": "INSUFFICIENT_DATA",
        }

    rng = np.random.default_rng(rng_seed)
    arr = np.array(spreads)
    boot_means = [float(rng.choice(arr, size=len(arr), replace=True).mean())
                  for _ in range(n_iter)]
    ci_low  = float(np.percentile(boot_means, 10))
    ci_high = float(np.percentile(boot_means, 90))
    band_width = ci_high - ci_low

    if band_width < ALPHA_CI_HIGH_THRESHOLD:
        reliability = "HIGH"
    elif band_width < ALPHA_CI_MEDIUM_THRESHOLD:
        reliability = "MEDIUM"
    else:
        reliability = "LOW"

    return {
        "alpha_ci_low": round(ci_low, 6),
        "alpha_ci_high": round(ci_high, 6),
        "alpha_reliability": reliability,
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
    """Evaluate promotion gate checklist. Returns dict with keys passed, failed, gates."""
    conn = agent_db._connect()
    row = conn.execute(
        "SELECT * FROM learning_models WHERE model_version=?", (model_version,)
    ).fetchone()
    conn.close()
    if not row:
        return {"passed": False, "failed": ["model_not_found"], "gates": {}}

    vm = json.loads(row["validation_metrics"] or "{}")
    ut  = row["unique_tickers"] or vm.get("unique_tickers") or 0
    ud  = row["unique_decision_dates"] or vm.get("unique_decision_dates") or 0
    uw  = row["unique_weeks"] or vm.get("unique_weeks") or 0
    cf  = vm.get("cv_folds") or 0
    bb  = vm.get("beats_baseline")

    gates: dict[str, bool] = {
        "unique_tickers":        ut >= PROMOTE_MIN_UNIQUE_TICKERS,
        "unique_decision_dates": ud >= PROMOTE_MIN_UNIQUE_DECISION_DATES,
        "unique_weeks":          uw >= PROMOTE_MIN_UNIQUE_WEEKS,
        "has_cv_folds":          cf >= 1,
        "beats_baseline":        bb is True,
    }
    failed = [k for k, v in gates.items() if not v]
    return {"passed": len(failed) == 0, "failed": failed, "gates": gates}


def promote(
    model_version: str,
    target_state: str,
    force: bool = False,
    promoted_by: str = "manual",
    promotion_reason: str = "",
) -> dict:
    """Advance lifecycle_state with gate validation (0335/0342).

    target_state: OBSERVE | PAPER_ACTIVE | RETIRED
    force=True skips gate checks (use for RETIRED).
    promoted_by: identifier for who/what triggered the promotion (0342).
    promotion_reason: free-text note captured at promotion time (0342).
    Returns {"promoted": bool, "new_state": str, "gates": dict}.
    """
    valid_transitions = {
        LIFECYCLE_TRAINED:      (LIFECYCLE_OBSERVE,),
        LIFECYCLE_OBSERVE:      (LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_RETIRED),
        LIFECYCLE_PAPER_ACTIVE: (LIFECYCLE_RETIRED,),
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

    if not force and target_state != LIFECYCLE_RETIRED:
        gate_result = _check_promotion_gates(model_version, target_state)
        if not gate_result["passed"]:
            conn.close()
            return {
                "promoted": False,
                "error": "gate_check_failed",
                "failed_gates": gate_result["failed"],
                "gates": gate_result["gates"],
            }
    else:
        gate_result = {"gates": {}}

    conn.execute(
        "UPDATE learning_models SET lifecycle_state=?, promotion_gates_json=? WHERE model_version=?",
        (target_state, json.dumps(gate_result["gates"]), model_version),
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
            json.dumps(gate_result["gates"]),
        ),
    )
    conn.commit()
    conn.close()
    return {"promoted": True, "new_state": target_state, "gates": gate_result["gates"]}


if __name__ == "__main__":
    import sys
    result = train_and_save()
    print(f"[calibration] {result}")
    sys.exit(0 if result.get("trained") else 1)
