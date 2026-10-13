"""CC Calibration Skill Diagnostics — Brier Skill Score against naive reference forecasts.

Diagnostic only — must not alter promotion eligibility.
Reference forecast is BASE_RATE_BY_DTE_OTM_BUCKET with shrinkage to global event frequency.
Reference is precommitted; results must not influence reference definition.
No-lookahead invariant: reference frequency for a sample uses only outcomes observed
before that sample's decision timestamp.
"""
from __future__ import annotations
from collections import defaultdict

SKILL_REFERENCE_VERSION = 'dte-otm-shrink-v1'
# Shrinkage parameter: weight of global prior relative to one bucket observation.
SHRINKAGE_STRENGTH = 5

# Events with expected probabilities in features
SKILL_EVENTS = [
    ('strike_touch_prob', 'strike_touched'),
    ('regret_barrier_touch_prob', 'regret_barrier_touched'),
    ('delta30_touch_prob', 'delta30_event'),
    ('delta50_touch_prob', 'delta50_event'),
]

_DTE_BUCKETS = [(0, 20), (20, 35), (35, 50), (50, 75), (75, 120), (120, 999)]
_OTM_BUCKETS = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.40), (0.40, 1.0)]


def _dte_bucket(dte):
    for lo, hi in _DTE_BUCKETS:
        if lo <= dte < hi:
            return lo
    return _DTE_BUCKETS[-1][0]


def _otm_bucket(otm_pct):
    for lo, hi in _OTM_BUCKETS:
        if lo <= otm_pct < hi:
            return lo
    return _OTM_BUCKETS[-1][0]


def _brier(predictions_outcomes):
    if not predictions_outcomes:
        return None
    return sum((p - y) ** 2 for p, y in predictions_outcomes) / len(predictions_outcomes)


def _build_causal_reference(samples_sorted, event_key):
    """Build per-sample reference forecasts using only prior outcomes (no lookahead).

    samples_sorted: [(timestamp_str, features, labels), ...] sorted by timestamp ascending.
    Returns list of (reference_prob, outcome) parallel to samples_sorted, for samples with
    non-censored outcomes.
    """
    bucket_counts = defaultdict(lambda: {'n': 0, 'y': 0})
    global_n = 0
    global_y = 0
    refs = []
    for ts, f, l in samples_sorted:
        y = l.get(event_key)
        if y is None or l.get('censored', True):
            refs.append(None)
        else:
            dte_b = _dte_bucket(float(f.get('dte', 30)))
            otm_b = _otm_bucket(float(f.get('otm_pct', 0.10)))
            bucket = (dte_b, otm_b)
            # Reference computed from PRIOR observations only
            bn = bucket_counts[bucket]['n']
            by = bucket_counts[bucket]['y']
            global_rate = global_y / global_n if global_n > 0 else 0.5
            # Shrinkage toward global rate
            shrunk = (by + SHRINKAGE_STRENGTH * global_rate) / (bn + SHRINKAGE_STRENGTH)
            refs.append((shrunk, bool(y)))
        # Update counters with THIS sample's outcome for future samples
        if y is not None and not l.get('censored', True):
            dte_b = _dte_bucket(float(f.get('dte', 30)))
            otm_b = _otm_bucket(float(f.get('otm_pct', 0.10)))
            bucket = (dte_b, otm_b)
            bucket_counts[bucket]['n'] += 1
            bucket_counts[bucket]['y'] += int(bool(y))
            global_n += 1
            global_y += int(bool(y))
    return refs


def _brier_skill_score(bs_model, bs_reference):
    """BSS = 1 - BS_model / BS_reference. Handles zero reference explicitly."""
    if bs_reference is None or bs_model is None:
        return None
    if bs_reference == 0:
        return 1.0 if bs_model == 0 else None  # undefined for non-perfect model vs perfect reference
    return 1.0 - bs_model / bs_reference


def calibration_skill(samples, predicted_key, event_key, min_n=20):
    """Compute Brier Skill Score for a predicted/event pair.

    samples: [(features_dict, labels_dict), ...] — already filtered to independent cohort.
    Returns dict with model_brier, reference_brier, brier_skill_score, reference_version,
    reference_sample_n, shrinkage_strength, delta_proxy (secondary reference), notes.
    Diagnostic only — does not affect promotion gates.
    """
    from time_utils import parse_timestamp
    # Sort by timestamp for causal reference construction
    timed = []
    for f, l in samples:
        ts = f.get('quote_timestamp') or f.get('timestamp') or '1970-01-01T00:00:00Z'
        timed.append((ts, f, l))
    timed.sort(key=lambda x: x[0])

    usable_model = []
    for ts, f, l in timed:
        p = f.get(predicted_key)
        y = l.get(event_key)
        if p is not None and y is not None and not l.get('censored', True) and \
           l.get('outcome_source', 'MARKET_PATH_ONLY') in ('ACTUAL_EXECUTION', 'PROSPECTIVE_VIRTUAL', 'MARKET_PATH_ONLY'):
            usable_model.append((float(p), bool(y)))

    bs_model = _brier(usable_model)
    n = len(usable_model)

    refs = _build_causal_reference(timed, event_key)
    usable_ref = [r for r in refs if r is not None]
    bs_reference = _brier(usable_ref)
    bss = _brier_skill_score(bs_model, bs_reference)

    # Secondary reference: entry delta as proxy (only meaningful for strike_touch events)
    delta_proxy = None
    if predicted_key == 'strike_touch_prob':
        delta_pairs = [(float(f.get('delta', 0)), bool(l.get(event_key)))
                       for ts, f, l in timed
                       if f.get('delta') is not None and l.get(event_key) is not None
                       and not l.get('censored', True)]
        delta_proxy = dict(
            reference='ENTRY_DELTA',
            brier=_brier(delta_pairs),
            n=len(delta_pairs),
            brier_skill_score=_brier_skill_score(bs_model, _brier(delta_pairs)) if delta_pairs else None,
        )

    return dict(
        predicted_key=predicted_key,
        event_key=event_key,
        n=n,
        minimum_n=min_n,
        minimum_n_met=n >= min_n,
        model_brier=bs_model,
        reference_brier=bs_reference,
        brier_skill_score=bss,
        reference_version=SKILL_REFERENCE_VERSION,
        reference_description='BASE_RATE_BY_DTE_OTM_BUCKET with shrinkage to global event frequency',
        reference_sample_n=len(usable_ref),
        shrinkage_strength=SHRINKAGE_STRENGTH,
        delta_proxy=delta_proxy,
        low_n_state='INSUFFICIENT_SAMPLE' if n < min_n else 'SUFFICIENT',
        notes='DIAGNOSTIC_ONLY — does not affect promotion eligibility. Negative BSS = model worse than reference.',
    )


def all_calibration_skills(samples, min_n=20):
    """Compute skill diagnostics for all standard CC events."""
    return {f'{pred}__skill': calibration_skill(samples, pred, event, min_n)
            for pred, event in SKILL_EVENTS}
