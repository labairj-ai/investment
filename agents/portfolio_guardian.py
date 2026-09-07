from __future__ import annotations
"""Portfolio Guardian Agent (Phase 3).

Runs four deterministic checks on every holding and layer, then calls
the LLM only for positions that crossed a materiality threshold. Severity
is computed deterministically — the LLM adds prose, not numbers.

Also runs three portfolio-scope checks: sector concentration, portfolio
beta (vs portfolio composite return), and marginal risk contribution.

Returns [] (no trade recommendations). All output goes to agent_findings.
"""
import csv
import math
import time
from pathlib import Path

import agent_db
import ollama_client
from strategy_config import (
    LAYER_TARGETS, LAYER_NAMES, LAYER_LABELS, DRIFT_THRESHOLD, HOLDING_GROSS_DOM,
    SECTOR_CONCENTRATION_PCT, PORTFOLIO_BETA_HIGH, PORTFOLIO_BETA_LOW,
    RISK_CONTRIBUTION_MULTIPLE, CORRELATION_CLUSTER_THRESHOLD,
    CORRELATION_CLUSTER_MIN_SIZE, COVARIANCE_LOOKBACK_DAYS,
)

# Reverse map: "Layer 1: L1 Structural Ballast" -> 1
_LABEL_TO_INT: dict[str, int] = {v: k for k, v in LAYER_LABELS.items()}
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

_PROMPT_VERSION = "portfolio_guardian_v1"

# --- Thresholds ----------------------------------------------------------------
_IMPACT_THRESHOLD_PP = 0.35   # portfolio NAV pp: weight_pct * |change_pct| / 100
_Z_THRESHOLD         = 2.0    # standard deviations above 20-day historical vol
_HV20_MIN_DAYS       = 5      # minimum trading days needed to compute HV20

# --- LLM schema ---------------------------------------------------------------
_POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":               {"type": "string"},
        "why_now":               {"type": "string"},
        "portfolio_implication": {"type": "string"},
        "no_action_case":        {"type": "string"},
        "suggested_action":      {"type": "string", "enum": ["REVIEW"]},
    },
    "required": ["summary", "why_now", "portfolio_implication",
                 "no_action_case", "suggested_action"],
}

_SYSTEM = (
    "You are a portfolio risk analyst. You receive structured data about a "
    "flagged equity position. Write concise, factual risk commentary. "
    "Do not recommend buying or selling — only flag for review. "
    "suggested_action must always be REVIEW."
)


# --- Data helpers -------------------------------------------------------------

def _current_holdings_tickers() -> set[str]:
    """Return the set of tickers currently in holdings.csv."""
    holdings_csv = Path(agent_db.DB_PATH).parent.parent / "holdings.csv"
    if not holdings_csv.exists():
        return set()
    with open(holdings_csv) as f:
        return {row["Stock"].strip().upper() for row in csv.DictReader(f) if row.get("Stock")}


def _latest_holding_rows() -> list[dict]:
    """Return the most recent holding_day row, filtered to current holdings only."""
    current = _current_holdings_tickers()
    if not current:
        return []
    conn = agent_db._connect()
    rows = conn.execute(
        """SELECT h.day, h.ticker, h.layer, h.change_pct, h.weight_pct, h.value
           FROM holding_day h
           INNER JOIN (
               SELECT ticker, MAX(day) AS max_day
               FROM holding_day
               GROUP BY ticker
           ) latest ON h.ticker = latest.ticker AND h.day = latest.max_day"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows if r["ticker"] in current]


def _latest_layer_rows() -> list[dict]:
    """Return the most recent layer_day row for every layer."""
    conn = agent_db._connect()
    rows = conn.execute(
        """SELECT l.day, l.layer, l.weight_pct
           FROM layer_day l
           INNER JOIN (
               SELECT layer, MAX(day) AS max_day
               FROM layer_day
               GROUP BY layer
           ) latest ON l.layer = latest.layer AND l.day = latest.max_day"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _compute_hv20(ticker: str) -> float | None:
    """Annualised HV20 from the last 20 holding_day.change_pct rows."""
    conn = agent_db._connect()
    rows = conn.execute(
        "SELECT change_pct FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 20",
        (ticker,),
    ).fetchall()
    conn.close()
    returns = [r[0] / 100.0 for r in rows if r[0] is not None]
    if len(returns) < _HV20_MIN_DAYS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance * 252)  # annualised


