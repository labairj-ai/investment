"""Single source of truth for strategy constants. All other modules import from here."""
import json
from pathlib import Path

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
