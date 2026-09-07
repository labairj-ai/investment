"""AI thesis drafting.

draft_thesis(ticker, intake) calls the LLM with the user's intake form + real
financial data and returns a structured draft the user can edit before approving.
"""
import json

import financials_fetcher
import ollama_client


_DRAFT_SCHEMA = {
    "claims": [
        {
            "claim": "",
            "importance": 0,
            "measurements": [
                {
                    "metric": "",
                    "healthy": "",
                    "warning": "",
                    "violation": "",
                    "persistence": "",
                }
            ],
        }
    ],
    "valuation_framework": {
        "primary_metric": "",
        "secondary_metrics": [],
        "historical_period_years": 5,
        "attractive_threshold": 0,
        "fair_value_low": 0,
        "fair_value_high": 0,
        "extreme_threshold": 0,
        "growth_adjustment_method": "",
        "rationale": "",
    },
}

_SYSTEM_PROMPT = """You are an investment analyst helping a private investor document
and formalize their investment thesis. Your job is to take a high-level investor
rationale and translate it into a structured, measurable thesis with concrete
financial thresholds grounded in the company's own history.

Rules:
- Derive thresholds from the actual historical data provided — not generic benchmarks.
- Each claim must have an importance weight; all importance values must sum to 100.
- Use 3–6 claims. Focus on the most decisive factors given the investor's stated rationale.
- Measurements should be specific and actionable (e.g. "> 12% YoY revenue growth").
- Persistence should be "1 quarter", "2 quarters", "3 quarters", or similar.
- metric should be a snake_case key like revenue_growth_yoy, gross_margin, fcf_margin, etc.
- Respond with valid JSON matching the requested schema exactly.
"""


def draft_thesis(ticker: str, intake: dict) -> dict:
    """Generate an AI-drafted thesis from intake form + financial data.

    Args:
        ticker: uppercase ticker symbol
        intake: dict with keys: why, role, period, conditions, sell, trim,
                conviction, max_pct, special

    Returns:
        dict with key "claims" — list of claim objects with measurements.
        Raises ollama_client.StructuredOutputError on LLM failure.
    """
    financial_context = financials_fetcher.get_financial_summary(ticker)
    if not financial_context:
        financial_context = f"No detailed financial history available for {ticker}."

    conditions_text = "\n".join(
        f"  - {c}" for c in (intake.get("conditions") or [])
    )

    prompt = f"""Draft a structured investment thesis for {ticker}.

INVESTOR'S RATIONALE:
Why I own this: {intake.get('why', '(not provided)')}
Portfolio role: {intake.get('role', '(not provided)')}
Expected holding period: {intake.get('period', '(not provided)')}
Key thesis conditions that must remain true:
{conditions_text or '  (not provided)'}
What would make me sell: {intake.get('sell', '(not provided)')}
What would make me trim: {intake.get('trim', '(not provided)')}
Conviction level: {intake.get('conviction', '(not provided)')} / 5
Max comfortable position: {intake.get('max_pct', '(not provided)')}%
Special considerations: {intake.get('special', 'none')}

COMPANY FINANCIAL DATA:
{financial_context}

Produce 3–6 measurable claims with thresholds derived from the financial history above.
All importance values must sum to exactly 100.

Also produce a valuation_framework that captures how this specific company should be valued:
- primary_metric: the most meaningful multiple for this business (forward_pe, ev_fcf, ps, ev_ebitda, etc.)
- secondary_metrics: 1-2 supporting metrics (list of strings)
- historical_period_years: how many years of history to use (5 is standard)
- attractive_threshold: primary_metric value below which the stock is attractively valued
- fair_value_low / fair_value_high: range representing fair value
- extreme_threshold: primary_metric value above which the stock is extremely expensive
- growth_adjustment_method: "peg", "ev_growth", or "" if not applicable
- rationale: one sentence explaining why this metric suits this business

Return JSON matching this schema exactly:
{{"claims": [{{"claim": "...", "importance": N, "measurements": [{{"metric": "...", "healthy": "...", "warning": "...", "violation": "...", "persistence": "..."}}]}}], "valuation_framework": {{"primary_metric": "...", "secondary_metrics": [], "historical_period_years": 5, "attractive_threshold": 0, "fair_value_low": 0, "fair_value_high": 0, "extreme_threshold": 0, "growth_adjustment_method": "", "rationale": "..."}}}}"""

    full_prompt = _SYSTEM_PROMPT + "\n\n" + prompt
    result = ollama_client.generate_structured(
        prompt=full_prompt,
        schema=_DRAFT_SCHEMA,
        model="mlx-community/Qwen3.6-35B-A3B-4bit",
        temperature=0.3,
        num_predict=2000,
        thinking=False,
        retries=2,
    )

    # Normalise importance sum to exactly 100 if LLM drifted
    claims = result.get("claims", [])
    total = sum(c.get("importance", 0) for c in claims)
    if claims and total > 0 and abs(total - 100) > 0.5:
        factor = 100 / total
        for c in claims:
            c["importance"] = round(c.get("importance", 0) * factor)
        # Fix rounding residual on the first claim
        residual = 100 - sum(c["importance"] for c in claims)
        if claims:
            claims[0]["importance"] += residual

    result["claims"] = claims
    return result