# --- Severity (deterministic) ------------------------------------------------

def _layer_severity(drift_pp: float) -> int:
    """Severity for layer drift: 5pp → 70, 8pp → 94, 10pp → 100."""
    return min(100, 30 + int(abs(drift_pp) * 8))


def _position_severity(triggers: dict) -> int:
    """Max deterministic severity across all triggered position checks."""
    scores: list[int] = []
    if "concentration" in triggers:
        w = triggers["concentration"]["weight_pct"]
        scores.append(min(100, 40 + int((w - HOLDING_GROSS_DOM) * 5)))
    if "impact" in triggers:
        pp = abs(triggers["impact"]["impact_pp"])
        scores.append(min(100, int(pp * 100 + 25)))
    if "z_score" in triggers:
        z = triggers["z_score"]["z"]
        scores.append(min(100, 20 + int(z * 20)))
    return max(scores) if scores else 50


# --- LLM call ----------------------------------------------------------------

def _llm_prose(ticker: str, layer: int, weight_pct: float,
               change_pct: float, triggers: dict) -> dict | None:
    trigger_lines = []
    if "concentration" in triggers:
        trigger_lines.append(
            f"  Position concentration: {weight_pct:.1f}% weight "
            f"(threshold {HOLDING_GROSS_DOM:.0f}%)"
        )
    if "impact" in triggers:
        pp = triggers["impact"]["impact_pp"]
        trigger_lines.append(
            f"  Portfolio NAV impact: {pp:+.2f}pp "
            f"({weight_pct:.1f}% weight × {change_pct:+.2f}% daily move)"
        )
    if "z_score" in triggers:
        z  = triggers["z_score"]["z"]
        hv = triggers["z_score"]["hv20_pct"]
        trigger_lines.append(
            f"  Abnormal move: Z={z:.1f} (|{change_pct:+.2f}%| vs "
            f"HV20={hv:.1f}% annualised, threshold Z≥2)"
        )

    prompt = (
        f"{_SYSTEM}\n\n"
        f"Ticker: {ticker}  Layer: {layer}  Weight: {weight_pct:.1f}%  "
        f"Daily return: {change_pct:+.2f}%\n\n"
        f"Triggered checks:\n" + "\n".join(trigger_lines) + "\n\n"
        "Return JSON matching the schema. summary: 1 sentence. "
        "why_now: why this matters today. portfolio_implication: portfolio-level "
        "consequence. no_action_case: strongest argument to wait. "
        "suggested_action must be REVIEW."
    )
    try:
        out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_POSITION_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=600,
            thinking=False,
            retries=2,
        )
        if isinstance(out, dict) and out.get("suggested_action") == "REVIEW":
            return out
        print(f"[guardian] {ticker}: LLM returned invalid schema — using fallback")
    except Exception as e:
        print(f"[guardian] {ticker}: LLM failed: {e}")
    return None


def _fallback_summary(ticker: str, triggers: dict) -> tuple[str, str]:
    parts = []
    if "concentration" in triggers:
        w = triggers["concentration"]["weight_pct"]
        parts.append(f"position concentration {w:.1f}%")
    if "impact" in triggers:
        pp = triggers["impact"]["impact_pp"]
        parts.append(f"NAV impact {pp:+.2f}pp")
    if "z_score" in triggers:
        z = triggers["z_score"]["z"]
        parts.append(f"Z={z:.1f}")
    summary  = f"{ticker}: flagged — " + ", ".join(parts)
    why_now  = "Deterministic materiality threshold crossed today."
    return summary, why_now


# --- Sector data (cached per process, yfinance .info) -------------------------

_sector_cache: dict[str, str] = {}


def _fetch_sector(ticker: str) -> str:
    if ticker in _sector_cache:
        return _sector_cache[ticker]
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        sector = info.get("sector") or "Unknown"
    except Exception:
        sector = "Unknown"
    _sector_cache[ticker] = sector
    return sector


# --- Multi-day price return matrix from holding_day ---------------------------

def _price_return_matrix(tickers: list[str], lookback: int) -> dict[str, list[float]]:
    """Return dict ticker -> list of daily change_pct (most recent last)."""
    conn = agent_db._connect()
    result: dict[str, list[float]] = {}
    for ticker in tickers:
        rows = conn.execute(
            "SELECT change_pct FROM holding_day WHERE ticker=? AND change_pct IS NOT NULL "
            "ORDER BY day DESC LIMIT ?",
            (ticker, lookback),
        ).fetchall()
        result[ticker] = [r[0] / 100.0 for r in reversed(rows)]
    conn.close()
    return result


