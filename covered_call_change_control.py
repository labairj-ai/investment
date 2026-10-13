"""CC V3 Model Freeze and Change-Control Policy (0716/0718/0719).

Three change categories:
  NON_BEHAVIORAL          — dashboard, docs, logging; no version bump needed
  EVIDENCE_INFRASTRUCTURE — reporting/provenance fixes, no decision behavior change
  BEHAVIORAL_MODEL_CHANGE — any change affecting decisions; requires version bump + manifest
"""
from __future__ import annotations
import json
import re
import subprocess
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


IDENTITY_FIELDS = BASELINE_REQUIRED_KEYS - {'schema_version'}
MANIFEST_REQUIRED_FIELDS |= frozenset(
    f'{side}_{field}' for side in ('prior', 'proposed') for field in IDENTITY_FIELDS)
VERSION_PATTERNS = {
    'model_version': r'cc-v((?:0|[1-9][0-9]*))\.((?:0|[1-9][0-9]*))',
    'simulator_version': r'cc-virtual-((?:0|[1-9][0-9]*))',
    'simulator_contract_version': r'simulator-contract-((?:0|[1-9][0-9]*))',
    'policy_version': r'shared-live-management-asof-((?:0|[1-9][0-9]*))',
    'cadence_comparability_policy_version': r'cadence-v((?:0|[1-9][0-9]*))',
}


def version_transition(field, prior, proposed):
    """Compare canonical numeric component versions without normalization."""
    a = re.fullmatch(VERSION_PATTERNS[field], prior or '')
    b = re.fullmatch(VERSION_PATTERNS[field], proposed or '')
    if not a or not b:
        return 'MALFORMED_VERSION'
    av, bv = tuple(map(int, a.groups())), tuple(map(int, b.groups()))
    return 'FORWARD' if bv > av else 'BACKWARD_VERSION' if bv < av else 'NO_VERSION_BUMP'


