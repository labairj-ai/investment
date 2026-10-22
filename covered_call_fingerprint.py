"""Named CC behavior inventories and deterministic source-only fingerprints.

No protected module is imported or executed. AST identity omits comments,
docstrings, locations and empty interpreter-added fields. Runtime monkeypatches
and live data cannot change source identity. Review inventory() for diagnostics.
"""
from __future__ import annotations
import ast
import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FINGERPRINT_VERSION = 'cc-behavior-v1'
LEGACY_FINGERPRINT_VERSION = 'cc-behavior-v0'
# Frozen AST identities of the legacy fingerprint definitions, not behavior digests.
LEGACY_DEFINITION_IDENTITIES = {'covered_call_virtual.management_contract': 'b63cde27006fed4f0129ab3ba30d3d2fdf2e4a332a3f96bdaddea95e3b7c0676', 'covered_call_virtual.simulator_contract_hash': 'cf5df2dc23caf33bdda4fa46120d0183d1a5dab5ab957dab5bc99ab3f0542dab'}


def _names(module, names):
    return tuple(f'{module}.{name}' for name in names.split())


MODEL_BEHAVIOR_FUNCTIONS = (
    *_names('covered_call_v3', 'bounded drift_model touch_probability path_oracle path_metrics eligibility surface regime_model overwrite execution tax_metrics utility divergence prepare'),
    *_names('covered_call_surface', 'valid_points interpolate_delta candidate_metrics surface_v2 duration_adjust'),
    *_names('covered_call_rec', '_yf_retry _norm_cdf _norm_pdf _bs_d1d2 call_delta call_gamma bs_call_price call_extrinsic itm_prob_rn itm_prob_real expected_upside_lost regret_prob _estimate_drift compute_vol_model _exec_premium _spread_pct _safe_int _liquidity_score _clears_profit_floor _expiry_implied_move get_risk_events normalize_ticker load_holdings _market_price _compute_opp_score _compute_scores analyze _lot_tax_friction _check_assignment_eligible _build_mgmt_context_from_db evaluate_cc_management_state evaluate_cc_roll_chain _remaining_call_alpha _friction_at_expiry _suggest_next_call _capture_quote_rows evaluate_open_position'),
    *_names('tax_utils', 'lt_threshold is_long_term days_until_lt'),
    *_names('agent_db', 'select_fifo_lots'),
    *_names('portfolio_positions', '_normalize load_positions get_position get_lots'),
    *_names('covered_call_ledger', 'surface_history execution_history active_scorer promotion_evidence transition'),
    *_names('agents.covered_call_agent', '_safe_float _sanitize_payload _decision_inputs _row_input_failures _insufficient_inputs _has_open_cc _get_open_cc_position _get_cc_policy _make_contract_id _build_candidates _build_evidence _analyze_roll _mgmt_iv_at_rec _build_mgmt_deps _analyze_ticker run_covered_call_agent'),
    *_names('time_utils', 'parse_timestamp now_utc now_utc_iso now_eastern today_eastern'),
)
SIMULATOR_BEHAVIOR_FUNCTIONS = (
    *_names('covered_call_virtual', 'migrate stamp enforce_asof store_snapshot state write_state fill_model start_from_decision context_for evaluate_snapshot record_interval terminal_outcome censor_version_mismatch missed_intervals advance metrics'),
    *_names('covered_call_rec', '_yf_retry _norm_cdf _norm_pdf _bs_d1d2 call_delta itm_prob_real expected_upside_lost _exec_premium _check_assignment_eligible evaluate_cc_management_state _remaining_call_alpha _friction_at_expiry _suggest_next_call _capture_quote_rows'),
    *_names('covered_call_v3', 'bounded execution'),
    *_names('tax_utils', 'lt_threshold is_long_term days_until_lt'),
    *_names('covered_call_outcomes', 'digest validate migrate persist latest contract base'),
    *_names('covered_call_ledger', 'clean config_digest encode record_episode calibration migrate reconcile_chain execution_history'),
    *_names('covered_call_evidence', 'committed_policy create_decision_contract classify_label _selected_id migrate_legacy no_call pair_outcomes promotion_report'),
    *_names('covered_call_validation', 'current_git_sha _config_contract_hash migrate normalize_action _generate_cadence_slots classify_cadence_comparability compare divergence_category acceptance replay run_validation certify certification record_actual_evaluation record_actual_fill'),
    *_names('time_utils', 'parse_timestamp now_utc now_utc_iso now_eastern today_eastern'),
)
MODEL_BEHAVIOR_TYPES = (*_names('covered_call_rec', 'TaxFrictionDetail ManagementPolicyContext'), *_names('portfolio_positions', 'Lot Position'))
SIMULATOR_BEHAVIOR_TYPES = (*_names('covered_call_rec', 'TaxFrictionDetail ManagementPolicyContext'), 'covered_call_virtual.DataUnavailable', 'covered_call_outcomes.OutcomeSource')
MODEL_BEHAVIOR_CONSTANTS = (
    'covered_call_v3.N', 'covered_call_surface.VERSION', 'portfolio_positions._TICKER_ALIASES',
    *_names('agents.covered_call_agent', '_SYSTEM _SCHEMA _PROMPT_VERSION _CC_ELIGIBLE_LAYERS _CC_MIN_SHARES'),
    *_names('covered_call_rec', 'RISK_FREE_RATE DRIFT_WEIGHT_60D DRIFT_WEIGHT_252D DRIFT_WEIGHT_MKT DRIFT_MKT_LONG_RUN DRIFT_CAP MIN_DTE MAX_DTE MAX_DTE_EXTENDED R_MIN R_FORWARD EXEC_LAMBDA MIN_BID TOP_N MAX_STRIKE_MULTIPLIER TAX_ST_RATE TAX_LT_RATE CC_ASSIGNMENT_TAX_FRICTION_THRESHOLD'),
    *_names('time_utils', 'TZ_UTC TZ_EASTERN'),
)
SIMULATOR_BEHAVIOR_CONSTANTS = (
    *_names('covered_call_virtual', 'OPEN_CHAIN_POLICY SIMULATOR_VERSION SIMULATOR_CONTRACT_VERSION POLICY_VERSION'),
    *_names('covered_call_rec', 'RISK_FREE_RATE EXEC_LAMBDA TAX_ST_RATE TAX_LT_RATE CC_ASSIGNMENT_TAX_FRICTION_THRESHOLD'),
    'covered_call_outcomes.PROVENANCE_VERSION', 'covered_call_evidence.CHAIN_FIELDS',
    *_names('covered_call_validation', 'CADENCE_COMPARABILITY_POLICY_VERSION _MARKET_OPEN_HOUR _MARKET_CLOSE_HOUR'),
    *_names('time_utils', 'TZ_UTC TZ_EASTERN'),
)
MODEL_CONFIG_KEYS = (
    'mode', 'preferred_dte_bands', 'path_count', 'management_cost_per_contract', 'fee_per_contract', 'fill_prior',
    'fill_min_n', 'fill_prior_strength', 'utility_hurdle_annual_pct',
    'max_regret_probability', 'regime_enabled', 'max_overwrite_fraction',
    'duration_utility.version', 'duration_utility.flexibility_lambda',
    'duration_utility.second_cycle_availability', 'duration_utility.second_cycle_alpha_retention',
)
SIMULATOR_CONFIG_KEYS = (
    'management_cost_per_contract', 'fee_per_contract', 'fill_prior', 'fill_min_n', 'fill_prior_strength',
    'virtual.version', 'virtual.creation_grace_seconds', 'virtual.maximum_quote_age_seconds',
    'virtual.cadence_minutes', 'virtual.maximum_missing_intervals',
    'promotion.version', 'promotion.minimum_n', 'promotion.minimum_divergent_n', 'promotion.minimum_days',
    'promotion.max_brier', 'promotion.max_assignment_violations', 'promotion.minimum_alpha_improvement',
    'promotion.max_roll_rate_increase', 'promotion.max_management_cost_increase', 'promotion.max_execution_cost_increase',
    'simulator_validation.version', 'simulator_validation.minimum_n', 'simulator_validation.maximum_entry_spread_error',
    'simulator_validation.minimum_action_agreement', 'simulator_validation.maximum_median_timing_sessions',
    'simulator_validation.minimum_roll_type_agreement', 'simulator_validation.maximum_alpha_absolute_error',
    'simulator_validation.maximum_alpha_relative_error',
)
# Not inferred from module contents: additions require a classification decision.
NONBEHAVIORAL_FUNCTIONS = {
    'covered_call_rec.print_report': 'Console rendering only.',
    'covered_call_rec.ai_context': 'Operator narrative, no recommendation selection.',
    'covered_call_rec.main': 'Console orchestration of already protected analyze().',
    'covered_call_virtual.management_contract': 'Fingerprint composition, covered by definition identity.',
    'covered_call_virtual.simulator_contract_hash': 'Fingerprint composition, covered by definition identity.',
}
GUARDED_MODULES = ('covered_call_v3', 'covered_call_virtual', 'covered_call_rec', 'covered_call_surface', 'tax_utils', 'covered_call_outcomes', 'covered_call_evidence', 'covered_call_validation', 'portfolio_positions', 'agents.covered_call_agent')
DEFINITION_COMPONENTS = (
    'covered_call_fingerprint.canonical_node', 'covered_call_fingerprint.stable_digest',
    'covered_call_fingerprint._parse_module', 'covered_call_fingerprint.validate_registry',
    'covered_call_fingerprint.canonical_value', 'covered_call_fingerprint.audit_bindings', 'covered_call_fingerprint._binding_declarations',
    'covered_call_fingerprint.SourceCatalog', 'covered_call_fingerprint.config_subset',
    'covered_call_fingerprint.fingerprint_payload', 'covered_call_fingerprint.model_fingerprint',
    'covered_call_fingerprint.simulator_fingerprint',
    'covered_call_virtual.management_contract', 'covered_call_virtual.simulator_contract_hash',
)


