"""Frozen pre-0729 fingerprint definitions for isolated migration fixtures."""
import inspect
from covered_call_outcomes import digest

_CONTRACT_CONFIG_KEYS = ('management_cost_per_contract', 'path_count', 'max_regret_probability', 'utility_hurdle_annual_pct', 'fill_prior', 'fill_prior_strength', 'fill_min_n', 'regime_enabled')

def management_contract():
    import covered_call_rec as cc
    from covered_call_v3 import execution
    functions = (fill_model,evaluate_snapshot,missed_intervals,execution,cc.evaluate_cc_management_state, cc._check_assignment_eligible,
                 cc._suggest_next_call, cc._remaining_call_alpha, cc._friction_at_expiry,
                 cc.call_delta, cc.expected_upside_lost, cc.itm_prob_real, cc._exec_premium)
    return dict(engine_hash=digest([inspect.getsource(f) for f in functions]),
                tax_st_rate=cc.TAX_ST_RATE, tax_lt_rate=cc.TAX_LT_RATE,
                risk_free_rate=cc.RISK_FREE_RATE, exec_lambda=cc.EXEC_LAMBDA,
                assignment_tax_friction_threshold=cc.CC_ASSIGNMENT_TAX_FRICTION_THRESHOLD,
                policy_version=POLICY_VERSION)


def simulator_contract_hash(config):
    """Deterministic hash of all simulator-relevant code and config.

    Changes when and only when CC virtual book behaviour can change.
    Unrelated commits (docs, dashboard copy, etc.) do not affect this hash.
    """
    mc = management_contract()
    cc_cfg = config.get('cc_v3', {})
    config_subset = {k: cc_cfg.get(k) for k in _CONTRACT_CONFIG_KEYS}
    return digest({
        'simulator_contract_version': SIMULATOR_CONTRACT_VERSION,
        'simulator_version': SIMULATOR_VERSION,
        'management_contract_hash': mc['engine_hash'],
        'policy_version': mc['policy_version'],
        'config_contract_hash': digest(config_subset),
    })


