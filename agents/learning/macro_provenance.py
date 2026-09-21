"""Decision-time reads of accepted macro evidence; never modifies acceptance."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DIMS = ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk")
ET = ZoneInfo("America/New_York")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value, local=False):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET if local else timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def accepted_contract(conn, at):
    """Read the active pointer and immutable artifact from this same database."""
    import portfolio_ai as pai
    row = conn.execute("SELECT record_id,accepted_at,scorer_contract_hash FROM macro_acceptance_state "
                       "WHERE contract='macro_validation_v1'").fetchone()
    if not row or not row[0] or row[2] != pai._compute_scorer_contract_hash():
        return None
    accepted_at = timestamp(row[1])
    if accepted_at is None or accepted_at > at:
        return None
    # Acceptance stored timestamp is the validation start; prospective registration
    # below is the effective boundary and is always after actual activation.
    artifact_row = conn.execute("SELECT artifact_json FROM macro_validation_runs WHERE record_id=?", (row[0],)).fetchone()
    if not artifact_row:
        return None
    artifact = json.loads(artifact_row[0])
    if (artifact.get("activated") is not True or artifact.get("verdict") != "PASS"
            or artifact.get("run_type") != "acceptance" or artifact.get("scorer_contract_hash") != row[2]):
        return None
    return {"record_id": row[0], "accepted_at": accepted_at, "scorer_contract_hash": row[2],
            "config_version": artifact["validation_config_version"],
            "config_hash": artifact["validation_config_hash"], "model_identity": artifact["model_identity"]}


def snapshot(ticker, conn, at):
    """Freeze current eligibility and score provenance as known at decision time."""
    import portfolio_ai as pai
    snap = {"macro_supported": False, "coverage_state": "no_score_available",
            "usable_dimensions": [], "macro_validation_status": "PRE_ACCEPTANCE",
            "captured_at": at, "schema": "accepted_episode_v1"}
    try:
        acceptance = accepted_contract(conn, at)
        if acceptance:
            snap.update(macro_validation_status="ACCEPTED_CURRENT",
                        macro_validation_record_id=acceptance["record_id"],
                        macro_acceptance_record_id=acceptance["record_id"],
                        macro_config_version=acceptance["config_version"],
                        macro_config_hash=acceptance["config_hash"], acceptance=acceptance)
        if pai.is_fund(ticker):
            snap["coverage_state"] = "fund_unsupported"
            return snap
        row = conn.execute("SELECT scores,updated_at,run_id FROM holding_macro_scores WHERE ticker=?", (ticker,)).fetchone()
        if not row:
            return snap
        scores = json.loads(row[0])
        scored_at = timestamp(row[1], local=True)
        item = conn.execute("SELECT status,completed_at,scorer_contract_hash FROM macro_scoring_run_items WHERE run_id=? AND ticker=?", (row[2], ticker)).fetchone()
        completed_at = timestamp(item[1], local=True) if item else None
        snap.update({d: scores.get(d) for d in DIMS})
        snap.update(scorer_contract_hash=scores.get("scorer_contract_hash"),
                    prompt_hash=scores.get("prompt_hash"), evidence_hash=scores.get("evidence_hash"),
                    scored_at=row[1], macro_score_timestamp=scored_at, run_id=row[2],
                    model_version=scores.get("model_version"), evidence_quality=scores.get("evidence_quality"))
        if scored_at is None or scored_at + 1 > at:
            snap["coverage_state"] = "future_or_invalid_score"
        elif (not item or item[0] != "SUPPORTED" or completed_at is None
              or completed_at + 1 > at or item[2] != scores.get("scorer_contract_hash")):
            snap["coverage_state"] = "unavailable_run_provenance"
        elif at - scored_at > pai._STALE_SCORE_DAYS * 86400:
            snap["coverage_state"] = "stale_score"
        elif not acceptance:
            snap["coverage_state"] = "no_current_acceptance"
        elif scores.get("scorer_contract_hash") != acceptance["scorer_contract_hash"]:
            snap["coverage_state"] = "stale_scorer_contract"
        elif not all(scores.get(k) for k in ("prompt_hash", "evidence_hash", "model_version")):
            snap["coverage_state"] = "missing_provenance"
        elif scores["model_version"] != acceptance["model_identity"]:
            snap["coverage_state"] = "model_mismatch"
        else:
            snap.update(macro_supported=True, coverage_state="company_supported")
            snap["score_completed_at"] = completed_at
            states = {}
            for dim in DIMS:
                evidence = scores.get(pai._DIM_EV_KEY[dim], "none")
                state = conn.execute("SELECT eligible,config_hash,scorer_contract_hash,n_samples,model_identity "
                                     "FROM macro_dimension_validation WHERE acceptance_record_id=? AND ticker=? AND dimension=?",
                                     (acceptance["record_id"], ticker, dim)).fetchone()
                data = scores.get(dim)
                score = data.get("score") if isinstance(data, dict) else None
                valid = (isinstance(score, (float, int)) and not isinstance(score, bool)
                         and math.isfinite(score) and 1 <= score <= 10)
                usable = bool(valid and state and state[0] == 1 and state[1] == acceptance["config_hash"]
                              and state[2] == acceptance["scorer_contract_hash"] and state[3] == 20
                              and state[4] == acceptance["model_identity"]
                              and evidence in pai._EV_MIN_FOR_USABILITY[dim])
                states[dim] = {"usable": usable, "evidence_quality": evidence}
                snap[f"{dim}_usable_for_attribution"] = usable
                if usable:
                    snap["usable_dimensions"].append(dim)
            snap["dimension_eligibility"] = states
        return snap
    except (ValueError, KeyError, TypeError) as exc:
        snap.update(coverage_state="invalid_provenance", error=str(exc), usable_dimensions=[])
        return snap