def canonical_node(node):
    """Portable named AST fields; no repr, locations, comments or docstrings."""
    if isinstance(node, ast.AST):
        fields = {}
        for field, value in ast.iter_fields(node):
            if field == 'type_params' and not value:
                continue  # Python 3.12 adds this empty field to ordinary defs/classes.
            if field == 'body' and isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if value and isinstance(value[0], ast.Expr) and isinstance(value[0].value, ast.Constant) and isinstance(value[0].value.value, str):
                    value = value[1:]
            fields[field] = canonical_node(value)
        return {'node': type(node).__name__, 'fields': fields}
    if isinstance(node, list):
        return [canonical_node(item) for item in node]
    if node is None or type(node) in (str, int, float, bool):
        return node
    raise ValueError('unsupported canonical AST value')



def canonical_value(value):
    """Serialize only explicit constant data, including named set membership."""
    if isinstance(value, (set, frozenset)):
        values = [canonical_value(item) for item in value]
        return {'set': sorted(values, key=lambda item: json.dumps(item, sort_keys=True))}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('protected constant mapping keys must be strings')
        return {key: canonical_value(item) for key, item in value.items()}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError('unsupported protected constant data')


def stable_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()


@lru_cache(maxsize=64)
def _parse_module(text):
    return ast.parse(text)


