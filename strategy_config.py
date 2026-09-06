"""Single source of truth for strategy constants. All other modules import from here."""
import json
import os
from pathlib import Path


class ConfigurationError(RuntimeError):
    pass

_cfg = json.loads((Path(__file__).parent / "config" / "strategy.json").read_text())

_layers = {int(k): v for k, v in _cfg["layers"].items()}

LAYER_NAMES: dict[int, str] = {n: d["name"] for n, d in _layers.items()}
LAYER_LABELS: dict[int, str] = {n: f"Layer {n}: {d['name']}" for n, d in _layers.items()}
LAYER_TARGETS: dict[int, float] = {n: d["target_pct"] for n, d in _layers.items()}
LAYER_COLORS: dict[int, str] = {n: d["color"] for n, d in _layers.items()}
LAYER_DESCRIPTIONS: dict[int, str] = {n: d["description"] for n, d in _layers.items()}

_cc = _cfg["covered_calls"]
CC_MIN_DTE: int = _cc["min_dte"]
CC_MAX_DTE: int = _cc["max_dte"]
CC_MAX_DTE_EXTENDED: int = _cc["extended_max_dte"]
CC_R_MIN: float = _cc["r_min"]
CC_R_FORWARD: float = _cc["r_forward"]
CC_EXEC_LAMBDA: float = _cc["exec_lambda"]
CC_MIN_BID: float = _cc["min_bid"]
CC_TOP_N: int = _cc["top_n"]
CC_MAX_STRIKE_MULTIPLIER: float = _cc["max_strike_multiplier"]

_risk = _cfg["risk"]
DRIFT_THRESHOLD: float = _risk["drift_threshold_pct"]
LAYER_GROSS_DOM: float = _risk["layer_gross_dom_pct"]
HOLDING_GROSS_DOM: float = _risk["holding_gross_dom_pct"]
SECTOR_CONCENTRATION_PCT: float = _risk.get("sector_concentration_pct", 35.0)
PORTFOLIO_BETA_HIGH: float = _risk.get("portfolio_beta_high", 1.4)
PORTFOLIO_BETA_LOW: float = _risk.get("portfolio_beta_low", 0.6)
RISK_CONTRIBUTION_MULTIPLE: float = _risk.get("risk_contribution_multiple", 2.0)
CORRELATION_CLUSTER_THRESHOLD: float = _risk.get("correlation_cluster_threshold", 0.75)
CORRELATION_CLUSTER_MIN_SIZE: int = int(_risk.get("correlation_cluster_min_size", 3))
COVARIANCE_LOOKBACK_DAYS: int = int(_risk.get("covariance_lookback_days", 60))

_trig = _cfg.get("triggers", {})
TRIGGER_PRICE_MOVE_Z: float = _trig.get("price_move_z_threshold", 2.0)
TRIGGER_NAV_IMPACT_PCT: float = _trig.get("nav_impact_threshold_pct", 0.35)
TRIGGER_MACRO_SCORE_CHANGE: int = _trig.get("macro_score_change_threshold", 2)
TRIGGER_CC_MGMT_DTE: int = _trig.get("cc_mgmt_dte", 21)
TRIGGER_TAX_LT_WINDOW_MIN: int = _trig.get("tax_lot_lt_window_days_min", 30)
TRIGGER_TAX_LT_WINDOW_MAX: int = _trig.get("tax_lot_lt_window_days_max", 45)
TRIGGER_TAX_LOSS_MIN: float = _trig.get("tax_loss_min_dollars", 500.0)
TRIGGER_LAYER_UNDERWEIGHT_DAYS: int = _trig.get("layer_underweight_days", 3)
TAX_ST_RATE: float = _trig.get("st_tax_rate", 0.37)


_urg = _cfg.get("urgency", {})
URGENCY_URGENT_THRESHOLD: float = _urg.get("urgent_threshold", 0.72)
URGENCY_ATTENTION_THRESHOLD: float = _urg.get("attention_threshold", 0.30)
URGENCY_SEVERITY: dict[str, float] = _urg.get("severity", {})


def validate_config() -> None:
    """Raise ConfigurationError if strategy.json contains invalid values."""
    errors = []

    # Layer targets must sum to 100
    target_sum = sum(LAYER_TARGETS.values())
    if abs(target_sum - 100.0) > 0.01:
        errors.append(
            f"Layer targets sum to {target_sum:.4f}% — must be 100.0% "
            f"(layers: {LAYER_TARGETS})"
        )

    # Each target must be positive
    for n, t in LAYER_TARGETS.items():
        if t <= 0:
            errors.append(f"Layer {n} target_pct must be positive, got {t}")

    # All 5 layers must be defined
    for n in range(1, 6):
        if n not in LAYER_TARGETS:
            errors.append(f"Layer {n} is missing from config")

    # CC DTE ordering
    if CC_MIN_DTE >= CC_MAX_DTE:
        errors.append(
            f"CC min_dte ({CC_MIN_DTE}) must be less than max_dte ({CC_MAX_DTE})"
        )
    if CC_MAX_DTE >= CC_MAX_DTE_EXTENDED:
        errors.append(
            f"CC max_dte ({CC_MAX_DTE}) must be less than extended_max_dte ({CC_MAX_DTE_EXTENDED})"
        )

    # CC r_min must be a sensible fraction
    if not (0 < CC_R_MIN < 1):
        errors.append(f"CC r_min must be in (0, 1), got {CC_R_MIN}")

    # Risk thresholds must be positive
    if DRIFT_THRESHOLD <= 0:
        errors.append(f"drift_threshold_pct must be positive, got {DRIFT_THRESHOLD}")
    if LAYER_GROSS_DOM <= 0:
        errors.append(f"layer_gross_dom_pct must be positive, got {LAYER_GROSS_DOM}")
    if HOLDING_GROSS_DOM <= 0:
        errors.append(f"holding_gross_dom_pct must be positive, got {HOLDING_GROSS_DOM}")

    if errors:
        msg = "strategy.json is invalid:\n" + "\n".join(f"  • {e}" for e in errors)
        raise ConfigurationError(msg)


if not os.environ.get("SKIP_CONFIG_VALIDATION"):
    validate_config()