def baseline_at_ref(ref, repo):
    """Read an exact immutable Git commit baseline; no network or writes."""
    if not re.fullmatch(r'[0-9a-f]{40}', ref or ''):
        raise ValueError('trusted prior must be an exact 40-character commit SHA')
    result = subprocess.run(['git', 'show', f'{ref}:.cc_contract_baseline.json'],
                            cwd=repo, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('trusted prior baseline cannot be resolved')
    return validate_baseline_text(result.stdout)


def validate_baseline_text(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return dict(malformed=True, reason='JSON parse error')
    if not isinstance(data, dict) or not BASELINE_REQUIRED_KEYS <= data.keys():
        return dict(malformed=True, reason='missing required baseline fields')
    if data['schema_version'] != BASELINE_SCHEMA_VERSION:
        return dict(malformed=True, reason='unknown schema_version')
    if any(not isinstance(data[k], str) or not data[k] for k in BASELINE_REQUIRED_KEYS):
        return dict(malformed=True, reason='baseline fields must be non-empty strings')
    return data


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


def read_baseline(path=None):
    """Read the committed contract baseline.

    Returns None if no baseline file exists.
    Returns a dict with key 'malformed'=True if the file cannot be parsed or is missing required keys.
    Returns the baseline dict on success (includes 'schema_version').
    """
    bf = Path(path) if path else BASELINE_FILE
    if not bf.exists():
        return None
    try:
        return validate_baseline_text(bf.read_text())
    except OSError:
        return dict(malformed=True, reason='baseline read error')


def write_baseline(config, path=None):
    """Write current contract state as the new baseline. Call this when bumping versions."""
    state = current_contract_state(config)
    state['schema_version'] = BASELINE_SCHEMA_VERSION
    bf = Path(path) if path else BASELINE_FILE
    bf.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
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
            if k in fm:
                fm['parse_error'] = f'duplicate field: {k}'
            fm[k] = v
    for key in ('cohort_reset_required', 'operator_acknowledged'):
        if fm.get(key) in ('true', 'false'):
            fm[key] = fm[key] == 'true'
    return fm


def _manifest_valid(fm):
    """Return (is_valid, reasons) for a parsed manifest front matter."""
    if fm.get('parse_error'):
        return False, [f"parse_error: {fm['parse_error']}"]
    missing = MANIFEST_REQUIRED_FIELDS - set(fm.keys())
    if missing:
        return False, [f'missing required fields: {sorted(missing)}']
    reasons = []
    empty = [k for k in MANIFEST_REQUIRED_FIELDS if fm.get(k) in ('', None)]
    if empty:
        reasons.append(f'empty required fields: {sorted(empty)}')
    categories = (CHANGE_CATEGORY_NON_BEHAVIORAL, CHANGE_CATEGORY_EVIDENCE_INFRASTRUCTURE,
                  CHANGE_CATEGORY_BEHAVIORAL)
    if fm.get('category') not in categories:
        reasons.append(f'INVALID_CHANGE_CATEGORY: category expected {categories}')
    for key in ('cohort_reset_required', 'operator_acknowledged'):
        if type(fm.get(key)) is not bool:
            reasons.append(f'INVALID_BOOLEAN: {key} expected true or false')
    if fm.get('operator_acknowledged') is not True:
        reasons.append('OPERATOR_NOT_ACKNOWLEDGED: operator_acknowledged must be true')
    if fm.get('category') == CHANGE_CATEGORY_BEHAVIORAL and fm.get('cohort_reset_required') is not True:
        reasons.append('COHORT_RESET_REQUIRED: cohort_reset_required must be true for behavioral changes')
    # 0712 implements one survivability policy: censor old-version open chains.
    from covered_call_virtual import OPEN_CHAIN_POLICY
    OPEN_CHAIN_POLICIES = frozenset({OPEN_CHAIN_POLICY})
    if fm.get('open_chain_policy') not in OPEN_CHAIN_POLICIES:
        reasons.append(f'INVALID_OPEN_CHAIN_POLICY: open_chain_policy expected {sorted(OPEN_CHAIN_POLICIES)}')
    return not reasons, reasons


def _manifest_applies(fm, baseline, current):
    """Return True if this manifest authorizes the transition baseline → current."""
    valid, _ = _manifest_valid(fm)
    if not valid:
        return False
    return all(fm.get(f'{side}_{field}') == state.get(field)
               for side, state in (('prior', baseline), ('proposed', current))
               for field in IDENTITY_FIELDS)


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


def check_contract_consistency(config, *, _baseline_file=None, _manifests_dir=None,
                               trusted_prior_file=None, prior_ref=None, expected_prior_ref=None, repo=ROOT):
    """Verify behavioral hash consistency against the baseline.

    Returns a dict with:
      ok                  — True if no issues found
      hash_changed        — whether engine_hash or simulator_contract_hash changed
      version_bumped      — whether every required component moved forward
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
    candidate = read_baseline(_baseline_file)
    findings = []
    trusted = trusted_prior_file is not None or prior_ref is not None
    baseline = candidate
    if prior_ref:
        try:
            if expected_prior_ref and prior_ref != expected_prior_ref:
                raise ValueError('prior SHA differs from event authority')
            baseline = baseline_at_ref(prior_ref, repo)
        except ValueError as exc:
            baseline = dict(malformed=True, reason=str(exc))
    elif trusted_prior_file:
        baseline = read_baseline(trusted_prior_file)

    if baseline is None:
        return dict(ok=False, hash_changed=False, version_bumped=False,
                    has_manifest=False, applicable_manifest=None,
                    baseline_missing=True,
                    findings=['MISSING_BASELINE: no .cc_contract_baseline.json committed. '
                              'Run: python scripts/check_cc_contract.py --update-baseline'],
                    current=current, baseline=None, trusted_prior_ref=prior_ref)

    if baseline.get('malformed'):
        return dict(ok=False, hash_changed=False, version_bumped=False,
                    has_manifest=False, applicable_manifest=None,
                    baseline_missing=False, baseline_malformed=True,
                    findings=[f"MALFORMED_BASELINE: {baseline.get('reason', 'unknown')}. "
                              'Delete and regenerate with: python scripts/check_cc_contract.py --update-baseline'],
                    current=current, baseline=baseline, trusted_prior_ref=prior_ref)

    hash_changed = (
        current['engine_hash'] != baseline.get('engine_hash') or
        current['simulator_contract_hash'] != baseline.get('simulator_contract_hash')
    )
    required_components = []
    if current['engine_hash'] != baseline['engine_hash']:
        required_components.append('model_version')
    if current['simulator_contract_hash'] != baseline['simulator_contract_hash']:
        required_components.append('simulator_contract_version')
    version_bumped = bool(required_components) and all(
        version_transition(field, baseline[field], current[field]) == 'FORWARD'
        for field in required_components)


    manifest_result = find_applicable_manifests(baseline, current, _manifests_dir)
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

    protected_changed = any(current[k] != baseline[k] for k in IDENTITY_FIELDS)
    if trusted and candidate and candidate.get('malformed'):
        findings.append(f'MALFORMED_CANDIDATE_BASELINE: {candidate["reason"]}')
    if trusted and candidate != dict(current, schema_version=BASELINE_SCHEMA_VERSION):
        findings.append('CANDIDATE_BASELINE_MISMATCH: candidate must exactly equal computed current state; promotion required')
    for fm in manifest_result['all_parsed']:
        valid, reasons = _manifest_valid(fm)
        if not valid:
            findings.extend(f'{reason} ({fm["path"].name})' for reason in reasons)
    drivers = {
        'model_version': current['engine_hash'] != baseline['engine_hash'],
        'simulator_contract_version': current['simulator_contract_hash'] != baseline['simulator_contract_hash'],
        'simulator_version': current['simulator_contract_hash'] != baseline['simulator_contract_hash'],
        'policy_version': current['simulator_contract_hash'] != baseline['simulator_contract_hash'],
        'cadence_comparability_policy_version': current['simulator_contract_hash'] != baseline['simulator_contract_hash'],
    }
    for field, driver in drivers.items():
        changed = current[field] != baseline[field]
        required = driver and field in ('model_version', 'simulator_contract_version')
        if changed or required:
            rule = version_transition(field, baseline[field], current[field])
            if rule != 'FORWARD':
                findings.append(f'{rule}: {field} prior={baseline[field]} proposed={current[field]}; expected forward numeric transition')
            if changed and not driver:
                findings.append(f'UNJUSTIFIED_VERSION_DRIFT: {field} prior={baseline[field]} proposed={current[field]}; corresponding behavior unchanged')
    if protected_changed and not has_manifest and not hash_changed:
        findings.append('PROTECTED_STATE_CHANGED_WITHOUT_APPLICABLE_MANIFEST: exact transition authorization required')

    if hash_changed and not version_bumped:
        findings.append('BEHAVIORAL_HASH_CHANGED_WITHOUT_VERSION_BUMP: engine_hash or simulator_contract_hash '
                        'changed but no version constant was incremented. Increment SIMULATOR_CONTRACT_VERSION '
                        'or SIMULATOR_VERSION.')
    if hash_changed and not has_manifest:
        findings.append('BEHAVIORAL_HASH_CHANGED_WITHOUT_APPLICABLE_MANIFEST: a transition-bound manifest '
                        'is required that matches the exact prior→proposed contract state. '
                        'Copy cc_change_manifests/.template.md and fill in prior/proposed hashes.')

    if hash_changed:
        # ── 0720: category consistency ──────────────────────────────────────
        declared_category = applicable_manifest.get('category', '') if applicable_manifest else ''
        if declared_category == CHANGE_CATEGORY_NON_BEHAVIORAL:
            findings.append('CATEGORY_MISMATCH_NON_BEHAVIORAL: manifest declares NON_BEHAVIORAL but '
                            'engine_hash or simulator_contract_hash changed. '
                            'Reclassify as BEHAVIORAL_MODEL_CHANGE.')
        elif declared_category == CHANGE_CATEGORY_EVIDENCE_INFRASTRUCTURE:
            findings.append('CATEGORY_MISMATCH_EVIDENCE_INFRASTRUCTURE: manifest declares '
                            'EVIDENCE_INFRASTRUCTURE but engine_hash or simulator_contract_hash changed. '
                            'Reclassify as BEHAVIORAL_MODEL_CHANGE.')

        # ── 0720: component-specific version bump ───────────────────────────
        sim_hash_changed = current['simulator_contract_hash'] != baseline['simulator_contract_hash']
        engine_hash_changed = current['engine_hash'] != baseline['engine_hash']
        sim_ver_bumped = (
            current['simulator_contract_version'] != baseline.get('simulator_contract_version')
        )
        mdl_ver_bumped = current['model_version'] != baseline.get('model_version')

        if sim_hash_changed and not sim_ver_bumped:
            findings.append(
                'WRONG_COMPONENT_VERSION_BUMP: simulator_contract_hash changed but '
                'SIMULATOR_CONTRACT_VERSION was not incremented. '
                'Fill-model, management-policy, and virtual-execution changes require '
                'a SIMULATOR_CONTRACT_VERSION bump.')
        if engine_hash_changed and not sim_hash_changed and not mdl_ver_bumped:
            findings.append(
                'WRONG_COMPONENT_VERSION_BUMP: engine_hash changed (simulator_contract_hash unchanged) '
                'but model_version was not incremented. '
                'Utility/ranking changes require a model_version bump.')
        if engine_hash_changed and sim_hash_changed and not mdl_ver_bumped:
            findings.append(
                'WRONG_COMPONENT_VERSION_BUMP: both engine_hash and simulator_contract_hash changed; '
                'model_version bump is also required alongside SIMULATOR_CONTRACT_VERSION '
                'for multi-component changes.')

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
        trusted_prior_ref=prior_ref,
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