def audit_bindings(module, tree):
    """A declaration cannot be silently replaced by module initialization code."""
    declared = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            names = {n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)}
            if names & declared:
                raise ValueError(f'REBOUND_BEHAVIOR_COMPONENT: {module}: {sorted(names & declared)}')
            if module in GUARDED_MODULES and any(not isinstance(t, ast.Name) for t in targets):
                raise ValueError(f'UNCLASSIFIED_INITIALIZER: mutable module binding in {module}')
            if module in GUARDED_MODULES and isinstance(getattr(statement, 'value', None), ast.Lambda):
                raise ValueError(f'UNCLASSIFIED_INITIALIZER: anonymous callback in {module}; use a named classified function')
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            names = {alias.asname or alias.name.split('.')[0] for alias in statement.names}
            if names & declared:
                raise ValueError(f'REBOUND_BEHAVIOR_COMPONENT: imported override in {module}')
        elif module in GUARDED_MODULES and isinstance(statement, ast.If):
            expected = ast.parse("if __name__ == '__main__': main()").body[0]
            if canonical_node(statement) != canonical_node(expected):
                raise ValueError(f'UNCLASSIFIED_INITIALIZER: conditional module execution in {module}')
        elif module in GUARDED_MODULES and isinstance(statement, ast.Expr):
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                continue
            call = statement.value
            warning_only = (module == 'covered_call_rec' and isinstance(call, ast.Call) and
                            isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and
                            call.func.value.id == 'warnings' and call.func.attr in ('filterwarnings', 'simplefilter') and
                            all(isinstance(arg, ast.Constant) for arg in call.args) and
                            all(isinstance(arg.value, ast.Constant) for arg in call.keywords))
            registration = (module == 'agents.covered_call_agent' and
                            canonical_node(statement) == canonical_node(ast.parse(
                                "register_agent('covered_call', run_covered_call_agent)").body[0]))
            if not warning_only and not registration:
                raise ValueError(f'UNCLASSIFIED_INITIALIZER: module execution in {module}')