# --- Portfolio-scope checks ---------------------------------------------------

def _check_sector_concentration(holding_rows: list[dict], run_id: int) -> None:
    """Fire a finding if any sector exceeds SECTOR_CONCENTRATION_PCT."""
    sector_weights: dict[str, float] = {}
    sector_tickers: dict[str, list[str]] = {}
    for row in holding_rows:
        ticker = row["ticker"]
        weight = row["weight_pct"] or 0.0
        sector = _fetch_sector(ticker)
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
        sector_tickers.setdefault(sector, []).append(ticker)

    for sector, total_weight in sector_weights.items():
        if sector == "Unknown" or total_weight <= SECTOR_CONCENTRATION_PCT:
            continue
        tickers_str = ", ".join(sector_tickers[sector])
        summary = (
            f"Sector concentration: {sector} at {total_weight:.1f}% "
            f"(threshold {SECTOR_CONCENTRATION_PCT:.0f}%) — {tickers_str}"
        )
        severity = min(100, int(40 + (total_weight - SECTOR_CONCENTRATION_PCT) * 4))
        fid = agent_db.insert_finding(
            run_id=run_id,
            finding_type="sector_concentration",
            ticker=None,
            severity=severity,
            confidence=90,
            summary=summary,
            why_now=f"{sector} sector exceeds concentration limit — diversification risk.",
            metrics={
                "sector": sector,
                "sector_weight_pct": round(total_weight, 2),
                "threshold_pct": SECTOR_CONCENTRATION_PCT,
                "tickers": sector_tickers[sector],
            },
        )
        print(f"[guardian] Sector finding #{fid}: {sector} {total_weight:.1f}% (severity={severity})")


