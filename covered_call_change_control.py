"""CC V3 Model Freeze and Change-Control Policy (0716).

Three change categories:
  NON_BEHAVIORAL          — dashboard, docs, logging; no version bump needed
  EVIDENCE_INFRASTRUCTURE — reporting/provenance fixes, no decision behavior change
  BEHAVIORAL_MODEL_CHANGE — any change affecting decisions; requires version bump + manifest
"""
from __future__ import annotations
import json
from pathlib import Path

from covered_call_validation import management_contract

ROOT = Path(__file__).resolve().parent
BASELINE_FILE = ROOT / '.cc_contract_baseline.json'
MANIFESTS_DIR = ROOT / 'cc_change_manifests'

CHANGE_CATEGORY_NON_BEHAVIORAL = 'NON_BEHAVIORAL'
CHANGE_CATEGORY_EVIDENCE_INFRASTRUCTURE = 'EVIDENCE_INFRASTRUCTURE'
CHANGE_CATEGORY_BEHAVIORAL = 'BEHAVIORAL_MODEL_CHANGE'


def current_contract_state(config):
    """Return current contract identity dict."""
    from covered_call_virtual import SIMULATOR_VERSION, SIMULATOR_CONTRACT_VERSION, simulator_contract_hash
    from covered_call_validation import CADENCE_COMPARABILITY_POLICY_VERSION
    from covered_call_v3 import VERSION as MODEL_VERSION
    mc = management_contract()
    return dict(
        model_version=MODEL_VERSION,
        simulator_version=SIMULATOR_VERSION,
        simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        simulator_contract_hash=simulator_contract_hash(config),
        engine_hash=mc['engine_hash'],
        policy_version=mc['policy_version'],
        cadence_comparability_policy_version=CADENCE_COMPARABILITY_POLICY_VERSION,
    )


def read_baseline():
    """Read the committed contract baseline. Returns None if no baseline exists."""
    if not BASELINE_FILE.exists():
        return None
    return json.loads(BASELINE_FILE.read_text())


def write_baseline(config):
    """Write current contract state as the new baseline. Call this when bumping versions."""
    state = current_contract_state(config)
    BASELINE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    return state


def list_manifests():
    """Return paths of all non-template change manifests in cc_change_manifests/."""
    if not MANIFESTS_DIR.exists():
        return []
    return sorted(p for p in MANIFESTS_DIR.iterdir()
                  if p.suffix == '.md' and not p.name.startswith('.'))


def check_contract_consistency(config):
    """Verify behavioral hash consistency against the baseline.

    Returns a dict with:
      ok          — True if no issues found
      hash_changed — whether engine_hash or simulator_contract_hash changed
      version_bumped — whether simulator_contract_version changed
      has_manifest — whether a change manifest exists
      findings     — list of issue strings (empty if ok)
      current      — current contract state
      baseline     — baseline state (or None)

    Rules enforced:
      1. Behavioral hash change without version bump → CI failure
      2. Behavioral hash change without manifest    → CI failure
      3. Non-behavioral declared change that changed behavior hash → CI failure
    """
    current = current_contract_state(config)
    baseline = read_baseline()
    findings = []

    if baseline is None:
        return dict(ok=True, hash_changed=False, version_bumped=False,
                    has_manifest=False, findings=[], current=current, baseline=None,
                    note='No baseline on file — run write_baseline() after first deployment.')

    hash_changed = (
        current['engine_hash'] != baseline.get('engine_hash') or
        current['simulator_contract_hash'] != baseline.get('simulator_contract_hash')
    )
    version_bumped = (
        current['simulator_contract_version'] != baseline.get('simulator_contract_version') or
        current['model_version'] != baseline.get('model_version') or
        current['simulator_version'] != baseline.get('simulator_version')
    )
    manifests = list_manifests()
    has_manifest = bool(manifests)

    if hash_changed and not version_bumped:
        findings.append('BEHAVIORAL_HASH_CHANGED_WITHOUT_VERSION_BUMP: engine_hash or simulator_contract_hash '
                        'changed but no version constant was incremented. Increment SIMULATOR_CONTRACT_VERSION '
                        'or SIMULATOR_VERSION.')
    if hash_changed and not has_manifest:
        findings.append('BEHAVIORAL_HASH_CHANGED_WITHOUT_MANIFEST: a change manifest is required in '
                        'cc_change_manifests/ for any behavioral change. Copy .template.md and fill it out.')

    return dict(
        ok=not findings,
        hash_changed=hash_changed,
        version_bumped=version_bumped,
        has_manifest=has_manifest,
        manifest_count=len(manifests),
        findings=findings,
        current=current,
        baseline=baseline,
    )


def experiment_version_info(config, path=None):
    """Return dashboard-facing experiment version metadata."""
    from covered_call_validation import certification
    from covered_call_ledger import connect, migrate
    cert = certification(config, path)
    db = connect(path)
    migrate(db)
    # Cohort start date: earliest prospective decision under current config
    from covered_call_ledger import config_digest
    current_hash = config_digest(config)
    row = db.execute(
        'SELECT MIN(timestamp) as start FROM cc_decisions WHERE config_hash=? AND prospective=1',
        (current_hash,)
    ).fetchone()
    cohort_start = row['start'] if row and row['start'] else None
    # Days since last behavioral reset: days since cohort_start
    reset_row = db.execute(
        'SELECT COUNT(DISTINCT config_hash) as reset_count FROM cc_decisions WHERE prospective=1'
    ).fetchone()
    reset_count = reset_row['reset_count'] if reset_row else 0
    from time_utils import now_utc, parse_timestamp
    if cohort_start:
        days_since_reset = (now_utc() - parse_timestamp(cohort_start)).days
    else:
        days_since_reset = None
    db.close()
    from covered_call_virtual import SIMULATOR_VERSION, SIMULATOR_CONTRACT_VERSION
    from covered_call_v3 import VERSION as MODEL_VERSION
    return dict(
        model_version=MODEL_VERSION,
        simulator_version=SIMULATOR_VERSION,
        simulator_contract_version=SIMULATOR_CONTRACT_VERSION,
        cohort_start_date=cohort_start,
        days_since_behavioral_reset=days_since_reset,
        config_version_reset_count=reset_count,
        certification_id=cert['id'] if cert else None,
        certified=cert is not None,
    )