@lru_cache(maxsize=64)
def _binding_declarations(tree):
    """Index immutable parsed declarations once, without serializing cache identity."""
    bound = {}
    for statement in tree.body:
        for node in ast.walk(statement):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = {item.id for target in targets for item in ast.walk(target) if isinstance(item, ast.Name)}
                for name in names:
                    bound.setdefault(name, []).append(node)
        if isinstance(statement, ast.Expr):
            for name in {n.id for n in ast.walk(statement) if isinstance(n, ast.Name)}:
                bound.setdefault(name, []).append(statement)
    return bound



class SourceCatalog:
    """Read a checkout or immutable Git ref; never execute its modules."""
    def __init__(self, root=ROOT, ref=None):
        self.root = Path(root)
        self.ref = ref
        self._texts = {}
        if ref is not None and not re.fullmatch(r'[0-9a-f]{40}', ref):
            raise ValueError('source authority must be an exact Git SHA')

    def text(self, relative):
        if relative not in self._texts:
            if self.ref:
                result = subprocess.run(['git', 'show', f'{self.ref}:{relative}'], cwd=self.root,
                                        capture_output=True, text=True)
                if result.returncode:
                    raise ValueError(f'missing trusted source: {relative}')
                self._texts[relative] = result.stdout
            else:
                self._texts[relative] = (self.root / relative).read_text(encoding='utf-8')
        return self._texts[relative]

    def tree(self, module):
        if not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*', module):
            raise ValueError('invalid canonical module identifier')
        return _parse_module(self.text(module.replace('.', '/') + '.py'))

    def node(self, identifier):
        if not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.[A-Za-z_][A-Za-z0-9_]*', identifier):
            raise ValueError('invalid canonical component identifier')
        module, name = identifier.rsplit('.', 1)
        audit_bindings(module, self.tree(module))
        matches = [node for node in self.tree(module).body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name]
        if len(matches) != 1:
            raise ValueError(f'missing or duplicate canonical component: {identifier}')
        return matches[0]

    def component(self, identifier):
        node = self.node(identifier)
        module = identifier.rsplit('.', 1)[0]
        loaded = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        bindings = {}
        for item in self.tree(module).body:
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                for alias in item.names:
                    local = alias.asname or alias.name.split('.')[0]
                    if local in loaded:
                        bindings[local] = {'module': getattr(item, 'module', None), 'name': alias.name,
                                           'level': getattr(item, 'level', 0)}
        return {'source': canonical_node(node), 'import_bindings': bindings}

    def value(self, identifier):
        module, name = identifier.rsplit('.', 1)
        tree = self.tree(module)
        for item in tree.body:
            if isinstance(item, ast.ImportFrom):
                for alias in item.names:
                    if (alias.asname or alias.name) == name and item.module in ('strategy_config', 'time_utils'):
                        return self.value(f'{item.module}.{alias.name}')
        assignments = {}
        for item in tree.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = item.value
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                assignments[item.target.id] = item.value
        def evaluate(node):
            if isinstance(node, ast.Name):
                if node.id == '_cfg' and module == 'strategy_config':
                    return json.loads(self.text('config/strategy.json'))
                if node.id in assignments:
                    return evaluate(assignments[node.id])
            if isinstance(node, ast.Subscript):
                index = node.slice.value if isinstance(node.slice, ast.Index) else node.slice
                return evaluate(node.value)[evaluate(index)]
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
                    return evaluate(node.func.value).get(*(evaluate(x) for x in node.args))
                if isinstance(node.func, ast.Name) and node.func.id in ('int', 'float', 'bool'):
                    return {'int': int, 'float': float, 'bool': bool}[node.func.id](*(evaluate(x) for x in node.args))
                if isinstance(node.func, ast.Name) and node.func.id == 'NormalDist':
                    args = [evaluate(x) for x in node.args]
                    kwargs = {x.arg: evaluate(x.value) for x in node.keywords}
                    if len(args) > 2 or set(kwargs) - {'mu', 'sigma'}:
                        raise ValueError('unsupported distribution constant')
                    return {'distribution': 'NormalDist', 'mu': kwargs.get('mu', args[0] if args else 0.0),
                            'sigma': kwargs.get('sigma', args[1] if len(args)>1 else 1.0)}
                if isinstance(node.func, ast.Name) and node.func.id == 'ZoneInfo':
                    return {'timezone': evaluate(node.args[0])}
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == 'timezone' and node.attr == 'utc':
                return {'timezone': 'UTC'}
            try:
                return ast.literal_eval(node)
            except (ValueError, TypeError):
                raise ValueError(f'noncanonical protected constant: {identifier}')
        if name not in assignments:
            raise ValueError(f'missing protected constant: {identifier}')
        return canonical_value(evaluate(assignments[name]))


    def constant_component(self, identifier):
        """Bind the serialized value to its declarative source dependencies."""
        bindings = {}
        def record(module, name):
            key = f'{module}.{name}'
            if key in bindings:
                return
            bindings[key] = []
            tree = self.tree(module)
            declarations = _binding_declarations(tree)
            for statement in tree.body:
                if isinstance(statement, ast.ImportFrom):
                    for alias in statement.names:
                        if (alias.asname or alias.name) == name:
                            bindings[key].append({'import': statement.module, 'name': alias.name, 'level': statement.level})
                            if statement.module in ('strategy_config', 'time_utils'):
                                record(statement.module, alias.name)
            for node in declarations.get(name, ()):
                bindings[key].append(canonical_node(node))
                value = getattr(node, 'value', None)
                if value is not None:
                    for used in ast.walk(value):
                        if isinstance(used, ast.Name) and used.id != name and used.id in declarations:
                            record(module, used.id)
        module, name = identifier.rsplit('.', 1)
        record(module, name)
        return {'value': self.value(identifier), 'declarations': bindings}