def _check_covariance_risk(holding_rows: list[dict], run_id: int) -> None:
    """Compute portfolio beta, risk contributions, and correlation clusters from holding_day."""
    import numpy as np

    tickers = [r["ticker"] for r in holding_rows]
    weights = {r["ticker"]: (r["weight_pct"] or 0.0) / 100.0 for r in holding_rows}
    total_w = sum(weights.values())
    if total_w <= 0 or len(tickers) < 2:
        return

    returns_map = _price_return_matrix(tickers, COVARIANCE_LOOKBACK_DAYS)
    min_len = min(len(v) for v in returns_map.values()) if returns_map else 0
    if min_len < 10:
        print("[guardian] Insufficient price history for covariance checks — skipping")
        return

    # Align all series to same length
    aligned = {t: returns_map[t][-min_len:] for t in tickers}
    R = np.array([aligned[t] for t in tickers])  # shape: (n_stocks, n_days)

    # Covariance matrix (annualised)
    cov = np.cov(R) * 252  # (n, n)
    w = np.array([weights[t] / total_w for t in tickers])  # normalised weights

    # Portfolio variance
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return

    # ── Portfolio beta vs composite portfolio return ──────────────────────────
    port_returns = w @ R  # (n_days,)
    port_var_daily = float(np.var(port_returns))
    betas: dict[str, float] = {}
    for i, ticker in enumerate(tickers):
        stock_cov = float(np.cov(R[i], port_returns)[0, 1])
        betas[ticker] = stock_cov / port_var_daily if port_var_daily > 0 else 1.0
    port_beta = float(sum(w[i] * betas[t] for i, t in enumerate(tickers)))

    if port_beta > PORTFOLIO_BETA_HIGH or port_beta < PORTFOLIO_BETA_LOW:
        direction = "high" if port_beta > PORTFOLIO_BETA_HIGH else "low"
        threshold = PORTFOLIO_BETA_HIGH if direction == "high" else PORTFOLIO_BETA_LOW
        severity = min(100, int(50 + abs(port_beta - threshold) * 30))
        summary = (
            f"Portfolio beta {port_beta:.2f} vs composite — "
            f"{'elevated' if direction == 'high' else 'defensive'} market sensitivity "
            f"(threshold {threshold:.1f})"
        )
        fid = agent_db.insert_finding(
            run_id=run_id,
            finding_type="portfolio_beta",
            ticker=None,
            severity=severity,
            confidence=75,
            summary=summary,
            why_now=f"Portfolio beta {port_beta:.2f} outside [{PORTFOLIO_BETA_LOW},{PORTFOLIO_BETA_HIGH}] range.",
            metrics={
                "portfolio_beta": round(port_beta, 3),
                "beta_high_threshold": PORTFOLIO_BETA_HIGH,
                "beta_low_threshold": PORTFOLIO_BETA_LOW,
                "ticker_betas": {t: round(betas[t], 3) for t in tickers},
            },
        )
        print(f"[guardian] Beta finding #{fid}: portfolio_beta={port_beta:.2f} (severity={severity})")

    # ── Risk contributions ────────────────────────────────────────────────────
    Cov_w = cov @ w
    for i, ticker in enumerate(tickers):
        rc = float(w[i] * Cov_w[i]) / port_var  # fractional risk contribution
        rc_pct = rc * 100.0
        weight_pct = float(w[i] * total_w) * 100.0
        if rc_pct > RISK_CONTRIBUTION_MULTIPLE * weight_pct and weight_pct > 0.5:
            severity = min(100, int(40 + (rc_pct / weight_pct - RISK_CONTRIBUTION_MULTIPLE) * 15))
            summary = (
                f"{ticker}: risk contribution {rc_pct:.1f}% vs weight {weight_pct:.1f}% "
                f"({rc_pct / weight_pct:.1f}× — threshold {RISK_CONTRIBUTION_MULTIPLE:.0f}×)"
            )
            fid = agent_db.insert_finding(
                run_id=run_id,
                finding_type="risk_contribution",
                ticker=ticker,
                severity=severity,
                confidence=75,
                summary=summary,
                why_now=f"{ticker} contributes disproportionate risk relative to its weight.",
                metrics={
                    "risk_contribution_pct": round(rc_pct, 2),
                    "weight_pct": round(weight_pct, 2),
                    "rc_to_weight_ratio": round(rc_pct / weight_pct, 2),
                    "threshold_multiple": RISK_CONTRIBUTION_MULTIPLE,
                },
            )
            print(f"[guardian] Risk contribution finding #{fid}: {ticker} rc={rc_pct:.1f}% weight={weight_pct:.1f}% (severity={severity})")

    # ── Correlation clustering ────────────────────────────────────────────────
    corr = np.corrcoef(R)  # (n, n)
    n = len(tickers)
    # Find connected components with correlation > threshold
    adj: dict[int, set[int]] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if corr[i, j] >= CORRELATION_CLUSTER_THRESHOLD:
                adj[i].add(j)
                adj[j].add(i)

    visited: set[int] = set()
    clusters: list[list[str]] = []
    for i in range(n):
        if i in visited or not adj[i]:
            continue
        cluster = []
        stack = [i]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            cluster.append(tickers[node])
            for nb in adj[node]:
                if nb not in visited:
                    stack.append(nb)
        if len(cluster) >= CORRELATION_CLUSTER_MIN_SIZE:
            clusters.append(cluster)

    for cluster in clusters:
        ticker_str = ", ".join(cluster)
        avg_corr = float(np.mean([
            corr[tickers.index(a), tickers.index(b)]
            for a in cluster for b in cluster if a != b
        ]))
        severity = min(100, int(50 + (avg_corr - CORRELATION_CLUSTER_THRESHOLD) * 200))
        summary = (
            f"Correlation cluster: {ticker_str} — avg correlation {avg_corr:.2f} "
            f"(threshold {CORRELATION_CLUSTER_THRESHOLD:.2f}, {len(cluster)} positions)"
        )
        fid = agent_db.insert_finding(
            run_id=run_id,
            finding_type="correlation_cluster",
            ticker=None,
            severity=severity,
            confidence=70,
            summary=summary,
            why_now=f"{len(cluster)} holdings move together — hidden concentration risk.",
            metrics={
                "cluster_tickers": cluster,
                "avg_correlation": round(avg_corr, 3),
                "threshold": CORRELATION_CLUSTER_THRESHOLD,
                "cluster_size": len(cluster),
            },
        )
        print(f"[guardian] Correlation cluster finding #{fid}: {ticker_str} avg_corr={avg_corr:.2f} (severity={severity})")


# --- Main agent entry point --------------------------------------------------

