"""Thesis proposal engine.

draft_thesis(ticker, intake_dict) → dict

Calls the LLM with the user's intake form + real financial data and returns a
structured draft that maps directly onto the 0030 schema (pillars/metrics/rules).
No DB writes — the caller persists.
"""
from __future__ import annotations

import json

import financials_fetcher
import ollama_client

# Metric keys derivable from company_financials raw columns.
# Any key the LLM proposes outside this set is flagged unverified=True so the
# caller (and future monitor agent) knows it cannot be auto-evaluated.
KNOWN_METRIC_KEYS: frozenset[str] = frozenset({
    "revenue",
    "revenue_growth_yoy",
    "revenue_growth_qoq",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "net_income",
    "free_cash_flow",
    "operating_income",
    "eps_diluted",
    "eps_growth_yoy",
    "total_debt",
    "cash",
    "net_debt",
    "debt_to_equity",
    "total_equity",
})

# Top-level keys the LLM must return (list items are not checked by generate_structured).
_LLM_SCHEMA: dict = {
    "pillars": [],
    "add_condition": "",
    "trim_condition": "",
    "exit_condition": "",
    "key_risks": [],
    "catalysts": [],
    "qualitative_signals": [],
    "review_triggers": [],
}

_SYSTEM_PROMPT = """\
You are a systematic investment analyst helping a private investor formalize their
thesis into concrete, measurable criteria grounded in the company's own financials.

Rules:
- Derive ALL numeric thresholds from the actual historical financial data provided.
  Never use generic industry benchmarks — ground every number in this company's history.
- Produce 3-5 pillars. Each pillar has an integer importance; all importances must sum
  to exactly 100.
- Mark critical=true on at most 1 pillar — the single pillar whose violation is an
  immediate dealbreaker regardless of all other signals.
- Each pillar should have 1-2 metrics with explicit healthy and violation thresholds.
- direction must be exactly "HIGHER_IS_BETTER" or "LOWER_IS_BETTER".
- metric_key must be snake_case. Prefer: revenue_growth_yoy, gross_margin, net_margin,
  fcf_margin, operating_margin, eps_diluted, eps_growth_yoy, debt_to_equity, net_debt,
  free_cash_flow, operating_income.
- persistence_periods = consecutive quarters the metric must breach the threshold before
  the violation is confirmed (integer, 1-4).
- healthy_threshold: the value at or above (HIGHER_IS_BETTER) / at or below
  (LOWER_IS_BETTER) that defines a healthy reading.
- violation_threshold: the value that defines a confirmed violation.
- add_condition, trim_condition, exit_condition: concise, actionable prose.
- key_risks: 2-4 specific risks with severity (HIGH/MEDIUM/LOW) and time_horizon (near/medium/long).
- catalysts: 2-3 upcoming milestones with importance (HIGH/MEDIUM/LOW) and time_horizon.
- qualitative_signals: 1-3 non-numeric signals to monitor (management tone, channel checks, news).
  Each signal: description (str), source (news/management/channel/macro), direction (positive/negative).
- review_triggers: 2-4 specific events that should force a full thesis re-evaluation. Plain strings.
- Return valid JSON exactly matching the requested schema.\
"""


def _make_metric_rules(metric: dict) -> tuple[str, str, str]:
    """Convert LLM metric thresholds to (healthy, warning, violation) rule JSON strings."""
    direction = metric.get("direction", "HIGHER_IS_BETTER")
    ht = float(metric.get("healthy_threshold", 0))
    vt = float(metric.get("violation_threshold", 0))

    if direction == "HIGHER_IS_BETTER":
        healthy   = json.dumps({"operator": ">=",      "value": ht})
        warning   = json.dumps({"operator": "BETWEEN", "min": vt, "max": ht})
        violation = json.dumps({"operator": "<",       "value": vt})
    else:  # LOWER_IS_BETTER
        healthy   = json.dumps({"operator": "<=",      "value": ht})
        warning   = json.dumps({"operator": "BETWEEN", "min": ht, "max": vt})
        violation = json.dumps({"operator": ">",       "value": vt})

    return healthy, warning, violation


