"""Confidence scoring for agent findings and recommendations.

calculate_confidence() implements the D+F+S+A+R composite:
  D — Data:        availability of expected data sources      (20%)
  F — Factual:     density of non-null evidence fields        (20%)
  S — Statistical: signal strength (z-score / magnitude)     (20%)
  A — Analyst:     AI model's own stated confidence weight    (20%)
  R — Rules:       fraction of hard criteria satisfied        (20%)

Confidence caps:
  Missing critical data sources (price + holdings) → max 60
  Low rule support (< 0.5)                         → max 70
"""

_EXPECTED_SOURCES = frozenset({"price", "fundamentals", "macro_scores", "holdings"})
_CRITICAL_SOURCES = frozenset({"price", "holdings"})


def calculate_confidence(
    data_sources: list[str],
    evidence: dict,
    rule_support: float,
    analyst_weight: float = 0.5,
) -> int:
    """Return an integer confidence score in [0, 100].

    Args:
        data_sources:   Names of data sources that were actually available
                        (e.g. ["price", "holdings", "macro_scores"]).
        evidence:       Arbitrary evidence dict; non-null values increase F score.
                        May include "z_score" or "magnitude" keys for S component.
        rule_support:   Fraction of hard rules/criteria satisfied, 0.0–1.0.
        analyst_weight: AI model's own confidence, 0.0–1.0 (default 0.5 = neutral).
    """
    available = set(data_sources)

    # D — data availability
    d_score = len(available & _EXPECTED_SOURCES) / len(_EXPECTED_SOURCES) * 100

    # F — evidence completeness
    if evidence:
        non_null = sum(1 for v in evidence.values() if v is not None)
        f_score = non_null / len(evidence) * 100
    else:
        f_score = 0.0

    # S — statistical signal strength
    raw_signal = evidence.get("z_score") or evidence.get("magnitude")
    if raw_signal is not None:
        s_score = min(abs(float(raw_signal)) / 3.0 * 100, 100.0)
    else:
        s_score = 50.0  # neutral when no signal data present

    # A — analyst (AI) confidence
    a_score = max(0.0, min(1.0, analyst_weight)) * 100

    # R — rule support
    r_score = max(0.0, min(1.0, rule_support)) * 100

    # Weighted composite (equal weights)
    raw = (d_score + f_score + s_score + a_score + r_score) / 5.0
    score = round(raw)

    # Caps
    if not (_CRITICAL_SOURCES <= available):
        score = min(score, 60)
    if rule_support < 0.5:
        score = min(score, 70)

    return max(0, min(100, score))