def config_subset(config, keys):
    """Support the runtime flat config and historical cc_v3 wrapper explicitly."""
    if 'cc_v3' in config and any(key.split('.')[0] in config for key in keys):
        raise ValueError('ambiguous mixed flat/wrapped behavioral config')
    config = config.get('cc_v3', config)
    subset = {}
    for key in sorted(keys):
        value = config
        for part in key.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        subset[key] = value
    return subset


def validate_registry(names, provider):
    if len(names) != len(set(names)):
        raise ValueError('duplicate canonical registry name')
    for name in names:
        provider.node(name)


def classification_findings(provider=None, *, model=None, simulator=None, exclusions=None):
    provider = provider or SourceCatalog()
    model = MODEL_BEHAVIOR_FUNCTIONS if model is None else model
    simulator = SIMULATOR_BEHAVIOR_FUNCTIONS if simulator is None else simulator
    exclusions = NONBEHAVIORAL_FUNCTIONS if exclusions is None else exclusions
    classified = set(model) | set(simulator) | set(exclusions) | set(MODEL_BEHAVIOR_TYPES) | set(SIMULATOR_BEHAVIOR_TYPES)
    findings = []
    for module in GUARDED_MODULES:
        actual = {f'{module}.{node.name}' for node in provider.tree(module).body
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        findings.extend(f'UNCLASSIFIED_FUNCTION: {name}' for name in sorted(actual-classified))
        known = {name for name in classified if name.rsplit('.', 1)[0] == module}
        findings.extend(f'MISSING_CLASSIFIED_FUNCTION: {name}' for name in sorted(known-actual))
    return findings


def fingerprint_payload(config, functions, constants, types, keys, provider=None):
    provider = provider or SourceCatalog()
    validate_registry((*functions, *types), provider)
    if len(constants) != len(set(constants)) or len(keys) != len(set(keys)):
        raise ValueError('duplicate canonical constant/config name')
    return {
        'fingerprint_version': FINGERPRINT_VERSION,
        'components': {name: provider.component(name) for name in sorted((*functions, *types))},
        'constants': {name: provider.constant_component(name) for name in sorted(constants)},
        'config': config_subset(config, keys),
        'definition': {name: provider.component(name) for name in sorted(DEFINITION_COMPONENTS)},
    }


def model_fingerprint(config, provider=None):
    return stable_digest(fingerprint_payload(config, MODEL_BEHAVIOR_FUNCTIONS, MODEL_BEHAVIOR_CONSTANTS,
                                            MODEL_BEHAVIOR_TYPES, MODEL_CONFIG_KEYS, provider))


def simulator_fingerprint(config, provider=None):
    # Management-policy sources/constants are included by name; unrelated entry
    # utility does not force a simulator bump. Shared execution changes affect both.
    return stable_digest(fingerprint_payload(config, SIMULATOR_BEHAVIOR_FUNCTIONS, SIMULATOR_BEHAVIOR_CONSTANTS,
                                            SIMULATOR_BEHAVIOR_TYPES, SIMULATOR_CONFIG_KEYS, provider))


def inventory():
    return {
        'fingerprint_version': FINGERPRINT_VERSION,
        'model': {'functions': sorted(MODEL_BEHAVIOR_FUNCTIONS), 'types': sorted(MODEL_BEHAVIOR_TYPES),
                  'constants': sorted(MODEL_BEHAVIOR_CONSTANTS), 'config_keys': sorted(MODEL_CONFIG_KEYS)},
        'simulator': {'functions': sorted(SIMULATOR_BEHAVIOR_FUNCTIONS), 'types': sorted(SIMULATOR_BEHAVIOR_TYPES),
                      'constants': sorted(SIMULATOR_BEHAVIOR_CONSTANTS), 'config_keys': sorted(SIMULATOR_CONFIG_KEYS)},
        'nonbehavioral_functions': NONBEHAVIORAL_FUNCTIONS,
    }


def verify_definition_migration(prior_ref, repo, baseline, current, config):
    """Only legacy→v1 composition with unchanged actual source/config can migrate."""
    if baseline.get('fingerprint_version') != LEGACY_FINGERPRINT_VERSION or current.get('fingerprint_version') != FINGERPRINT_VERSION:
        return False, ['unsupported fingerprint-definition transition']
    if not prior_ref:
        return False, ['fingerprint migration requires immutable prior Git source']
    prior, proposed = SourceCatalog(repo, prior_ref), SourceCatalog(repo)
    try:
        if any(stable_digest(prior.component(name)) != identity for name, identity in LEGACY_DEFINITION_IDENTITIES.items()):
            return False, ['prior source is not the supported legacy fingerprint definition']
        names = set(MODEL_BEHAVIOR_FUNCTIONS+SIMULATOR_BEHAVIOR_FUNCTIONS+MODEL_BEHAVIOR_TYPES+SIMULATOR_BEHAVIOR_TYPES)
        changed = [name for name in sorted(names) if prior.component(name) != proposed.component(name)]
        constants = set(MODEL_BEHAVIOR_CONSTANTS+SIMULATOR_BEHAVIOR_CONSTANTS)
        changed += [name for name in sorted(constants) if prior.constant_component(name) != proposed.constant_component(name)]
        old_config = json.loads(prior.text('config/strategy.json'))['covered_call_v3']
        legacy = legacy_contract_state(prior, old_config)
        if any(legacy[field] != baseline[field] for field in legacy):
            changed.append('trusted legacy baseline does not match its Git source')
        if config_subset(old_config, MODEL_CONFIG_KEYS+SIMULATOR_CONFIG_KEYS) != config_subset(config, MODEL_CONFIG_KEYS+SIMULATOR_CONFIG_KEYS):
            changed.append('behavioral configuration')
        if any(baseline[field] != current[field] for field in ('model_version','simulator_version','simulator_contract_version','policy_version','cadence_comparability_policy_version')):
            changed.append('runtime contract versions')
        changed += classification_findings(proposed)
        if current['engine_hash'] != model_fingerprint(config, proposed) or current['simulator_contract_hash'] != simulator_fingerprint(config, proposed):
            changed.append('proposed fingerprints do not match their actual source')
        return not changed, changed
    except (ValueError, OSError, KeyError, SyntaxError) as exc:
        return False, [str(exc)]



def legacy_contract_state(provider, config):
    """Frozen 0711 source hashing, only to verify the one-time migration prior."""
    functions = (
        *_names('covered_call_virtual', 'fill_model evaluate_snapshot missed_intervals'),
        'covered_call_v3.execution',
        *_names('covered_call_rec', 'evaluate_cc_management_state _check_assignment_eligible _suggest_next_call _remaining_call_alpha _friction_at_expiry call_delta expected_upside_lost itm_prob_real _exec_premium'),
    )
    raw = []
    for name in functions:
        node = provider.node(name)
        lines = provider.text(name.split('.')[0]+'.py').splitlines(keepends=True)
        raw.append(''.join(lines[node.lineno-1:node.end_lineno]))
    engine = stable_digest(raw)
    # Preserve the old wrapper bug to reproduce, never to authorize new behavior.
    wrapped = config.get('cc_v3', {})
    keys = provider.value('covered_call_virtual._CONTRACT_CONFIG_KEYS')
    versions = {field: provider.value(name) for field, name in (
        ('model_version','covered_call_v3.VERSION'), ('simulator_version','covered_call_virtual.SIMULATOR_VERSION'),
        ('simulator_contract_version','covered_call_virtual.SIMULATOR_CONTRACT_VERSION'),
        ('policy_version','covered_call_virtual.POLICY_VERSION'),
        ('cadence_comparability_policy_version','covered_call_validation.CADENCE_COMPARABILITY_POLICY_VERSION'))}
    simulator = stable_digest(dict(simulator_contract_version=versions['simulator_contract_version'],
                                   simulator_version=versions['simulator_version'], management_contract_hash=engine,
                                   policy_version=versions['policy_version'],
                                   config_contract_hash=stable_digest({key:wrapped.get(key) for key in keys})))
    return dict(versions, engine_hash=engine, simulator_contract_hash=simulator)