def draft_thesis(ticker: str, intake_dict: dict) -> dict:
    """Generate a structured thesis draft from intake form + financial data.

    Args:
        ticker: uppercase ticker symbol (e.g. "ANET")
        intake_dict: keys — why, role, period, conditions (list), sell, trim,
                     conviction (int 1-5), max_pct (float), special

    Returns:
        dict with keys:
          ticker (str)
          pillars (list of dicts):
            name, description, importance (int, sums to 100), critical (bool),
            metrics (list): metric_key, direction, healthy_rule_json,
                            warning_rule_json, violation_rule_json,
                            persistence_periods (int), unverified (bool)
          rules (list of dicts): rule_type (ADD/TRIM/EXIT), rule_json (str)
          key_risks (list of str)
          catalysts (list of str)

    Raises:
        ValueError: if company_financials has no data for ticker.
        ollama_client.StructuredOutputError: if LLM fails after retries.
    """
    financial_context = financials_fetcher.get_financial_summary(ticker)
    if not financial_context:
        raise ValueError(
            f"No financial data in company_financials for {ticker!r}. "
            "Run financials_fetcher.fetch_all() for this ticker first."
        )

    conditions_text = "\n".join(
        f"  - {c}" for c in (intake_dict.get("conditions") or [])
    )

    prompt = f"""Draft a structured investment thesis for {ticker}.

INVESTOR'S RATIONALE:
Why I own this: {intake_dict.get('why', '(not provided)')}
Portfolio role: {intake_dict.get('role', '(not provided)')}
Expected holding period: {intake_dict.get('period', '(not provided)')}
Key thesis conditions that must remain true:
{conditions_text or '  (not provided)'}
What would make me sell: {intake_dict.get('sell', '(not provided)')}
What would make me trim: {intake_dict.get('trim', '(not provided)')}
Conviction level: {intake_dict.get('conviction', '(not provided)')} / 5
Max comfortable position: {intake_dict.get('max_pct', '(not provided)')}%
Special considerations: {intake_dict.get('special', 'none')}

COMPANY FINANCIAL DATA:
{financial_context}

Produce 3-5 pillars. Importance values must sum to exactly 100.
All thresholds must be grounded in the financial history above.
Return JSON matching exactly this schema:
{{
  "pillars": [
    {{
      "name": "Revenue Growth",
      "description": "Why this pillar matters for the thesis",
      "importance": 35,
      "critical": false,
      "metrics": [
        {{
          "metric_key": "revenue_growth_yoy",
          "direction": "HIGHER_IS_BETTER",
          "healthy_threshold": 15.0,
          "violation_threshold": 8.0,
          "persistence_periods": 2
        }}
      ]
    }}
  ],
  "add_condition": "Describe when to add more shares",
  "trim_condition": "Describe when to trim the position",
  "exit_condition": "Describe what triggers a full exit",
  "key_risks": [
    {{"description": "Risk 1", "severity": "HIGH", "time_horizon": "near"}},
    {{"description": "Risk 2", "severity": "MEDIUM", "time_horizon": "medium"}}
  ],
  "catalysts": [
    {{"description": "Catalyst 1", "importance": "HIGH", "time_horizon": "near"}},
    {{"description": "Catalyst 2", "importance": "MEDIUM", "time_horizon": "medium"}}
  ],
  "qualitative_signals": [
    {{"description": "Management tone on calls", "source": "management", "direction": "positive"}}
  ],
  "review_triggers": [
    "Revenue miss >10% for two consecutive quarters",
    "Management team change at CEO or CFO level"
  ]
}}"""

    raw = ollama_client.generate_structured(
        prompt=_SYSTEM_PROMPT + "\n\n" + prompt,
        schema=_LLM_SCHEMA,
        temperature=0.25,
        num_predict=3500,
        thinking=False,
        retries=2,
    )

    # Normalise importance sum to exactly 100
    pillars = list(raw.get("pillars") or [])
    total = sum(float(p.get("importance", 0)) for p in pillars)
    if pillars and total > 0 and abs(total - 100) > 0.5:
        factor = 100 / total
        for p in pillars:
            p["importance"] = round(float(p.get("importance", 0)) * factor)
        residual = 100 - sum(p["importance"] for p in pillars)
        pillars[0]["importance"] += residual

    # Build structured output matching 0030 CRUD helper signatures
    out_pillars = []
    for p in pillars:
        out_metrics = []
        for m in (p.get("metrics") or []):
            healthy_j, warning_j, violation_j = _make_metric_rules(m)
            out_metrics.append({
                "metric_key":         m.get("metric_key", ""),
                "direction":          m.get("direction", "HIGHER_IS_BETTER"),
                "healthy_rule_json":  healthy_j,
                "warning_rule_json":  warning_j,
                "violation_rule_json": violation_j,
                "persistence_periods": int(m.get("persistence_periods", 1)),
                "unverified":         m.get("metric_key", "") not in KNOWN_METRIC_KEYS,
            })
        out_pillars.append({
            "name":        p.get("name", ""),
            "description": p.get("description", ""),
            "importance":  int(p.get("importance", 0)),
            "critical":    bool(p.get("critical", False)),
            "metrics":     out_metrics,
        })

    rules = []
    for rule_type, field in [
        ("ADD",  "add_condition"),
        ("TRIM", "trim_condition"),
        ("EXIT", "exit_condition"),
    ]:
        cond = (raw.get(field) or "").strip()
        if cond:
            rules.append({
                "rule_type": rule_type,
                "rule_json": json.dumps({"condition": cond}),
            })

    def _norm_risks(items):
        out = []
        for item in (items or []):
            if isinstance(item, str):
                out.append({"description": item, "severity": "MEDIUM", "time_horizon": None})
            elif isinstance(item, dict):
                out.append({
                    "description": item.get("description", ""),
                    "severity": item.get("severity", "MEDIUM").upper(),
                    "time_horizon": item.get("time_horizon"),
                })
        return out

    def _norm_catalysts(items):
        out = []
        for item in (items or []):
            if isinstance(item, str):
                out.append({"description": item, "importance": "MEDIUM", "time_horizon": None})
            elif isinstance(item, dict):
                out.append({
                    "description": item.get("description", ""),
                    "importance": item.get("importance", "MEDIUM").upper(),
                    "time_horizon": item.get("time_horizon"),
                })
        return out

    return {
        "ticker":              ticker,
        "pillars":             out_pillars,
        "rules":               rules,
        "key_risks":           _norm_risks(raw.get("key_risks")),
        "catalysts":           _norm_catalysts(raw.get("catalysts")),
        "qualitative_signals": list(raw.get("qualitative_signals") or []),
        "review_triggers":     list(raw.get("review_triggers") or []),
    }
