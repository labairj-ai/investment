"""0795: missing metrics stay missing at the strict JSON boundary."""
import json
import math

import pytest

from agents.covered_call_agent import _safe_float, _sanitize_payload


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), None, "missing"])
def test_unavailable_numeric_metrics_do_not_become_fabricated_zero(value):
    assert _safe_float(value) is None


@pytest.mark.parametrize("value,expected", [(0, 0.0), (-1.25, -1.25), ("2.5", 2.5)])
def test_finite_numeric_metrics_keep_their_value(value, expected):
    assert _safe_float(value) == expected


def test_nested_entry_and_management_payloads_are_strict_json_without_input_mutation():
    payload = {
        "action": "ROLL_OUT", "strike": 110.5, "contracts": 2,
        "exec_premium": float("nan"), "cc_alpha": -float("inf"),
        "challenger": {"regret_prob": float("inf"), "eligible": False},
        "v3_utility": {"expected_tax_cost": None, "expected_execution_cost": 0.125},
        "candidates": [{"delta": float("nan"), "contract_id": "TEST:20261120:110"}],
    }
    cleaned = _sanitize_payload(payload)
    persisted = json.loads(json.dumps(cleaned, allow_nan=False))
    assert persisted == {
        "action": "ROLL_OUT", "strike": 110.5, "contracts": 2,
        "exec_premium": None, "cc_alpha": None,
        "challenger": {"regret_prob": None, "eligible": False},
        "v3_utility": {"expected_tax_cost": None, "expected_execution_cost": 0.125},
        "candidates": [{"delta": None, "contract_id": "TEST:20261120:110"}],
    }
    assert math.isnan(payload["exec_premium"])
    assert math.isinf(payload["challenger"]["regret_prob"])
    assert math.isnan(payload["candidates"][0]["delta"])
    assert _sanitize_payload(cleaned) == cleaned