def run_portfolio_guardian(ctx: AgentContext) -> list[Recommendation]:
    print("[guardian] Starting Portfolio Guardian sweep")

    # ── 1. Layer drift ────────────────────────────────────────────────────────
    layer_rows = _latest_layer_rows()
    for row in layer_rows:
        layer_label = row["layer"]
        layer_num   = _LABEL_TO_INT.get(layer_label)
        weight_pct  = row["weight_pct"]
        target      = LAYER_TARGETS.get(layer_num) if layer_num else None
        if target is None:
            continue
        drift = weight_pct - target
        if abs(drift) < DRIFT_THRESHOLD:
            continue
        severity = _layer_severity(drift)
        layer_name = LAYER_NAMES.get(layer_num, layer_label)
        direction  = "over" if drift > 0 else "under"
        summary = (
            f"{layer_name}: {direction}weight by {abs(drift):.1f}pp "
            f"({weight_pct:.1f}% actual vs {target:.0f}% target)"
        )
        fid = agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="layer_drift",
            ticker=None,
            severity=severity,
            confidence=90,
            summary=summary,
            why_now=f"Layer weight has drifted {abs(drift):.1f}pp from target — "
                    f"rebalancing consideration.",
            metrics={"layer": layer_num, "weight_pct": weight_pct,
                     "target_pct": target, "drift_pp": round(drift, 2)},
        )
        print(f"[guardian] Layer drift finding #{fid}: {summary} (severity={severity})")

    # ── 2. Per-position checks ────────────────────────────────────────────────
    holding_rows = _latest_holding_rows()
    if not holding_rows:
        print("[guardian] No holding_day data — skipping position checks")
        return []

    for row in holding_rows:
        ticker     = row["ticker"]
        weight_pct = row["weight_pct"] or 0.0
        change_pct = row["change_pct"]  # may be None if no price change recorded

        triggers: dict = {}

        # Check A: position concentration
        if weight_pct > HOLDING_GROSS_DOM:
            triggers["concentration"] = {"weight_pct": weight_pct}

        if change_pct is not None:
            # Check B: portfolio NAV contribution
            impact_pp = weight_pct * change_pct / 100.0
            if abs(impact_pp) > _IMPACT_THRESHOLD_PP:
                triggers["impact"] = {
                    "impact_pp": round(impact_pp, 3),
                    "weight_pct": weight_pct,
                    "change_pct": change_pct,
                }

            # Check C: volatility-normalised Z-score
            hv20 = _compute_hv20(ticker)
            if hv20 and hv20 > 0:
                daily_vol = hv20 / math.sqrt(252)
                z = abs(change_pct / 100.0) / daily_vol
                if z >= _Z_THRESHOLD:
                    triggers["z_score"] = {
                        "z": round(z, 2),
                        "hv20_pct": round(hv20 * 100, 1),
                        "change_pct": change_pct,
                    }

        if not triggers:
            continue

        # Deterministic severity
        severity = _position_severity(triggers)

        # LLM prose (only if we have change_pct — concentration-only findings use fallback)
        llm = None
        if change_pct is not None and any(k in triggers for k in ("impact", "z_score")):
            llm = _llm_prose(
                ticker=ticker,
                layer=row["layer"],
                weight_pct=weight_pct,
                change_pct=change_pct,
                triggers=triggers,
            )

        if llm:
            summary  = llm["summary"]
            why_now  = llm["why_now"]
            metrics  = {
                "portfolio_implication": llm["portfolio_implication"],
                "no_action_case":        llm["no_action_case"],
                "suggested_action":      "REVIEW",
                **{k: v for k, v in triggers.items()},
            }
        else:
            summary, why_now = _fallback_summary(ticker, triggers)
            metrics = {"suggested_action": "REVIEW", **triggers}

        fid = agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="position_risk",
            ticker=ticker,
            severity=severity,
            confidence=80 if llm else 65,
            summary=summary,
            why_now=why_now,
            metrics=metrics,
        )
        print(f"[guardian] Position finding #{fid}: {ticker} "
              f"triggers={list(triggers)} severity={severity}")

    # ── 3. Portfolio-scope: sector concentration ──────────────────────────────
    _check_sector_concentration(holding_rows, ctx.run_id)

    # ── 4. Portfolio-scope: beta + risk contribution + correlation clusters ───
    _check_covariance_risk(holding_rows, ctx.run_id)

    print("[guardian] Sweep complete")
    return []


register_agent("portfolio_guardian", run_portfolio_guardian)
