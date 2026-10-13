"""CC V3 Model Freeze and Change-Control Policy (0716/0718/0719).

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

BASELINE_SCHEMA_VERSION = 'cc-contract-v1'
BASELINE_REQUIRED_KEYS = frozenset({
    'schema_version', 'model_version', 'simulator_version',
    'simulator_contract_version', 'simulator_contract_hash',
    'engine_hash', 'policy_version', 'cadence_comparability_policy_version',
})

MANIFEST_REQUIRED_FIELDS = frozenset({
    'manifest_id', 'date', 'category', 'author', 'related_commit_or_pr',
    'prior_model_version', 'prior_simulator_version', 'prior_simulator_contract_version',
    'prior_simulator_contract_hash', 'prior_engine_hash',
    'proposed_model_version', 'proposed_simulator_version', 'proposed_simulator_contract_version',
    'proposed_simulator_contract_hash', 'proposed_engine_hash',
    'cohort_reset_required', 'open_chain_policy', 'operator_acknowledged',
})


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
    """Read the committed contract baseline.

    Returns None if no baseline file exists.
    Returns a dict with key 'malformed'=True if the file cannot be parsed or is missing required keys.
    Returns the baseline dict on success (includes 'schema_version').
    """
    if not BASELINE_FILE.exists():
        return None
    try:
        data = json.loads(BASELINE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(malformed=True, reason='JSON parse error')
    if not isinstance(data, dict):
        return dict(malformed=True, reason='baseline is not a JSON object')
    missing = BASELINE_REQUIRED_KEYS - set(data.keys())
    if missing:
        return dict(malformed=True, reason=f'missing required keys: {sorted(missing)}')
    if data.get('schema_version') != BASELINE_SCHEMA_VERSION:
        return dict(malformed=True, reason=f"unknown schema_version '{data.get('schema_version')}'")
    return data


def write_baseline(config):
    """Write current contract state as the new baseline. Call this when bumping versions."""
    state = current_contract_state(config)
    state['schema_version'] = BASELINE_SCHEMA_VERSION
    BASELINE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    return state


def list_manifests(manifests_dir=None):
    """Return paths of all non-template change manifests."""
    d = manifests_dir or MANIFESTS_DIR
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir()
                  if p.suffix == '.md' and not p.name.startswith('.'))


def parse_manifest(path):
    """Parse manifest front matter.

    Returns a dict containing all parsed key:value pairs from the front matter block,
    plus 'path' (the Path object). If parsing fails, includes 'parse_error' key.
    """
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError as e:
        return dict(path=path, parse_error=f'Cannot read file: {e}')
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return dict(path=path, parse_error='No front matter delimiter at start')
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == '---':
            end = i
            break
    if end is None:
        return dict(path=path, parse_error='No closing front matter delimiter')
    fm = {'path': path}
    for line in lines[1:end]:
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        k = key.strip()
        v = val.strip()
        if k:
            fm[k] = v
    return fm


def _manifest_valid(fm):
    """Return (is_valid, reasons) for a parsed manifest front matter."""
    if fm.get('parse_error'):
        return False, [f"parse_error: {fm['parse_error']}"]
    missing = MANIFEST_REQUIRED_FIELDS - set(fm.keys())
    if missing:
        return False, [f'missing required fields: {sorted(missing)}']
    empty = [k for k in MANIFEST_REQUIRED_FIELDS if not fm.get(k)]
    if empty:
        return False, [f'empty required fields: {sorted(empty)}']
    if fm.get('operator_acknowledged', '').lower() != 'true':
        return False, ['operator_acknowledged must be "true"']
    return True, []


def _manifest_applies(fm, baseline, current):
    """Return True if this manifest authorizes the transition baseline → current."""
    valid, _ = _manifest_valid(fm)
    if not valid:
        return False
    prior_match = (
        fm.get('prior_engine_hash') == baseline.get('engine_hash') and
        fm.get('prior_simulator_contract_hash') == baseline.get('simulator_contract_hash') and
        fm.get('prior_model_version') == baseline.get('model_version') and
        fm.get('prior_simulator_version') == baseline.get('simulator_version') and
        fm.get('prior_simulator_contract_version') == baseline.get('simulator_contract_version')
    )
    proposed_match = (
        fm.get('proposed_engine_hash') == current.get('engine_hash') and
        fm.get('proposed_simulator_contract_hash') == current.get('simulator_contract_hash') and
        fm.get('proposed_model_version') == current.get('model_version') and
        fm.get('proposed_simulator_version') == current.get('simulator_version') and
        fm.get('proposed_simulator_contract_version') == current.get('simulator_contract_version')
    )
    return prior_match and proposed_match


def find_applicable_manifests(baseline, current, manifests_dir=None):
    """Locate manifests authorizing the exact transition baseline → current.

    Returns:
      applicable     — list of parsed manifests that apply (ideally exactly 1)
      all_parsed     — list of all parsed manifests (for duplicate-id detection)
      duplicate_ids  — list of manifest_id values that appear more than once
    """
    paths = list_manifests(manifests_dir)
    all_parsed = [parse_manifest(p) for p in paths]
    applicable = [fm for fm in all_parsed if _manifest_applies(fm, baseline, current)]
    # Check for duplicate manifest_ids across all manifests
    ids = [fm.get('manifest_id') for fm in all_parsed if fm.get('manifest_id')]
    seen = set()
    duplicate_ids = [mid for mid in ids if mid in seen or seen.add(mid)]  # type: ignore[func-returns-value]
    return dict(applicable=applicable, all_parsed=all_parsed, duplicate_ids=duplicate_ids)


def check_contract_consistency(config):
    """Verify behavioral hash consistency against the baseline.

    Returns a dict with:
      ok                  — True if no issues found
      hash_changed        — whether engine_hash or simulator_contract_hash changed
      version_bumped      — whether simulator_contract_version changed
      has_manifest        — whether an applicable transition manifest was found
      applicable_manifest — parsed manifest dict (if exactly one found), else None
      findings            — list of issue strings (empty if ok)
      current             — current contract state
      baseline            — baseline state (or None)

    Rules enforced:
      1. Behavioral hash change without version bump → CI failure
      2. Behavioral hash change without transition-bound manifest → CI failure
      3. Duplicate applicable manifests → ambiguity failure
      4. Duplicate manifest_ids → CI failure
    """
    current = current_contract_state(config)
    baseline = read_baseline()
    findings = []

    if baseline is None:
        return dict(ok=False, hash_changed=False, version_bumped=False,
                    has_manifest=False, applicable_manifest=None,
                    baseline_missing=True,
                    findings=['MISSING_BASELINE: no .cc_contract_baseline.json committed. '
                              'Run: python scripts/check_cc_contract.py --update-baseline'],
                    current=current, baseline=None)

    if baseline.get('malformed'):
        return dict(ok=False, hash_changed=False, version_bumped=False,
                    has_manifest=False, applicable_manifest=None,
                    baseline_missing=False, baseline_malformed=True,
                    findings=[f"MALFORMED_BASELINE: {baseline.get('reason', 'unknown')}. "
                              'Delete and regenerate with: python scripts/check_cc_contract.py --update-baseline'],
                    current=current, baseline=baseline)

    hash_changed = (
        current['engine_hash'] != baseline.get('engine_hash') or
        current['simulator_contract_hash'] != baseline.get('simulator_contract_hash')
    )
    version_bumped = (
        current['simulator_contract_version'] != baseline.get('simulator_contract_version') or
        current['model_version'] != baseline.get('model_version') or
        current['simulator_version'] != baseline.get('simulator_version')
    )

    manifest_result = find_applicable_manifests(baseline, current)
    applicable = manifest_result['applicable']
    duplicate_ids = manifest_result['duplicate_ids']

    has_manifest = len(applicable) == 1
    applicable_manifest = applicable[0] if len(applicable) == 1 else None

    if duplicate_ids:
        findings.append(f'DUPLICATE_MANIFEST_IDS: manifest_id values used more than once: '
                        f'{sorted(set(duplicate_ids))}')

    if len(applicable) > 1:
        ids = [fm.get('manifest_id', str(fm['path'].name)) for fm in applicable]
        findings.append(f'DUPLICATE_APPLICABLE_MANIFESTS: {len(applicable)} manifests authorize '
                        f'this transition — ambiguous: {ids}')

    if hash_changed and not version_bumped:
        findings.append('BEHAVIORAL_HASH_CHANGED_WITHOUT_VERSION_BUMP: engine_hash or simulator_contract_hash '
                        'changed but no version constant was incremented. Increment SIMULATOR_CONTRACT_VERSION '
                        'or SIMULATOR_VERSION.')
    if hash_changed and not has_manifest:
        findings.append('BEHAVIORAL_HASH_CHANGED_WITHOUT_APPLICABLE_MANIFEST: a transition-bound manifest '
                        'is required that matches the exact prior→proposed contract state. '
                        'Copy cc_change_manifests/.template.md and fill in prior/proposed hashes.')

    return dict(
        ok=not findings,
        hash_changed=hash_changed,
        version_bumped=version_bumped,
        has_manifest=has_manifest,
        applicable_manifest=applicable_manifest,
        manifest_count=len(manifest_result['all_parsed']),
        baseline_missing=False,
        baseline_malformed=False,
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
