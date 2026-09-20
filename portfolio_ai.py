#!/usr/bin/env python3
"""
Portfolio AI analysis engine.
Generates daily macro-aware portfolio insights and per-holding macro risk scores.
All AI calls go through ollama_client (phi-4-4bit on MLX).
"""
import csv
import hashlib
import json
import os
import sqlite3
import statistics
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from strategy_config import (
    LAYER_NAMES, LAYER_LABELS, LAYER_TARGETS, LAYER_DESCRIPTIONS, DRIFT_THRESHOLD,
)


def _normalize_ticker(t: str) -> str:
    """Mirror generate_dashboard.normalize_ticker: BRK.B → BRK-B."""
    t = str(t).strip().upper()
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            return f"{left}-{right}"
    return t


# ── Legislative connection rule ────────────────────────────────────────────────
# Single source of truth — injected verbatim into every AI prompt that involves
# legislative risk/opportunity assessment. Enforces a one-step direct connection:
# the bill must target this company's actual industry, products, or supply chain.
_LEG_RULE = (
    "LEGISLATIVE CONNECTION RULE (applies to all leg_risk, leg_opp, tax_angle, and "
    "legislative_watch fields): A bill qualifies ONLY if the connection is one direct "
    "logical step — the bill explicitly regulates, taxes, subsidizes, or creates demand "
    "for THIS company's actual business. Test: 'bill targets X → this company does X.' "
    "If the connection requires inference or analogy (e.g. a healthcare bill affecting a "
    "streaming company; an energy bill affecting a retailer; a defense bill affecting a "
    "consumer brand), it does NOT qualify — omit the field entirely or write null. "
    "Do not manufacture connections to fill the field. "
    "DOMAIN CROSS-CHECK: Each bill in the BILLS UNDER REVIEW section is annotated with "
    "[domains: ...]. Each ticker in the TICKER PROFILES section lists its domains. "
    "If a bill's domains and a ticker's domains share NO overlap, there is no direct "
    "connection — skip that bill for that ticker and write null."
)


def _extract_json(text: str):
    """
    Robustly extract the first complete JSON object from raw LLM output.
    Handles code fences (```json...```) and preamble text before the JSON.
    Tries each '{' position in order until one yields valid JSON.
    Returns the parsed object, or None if nothing parses.
    """
    import re
    # Strip common code-fence wrappers
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text, i)
                return obj
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def _is_placeholder_json(obj: dict) -> bool:
    """Return True if all string values in obj are '...' (reasoning sketch, not real output)."""
    vals = []
    for v in obj.values():
        if isinstance(v, str):
            vals.append(v.strip())
        elif isinstance(v, list) and v:
            vals.extend(str(x).strip() for x in v[:3])
    return bool(vals) and all(v == "..." for v in vals)


def _extract_last_json(text: str, required_keys=None):
    """Return the LAST valid JSON object in text that contains all required_keys
    and does not consist entirely of '...' placeholder values.

    Qwen3 thinking models write JSON sketches with '...' placeholders early in
    their reasoning chain, then write the real filled-in answer later. Scanning
    from the end (keeping the last match) picks up the real answer and ignores
    the reasoning drafts. required_keys filters out nested objects inside the
    answer (e.g. array elements) that don't have the top-level schema keys.
    """
    import re
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())
    dec = json.JSONDecoder()
    last_obj = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
            if not isinstance(obj, dict):
                continue
            if required_keys and not all(k in obj for k in required_keys):
                continue
            if _is_placeholder_json(obj):
                continue
            last_obj = obj
        except (ValueError, json.JSONDecodeError):
            continue
    return last_obj

# Load .env before ollama_client reads LLM_URL at import time
_PROJECT_DIR_EARLY = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_PROJECT_DIR_EARLY / ".env")
except Exception:
    pass

import ollama_client

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"

_LAYER_NAMES_LONG = {
    n: f"{LAYER_NAMES[n]} ({LAYER_DESCRIPTIONS[n]})"
    for n in LAYER_NAMES
}

# ── Canonical macro framework ─────────────────────────────────────────────────
# Single source of truth for all three scoring systems: macro scores, news
# analysis, and portfolio insight. All prompts derive language from here.
MACRO_DIMS = {
    "rate_sensitivity": {
        "label":      "Rate Sensitivity",
        "short":      "Hurt by rising rates",
        "direction":  "risk",
        "prompt_def": (
            "How much does a +50bps rise in the 10Y Treasury yield hurt this position? "
            "(10=very hurt: long-duration bonds, high-PE growth, REITs, leveraged balance sheets; "
            "1=immune or benefits: short-duration cash, banks, financials with floating-rate assets)"
        ),
    },
    "inflation_hedge": {
        "label":      "Inflation Hedge",
        "short":      "Benefits from sustained inflation",
        "direction":  "benefit",
        "prompt_def": (
            "How well does this position benefit from sustained inflation above 3%? "
            "(10=strong hedge: gold, commodities, energy, TIPS, real assets, pricing-power franchises; "
            "1=hurt: fixed income, long-duration, consumer discretionary with margin pressure)"
        ),
    },
    "dollar_sensitivity": {
        "label":      "Dollar Sensitivity",
        "short":      "Hurt by strong dollar",
        "direction":  "risk",
        "prompt_def": (
            "How much does a strengthening US dollar hurt this position? "
            "(10=very hurt: multinational exporters with large overseas revenue, EM exposure, "
            "USD-priced commodity producers; 1=immune or benefits: domestic services, US importers)"
        ),
    },
    "geopolitical_risk": {
        "label":      "Geopolitical / Trade Risk",
        "short":      "Trade/geopolitical exposure",
        "direction":  "risk",
        "prompt_def": (
            "How exposed is this position to trade wars, tariffs, sanctions, or geopolitical disruption? "
            "(10=high: China-exposed tech, global supply chains, defense-adjacent, foreign revenue dependent; "
            "1=low: domestic utilities, US healthcare services, domestically sourced businesses)"
        ),
    },
}
SCORE_STALE_DAYS = 5          # scores older than this get a staleness warning in prompts
SCORE_DIMS   = list(MACRO_DIMS.keys())                      # backwards compat
SCORE_LABELS = {k: v["short"] for k, v in MACRO_DIMS.items()}  # backwards compat

# ── Holding profiles ─────────────────────────────────────────────────────────
# Per-ticker description and legislative domain list.  Used to cross-check bill
# domains against holding domains before the model writes leg_risk/leg_opp/tax_angle.
# Funds (is_fund=True) are passive vehicles — only connect to tax_capital_gains /
# tax_corporate; they have no direct operational regulatory exposure.
HOLDING_PROFILES = {
    # Layer 1 — Structural Ballast
    "VTSAX":  {"desc": "Vanguard Total Stock Market Index Fund (passive broad market)",  "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "VFIAX":  {"desc": "Vanguard 500 Index Fund (passive S&P 500)",                      "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "VTMGX":  {"desc": "Vanguard Developed Markets Index Fund (passive international)",  "domains": ["tax_capital_gains", "trade"],         "is_fund": True},
    "BRK-B":  {"desc": "Berkshire Hathaway — diversified holding company: insurance, energy (BNSF/utilities), financial services, consumer brands",
               "domains": ["financial", "energy", "trade", "consumer", "tax_corporate", "environment"]},
    # Layer 2 — Cash-Flow Engines
    "SCHD":   {"desc": "Schwab U.S. Dividend Equity ETF (passive dividend-focused)",     "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "BP":     {"desc": "BP — integrated oil & gas company, global energy operations",
               "domains": ["energy", "environment", "trade", "tax_corporate"]},
    # Layer 3 — Compounders
    "FSPTX":  {"desc": "Fidelity Select Technology Portfolio (active tech fund)",        "domains": ["technology", "tax_capital_gains"], "is_fund": True},
    "STZ":    {"desc": "Constellation Brands — beer, wine, and spirits producer; significant Mexico import operations",
               "domains": ["food_ag", "consumer", "trade", "tax_corporate"]},
    "SNA":    {"desc": "Snap-on Tools — industrial tools and equipment manufacturer",
               "domains": ["labor", "trade", "tax_corporate"]},
    "SLYV":   {"desc": "SPDR S&P 600 Small-Cap Value ETF (passive small-cap value)",    "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "GRMN":   {"desc": "Garmin — GPS navigation, aviation avionics, wearables, marine electronics",
               "domains": ["technology", "aviation", "consumer", "trade"]},
    "EW":     {"desc": "Edwards Lifesciences — structural heart valves and hemodynamic monitoring (medical devices)",
               "domains": ["healthcare", "tax_corporate"]},
    "ITW":    {"desc": "Illinois Tool Works — diversified industrial manufacturer: automotive, construction, food equipment",
               "domains": ["trade", "labor", "environment", "tax_corporate"]},
    "NFLX":   {"desc": "Netflix — streaming entertainment subscription service",
               "domains": ["telecom", "technology", "consumer", "tax_corporate"]},
    "WMT":    {"desc": "Walmart — retail and grocery chain; large China import sourcing; major employer",
               "domains": ["consumer", "trade", "labor", "food_ag", "tax_corporate"]},
    # Layer 4 — Convexity / Optionality
    "JOBY":   {"desc": "Joby Aviation — electric air taxi (eVTOL) manufacturer, FAA certification in progress",
               "domains": ["aviation", "energy", "environment", "technology", "tax_corporate"]},
    "IGV":    {"desc": "iShares Expanded Tech-Software ETF (passive software-sector)",  "domains": ["technology", "tax_capital_gains"], "is_fund": True},
    "BTC":    {"desc": "Bitcoin — decentralized cryptocurrency",
               "domains": ["crypto", "financial", "tax_capital_gains"]},
    "DSGX":   {"desc": "Descartes Systems — logistics and supply chain software platform",
               "domains": ["technology", "transportation", "trade", "tax_corporate"]},
    "VVIAX":  {"desc": "Vanguard Value Index Fund Admiral (passive large-cap value index)", "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    # Layer 5 — Shock Absorbers
    "ITOCF":  {"desc": "Itochu Corp — Japanese trading conglomerate: food, textiles, energy, finance",
               "domains": ["trade", "food_ag", "energy", "financial"]},
    "MITSF":  {"desc": "Mitsubishi Corp — Japanese conglomerate: energy, materials, finance, infrastructure",
               "domains": ["trade", "energy", "financial", "environment"]},
    "UNP":    {"desc": "Union Pacific — Class I freight railroad, major cross-country rail network",
               "domains": ["transportation", "trade", "labor", "environment", "tax_corporate"]},
    "MCO":    {"desc": "Moody's — credit rating agency and financial data/analytics provider",
               "domains": ["financial", "ratings_advisory", "tax_corporate"]},
    "NOC":    {"desc": "Northrop Grumman — defense contractor, aerospace and nuclear systems",
               "domains": ["defense", "aviation", "tax_corporate"]},
}


_TAX_CATCHALL = {"tax_corporate", "tax_capital_gains"}

def _bills_with_holdings(bills: list, tickers: list) -> str:
    """Format bills annotated with pre-computed portfolio matches.
    Each bill line shows exactly which holdings are directly affected.
    Bills marked 'No holdings affected' are irrelevant to this portfolio.

    Matching uses primary domains only (strips tax_corporate/tax_capital_gains
    when other domains exist) to prevent every budget bill from matching all stocks."""
    lines = ["BILLS UNDER REVIEW — OFFICIAL RECORD (Congress.gov):"]
    for b in bills[:12]:
        bill_domains = set(b.get("domains", []))
        id_str   = f"[{b.get('bill_id', '')}] " if b.get("bill_id") else ""
        stage    = f" — {b['stage']}" if b.get("stage") else ""
        domain_s = f" [domains: {', '.join(sorted(bill_domains))}]" if bill_domains else ""
        # Strip generic tax catch-all domains when primary domains exist
        primary = bill_domains - _TAX_CATCHALL
        match_against = primary if primary else bill_domains
        matched = []
        for t in tickers:
            p = HOLDING_PROFILES.get(t) or HOLDING_PROFILES.get(t.replace(".", "-"))
            if p and (match_against & set(p["domains"])):
                matched.append(t)
        match_s = f" → Portfolio match: {', '.join(matched)}" if matched else " → No holdings affected"
        lines.append(f"  {id_str}{b['title']}{domain_s}{stage}{match_s}")
        if b.get("summary") and matched:
            lines.append(f"    CRS: {b['summary'][:200]}")
    return "\n".join(lines)


def _holding_profile_block(tickers: list) -> str:
    """Format a TICKER PROFILES section for AI prompts listing each ticker's desc and domains."""
    lines = ["TICKER PROFILES (use domains to evaluate legislative relevance):"]
    for t in tickers:
        profile = HOLDING_PROFILES.get(t) or HOLDING_PROFILES.get(t.replace(".", "-"))
        if profile:
            domain_str = ", ".join(profile["domains"])
            fund_note  = " (passive fund — only tax/budget bills apply)" if profile.get("is_fund") else ""
            lines.append(f"  {t}: {profile['desc']}{fund_note} [domains: {domain_str}]")
        else:
            lines.append(f"  {t}: (no profile — evaluate on company fundamentals)")
    return "\n".join(lines)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _init_ai_tables():
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_insights (
        day          TEXT PRIMARY KEY,
        insight      TEXT,
        macro_snap   TEXT,
        generated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS holding_macro_scores (
        ticker     TEXT PRIMARY KEY,
        scores     TEXT,
        updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS news_summaries (
        day          TEXT PRIMARY KEY,
        summaries    TEXT,
        generated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS holding_macro_scores_history (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker    TEXT NOT NULL,
        scores    TEXT NOT NULL,
        scored_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_score_summaries (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        summary_json TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hmsh_ticker_scored "
        "ON holding_macro_scores_history (ticker, scored_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mss_created "
        "ON macro_score_summaries (created_at DESC)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_scoring_runs (
        run_id             TEXT PRIMARY KEY,
        run_at             TEXT NOT NULL,
        expected_n         INTEGER,
        scored_n           INTEGER,
        failed_n           INTEGER,
        supported_scored_n INTEGER,
        unsupported_n      INTEGER,
        coverage_pct       REAL,
        model_ver          TEXT,
        schema_ver         TEXT,
        macro_hash         TEXT,
        status             TEXT NOT NULL DEFAULT 'IN_PROGRESS',
        errors_json        TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_regime_snapshots (
        snapshot_date TEXT PRIMARY KEY,
        regime_json   TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )""")
    # Add run_id column to holding_macro_scores if not present
    try:
        conn.execute("ALTER TABLE holding_macro_scores ADD COLUMN run_id TEXT")
    except Exception:
        pass
    # Add provenance columns to holding_macro_scores_history if not present (0475)
    for col_sql in [
        "ALTER TABLE holding_macro_scores_history ADD COLUMN run_id TEXT",
        "ALTER TABLE holding_macro_scores_history ADD COLUMN model_ver TEXT",
        "ALTER TABLE holding_macro_scores_history ADD COLUMN schema_ver TEXT",
        "ALTER TABLE holding_macro_scores_history ADD COLUMN evidence_hash TEXT",
    ]:
        try:
            conn.execute(col_sql)
        except Exception:
            pass
    # Add errors_json to macro_scoring_runs if not present (0478)
    try:
        conn.execute("ALTER TABLE macro_scoring_runs ADD COLUMN errors_json TEXT")
    except Exception:
        pass
    # Add supported_scored_n / unsupported_n columns to macro_scoring_runs (0515)
    for _col_sql in [
        "ALTER TABLE macro_scoring_runs ADD COLUMN supported_scored_n INTEGER",
        "ALTER TABLE macro_scoring_runs ADD COLUMN unsupported_n INTEGER",
    ]:
        try:
            conn.execute(_col_sql)
        except Exception:
            pass
    # Health snapshots table (0492)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_health_snapshots (
            snapshot_id            TEXT PRIMARY KEY,
            run_id                 TEXT,
            captured_at            TEXT,
            supported_count        INTEGER,
            unsupported_count      INTEGER,
            portfolio_coverage_pct REAL,
            stale_series_json      TEXT,
            unknown_regime_fields_json TEXT,
            weak_beta_count        INTEGER,
            unexplained_drift_count INTEGER,
            stale_failed_count     INTEGER,
            health_json            TEXT
        )
    """)
    # macro_snapshot column on decision_episodes (0494)
    try:
        conn.execute("ALTER TABLE decision_episodes ADD COLUMN macro_snapshot TEXT")
    except Exception:
        pass
    # Validation acceptance state table (0497)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_acceptance_state (
            contract       TEXT PRIMARY KEY,
            accepted_at    TEXT,
            record_id      TEXT,
            commit_sha     TEXT,
            model_identity TEXT,
            notes          TEXT
        )
    """)
    # Per-ticker × dim stability from acceptance/scoring runs (0506, 0510)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_dimension_stability (
            ticker              TEXT NOT NULL,
            dim                 TEXT NOT NULL,
            stdev               REAL,
            mean                REAL,
            n_samples           INTEGER,
            stability_class     TEXT,
            updated_at          TEXT NOT NULL,
            acceptance_record_id TEXT,
            config_version      TEXT,
            config_hash         TEXT,
            model_identity      TEXT,
            validation_run_type TEXT,
            PRIMARY KEY (ticker, dim)
        )
    """)
    # Geo evidence for foreign / geopolitical scoring (0508, 0516)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_geo_profile (
            ticker                     TEXT PRIMARY KEY,
            primary_hq_country         TEXT,
            incorporation_country      TEXT,
            major_operating_regions    TEXT,
            revenue_domestic_pct       REAL,
            revenue_us_pct             REAL,
            revenue_em_pct             REAL,
            supply_chain_concentration TEXT,
            sanctions_exposure         TEXT,
            tariff_sensitivity         TEXT,
            updated_at                 TEXT NOT NULL,
            data_source                TEXT,
            source_date                TEXT,
            retrieved_at               TEXT,
            confidence                 TEXT,
            evidence_hash              TEXT,
            notes                      TEXT
        )
    """)
    # Add scorer_contract_hash to acceptance tables for existing DBs (0531)
    for _col_sql in [
        "ALTER TABLE macro_acceptance_state ADD COLUMN scorer_contract_hash TEXT",
        "ALTER TABLE macro_dimension_validation ADD COLUMN scorer_contract_hash TEXT",
    ]:
        try:
            conn.execute(_col_sql)
        except Exception:
            pass
    # Add provenance columns to macro_dimension_stability for existing DBs (0510)
    for _col_sql in [
        "ALTER TABLE macro_dimension_stability ADD COLUMN acceptance_record_id TEXT",
        "ALTER TABLE macro_dimension_stability ADD COLUMN config_version TEXT",
        "ALTER TABLE macro_dimension_stability ADD COLUMN config_hash TEXT",
        "ALTER TABLE macro_dimension_stability ADD COLUMN model_identity TEXT",
        "ALTER TABLE macro_dimension_stability ADD COLUMN validation_run_type TEXT",
    ]:
        try:
            conn.execute(_col_sql)
        except Exception:
            pass
    # Add provenance columns to company_geo_profile for existing DBs (0516)
    for _col_sql in [
        "ALTER TABLE company_geo_profile ADD COLUMN data_source TEXT",
        "ALTER TABLE company_geo_profile ADD COLUMN source_date TEXT",
        "ALTER TABLE company_geo_profile ADD COLUMN retrieved_at TEXT",
        "ALTER TABLE company_geo_profile ADD COLUMN confidence TEXT",
        "ALTER TABLE company_geo_profile ADD COLUMN evidence_hash TEXT",
        "ALTER TABLE company_geo_profile ADD COLUMN notes TEXT",
    ]:
        try:
            conn.execute(_col_sql)
        except Exception:
            pass
    # Accepted validation table — append-only; one row per acceptance run × ticker × dim (0517)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_dimension_validation (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            acceptance_record_id TEXT NOT NULL,
            ticker               TEXT NOT NULL,
            dimension            TEXT NOT NULL,
            mean_score           REAL,
            stddev               REAL,
            n_samples            INTEGER,
            stability_class      TEXT,
            config_version       TEXT,
            config_hash          TEXT,
            model_identity       TEXT,
            recorded_at          TEXT,
            UNIQUE(acceptance_record_id, ticker, dimension)
        )
    """)
    for _table, _column in (
        ("macro_dimension_validation", "scorer_contract_hash"),
        ("macro_dimension_validation", "prompt_hash"),
        ("macro_dimension_validation", "evidence_hash"),
        ("macro_dimension_validation", "eligible"),
        ("macro_dimension_validation", "eligibility_reason"),
        ("macro_acceptance_state", "output_path"),
        ("macro_scoring_runs", "scorer_contract_hash"),
    ):
        _columns = {r[1] for r in conn.execute(f"PRAGMA table_info({_table})")}
        if _column not in _columns:
            conn.execute(f"ALTER TABLE {_table} ADD COLUMN {_column} TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_validation_runs (
        record_id TEXT PRIMARY KEY, output_path TEXT NOT NULL,
        run_type TEXT NOT NULL, verdict TEXT NOT NULL, artifact_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    )""")
    # Runtime stability table — mutable; one row per ticker × dim; scorer overwrites here (0517)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_dimension_runtime_stability (
            ticker          TEXT NOT NULL,
            dimension       TEXT NOT NULL,
            mean_score      REAL,
            stddev          REAL,
            n_samples       INTEGER,
            stability_class TEXT,
            updated_at      TEXT,
            PRIMARY KEY (ticker, dimension)
        )
    """)
    # Schema migration version tracking — idempotent (0527)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at   TEXT NOT NULL
        )
    """)
    # Migration M001 (0517): copy macro_dimension_stability rows into split tables.
    # Savepoint-guarded so partial failure leaves new tables empty rather than partially filled.
    _m001 = conn.execute(
        "SELECT 1 FROM _schema_migrations WHERE migration_id='M001_stability_split'"
    ).fetchone()
    if not _m001:
        try:
            conn.execute("SAVEPOINT m001")
            _old_rows = conn.execute(
                "SELECT ticker, dim, stdev, mean, n_samples, stability_class, updated_at, "
                "acceptance_record_id, config_version, config_hash, model_identity, validation_run_type "
                "FROM macro_dimension_stability"
            ).fetchall()
            for _r in _old_rows:
                _tk, _dm, _sv, _mn, _ns, _sc, _up, _ar, _cv, _ch, _mi, _vt = _r
                if _vt == "accepted_validation" and _ar:
                    conn.execute(
                        "INSERT OR IGNORE INTO macro_dimension_validation "
                        "(acceptance_record_id, ticker, dimension, mean_score, stddev, "
                        "n_samples, stability_class, config_version, config_hash, "
                        "model_identity, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (_ar, _tk, _dm, _mn, _sv, _ns, _sc, _cv, _ch, _mi, _up)
                    )
                else:
                    conn.execute(
                        "INSERT OR REPLACE INTO macro_dimension_runtime_stability "
                        "(ticker, dimension, mean_score, stddev, n_samples, stability_class, updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (_tk, _dm, _mn, _sv, _ns, _sc, _up)
                    )
            conn.execute(
                "INSERT INTO _schema_migrations (migration_id, applied_at) VALUES (?,?)",
                ("M001_stability_split", datetime.utcnow().isoformat())
            )
            conn.execute("RELEASE SAVEPOINT m001")
        except Exception as _mig_err:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT m001")
                conn.execute("RELEASE SAVEPOINT m001")
            except Exception:
                pass
            print(f"[InitDB] WARNING: M001 migration failed, new tables left empty: {_mig_err}")
    # Seed initial geo profiles for known foreign companies (0508, 0516)
    # INSERT OR IGNORE — only writes on first creation; retrieved_at reflects actual sourcing date.
    now_iso = datetime.utcnow().isoformat()
    _GEO_SEEDS = [
        # ITOCF — Itochu Corp, Japanese general trading company; EM/Asia exposure from annual report
        {
            "ticker": "ITOCF",
            "primary_hq_country": "JP", "incorporation_country": "JP",
            "major_operating_regions": '["Japan","China","Southeast Asia","United States"]',
            "revenue_domestic_pct": 45.0, "revenue_us_pct": 5.0, "revenue_em_pct": 30.0,
            "supply_chain_concentration": "diversified",
            "sanctions_exposure": "none_known", "tariff_sensitivity": "medium",
            "data_source": "manual_research", "source_date": "2026-09",
            "retrieved_at": "2026-09-19T00:00:00",  # fixed: reflects actual sourcing date
            "confidence": "medium",
            "notes": "Ito Corporation — Japanese general trading company; EM/Asia exposure estimated from annual report",
        },
        # MITSF — Mitsubishi Corp, diversified Japanese conglomerate; global operations per IR materials
        {
            "ticker": "MITSF",
            "primary_hq_country": "JP", "incorporation_country": "JP",
            "major_operating_regions": '["Japan","China","Southeast Asia","Australia","United States"]',
            "revenue_domestic_pct": 40.0, "revenue_us_pct": 8.0, "revenue_em_pct": 28.0,
            "supply_chain_concentration": "diversified",
            "sanctions_exposure": "none_known", "tariff_sensitivity": "medium",
            "data_source": "manual_research", "source_date": "2026-09",
            "retrieved_at": "2026-09-19T00:00:00",  # fixed: reflects actual sourcing date
            "confidence": "medium",
            "notes": "Mitsubishi Corporation — diversified Japanese conglomerate; global operations per IR materials",
        },
    ]
    for _seed in _GEO_SEEDS:
        try:
            _ev_hash = hashlib.sha256(
                json.dumps({k: v for k, v in _seed.items()
                            if k not in ("retrieved_at", "notes")},
                           sort_keys=True).encode()
            ).hexdigest()
            conn.execute(
                "INSERT OR IGNORE INTO company_geo_profile "
                "(ticker, primary_hq_country, incorporation_country, major_operating_regions, "
                "revenue_domestic_pct, revenue_us_pct, revenue_em_pct, "
                "supply_chain_concentration, sanctions_exposure, tariff_sensitivity, updated_at, "
                "data_source, source_date, retrieved_at, confidence, evidence_hash, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (_seed["ticker"], _seed["primary_hq_country"], _seed["incorporation_country"],
                 _seed["major_operating_regions"], _seed["revenue_domestic_pct"],
                 _seed["revenue_us_pct"], _seed["revenue_em_pct"],
                 _seed["supply_chain_concentration"], _seed["sanctions_exposure"],
                 _seed["tariff_sensitivity"], now_iso,
                 _seed["data_source"], _seed["source_date"], _seed["retrieved_at"],
                 _seed["confidence"], _ev_hash, _seed["notes"])
            )
        except Exception:
            pass
    conn.commit()
    conn.close()


MACRO_SCORE_SCHEMA_VERSION = "v3"
MACRO_EVIDENCE_SCHEMA_VERSION = "v2"
MACRO_AGGREGATION_VERSION = "adaptive-median-v1"
MACRO_INTERACTION_VERSION = "macro_interaction_v1"
_MACRO_SCORE_DIMS = ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk")
_STALE_SCORE_DAYS = 14

# Minimum evidence quality for each dimension to be usable for formal attribution (0512).
# "none" and "unsupported" are always ineligible regardless of stability.
# geopolitical_risk requires "full" — "partial" geo evidence is too thin until 0508 data matures.
_EV_MIN_FOR_USABILITY = {
    "rate_sensitivity":   {"full", "partial"},
    "dollar_sensitivity": {"full", "partial"},
    "inflation_hedge":    {"full", "partial"},
    "geopolitical_risk":  {"full"},
}

# Map dim name to its evidence_quality key in the score/evidence dict (0512)
_DIM_EV_KEY = {
    "rate_sensitivity":   "evidence_quality_rate",
    "dollar_sensitivity": "evidence_quality_dollar",
    "inflation_hedge":    "evidence_quality_inflation",
    "geopolitical_risk":  "evidence_quality_geo",
}

# LLM parameters that are part of the scoring contract (0529/0531)
_MACRO_SCORE_TEMPERATURE = 0.2
_MACRO_SCORE_NUM_PREDICT = 1600


def _build_macro_score_request(ticker: str, evidence: dict, betas) -> str:
    """Canonical LLM macro scoring prompt for a single ticker (0529).
    Both generate_holding_macro_scores() and the validator call this function.
    evidence: output of _fetch_company_evidence(ticker, conn)
    betas: output of _compute_equity_betas(ticker), or None/empty
    """
    dim_defs = "\n".join(
        f"- {dim} ({'1=low inflation protection, 10=strong inflation protection' if meta.get('direction') == 'benefit' else '1=low exposure, 10=high exposure'}): {meta['prompt_def']}"
        for dim, meta in MACRO_DIMS.items()
    )
    evidence_lines = []
    ev = evidence or {}
    if ev.get("evidence_quality") not in ("none", "fund"):
        parts = []
        if ev.get("sector"):
            parts.append(f"sector={ev['sector']}")
        if ev.get("gross_margin_pct") is not None:
            parts.append(f"gross_margin={ev['gross_margin_pct']:.1f}%")
        if ev.get("net_debt") is not None:
            parts.append(f"net_debt=${ev['net_debt']:.0f}M")
        if ev.get("interest_coverage") is not None:
            parts.append(f"interest_coverage={ev['interest_coverage']:.1f}x")
        if ev.get("foreign_rev_pct") is not None:
            parts.append(f"foreign_rev={ev['foreign_rev_pct']:.1f}%")
        if ev.get("revenue_ttm") is not None:
            parts.append(f"revenue_ttm=${ev['revenue_ttm']:.0f}M")
        if ev.get("geo_hq_country"):
            parts.append(f"hq={ev['geo_hq_country']}")
        if ev.get("geo_major_regions"):
            parts.append(f"regions={ev['geo_major_regions']}")
        if ev.get("geo_revenue_domestic_pct") is not None:
            parts.append(f"domestic_rev={ev['geo_revenue_domestic_pct']:.0f}%")
        if ev.get("geo_sanctions_exposure") and ev["geo_sanctions_exposure"] != "none_known":
            parts.append(f"sanctions={ev['geo_sanctions_exposure']}")
        if ev.get("geo_tariff_sensitivity") and ev["geo_tariff_sensitivity"] != "low":
            parts.append(f"tariff_sensitivity={ev['geo_tariff_sensitivity']}")
        if parts:
            evidence_lines.append(f"Company data for {ticker}: {', '.join(parts)}")
    b = betas or {}
    if b:
        rb = b.get("rate_beta_100bp_return_pct")
        ub = b.get("usd_beta_1pct_return_pct")
        r2 = b.get("r_squared")
        rate_conf = b.get("rate_beta_confidence", "insufficient_data")
        usd_conf  = b.get("usd_beta_confidence",  "insufficient_data")
        rate_line = (
            f"rate_beta={rb:.2f}%/100bps (t={b.get('rate_t')}, {rate_conf})"
            if rate_conf in ("suggestive", "stronger")
            else "rate factor: insufficient data (t<1.5) — not reliable"
        )
        usd_line = (
            f"usd_beta={ub:.2f}%/1%UUP (t={b.get('usd_t')}, {usd_conf})"
            if usd_conf in ("suggestive", "stronger")
            else "usd factor: insufficient data (t<1.5) — not reliable"
        )
        evidence_lines.append(
            f"Measured betas for {ticker}: {rate_line}, {usd_line}, "
            f"market_beta={b.get('market_beta', 0):.2f}, R²={r2:.2f}, n={b.get('n_weeks')}wk"
        )
    evidence_block = ("\n" + "\n".join(evidence_lines) + "\n") if evidence_lines else ""
    return f"""You are a quantitative analyst. Score each ticker's structural macro exposure on 4 dimensions from 1-10, with a specific reason for each score.

Structural exposure measures how sensitive each company's business is to each macro factor — independent of current market conditions. Score based on business model, revenue geography, balance sheet structure, and sector characteristics.
{evidence_block}
Scoring definitions (scale is dimension-specific — read each label carefully):
{dim_defs}

Tickers to score: {ticker}

Return ONLY valid JSON. Each dimension must include a score AND a one-sentence reason explaining specifically why that score applies to this ticker:
{{
  "TICKER1": {{
    "rate_sensitivity": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "inflation_hedge": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "dollar_sensitivity": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "geopolitical_risk": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "note": "<one sentence overall summary>"
  }}
}}"""


def _compute_scorer_contract_hash() -> str:
    """Content hash over all scoring contract components that define compatibility (0531).
    Changes to MACRO_DIMS, model, temperature, num_predict, or the prompt template
    all produce a different hash, automatically invalidating stale acceptance records.
    """
    import ollama_client
    import inspect
    contract = {
        "prompt_builder_source": inspect.getsource(_build_macro_score_request),
        "response_validator_source": inspect.getsource(_parse_and_validate_macro_score_response) + inspect.getsource(_validate_macro_score_response),
        "macro_dims":      MACRO_DIMS,
        "model_identity":  ollama_client.DEFAULT_MODEL,
        "temperature":     _MACRO_SCORE_TEMPERATURE,
        "num_predict":     _MACRO_SCORE_NUM_PREDICT,
        "schema_version":  MACRO_SCORE_SCHEMA_VERSION,
        "evidence_schema_version": MACRO_EVIDENCE_SCHEMA_VERSION,
        "aggregation_version": MACRO_AGGREGATION_VERSION,
        "prompt_template": _build_macro_score_request("__TICKER__", {}, None),
    }
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True).encode()
    ).hexdigest()


def _stability_class(stdev) -> str:
    """Map per-dim stdev to stability class (0506)."""
    if stdev is None:
        return "untested"
    if stdev <= 1.0:
        return "stable"
    if stdev <= 1.5:
        return "borderline"
    return "unstable"


def _dimension_validation_state(row: dict, config=None) -> dict:
    """Canonical per-dimension validation class and eligibility policy (0541).

    Range remains a diagnostic warning. Eligibility is based on the versioned
    stability class: stable and borderline are eligible; unstable/incomplete
    observations are not.
    """
    config = config or {}
    stdev = row.get("stdev")
    n = row.get("n", row.get("n_samples", 0))
    expected_n = config.get("n_repeats")
    cls = _stability_class(stdev)
    if expected_n is not None and n != expected_n:
        return {"stability_class": "untested", "eligible": False,
                "eligibility_reason": "incomplete_samples", "range_warning": False}
    eligible = cls in ("stable", "borderline")
    threshold = config.get("thresholds", {}).get("same_input_score_max_range")
    range_warning = threshold is not None and row.get("range") is not None and row["range"] > threshold
    reason = None if eligible else "unstable_standard_deviation"
    if range_warning and eligible:
        reason = "range_warning"
    return {"stability_class": cls, "eligible": eligible,
            "eligibility_reason": reason, "range_warning": bool(range_warning)}


def _accepted_dim_state(ticker: str, dim: str, conn) -> dict:
    """Return the accepted dimension state for ticker×dim from the active contract (0525, 0531).
    Single source of truth for both usability gate and *_validated_stability fields.
    Returns dict with: stability_class, mean_score, stddev, n_samples, record_id, usable (bool),
    usable_reason (str|None). Returns usable=False with usable_reason='acceptance_stale_scorer_contract'
    when the current scoring contract differs from the one accepted (0531)."""
    default = {"stability_class": None, "mean_score": None, "stddev": None,
               "n_samples": None, "record_id": None, "usable": False, "usable_reason": None}
    try:
        rec = conn.execute(
            "SELECT record_id, scorer_contract_hash FROM macro_acceptance_state "
            "WHERE contract='macro_validation_v1' AND record_id IS NOT NULL "
            "ORDER BY accepted_at DESC LIMIT 1"
        ).fetchone()
        if not rec:
            return default
        record_id, stored_hash = rec[0], rec[1]
        try:
            if not stored_hash or _compute_scorer_contract_hash() != stored_hash:
                return {**default, "record_id": record_id,
                        "usable_reason": "acceptance_stale_scorer_contract"}
        except Exception:
            return {**default, "record_id": record_id,
                    "usable_reason": "acceptance_contract_unavailable"}
        row = conn.execute(
            "SELECT stability_class, mean_score, stddev, n_samples, eligible, eligibility_reason FROM macro_dimension_validation "
            "WHERE acceptance_record_id=? AND ticker=? AND dimension=?",
            (record_id, ticker, dim)
        ).fetchone()
        if not row:
            return {**default, "record_id": record_id}
        cls = row[0]
        eligible = bool(row[4]) if row[4] is not None else cls in ("stable", "borderline")
        return {
            "stability_class": cls,
            "mean_score":      row[1],
            "stddev":          row[2],
            "n_samples":       row[3],
            "record_id":       record_id,
            "usable":          eligible,
            "usable_reason":   row[5] if not eligible else None,
        }
    except Exception:
        return default


def _is_formally_usable(ticker, dim, conn):
    """True only when the active acceptance contract has validated this ticker×dim as stable (0519, 0525)."""
    return _accepted_dim_state(ticker, dim, conn)["usable"]


def _usable_for_attribution(ticker, dim, evidence_quality, conn):
    """Dimension is attribution-ready only when BOTH evidence quality meets the minimum
    AND a formal accepted_validation stability row exists (0511, 0512)."""
    if evidence_quality not in _EV_MIN_FOR_USABILITY.get(dim, set()):
        return False
    return _is_formally_usable(ticker, dim, conn)


def _n_samples_for_dim(ticker, dim, conn):
    """Adaptive N: 1 for stable, 3 for borderline/untested, 5 for unstable (0507).
    Reads runtime_stability first; falls back to validation table (0517)."""
    try:
        row = conn.execute(
            "SELECT stability_class FROM macro_dimension_runtime_stability WHERE ticker=? AND dimension=?",
            (ticker, dim)
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT stability_class FROM macro_dimension_validation "
                "WHERE ticker=? AND dimension=? ORDER BY recorded_at DESC LIMIT 1",
                (ticker, dim)
            ).fetchone()
        cls = row[0] if row else "untested"
    except Exception:
        cls = "untested"
    return {"stable": 1, "borderline": 3, "untested": 3, "unstable": 5}.get(cls, 3)


def _get_macro_acceptance_state(conn: sqlite3.Connection) -> dict:
    """Return the latest macro acceptance record, or {} if none exists (0497)."""
    try:
        row = conn.execute(
            "SELECT contract, accepted_at, record_id, commit_sha, scorer_contract_hash "
            "FROM macro_acceptance_state ORDER BY accepted_at DESC LIMIT 1"
        ).fetchone()
        if row:
            current = _compute_scorer_contract_hash()
            return {"contract": row[0], "accepted_at": row[1],
                    "record_id": row[2], "commit_sha": row[3],
                    "scorer_contract_hash": row[4],
                    "usable": bool(row[4]) and row[4] == current,
                    "usable_reason": None if row[4] == current else "acceptance_stale_scorer_contract"}
    except Exception:
        pass
    return {}


def _classify_macro_coverage(ticker: str, conn: sqlite3.Connection) -> str:
    """Return one of the five coverage states for a ticker (0500)."""
    if is_fund(ticker):
        return "fund_unsupported"
    row = conn.execute(
        "SELECT updated_at, scores FROM holding_macro_scores WHERE ticker=? ORDER BY updated_at DESC LIMIT 1",
        (ticker,)
    ).fetchone()
    if not row:
        return "no_score_available"
    try:
        scored_dt = datetime.fromisoformat(row[0])
        if (datetime.now() - scored_dt).days > _STALE_SCORE_DAYS:
            return "stale_score"
    except Exception:
        return "stale_score"
    try:
        payload = json.loads(row[1])
        if payload.get("scorer_contract_hash") != _compute_scorer_contract_hash():
            return "stale_scorer_contract"
    except Exception:
        return "stale_scorer_contract"
    return "company_supported"


# Canonical security master — single source of truth for security type classification.
# security_type: "company" | "etf" | "mutual_fund"
# MSTR is a company (MicroStrategy), not a fund. Do not add it here.
SECURITY_MASTER: dict[str, dict] = {
    # ETFs
    "SPY":   {"security_type": "etf",         "fund_family": "SPDR"},
    "IVV":   {"security_type": "etf",         "fund_family": "iShares"},
    "VTI":   {"security_type": "etf",         "fund_family": "Vanguard"},
    "QQQ":   {"security_type": "etf",         "fund_family": "Invesco"},
    "IWM":   {"security_type": "etf",         "fund_family": "iShares"},
    "DIA":   {"security_type": "etf",         "fund_family": "SPDR"},
    "EFA":   {"security_type": "etf",         "fund_family": "iShares"},
    "EEM":   {"security_type": "etf",         "fund_family": "iShares"},
    "VEA":   {"security_type": "etf",         "fund_family": "Vanguard"},
    "VWO":   {"security_type": "etf",         "fund_family": "Vanguard"},
    "IEFA":  {"security_type": "etf",         "fund_family": "iShares"},
    "SCHD":  {"security_type": "etf",         "fund_family": "Schwab"},
    "VYM":   {"security_type": "etf",         "fund_family": "Vanguard"},
    "DVY":   {"security_type": "etf",         "fund_family": "iShares"},
    "NOBL":  {"security_type": "etf",         "fund_family": "ProShares"},
    "IGV":   {"security_type": "etf",         "fund_family": "iShares"},
    "SLYV":  {"security_type": "etf",         "fund_family": "SPDR"},
    "GLD":   {"security_type": "etf",         "fund_family": "SPDR"},
    "SLV":   {"security_type": "etf",         "fund_family": "iShares"},
    "IAU":   {"security_type": "etf",         "fund_family": "iShares"},
    "GDX":   {"security_type": "etf",         "fund_family": "VanEck"},
    "GDXJ":  {"security_type": "etf",         "fund_family": "VanEck"},
    "USO":   {"security_type": "etf",         "fund_family": "USCF"},
    "BIL":   {"security_type": "etf",         "fund_family": "SPDR"},
    "SHY":   {"security_type": "etf",         "fund_family": "iShares"},
    "IEI":   {"security_type": "etf",         "fund_family": "iShares"},
    "IEF":   {"security_type": "etf",         "fund_family": "iShares"},
    "TLT":   {"security_type": "etf",         "fund_family": "iShares"},
    "AGG":   {"security_type": "etf",         "fund_family": "iShares"},
    "BND":   {"security_type": "etf",         "fund_family": "Vanguard"},
    "LQD":   {"security_type": "etf",         "fund_family": "iShares"},
    "HYG":   {"security_type": "etf",         "fund_family": "iShares"},
    "JNK":   {"security_type": "etf",         "fund_family": "SPDR"},
    "EMB":   {"security_type": "etf",         "fund_family": "iShares"},
    "TIP":   {"security_type": "etf",         "fund_family": "iShares"},
    "XLF":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLK":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLE":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLV":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLI":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLU":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLB":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLP":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLY":   {"security_type": "etf",         "fund_family": "SPDR"},
    "XLRE":  {"security_type": "etf",         "fund_family": "SPDR"},
    "VNQ":   {"security_type": "etf",         "fund_family": "Vanguard"},
    "REM":   {"security_type": "etf",         "fund_family": "iShares"},
    "KBWB":  {"security_type": "etf",         "fund_family": "Invesco"},
    "IBB":   {"security_type": "etf",         "fund_family": "iShares"},
    "XBI":   {"security_type": "etf",         "fund_family": "SPDR"},
    "SMH":   {"security_type": "etf",         "fund_family": "VanEck"},
    "SOXX":  {"security_type": "etf",         "fund_family": "iShares"},
    "ARKK":  {"security_type": "etf",         "fund_family": "ARK"},
    "ARKG":  {"security_type": "etf",         "fund_family": "ARK"},
    "UUP":   {"security_type": "etf",         "fund_family": "Invesco"},
    "EWJ":   {"security_type": "etf",         "fund_family": "iShares"},
    "EWZ":   {"security_type": "etf",         "fund_family": "iShares"},
    "FXI":   {"security_type": "etf",         "fund_family": "iShares"},
    "KWEB":  {"security_type": "etf",         "fund_family": "KraneShares"},
    "BITO":  {"security_type": "etf",         "fund_family": "ProShares"},
    "GBTC":  {"security_type": "etf",         "fund_family": "Grayscale"},
    # Mutual funds
    "VFIAX": {"security_type": "mutual_fund", "fund_family": "Vanguard"},
    "VTSAX": {"security_type": "mutual_fund", "fund_family": "Vanguard"},
    "VTMGX": {"security_type": "mutual_fund", "fund_family": "Vanguard"},
    "VVIAX": {"security_type": "mutual_fund", "fund_family": "Vanguard"},
    "FSPTX": {"security_type": "mutual_fund", "fund_family": "Fidelity"},
    "FXAIX": {"security_type": "mutual_fund", "fund_family": "Fidelity"},
}


def is_fund(ticker: str) -> bool:
    """Return True if ticker is a known ETF or mutual fund (not a company)."""
    entry = SECURITY_MASTER.get(ticker.upper())
    return entry is not None and entry["security_type"] in ("etf", "mutual_fund")


def _score_val(dim_data):
    """Extract integer score from {score, reason} dict or bare int. Returns int in [1,10] or None."""
    if isinstance(dim_data, dict):
        v = dim_data.get("score")
    elif isinstance(dim_data, (int, float)):
        v = dim_data
    else:
        return None
    try:
        return max(1, min(10, int(v)))
    except (TypeError, ValueError):
        return None


def _validate_macro_score_response(raw: dict, ticker: str) -> dict:
    """Validate LLM score response for one ticker. Raises ValueError on invalid output."""
    for dim in _MACRO_SCORE_DIMS:
        if dim not in raw:
            raise ValueError(f"{ticker}: missing dimension '{dim}'")
        entry = raw[dim]
        if not isinstance(entry, dict):
            raise ValueError(f"{ticker}.{dim}: expected dict, got {type(entry).__name__}")
        score = entry.get("score")
        try:
            score_int = int(score)
        except (TypeError, ValueError):
            raise ValueError(f"{ticker}.{dim}: score {score!r} is not numeric")
        if not (1 <= score_int <= 10):
            raise ValueError(f"{ticker}.{dim}: score {score_int} out of range [1,10]")
        reason = entry.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{ticker}.{dim}: reason is missing or empty")
    return raw


def _parse_and_validate_macro_score_response(text: str, ticker: str) -> dict:
    """Parse and validate the exact response contract shared by production and validator."""
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{ticker}: response is not a JSON object")
    payload = next((v for k, v in parsed.items() if _normalize_ticker(k) == _normalize_ticker(ticker)), None)
    if not isinstance(payload, dict):
        raise ValueError(f"{ticker}: ticker payload missing")
    return _validate_macro_score_response(payload, ticker)


def _score_reason(dim_data) -> str:
    if isinstance(dim_data, dict):
        return str(dim_data.get("reason", ""))
    return ""


def _get_macro_scores_block(tickers=None, compact=False, reason_max=120):
    """
    Load macro scores from DB and return (scores_dict, formatted_block_for_prompt).
    Scores older than SCORE_STALE_DAYS get a staleness annotation.
    tickers: if given, only include those tickers in the block.
    compact: if True, omit per-dimension reasons (much smaller output, use for news prompts).
    reason_max: max chars per reason line when compact=False.
    """
    if not DB_PATH.exists():
        return {}, ""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, scores, updated_at FROM holding_macro_scores"
        ).fetchall()
        conn.close()
    except Exception:
        return {}, ""

    stale_cutoff = (datetime.now() - timedelta(days=SCORE_STALE_DAYS)).strftime("%Y-%m-%d")
    scores: dict = {}
    for r in rows:
        t = _normalize_ticker(r["ticker"])
        if tickers and t not in tickers:
            continue
        try:
            data = json.loads(r["scores"])
            scored_at = (r["updated_at"] or "")[:10]
            data["_scored_at"] = scored_at
            data["_stale"]     = scored_at < stale_cutoff
            data["_stale_contract"] = data.get("scorer_contract_hash") != _compute_scorer_contract_hash()
            data["_coverage_state"] = "stale_scorer_contract" if data["_stale_contract"] else ("stale_score" if data["_stale"] else "company_supported")
            if data["_stale_contract"]:
                # A stale-contract score is diagnostic coverage only; never feed it
                # back into downstream prompts as if it were current production data.
                continue
            scores[t] = data
        except Exception:
            pass

    if not scores:
        return {}, ""

    lines = [
        "PORTFOLIO MACRO DIMENSION SCORES (weekly AI scoring; 50bps rate-move basis; 1=low risk, 10=high):",
        "  Dimensions: Rate Sensitivity | Inflation Hedge | Dollar Sensitivity | Geopolitical/Trade Risk",
    ]
    for t, data in scores.items():
        scored_at = data["_scored_at"]
        stale_note = ("  ⚠ stale scorer contract" if data["_stale_contract"] else (f"  ⚠ scored {scored_at}" if data["_stale"] else f"  scored {scored_at}"))
        row = "  ".join(
            f"{dim[:4]}={_score_val(data.get(dim)) or '?'}"
            for dim in SCORE_DIMS
        )
        lines.append(f"  {t} [{row}]{stale_note}")
        if not compact:
            for dim in SCORE_DIMS:
                sv = _score_val(data.get(dim))
                sr = _score_reason(data.get(dim))
                if sv is not None and sr:
                    sr_trunc = sr[:reason_max] + "…" if len(sr) > reason_max else sr
                    lines.append(f"    {MACRO_DIMS[dim]['short']}: {sv}/10 — {sr_trunc}")
    return scores, "\n".join(lines)


def _load_holdings_csv() -> list[dict]:
    path = PROJECT_DIR / "holdings.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _get_layer_weights_from_db() -> dict:
    """Return most recent layer_day row as {layer_label: weight_pct}."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    day = conn.execute("SELECT MAX(day) FROM layer_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute("SELECT * FROM layer_day WHERE day=?", (day,)).fetchall()
    conn.close()
    return {r["layer"]: {"weight_pct": r["weight_pct"], "chg_pct": r["change_pct"],
                         "value": r["value"]} for r in rows}


def _get_holding_prices_from_db() -> dict:
    """Return most recent holding_day rows as {ticker: {price, chg_pct, value, weight_pct}}."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    day = conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute("SELECT * FROM holding_day WHERE day=?", (day,)).fetchall()
    conn.close()
    return {r["ticker"]: dict(r) for r in rows}


def _get_drift_alerts(layer_weights: dict) -> list[dict]:
    """Return layers with drift >= 5pp from targets."""
    _targets_by_label = {LAYER_LABELS[n]: LAYER_TARGETS[n] for n in LAYER_TARGETS}
    alerts = []
    for layer_label, data in layer_weights.items():
        target = _targets_by_label.get(layer_label)
        if target is None:
            continue
        drift = data["weight_pct"] - target
        if abs(drift) >= DRIFT_THRESHOLD:
            alerts.append({
                "layer": layer_label,
                "current": round(data["weight_pct"], 1),
                "target": target,
                "drift": round(drift, 1),
            })
    return sorted(alerts, key=lambda x: abs(x["drift"]), reverse=True)


def _get_upcoming_events() -> list[dict]:
    """Return earnings / ex-div events from DB within the next 7 days (if stored)."""
    return []


# ── Personal context builders ─────────────────────────────────────────────────

def _get_cc_context() -> str:
    """Build covered call program summary for prompt injection."""
    if not DB_PATH.exists():
        return ""
    today = date.today()

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM cc_positions ORDER BY opened_date DESC").fetchall()
    conn.close()

    if not rows:
        return ""

    open_pos   = [r for r in rows if r["status"] == "open"]
    closed_pos = [r for r in rows if r["status"] != "open"]
    cc_tickers = sorted(set(r["ticker"] for r in rows))

    lines = ["COVERED CALL PROGRAM:"]
    lines.append(f"All-time CC tickers: {', '.join(cc_tickers)}")

    if open_pos:
        lines.append(f"\nOpen CC positions ({len(open_pos)}):")
        for r in open_pos:
            exp_date = date.fromisoformat(r["expiry"])
            dte = (exp_date - today).days
            gross = r["premium_per_contract"] * r["contracts"] * 100
            dte_str = (f"{dte} DTE" if dte >= 0
                       else f"exp {abs(dte)} days ago — needs status update")
            mark = r["current_mark"]
            mark_str = f", mark ${mark:.3f}" if mark is not None else ""
            lines.append(
                f"  {r['ticker']:6s} ${r['strike']:.2f} strike, exp {r['expiry']} "
                f"({dte_str}), ${r['premium_per_contract']:.3f}/contract × "
                f"{r['contracts']}c = ${gross:.0f} gross{mark_str}"
            )

    if closed_pos:
        cutoff = (today - timedelta(days=90)).isoformat()
        recent = [r for r in closed_pos if (r["opened_date"] or "") >= cutoff]
        if recent:
            lines.append(f"\nClosed positions (last 90 days):")
            for r in recent:
                net = r["net_premium"] or r["premium_per_contract"] * r["contracts"] * 100
                ctype = (r["close_type"] or "closed").upper()
                lines.append(
                    f"  {r['ticker']:6s} ${r['strike']:.2f} strike, exp {r['expiry']}, "
                    f"{ctype} — collected ${net:.0f}"
                )

    total_open  = sum(r["premium_per_contract"] * r["contracts"] * 100 for r in open_pos)
    total_closed = sum(r["net_premium"] or 0 for r in closed_pos)
    lines.append(f"\nCC income: ${total_open:.0f} gross in open positions, ${total_closed:.0f} from closed (all-time in DB)")
    return "\n".join(lines)


def _get_lot_context() -> str:
    """Build cost basis, holding periods, and unrealized P&L for prompt injection."""
    if not DB_PATH.exists():
        return ""
    today = date.today()

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    # Per-ticker aggregates from cost_lots
    summary = conn.execute("""
        SELECT ticker,
               COUNT(*)                                    AS lots,
               SUM(shares)                                 AS total_shares,
               SUM(shares * cost_per_share) / SUM(shares) AS avg_cost,
               MIN(purchase_date)                          AS oldest,
               MAX(purchase_date)                          AS newest
        FROM cost_lots
        GROUP BY ticker
        ORDER BY lots DESC
    """).fetchall()

    # Current prices
    latest_day = conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
    prices: dict = {}
    if latest_day:
        for r in conn.execute("SELECT ticker, price FROM holding_day WHERE day=?", (latest_day,)):
            prices[r["ticker"]] = r["price"]
    conn.close()

    if not summary:
        return ""

    lines = ["COST BASIS & HOLDING PERIODS (tax lot analysis):"]

    # Systematic accumulators
    accumulators = [(r, r["lots"]) for r in summary if r["lots"] >= 10]
    if accumulators:
        lines.append("\nSystematic accumulators (10+ lots — DCA/DRIP pattern):")
        for r, _ in accumulators:
            oldest_date = date.fromisoformat(r["oldest"])
            age_mo = (today - oldest_date).days // 30
            from tax_utils import lt_threshold as _lt_thr, is_long_term as _is_lt
            lt_date = _lt_thr(oldest_date)
            lt_note = ("all lots LT eligible" if _is_lt(oldest_date, today)
                       else f"oldest lot LT on {lt_date}")
            lines.append(
                f"  {r['ticker']}: {r['lots']} lots, {r['total_shares']:.0f} shares, "
                f"oldest {r['oldest']} ({age_mo}mo old), {lt_note}"
            )

    # Unrealized P&L for all tickers with prices
    lines.append("\nUnrealized gain/loss by position (avg cost → current price):")
    rows_with_prices = [
        r for r in summary if prices.get(r["ticker"]) is not None
    ]
    rows_with_prices.sort(key=lambda r: (prices[r["ticker"]] - r["avg_cost"]) / r["avg_cost"], reverse=True)
    for r in rows_with_prices:
        curr = prices[r["ticker"]]
        pct  = (curr - r["avg_cost"]) / r["avg_cost"] * 100
        oldest_date = date.fromisoformat(r["oldest"])
        from tax_utils import is_long_term as _is_lt
        lt_label = "LT" if _is_lt(oldest_date, today) else "ST"
        tlh_flag = " ← TLH candidate" if pct < -5 else ""
        sign = "+" if pct >= 0 else ""
        lines.append(
            f"  {r['ticker']:6s} {sign}{pct:.0f}% unrealized "
            f"(avg ${r['avg_cost']:.2f} → ${curr:.2f}), "
            f"{r['total_shares']:.0f} shares, oldest lot {r['oldest']} ({lt_label}){tlh_flag}"
        )

    # Positions crossing LT threshold in next 90 days
    approaching = []
    for r in summary:
        oldest_date = date.fromisoformat(r["oldest"])
        from tax_utils import lt_threshold as _lt_thr, days_until_lt as _days_lt
        lt_date = _lt_thr(oldest_date)
        days_to_lt = _days_lt(oldest_date, today)
        if 0 < days_to_lt <= 90:
            approaching.append((r["ticker"], r["oldest"], lt_date, days_to_lt))
    if approaching:
        approaching.sort(key=lambda x: x[3])
        lines.append("\nPositions crossing LT threshold in next 90 days:")
        for ticker, oldest, lt_date, days in approaching:
            lines.append(f"  {ticker}: oldest lot {oldest} → LT on {lt_date} ({days} days away)")

    return "\n".join(lines)


def _get_realized_context() -> str:
    """Summarize YTD realized gains from sell_transactions."""
    if not DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM sell_transactions").fetchone()[0]
        if count == 0:
            conn.close()
            return "REALIZED GAINS YTD:\n  No sell transactions recorded — all gains/losses are currently unrealized."
        year = str(date.today().year)
        rows = conn.execute(
            "SELECT * FROM sell_transactions WHERE strftime('%Y', sell_date) = ?", (year,)
        ).fetchall()
        conn.close()
    except Exception:
        return ""

    if not rows:
        return f"REALIZED GAINS YTD ({year}):\n  No sales this year."

    st_total = sum(r["st_gain"] or 0 for r in rows)
    lt_total = sum(r["lt_gain"] or 0 for r in rows)
    lines = [f"REALIZED GAINS YTD ({year}):"]
    lines.append(f"  Short-term: ${st_total:+,.0f}")
    lines.append(f"  Long-term:  ${lt_total:+,.0f}")
    lines.append(f"  Total:      ${st_total + lt_total:+,.0f}")
    return "\n".join(lines)


def _get_behavior_patterns() -> str:
    """Derive investor behavior patterns from CC and lot data."""
    if not DB_PATH.exists():
        return ""

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    cc_rows = conn.execute("SELECT ticker, status FROM cc_positions").fetchall()
    lot_counts = conn.execute(
        "SELECT ticker, COUNT(*) as cnt, SUM(shares) as total FROM cost_lots GROUP BY ticker"
    ).fetchall()
    conn.close()

    cc_tickers   = sorted(set(r["ticker"] for r in cc_rows))
    open_cc      = sorted(set(r["ticker"] for r in cc_rows if r["status"] == "open"))
    expired_ok   = sorted(set(r["ticker"] for r in cc_rows if r["status"] == "expired"))
    lot_dict     = {r["ticker"]: r["total"] for r in lot_counts}
    accumulators = [(r["ticker"], r["cnt"], r["total"]) for r in lot_counts if r["cnt"] >= 10]
    accumulators.sort(key=lambda x: x[1], reverse=True)

    lines = ["OBSERVED INVESTOR BEHAVIOR PATTERNS:"]

    if accumulators:
        acc_str = ", ".join(f"{t} ({n} lots, {s:.0f} sh)" for t, n, s in accumulators)
        lines.append(f"- Systematic DCA/accumulator: {acc_str}")

    if cc_tickers:
        lines.append(f"- Active CC writer on: {', '.join(cc_tickers)}")
    if open_cc:
        lines.append(f"  Currently open calls: {', '.join(open_cc)}")
    if expired_ok:
        lines.append(f"  Expired worthless (favorable outcomes): {', '.join(set(expired_ok))}")

    # Large holdings not in CC program (100+ shares)
    non_cc_large = [(t, s) for t, s in lot_dict.items() if t not in cc_tickers and s >= 100]
    non_cc_large.sort(key=lambda x: x[1], reverse=True)
    if non_cc_large:
        nc_str = ", ".join(f"{t} ({s:.0f} sh)" for t, s in non_cc_large)
        lines.append(f"- CC expansion candidates (100+ shares, no active calls): {nc_str}")

    return "\n".join(lines)


# ── Prompt builders ───────────────────────────────────────────────────────────

def _get_news_block(holdings: list[dict], max_per_ticker: int = 3) -> str:
    """Fetch holding-specific news headlines and return a prompt block."""
    tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return ""
    try:
        import news_fetcher
        result = news_fetcher.fetch(tickers)
        by_ticker = result.get("by_ticker", {})
        if not by_ticker:
            return ""
        lines = ["RECENT NEWS FOR YOUR HOLDINGS (from WSJ, Barrons, MarketWatch, Yahoo Finance):"]
        for ticker in tickers:
            items = by_ticker.get(ticker, [])[:max_per_ticker]
            if not items:
                continue
            lines.append(f"  {ticker}:")
            for item in items:
                src = item.get("source", "")
                title = item.get("title", "")
                lines.append(f"    - [{src}] {title}")
        return "\n".join(lines) + "\n"
    except Exception as e:
        print(f"[AI] News fetch for prompt failed: {e}")
        return ""


def _build_thesis_health_block(holdings: list[dict]) -> str:
    """Summarise active thesis health for all holdings that have evaluated pillars."""
    try:
        import agent_db as _adb
        lines: list[str] = []
        for h in holdings:
            ticker = str(h.get("Stock", "")).strip().upper()
            if not ticker:
                continue
            t = _adb.get_thesis(ticker)
            if not t or t.get("status") != "ACTIVE":
                continue
            pillars = t.get("pillars", [])
            scored = [p for p in pillars if p.get("score") is not None]
            if not scored:
                continue
            health = t.get("health_score")
            violated = [p["name"] for p in pillars if p.get("status") == "VIOLATED"]
            warning  = [p["name"] for p in pillars if p.get("status") == "WARNING"]
            line = f"  {ticker}: health={health:.0f}/100" if health is not None else f"  {ticker}: health=?"
            if violated:
                line += f"  VIOLATED=[{', '.join(violated)}]"
            if warning:
                line += f"  WARNING=[{', '.join(warning)}]"
            lines.append(line)
        if not lines:
            return ""
        return (
            "INVESTMENT THESIS HEALTH (from thesis monitor agent — flag violations in risk_flags):\n"
            + "\n".join(lines) + "\n"
        )
    except Exception:
        return ""


def _build_portfolio_block(holdings: list[dict], prices: dict) -> str:
    lines = ["PORTFOLIO HOLDINGS:"]
    lines.append(f"{'Ticker':<8} {'Layer':<6} {'Value':>10} {'Day%':>7} {'Wt%':>6}")
    lines.append("-" * 45)
    for h in sorted(holdings, key=lambda x: int(x.get("Layer", 5))):
        t = str(h.get("Stock", "")).strip().upper()
        layer = h.get("Layer", "?")
        p = prices.get(t, {})
        value = p.get("value", 0) or 0
        chg   = p.get("change_pct", 0) or 0
        wt    = p.get("weight_pct", 0) or 0
        lines.append(f"{t:<8} L{layer:<5} ${value:>9,.0f} {chg:>+6.1f}% {wt:>5.1f}%")
    return "\n".join(lines)


def _build_layer_block(layer_weights: dict, drift_alerts: list[dict]) -> str:
    lines = ["LAYER WEIGHTS vs TARGETS:"]
    for label, data in sorted(layer_weights.items()):
        wt  = data.get("weight_pct", 0)
        chg = data.get("chg_pct", 0)
        lines.append(f"  {label}: {wt:.1f}% actual ({chg:+.1f}% today)")
    if drift_alerts:
        lines.append("\nDRIFT ALERTS (≥5pp from target):")
        for d in drift_alerts:
            lines.append(f"  {d['layer']}: {d['current']:.1f}% vs {d['target']:.0f}% target ({d['drift']:+.1f}pp)")
    return "\n".join(lines)


# ── Daily insight ─────────────────────────────────────────────────────────────

def get_cached_insight_today():
    """Return (insight_dict, generated_at_str) for today, or (None, None)."""
    _init_ai_tables()
    today = date.today().isoformat()
    if not DB_PATH.exists():
        return None, None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute(
            "SELECT insight, generated_at FROM ai_insights WHERE day=?", (today,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0]), (row[1] or "")
    except Exception:
        pass
    return None, None


def get_cached_news_summaries_today():
    """Return (data, generated_at_str) for today's cached per-ticker news summaries, or (None, None).
    Returns (sentinel, generated_at) during error cooldown so caller can distinguish."""
    _init_ai_tables()
    today = date.today().isoformat()
    if not DB_PATH.exists():
        return None, None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute(
            "SELECT summaries, generated_at FROM news_summaries WHERE day=?", (today,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            data = json.loads(row[0])
            generated_at = row[1] or ""
            if data.get("_failed"):
                # Allow retry after 30-minute cooldown
                try:
                    gen_ts = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
                    if (datetime.now() - gen_ts).total_seconds() < 1800:
                        return data, generated_at  # still in cooldown — block retry
                except Exception:
                    pass
                return None, None  # cooldown expired — allow fresh attempt
            return data, generated_at
    except Exception:
        pass
    return None, None


def generate_news_summaries(force: bool = False) -> dict:
    """
    For each holding that has recent news, generate an AI summary of the
    headlines plus a macro-angle sentence.  Returns {ticker: {summary, macro_angle}}.
    Cached in DB by day.
    """
    _init_ai_tables()
    today = date.today().isoformat()

    if not force:
        cached, _ = get_cached_news_summaries_today()
        if cached is not None:
            sample = next((v for v in cached.values() if isinstance(v, dict)), {})
            # Accept cache only if it has current schema: per-ticker news + portfolio _outlook
            if sample.get("news") and isinstance(cached.get("_outlook"), dict):
                return cached

    if not ollama_client.available():
        return {"error": "AI model unavailable — check MLX server"}

    holdings = _load_holdings_csv()
    tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
    tickers = list(dict.fromkeys(t for t in tickers if t))

    import news_fetcher
    result = news_fetcher.fetch(tickers)
    by_ticker = result.get("by_ticker", {})
    tickers_with_news = {t: items for t, items in by_ticker.items() if items}
    if not tickers_with_news:
        return {}

    news_fetcher.enrich_with_bodies(tickers_with_news)

    import macro_context
    macro = macro_context.fetch()
    macro_block = macro.get("formatted_block", "Macro data unavailable.")

    # Load macro scores for newsworthy tickers — compact (no per-dim reasons) to stay within context budget
    news_tickers = list(tickers_with_news.keys())
    _, scores_block = _get_macro_scores_block(tickers=news_tickers, compact=True)

    # Keep news content lean to stay within 8192-token context window
    news_block = ""
    for ticker, items in tickers_with_news.items():
        news_block += f"\n{ticker}:\n"
        for item in items[:4]:
            src     = item.get("source", "")
            title   = item.get("title", "")
            body    = item.get("body", "")
            excerpt = item.get("excerpt", "")
            news_block += f"  [{src}] {title}\n"
            detail = body[:150] if body else excerpt[:100] if excerpt else ""
            if detail:
                news_block += f"    {detail}\n"

    fed   = macro.get("fed_funds", "N/A")
    tnx   = macro.get("yield_10y", "N/A")
    cpi   = macro.get("cpi_yoy", "N/A")
    unemp = macro.get("unemployment", "N/A")
    vix   = macro.get("vix", "N/A")
    dol   = macro.get("dollar_interp", "N/A")
    crv   = macro.get("curve_interp", "N/A")

    official_bills = macro.get("official_bills", [])
    media_coverage = macro.get("legislative_media", [])

    if official_bills:
        off_lines = []
        for b in official_bills[:12]:
            id_str   = f"[{b.get('bill_id', '')}] " if b.get("bill_id") else ""
            stage    = f" — Stage: {b['stage']}" if b.get("stage") else ""
            dt       = (b.get("action_date") or b.get("introduced") or "")[:10]
            date_s   = f" ({dt})" if dt else ""
            domain_s = f" [domains: {', '.join(b['domains'])}]" if b.get("domains") else ""
            off_lines.append(f"  {id_str}{b['title']}{domain_s}{stage}{date_s}")
            if b.get("summary"):
                off_lines.append(f"    CRS Summary: {b['summary'][:350]}")
            if b.get("latest_action") and b.get("stage") in (
                "Floor vote", "Passed chamber", "Signed into law", "Vetoed"
            ):
                off_lines.append(f"    Latest action: {b['latest_action']}")
        official_block = "\n".join(off_lines)
    else:
        official_block = "  No official bill data available."

    all_portfolio_tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
    all_portfolio_tickers = list(dict.fromkeys(t for t in all_portfolio_tickers if t))
    profiles_block = _holding_profile_block(list(tickers_with_news.keys()))
    bills_holdings_block = _bills_with_holdings(official_bills, all_portfolio_tickers)

    media_block = (
        "\n".join(f"  - {b['title']}" for b in media_coverage[:6])
        if media_coverage else "  None."
    )

    legislative_block = official_block  # kept for outlook_prompt

    prompt = f"""You are a portfolio risk analyst helping a personal investor take action. Your job is not to describe — it is to FLAG risks, surface OPPORTUNITIES, and call out TAX implications so the investor knows what needs attention TODAY.

CURRENT MACRO ENVIRONMENT:
{macro_block}

KEY NUMBERS:
  Fed Funds Rate: {fed}%  |  10Y Treasury: {tnx}%  |  CPI YoY: {cpi}%
  Unemployment: {unemp}%  |  VIX: {vix}  |  Dollar: {dol}  |  Yield Curve: {crv}

{scores_block}

RECENT NEWS BY HOLDING (last 24 hours):
{news_block}

BILLS UNDER REVIEW — OFFICIAL GOVERNMENT RECORD (Congress.gov; authoritative — weight these facts over any media framing):
{official_block}

LEGISLATIVE MEDIA COVERAGE (secondary; editorial sources may reflect political bias — use only to identify story angles, not as factual basis):
{media_block}

For each ticker in the news above, provide these components:

1. "news" — 2-3 sentences on what actually happened. Reference specific numbers, events, or company actions. No vague summaries.
2. "rates" — CONDITIONAL: only include if MACRO SCORES rate_sensitivity is 7 or higher AND the current rate level creates a concrete near-term risk (e.g., refinancing pressure, spread widening, valuation compression on a high-multiple stock). A low score means the company is rate-insensitive — do not fill this field just to explain immunity. Omit entirely for scores 1-6 unless today's news changes the picture.
3. "trade" — CONDITIONAL: only include if this company has direct material exposure to active tariff, FX, or trade policy changes in the current news cycle (e.g., specific China tariff hitting a core product line, dollar move affecting a major revenue stream). Omit if the company has minimal international/trade exposure or if nothing has changed.
4. "environment" — CONDITIONAL: only include if there is a material current headwind or tailwind that should affect a near-term decision (e.g., accelerating margin compression, cycle inflection, significant regulatory shift underway). Omit if macro conditions for this company are neutral or unchanged.
5. "leg_risk" — Apply the LEGISLATIVE CONNECTION RULE below. If a bill directly burdens this company's business (regulation, cost, pricing pressure), name it by ID, explain the mechanism, and give its stage. Otherwise omit.
6. "leg_opp" — Apply the LEGISLATIVE CONNECTION RULE below. If a bill directly benefits this company (subsidy, deregulation, new demand), name it by ID, explain the mechanism, and give its stage. Otherwise omit.
7. "tax_angle" — ONLY if a bill directly changes the tax treatment of this holding (capital gains rates, corporate tax, sector-specific credits). Name the bill by ID. Omit if not applicable.

{profiles_block}

{_LEG_RULE}

Also provide a top-level "_outlook" object (not per-ticker) with four keys:
- "top_risk": The single most urgent legislative or macro risk to the portfolio right now. One sentence, specific.
- "top_opportunity": The single clearest legislative or macro tailwind. One sentence, specific.
- "tax_watch": Any pending legislation that could affect the investor's tax bill on current positions (capital gains rates, wash-sale rules, SALT cap changes, corporate rates). If none, write null.
- "action_items": A JSON array of 2-4 specific, actionable things the investor should do or watch this week. Each item is one sentence starting with an action verb (Review, Consider, Watch, Monitor, Avoid).

Return ONLY valid JSON — no markdown, no extra text. START with "_outlook" before any tickers:
{{
  "_outlook": {{
    "top_risk": "...",
    "top_opportunity": "...",
    "tax_watch": "... or null",
    "action_items": ["...", "..."]
  }},
  "TICKER": {{
    "news": "...",
    "rates": "(omit if rate_sensitivity < 7 and no new rate catalyst)",
    "trade": "(omit if no material trade/FX exposure or development)",
    "environment": "(omit if macro conditions for this name are neutral)",
    "leg_risk": "(omit if not applicable)",
    "leg_opp": "(omit if not applicable)",
    "tax_angle": "(omit if not applicable)"
  }}
}}

Only include tickers with news. Only include leg_risk, leg_opp, tax_angle when specifically applicable. Be direct and use concrete numbers — vague analysis is not useful."""

    outlook_prompt = f"""You are a portfolio risk analyst. Given the context below, produce a concise portfolio-level action briefing in JSON.

MACRO: Fed={fed}%, 10Y={tnx}%, CPI={cpi}%, VIX={vix}, Dollar={dol}, Curve={crv}

{bills_holdings_block}

Each bill above is pre-annotated with "Portfolio match: TICKER" showing which holdings are directly affected. Bills marked "No holdings affected" are irrelevant to this portfolio — do not cite them.

Return ONLY this JSON object with exactly these four keys:
{{
  "top_risk": "<one sentence: the single most urgent macro or legislative risk — for legislation, only cite bills that show a Portfolio match above>",
  "top_opportunity": "<one sentence: the clearest macro or legislative tailwind — for legislation, only cite bills that show a Portfolio match above; name the specific matching ticker>",
  "tax_watch": "<one sentence: any pending tax legislation relevant to these holdings per the Portfolio match annotations, or null if none>",
  "action_items": ["<action verb + specific action>", "<action verb + specific action>", "<action verb + specific action>"]
}}

Be specific. Name the legislation by ID and the matching holding. No generic statements."""

    def _cache_sentinel(error_msg):
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if DB_PATH.exists():
            try:
                c = sqlite3.connect(str(DB_PATH), timeout=10)
                c.execute(
                    "INSERT OR REPLACE INTO news_summaries (day, summaries, generated_at) VALUES (?,?,?)",
                    (today, json.dumps({"_failed": True, "_error": error_msg}), now_s)
                )
                c.commit()
                c.close()
            except Exception:
                pass

    # Call 1: per-ticker summaries
    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=6000
        ):
            full_text += tok
    except Exception as e:
        err = f"AI generation failed: {e}"
        _cache_sentinel(err)
        return {"error": err}

    summaries = _extract_json(full_text)
    if summaries is None:
        err = "AI returned malformed JSON"
        print(f"[NewsSummaries] Parse failed. Raw output (first 600): {full_text[:600]!r}")
        _cache_sentinel(err)
        return {"error": err, "raw": full_text[:500]}

    # Strip fields where the AI echoed the placeholder "omit" text instead of omitting the field
    _OMIT_FIELDS = {"rates", "trade", "environment", "leg_risk", "leg_opp", "tax_angle"}
    for ticker_data in summaries.values():
        if not isinstance(ticker_data, dict):
            continue
        for field in _OMIT_FIELDS:
            val = ticker_data.get(field)
            if isinstance(val, str) and (val.lower().startswith("omit") or val.lower().startswith("(omit")):
                del ticker_data[field]

    # Call 2: portfolio-level outlook
    try:
        outlook_raw = ""
        for tok in ollama_client.stream_generate(
            outlook_prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.2, num_predict=4000,
            enable_thinking=True
        ):
            outlook_raw += tok
        outlook_obj = _extract_last_json(outlook_raw, required_keys=["top_risk"])
        if outlook_obj:
            summaries["_outlook"] = outlook_obj
    except Exception as e:
        summaries["_outlook"] = {
            "top_risk": "Unable to generate outlook — check AI server.",
            "top_opportunity": None,
            "tax_watch": None,
            "action_items": [],
        }

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "INSERT OR REPLACE INTO news_summaries (day, summaries, generated_at) VALUES (?,?,?)",
            (today, json.dumps(summaries), now_str)
        )
        conn.commit()
        conn.close()

    return summaries


def generate_daily_insight(force: bool = False) -> dict:
    """
    Generate today's portfolio briefing by synthesizing specialist agent findings.
    Returns the insight dict. Stores in DB. Uses cached result if already run today.
    """
    _init_ai_tables()
    today = date.today().isoformat()

    # Return cached result if already generated today
    if not force and DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        row = conn.execute(
            "SELECT insight FROM ai_insights WHERE day=?", (today,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except Exception:
                pass

    if not ollama_client.available():
        return {"error": "AI model unavailable — check MLX server"}

    import macro_context
    import agent_db as _adb
    macro = macro_context.fetch()
    macro_block = macro.get("formatted_block", "Macro data unavailable.")

    # Portfolio summary: total value + layer weights with drift
    prices        = _get_holding_prices_from_db()
    layer_weights = _get_layer_weights_from_db()
    drift_alerts  = _get_drift_alerts(layer_weights)
    total_value   = sum(v.get("value", 0) or 0 for v in prices.values())

    layer_lines = ["PORTFOLIO SUMMARY:"]
    if total_value:
        layer_lines.append(f"  Total value: ${total_value:,.0f}")
    for label, data in sorted(layer_weights.items()):
        wt  = data.get("weight_pct", 0)
        chg = data.get("chg_pct", 0)
        layer_lines.append(f"  {label}: {wt:.1f}% actual ({chg:+.1f}% today)")
    if drift_alerts:
        layer_lines.append("  Drift alerts (≥5pp from target):")
        for d in drift_alerts:
            layer_lines.append(
                f"    {d['layer']}: {d['current']:.1f}% vs {d['target']:.0f}% target ({d['drift']:+.1f}pp)"
            )
    portfolio_summary_block = "\n".join(layer_lines)

    # Specialist agent findings (today's runs) + open recommendations
    agent_data = _adb.get_todays_findings()
    findings_by_agent = agent_data["findings"]
    open_recs = agent_data["recommendations"]

    findings_lines = ["SPECIALIST AGENT FINDINGS (today):"]
    if findings_by_agent:
        for agent_type, flist in sorted(findings_by_agent.items()):
            for f in flist:
                ticker_tag = f"[{f['ticker']}] " if f["ticker"] else ""
                sev = f["severity"]
                summary = (f["summary"] or "")[:200]
                why = (f["why_now"] or "")[:120]
                why_part = f" | {why}" if why else ""
                findings_lines.append(
                    f"  {agent_type}: {ticker_tag}{f['finding_type']} sev={sev} — {summary}{why_part}"
                )
    else:
        findings_lines.append("  No specialist findings recorded for today.")

    recs_lines = [f"\nOPEN RECOMMENDATIONS ({len(open_recs)} total):"]
    if open_recs:
        for r in open_recs[:20]:  # cap to avoid prompt bloat
            ticker = r["ticker"]
            action = r["action"]
            score  = r["score"]
            conf   = r["confidence"]
            pri    = r["priority"]
            agent  = r["agent_type"] or "?"
            why    = (r["why_now"] or "")[:160]
            rationale = (r["rationale"] or "")[:160]
            critic_v = r["critic_verdict"] or ""
            critic_o = (r["critic_objection"] or "")[:100]
            critic_part = f" | critic: {critic_v}" + (f" — {critic_o}" if critic_o else "") if critic_v else ""
            recs_lines.append(
                f"  [{ticker}] {action} | score={score} conf={conf} pri={pri} | {agent}{critic_part}"
            )
            if why:
                recs_lines.append(f"    why: {why}")
            if rationale and rationale != why:
                recs_lines.append(f"    rationale: {rationale}")
    else:
        recs_lines.append("  No open recommendations.")

    # News outlook summary (pre-computed — compact, no per-ticker details)
    news_block = ""
    news_summaries, _ = get_cached_news_summaries_today()
    if news_summaries and not news_summaries.get("_failed"):
        ol = news_summaries.get("_outlook") or {}
        news_lines = ["NEWS OUTLOOK (pre-computed highlights):"]
        if ol.get("top_risk"):
            news_lines.append(f"  Top risk: {ol['top_risk']}")
        if ol.get("top_opportunity"):
            news_lines.append(f"  Top opportunity: {ol['top_opportunity']}")
        if ol.get("tax_watch"):
            news_lines.append(f"  Tax watch: {ol['tax_watch']}")
        if ol.get("action_items"):
            for item in (ol["action_items"] or [])[:4]:
                news_lines.append(f"  - {item}")
        if len(news_lines) > 1:
            news_block = "\n".join(news_lines) + "\n\n"

    specialist_block = "\n".join(findings_lines) + "\n" + "\n".join(recs_lines)

    prompt = f"""You are a sophisticated investment advisor writing a daily portfolio briefing. Your job is to SYNTHESIZE the specialist agent findings below — not re-analyze the portfolio from scratch. Return ONLY valid JSON — no markdown, no extra text.

{macro_block}

{portfolio_summary_block}

{specialist_block}

{news_block}INSTRUCTIONS:
- Open with the most important issue flagged by specialist agents today
- Reference agents by name: "Guardian flagged GRMN...", "CC Agent recommends...", "Critic approved/rejected..."
- If critic reviewed a recommendation, include the verdict and key objection in risk_flags
- For tax_timing_note and tax_opportunity: use agent findings if available; otherwise note "No agent tax findings today"
- If no material findings exist, say so concisely ("No material specialist findings today — routine monitoring only")
- Do not invent risks not grounded in the findings above
- Do not give generic market commentary — tie every observation to specific tickers from the findings

Return exactly this JSON structure:
{{
  "macro_summary": "<2-3 sentence description of today's macro regime and its most relevant implication for this specific portfolio based on layer weights and any flagged drift>",
  "risk_flags": [
    "<agent name + ticker: specific risk from findings — e.g. 'Guardian flagged GRMN: 10Y yield at 4.7% compresses its growth multiple'>",
    "<agent name + ticker: recommendation with critic verdict if reviewed — e.g. 'CC Agent: SELL_CC on EW (score=78) — Critic APPROVED'>",
    "<additional finding or 'No further material risks flagged'>"
  ],
  "tax_timing_note": "<tax agent findings if any, or 'No agent tax findings today'>",
  "key_question": "<the single most important portfolio decision surfaced by today's agent findings — specific and actionable>",
  "tax_opportunity": "<specific ticker from tax agent findings, or 'None this week'>",
  "legislative_watch": "<apply the LEGISLATIVE CONNECTION RULE: only name a bill if it has a direct one-step impact on a specific held ticker's actual industry or business. Name the bill by ID, the holding, the mechanism, and the stage. If no bill qualifies, write 'No material legislation this week'>"
}}

{_LEG_RULE}"""

    # Log estimated prompt size vs old approach for token reduction verification
    est_tokens = len(prompt) // 4
    print(f"[DailyInsight] New prompt ~{est_tokens} tokens "
          f"({len(findings_by_agent)} agent types, {len(open_recs)} recs)")

    # Collect both reasoning and content tokens: Qwen3 thinking models sometimes
    # put the final answer in delta.reasoning tail (content stays empty when the
    # budget runs out). _extract_last_json then picks the LAST valid JSON with
    # the expected schema keys, skipping reasoning sketches with "..." placeholders.
    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=8000,
            enable_thinking=True
        ):
            full_text += tok
    except Exception as e:
        return {"error": f"AI generation failed: {e}"}

    insight = _extract_last_json(full_text, required_keys=["macro_summary", "risk_flags"])
    if insight is None:
        print(f"[DailyInsight] Parse failed. Raw output (first 600): {full_text[:600]!r}")
        return {"error": "AI returned malformed JSON", "raw": full_text[:500]}

    # Persist to DB
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    macro_snap = {k: v for k, v in macro.items() if k not in ("formatted_block", "headlines")}
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "INSERT OR REPLACE INTO ai_insights (day, insight, macro_snap, generated_at) VALUES (?,?,?,?)",
            (today, json.dumps(insight), json.dumps(macro_snap), now_str)
        )
        conn.commit()
        conn.close()

    return insight


# ── Holding macro scores ──────────────────────────────────────────────────────

def _fetch_company_evidence(ticker: str, conn) -> dict:
    """Fetch available quantitative evidence for a ticker from company_financials.
    Returns dict with fetched fields plus:
      evidence_quality        — overall: "full" | "partial" | "none" | "fund"
      evidence_quality_rate   — rate_sensitivity evidence: "good" | "limited" | "none"
      evidence_quality_dollar — dollar_sensitivity evidence: "good" | "limited" | "none"
      is_fund                 — True if ticker is a known ETF/index fund
    """
    evidence: dict = {}
    if is_fund(ticker):
        st = SECURITY_MASTER.get(ticker.upper(), {}).get("security_type", "fund")
        evidence["is_fund"] = True
        evidence["evidence_quality"]           = "unsupported"
        evidence["evidence_quality_rate"]      = "unsupported"
        evidence["evidence_quality_dollar"]    = "unsupported"
        evidence["evidence_quality_inflation"] = "unsupported"
        evidence["evidence_quality_geo"]       = "unsupported"
        evidence["fund_note"] = f"{st} — constituent-derived exposure not implemented"
        return evidence
    evidence["is_fund"] = False
    if conn is None:
        evidence["evidence_quality"] = "none"
        evidence["evidence_quality_rate"] = "none"
        evidence["evidence_quality_dollar"] = "none"
        return evidence
    try:
        cols_info = conn.execute("PRAGMA table_info(company_financials)").fetchall()
        available_cols = {row[1] for row in cols_info}  # row[1] = column name
        # Map desired fields to possible column names
        field_candidates = {
            "sector":           ["sector"],
            "foreign_rev_pct":  ["international_revenue_pct", "foreign_revenue_pct", "intl_rev_pct"],
            "net_debt":         ["net_debt", "net_debt_millions"],
            "interest_coverage":["interest_coverage", "interest_coverage_ratio"],
            "gross_margin_pct": ["gross_margin_pct", "gross_margin", "gross_profit_margin"],
            "revenue_ttm":      ["revenue_ttm", "revenue_trailing_12m", "total_revenue"],
        }
        select_parts = []
        col_map = {}
        for field, candidates in field_candidates.items():
            for cand in candidates:
                if cand in available_cols:
                    select_parts.append(cand)
                    col_map[cand] = field
                    break
        if select_parts:
            row = conn.execute(
                f"SELECT {', '.join(select_parts)} FROM company_financials WHERE ticker=? ORDER BY rowid DESC LIMIT 1",
                (ticker,)
            ).fetchone()
            if row:
                for col, field in col_map.items():
                    try:
                        val = row[col]
                        evidence[field] = float(val) if val is not None and field != "sector" else val
                    except Exception:
                        pass
    except Exception:
        pass
    _meta_keys = {"evidence_quality", "evidence_quality_rate", "evidence_quality_dollar",
                  "evidence_quality_inflation", "evidence_quality_geo", "is_fund", "fund_note"}
    filled = sum(1 for k, v in evidence.items() if k not in _meta_keys and v is not None)
    evidence["evidence_quality"] = "full" if filled >= 3 else ("partial" if filled >= 1 else "none")

    # Per-dimension evidence quality — canonical vocab: full/partial/none (0518)
    rate_fields = [evidence.get("net_debt"), evidence.get("interest_coverage")]
    rate_filled = sum(1 for v in rate_fields if v is not None)
    evidence["evidence_quality_rate"] = "full" if rate_filled >= 2 else ("partial" if rate_filled >= 1 else "none")

    dollar_filled = 1 if evidence.get("foreign_rev_pct") is not None else 0
    evidence["evidence_quality_dollar"] = "full" if dollar_filled >= 1 else "none"

    # Inflation hedge: gross margin (pricing power proxy)
    inflation_filled = 1 if evidence.get("gross_margin_pct") is not None else 0
    evidence["evidence_quality_inflation"] = "full" if inflation_filled >= 1 else (
        "partial" if evidence.get("sector") else "none"
    )

    # Geo profile (0508) — query company_geo_profile for structured country/region evidence
    try:
        geo_row = conn.execute(
            "SELECT primary_hq_country, incorporation_country, major_operating_regions, "
            "revenue_domestic_pct, revenue_us_pct, revenue_em_pct, "
            "supply_chain_concentration, sanctions_exposure, tariff_sensitivity "
            "FROM company_geo_profile WHERE ticker=?",
            (ticker,)
        ).fetchone()
        if geo_row:
            evidence["geo_hq_country"]               = geo_row[0]
            evidence["geo_incorporation_country"]    = geo_row[1]
            evidence["geo_major_regions"]            = geo_row[2]
            evidence["geo_revenue_domestic_pct"]     = geo_row[3]
            evidence["geo_revenue_us_pct"]           = geo_row[4]
            evidence["geo_revenue_em_pct"]           = geo_row[5]
            evidence["geo_supply_chain"]             = geo_row[6]
            evidence["geo_sanctions_exposure"]       = geo_row[7]
            evidence["geo_tariff_sensitivity"]       = geo_row[8]
    except Exception:
        pass

    # Geopolitical quality derived from confidence + freshness in company_geo_profile (0522)
    evidence["evidence_quality_geo"] = _geo_evidence_quality(ticker, conn)

    return evidence


def _geo_evidence_quality(ticker: str, conn) -> str:
    """Derive evidence_quality_geo from confidence + source_date in company_geo_profile (0522, 0526).
    Returns 'full' | 'partial' | 'none'. Fails closed on all provenance gaps.

    'full' requires ALL of: confidence='high', source_date present, parseable, non-future, ≤18 months old.
    Any gap (missing date, malformed, future date, stale, or confidence != 'high') → 'partial' or 'none'.
    No record or no primary country → 'none'. Presence of a record but incomplete provenance → 'partial'.
    """
    if conn is None:
        return "none"
    try:
        row = conn.execute(
            "SELECT confidence, source_date, primary_hq_country FROM company_geo_profile WHERE ticker=?",
            (ticker,)
        ).fetchone()
        if not row or not row[2]:
            return "none"
        confidence, source_date, _ = row
        # source_date required for 'full' — absence means provenance is incomplete (0526)
        if not source_date:
            if confidence == "high":
                print(f"[GeoQuality] {ticker}: confidence=high but source_date missing — downgraded to partial")
            return "partial"
        # Parse and validate date
        try:
            yr = int(source_date[:4])
            mo = int(source_date[5:7]) if len(source_date) >= 7 else 1
        except (ValueError, TypeError, IndexError):
            print(f"[GeoQuality] {ticker}: unparseable source_date '{source_date}' — downgraded to partial")
            return "partial"
        today = date.today()
        # Future date (impossible) → partial
        if yr > today.year or (yr == today.year and mo > today.month):
            print(f"[GeoQuality] {ticker}: source_date '{source_date}' is in the future — downgraded to partial")
            return "partial"
        age_months = (today.year - yr) * 12 + (today.month - mo)
        if age_months > 18:
            print(f"[GeoQuality] {ticker}: source_date '{source_date}' is {age_months}m old (>18) — downgraded to partial")
            return "partial"
        if confidence == "high":
            return "full"
        return "partial"
    except Exception:
        return "none"


def _beta_confidence(tstat) -> str:
    """Classify t-statistic into confidence tier for LLM gating."""
    if tstat is None:
        return "insufficient_data"
    t = abs(tstat)
    if t >= 2.0:
        return "stronger"
    if t >= 1.5:
        return "suggestive"
    return "weak"


def _is_concordance_warning(rate_beta: float, rate_sensitivity: int) -> bool:
    """Return True when measured rate_beta directionally disagrees with LLM rate_sensitivity score.
    rate_beta < -5 (stock hurt by rising rates) → supports HIGH sensitivity (≥6); warns if ≤4.
    rate_beta > -2 (near-zero/positive) → supports LOW sensitivity (≤4); warns if ≥6.
    Neutral zone (-5 to -2): no concordance check.
    """
    if rate_beta < -5.0:
        return rate_sensitivity <= 4
    if rate_beta > -2.0:
        return rate_sensitivity >= 6
    return False


def _compute_equity_betas(ticker: str, lookback_days: int = 365) -> dict:
    """Compute historical rate, USD, and market betas via multivariate OLS with SPY control.

    Returns:
      rate_beta_100bp_return_pct — idiosyncratic equity % return per +100bps yield rise
      usd_beta_1pct_return_pct   — idiosyncratic equity % return per +1% UUP rise
      market_beta                — equity % return per +1% SPY return
      rate_beta_confidence       — "stronger" | "suggestive" | "weak" | "insufficient_data"
      usd_beta_confidence        — same
      r_squared                  — multivariate R² (float 0–1)
      rate_se, usd_se, market_se — standard errors
      rate_t, usd_t, market_t    — t-statistics
      n_weeks                    — number of weekly observations
      lookback_start, lookback_end — ISO dates
    Returns {} on failure/insufficient data.
    """
    try:
        import numpy as np
        import yfinance as yf
        import warnings
        warnings.filterwarnings("ignore")
        period = f"{lookback_days}d"
        data = yf.download(
            [ticker, "^TNX", "UUP", "SPY"], period=period, interval="1wk",
            group_by="ticker", progress=False, auto_adjust=True
        )
        lvl0 = data.columns.get_level_values(0)
        eq  = data[ticker]["Close"].dropna() if ticker in lvl0 else None
        tnx = data["^TNX"]["Close"].dropna() if "^TNX" in lvl0 else None
        uup = data["UUP"]["Close"].dropna()  if "UUP"  in lvl0 else None
        spy = data["SPY"]["Close"].dropna()  if "SPY"  in lvl0 else None
        if eq is None or tnx is None or uup is None or spy is None:
            return {}
        idx = eq.index.intersection(tnx.index).intersection(uup.index).intersection(spy.index)
        if len(idx) < 27:
            return {}
        eq_r_pct  = eq.loc[idx].pct_change().dropna() * 100    # equity % return
        tnx_c_pct = tnx.loc[idx].diff().dropna()               # 10Y yield change in % pts (1 unit = 100bps)
        uup_r_pct = uup.loc[idx].pct_change().dropna() * 100   # UUP % return
        spy_r_pct = spy.loc[idx].pct_change().dropna() * 100   # SPY % return (market control)
        common = (eq_r_pct.index
                  .intersection(tnx_c_pct.index)
                  .intersection(uup_r_pct.index)
                  .intersection(spy_r_pct.index))
        if len(common) < 26:
            return {}
        y  = eq_r_pct.loc[common].values.astype(float)
        x1 = tnx_c_pct.loc[common].values.astype(float)
        x2 = uup_r_pct.loc[common].values.astype(float)
        x3 = spy_r_pct.loc[common].values.astype(float)
        n  = len(y)

        # Multivariate OLS: Y = a + b1*yield_chg + b2*uup_ret + b3*spy_ret + e
        # Partial coefficients b1/b2 are idiosyncratic (market-return controlled).
        X = np.column_stack([np.ones(n), x1, x2, x3])
        try:
            betas_arr, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            return {}
        a, b1, b2, b3 = (float(betas_arr[i]) for i in range(4))

        y_hat = X @ betas_arr
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        dof = n - 4
        if dof < 1:
            return {}
        mse = ss_res / dof
        XtX_inv = np.linalg.pinv(X.T @ X)
        se = np.sqrt(np.maximum(np.diag(XtX_inv) * mse, 0))
        b1_se, b2_se, b3_se = float(se[1]), float(se[2]), float(se[3])
        b1_t = b1 / b1_se if b1_se > 0 else None
        b2_t = b2 / b2_se if b2_se > 0 else None
        b3_t = b3 / b3_se if b3_se > 0 else None

        dates = common.tolist()
        return {
            "rate_beta_100bp_return_pct": round(b1, 4),
            "usd_beta_1pct_return_pct":   round(b2, 4),
            "market_beta":                round(b3, 4),
            "rate_beta_confidence":       _beta_confidence(b1_t),
            "usd_beta_confidence":        _beta_confidence(b2_t),
            "r_squared":      round(r2, 4),
            "rate_se":        round(b1_se, 4),
            "usd_se":         round(b2_se, 4),
            "market_se":      round(b3_se, 4),
            "rate_t":         round(b1_t, 2) if b1_t is not None else None,
            "usd_t":          round(b2_t, 2) if b2_t is not None else None,
            "market_t":       round(b3_t, 2) if b3_t is not None else None,
            "n_weeks":        n,
            "lookback_start": str(dates[0])[:10] if dates else None,
            "lookback_end":   str(dates[-1])[:10] if dates else None,
        }
    except Exception:
        return {}


def _compute_macro_health_snapshot(run_id: str, conn: sqlite3.Connection) -> dict:
    """Compute a health/coverage snapshot for the current scoring run (0492)."""
    snap: dict = {"run_id": run_id, "captured_at": datetime.now().isoformat()}
    try:
        rows = conn.execute(
            "SELECT scores FROM holding_macro_scores ORDER BY scored_at DESC LIMIT 200"
        ).fetchall()
        supported = unsupported = 0
        for (scores_json,) in rows:
            try:
                s = json.loads(scores_json)
                if s.get("evidence_quality") == "unsupported" or s.get("is_fund"):
                    unsupported += 1
                else:
                    supported += 1
            except Exception:
                pass
        total = supported + unsupported
        snap["supported_count"] = supported
        snap["unsupported_count"] = unsupported
        snap["portfolio_coverage_pct"] = round(100 * supported / total, 1) if total else 0.0

        stale_failed = conn.execute(
            "SELECT COUNT(*) FROM macro_scoring_runs WHERE status='STALE_FAILED'"
        ).fetchone()[0]
        snap["stale_failed_count"] = stale_failed

        weak_count = conn.execute(
            "SELECT COUNT(*) FROM holding_macro_scores WHERE "
            "scores LIKE '%\"weak\"%' OR scores LIKE '%\"insufficient_data\"%'"
        ).fetchone()[0]
        snap["weak_beta_count"] = weak_count

        drift_count = 0
        tickers = conn.execute(
            "SELECT DISTINCT ticker FROM holding_macro_scores_history"
        ).fetchall()
        for (ticker,) in tickers:
            hist = conn.execute(
                "SELECT scores, evidence_hash FROM holding_macro_scores_history "
                "WHERE ticker=? ORDER BY scored_at DESC LIMIT 2", (ticker,)
            ).fetchall()
            if len(hist) == 2:
                try:
                    s1 = json.loads(hist[0][0]); s2 = json.loads(hist[1][0])
                    h1 = hist[0][1]; h2 = hist[1][1]
                    if h1 and h2 and h1 == h2:
                        for dim in _MACRO_SCORE_DIMS:
                            v1 = _score_val(s1.get(dim)) or 5
                            v2 = _score_val(s2.get(dim)) or 5
                            if abs(v1 - v2) > 1:
                                drift_count += 1
                                break
                except Exception:
                    pass
        snap["unexplained_drift_count"] = drift_count
        snap["stale_series_json"] = None
        snap["unknown_regime_fields_json"] = None
        snap["health_json"] = json.dumps(snap)
    except Exception as e:
        snap["error"] = str(e)
        snap["health_json"] = json.dumps(snap)
    return snap


def _reconcile_stale_runs(conn: sqlite3.Connection, stale_threshold_minutes: int = 60) -> int:
    """Transition STARTED runs older than threshold to STALE_FAILED (0493). Returns count updated."""
    try:
        cutoff = (datetime.now() - timedelta(minutes=stale_threshold_minutes)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "UPDATE macro_scoring_runs SET status='STALE_FAILED', errors_json=? "
            "WHERE status='STARTED' AND run_at < ?",
            (json.dumps(["Reconciled: process likely crashed — no FAILED written"]), cutoff)
        )
        conn.commit()
        count = cursor.rowcount
        if count > 0:
            print(f"[MacroScores] Reconciled {count} stale STARTED run(s) → STALE_FAILED")
        return count
    except Exception as e:
        print(f"[MacroScores] WARNING: stale run reconciliation failed: {e}")
        return 0


def compute_macro_health() -> dict:
    """Compute macro health state on demand — does not require a scoring run (0499)."""
    health: dict = {"computed_at": datetime.now().isoformat()}

    if not DB_PATH.exists():
        return {**health, "status": "NO_DB", "error": "Database not found"}

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)

        # Reconcile stale runs first so health is immediately accurate (0493/0499)
        _reconcile_stale_runs(conn)

        # Latest successful run
        latest_run = conn.execute(
            "SELECT run_id, run_at, scored_n, expected_n, status "
            "FROM macro_scoring_runs "
            "WHERE status IN ('COMPLETE','PARTIAL') ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
        if latest_run:
            run_id, run_at_str, scored, expected, status = latest_run
            try:
                run_age_h = (datetime.now() - datetime.fromisoformat(run_at_str)).total_seconds() / 3600
            except Exception:
                run_age_h = None
            health["latest_successful_run"] = {
                "run_id": run_id, "run_at": run_at_str, "scored_n": scored,
                "expected_n": expected, "status": status,
                "age_hours": round(run_age_h, 1) if run_age_h is not None else None,
            }
            health["scorer_status"] = "WARNING" if run_age_h and run_age_h > 192 else "OK"
        else:
            health["latest_successful_run"] = None
            health["scorer_status"] = "NO_RUNS"

        # Stale STARTED count
        health["stale_failed_count"] = conn.execute(
            "SELECT COUNT(*) FROM macro_scoring_runs WHERE status='STALE_FAILED'"
        ).fetchone()[0]

        # Last health snapshot age
        last_snap = conn.execute(
            "SELECT captured_at FROM macro_health_snapshots ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        if last_snap:
            try:
                snap_age_h = (datetime.now() - datetime.fromisoformat(last_snap[0])).total_seconds() / 3600
                health["last_health_snapshot_age_hours"] = round(snap_age_h, 1)
            except Exception:
                health["last_health_snapshot_age_hours"] = None
        else:
            health["last_health_snapshot_age_hours"] = None

        # Portfolio coverage
        total = conn.execute("SELECT COUNT(*) FROM holding_macro_scores").fetchone()[0]
        unsupported = conn.execute(
            "SELECT COUNT(*) FROM holding_macro_scores "
            "WHERE scores LIKE '%\"unsupported\"%' OR scores LIKE '%\"is_fund\": true%'"
        ).fetchone()[0]
        health["portfolio_coverage"] = {
            "total": total,
            "supported": total - unsupported,
            "unsupported": unsupported,
            "coverage_pct": round(100 * (total - unsupported) / total, 1) if total else 0.0,
        }

        # Macro cache freshness
        cache_candidates = [
            Path("out/macro_cache.json"),
            Path("macro_cache.json"),
            Path("out/macro_context_cache.json"),
        ]
        cache_file = next((p for p in cache_candidates if p.exists()), None)
        if cache_file:
            try:
                cached = json.loads(cache_file.read_text())
                fetched_at = cached.get("_fetched_at", 0)
                cache_age_h = (datetime.now().timestamp() - fetched_at) / 3600
                health["macro_cache_age_hours"] = round(cache_age_h, 1)
                health["macro_cache_status"] = "STALE" if cache_age_h > 48 else "OK"
            except Exception:
                health["macro_cache_age_hours"] = None
                health["macro_cache_status"] = "UNKNOWN"
        else:
            health["macro_cache_status"] = "NO_CACHE"

        # Validation status (0497)
        try:
            acceptance = _get_macro_acceptance_state(conn)
            health["validation_status"] = "ACCEPTED" if acceptance else "PRE_ACCEPTANCE"
            health["validation_contract"] = acceptance.get("contract") if acceptance else None
        except Exception:
            health["validation_status"] = "UNKNOWN"
            health["validation_contract"] = None

        # Weak betas
        health["weak_beta_count"] = conn.execute(
            "SELECT COUNT(*) FROM holding_macro_scores "
            "WHERE scores LIKE '%\"weak\"%' OR scores LIKE '%\"insufficient_data\"%'"
        ).fetchone()[0]

        # Episode coverage breakdown by state — last 30 days (0500)
        try:
            rows = conn.execute("""
                SELECT macro_snapshot FROM decision_episodes
                WHERE created_at >= (strftime('%s','now') - 2592000)
                  AND macro_snapshot IS NOT NULL
            """).fetchall()
            coverage_counts: dict[str, int] = {
                "company_supported": 0, "fund_unsupported": 0,
                "no_score_available": 0, "stale_score": 0,
                "macro_context_unavailable": 0, "unknown": 0,
            }
            for (snap_json,) in rows:
                try:
                    snap = json.loads(snap_json)
                    state = snap.get("coverage_state", "unknown")
                    coverage_counts[state] = coverage_counts.get(state, 0) + 1
                except Exception:
                    coverage_counts["unknown"] += 1
            health["episode_coverage_30d"] = coverage_counts
            total_ep = sum(coverage_counts.values())
            no_score = coverage_counts.get("no_score_available", 0)
            if total_ep > 0 and no_score / total_ep > 0.20:
                health["episode_coverage_warning"] = (
                    f"WARNING: {no_score}/{total_ep} episodes ({100*no_score//total_ep}%) "
                    f"have no_score_available — consider expanding macro scoring universe"
                )
        except Exception:
            health["episode_coverage_30d"] = None

        conn.close()

    except Exception as e:
        health["error"] = str(e)
        health["status"] = "ERROR"

    return health


def generate_holding_macro_scores(force: bool = False) -> dict:
    """Score each holding on 4 macro dimensions (1–10 scale), BATCH=1 per LLM call.
    Skips tickers scored within the last 7 days unless force=True.
    Returns {ticker: {rate_sensitivity, inflation_hedge, dollar_sensitivity, geopolitical_risk, note}}.
    """
    _init_ai_tables()

    if not ollama_client.available():
        return {}

    holdings = _load_holdings_csv()
    if not holdings:
        return {}

    tickers = [_normalize_ticker(h.get("Stock", "")) for h in holdings if h.get("Stock")]
    tickers = list(dict.fromkeys(t for t in tickers if t))

    # Load existing scores from DB
    existing: dict = {}
    current_contract = _compute_scorer_contract_hash()
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT ticker, scores, updated_at FROM holding_macro_scores").fetchall()
        conn.close()
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        for r in rows:
            if r["updated_at"] and r["updated_at"][:10] >= cutoff:
                try:
                    payload = json.loads(r["scores"])
                    if payload.get("scorer_contract_hash") == current_contract:
                        existing[_normalize_ticker(r["ticker"])] = payload
                except Exception:
                    pass

    to_score = [t for t in tickers if force or t not in existing]
    if not to_score:
        return existing

    import macro_context
    macro = macro_context.fetch()

    # Persist regime snapshot if available (0468)
    regime = macro.get("regime")
    if regime and DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute(
                "INSERT OR REPLACE INTO macro_regime_snapshots (snapshot_date, regime_json, created_at) VALUES (?,?,?)",
                (date.today().isoformat(), json.dumps(regime), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    # Open a DB connection for evidence lookups
    _evidence_conn = None
    if DB_PATH.exists():
        try:
            _evidence_conn = sqlite3.connect(str(DB_PATH), timeout=10)
            _evidence_conn.row_factory = sqlite3.Row
        except Exception:
            pass

    results = dict(existing)
    BATCH = 1
    run_id = str(uuid.uuid4())  # full UUID (0478)
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scorer_contract_hash = _compute_scorer_contract_hash()

    # SHA-256 macro_hash over full nested context including measurements and regime (0478).
    # Exclude non-deterministic keys (_fetched_at, formatted_block, headlines, bills).
    _hash_ctx = {k: v for k, v in macro.items()
                 if k not in ("_fetched_at", "formatted_block", "headlines",
                              "official_bills", "legislative_bills", "legislative_media")}
    macro_hash = hashlib.sha256(
        json.dumps(_hash_ctx, sort_keys=True, default=str).encode()
    ).hexdigest()  # full 64-char SHA-256 (0484)

    # STARTED row is mandatory — raise if write fails so the run is never untracked (0478, 0485).
    # sqlite3.connect() creates the DB file if absent; no DB_PATH.exists() guard needed (0485).
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        _reconcile_stale_runs(conn)  # transition old STARTED rows to STALE_FAILED (0493)
        conn.execute(
                "INSERT OR REPLACE INTO macro_scoring_runs "
                "(run_id, run_at, expected_n, scored_n, failed_n, supported_scored_n, unsupported_n, "
                "coverage_pct, model_ver, schema_ver, macro_hash, scorer_contract_hash, status) "
                "VALUES (?,?,?,0,0,0,0,0,?,?,?,?, 'STARTED')",
                (run_id, run_at, len(to_score), ollama_client.DEFAULT_MODEL, MACRO_SCORE_SCHEMA_VERSION,
                 macro_hash, scorer_contract_hash)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[MacroScores] FATAL: cannot write ledger STARTED row: {e}")
        raise

    scored_n = 0
    failed_n = 0
    supported_scored_n = 0
    unsupported_n = 0
    run_errors: list = []

    # 0504 — fund early-exit: write unsupported record immediately, skip LLM entirely
    company_tickers = []
    if DB_PATH.exists():
        _fund_conn = sqlite3.connect(str(DB_PATH), timeout=10)
        for _ft in to_score:
            if not is_fund(_ft):
                company_tickers.append(_ft)
                continue
            _fund_rec = {
                "macro_supported": False,
                "scorer_contract_hash": scorer_contract_hash,
                "evidence_quality": "unsupported",
                "is_fund": True,
                "schema_version": MACRO_SCORE_SCHEMA_VERSION,
                "interaction_version": MACRO_INTERACTION_VERSION,
                "run_id": run_id,
                "model_version": ollama_client.DEFAULT_MODEL,
                "scored_at": run_at,
            }
            _fund_json = json.dumps(_fund_rec)
            _ev_hash_fund = hashlib.sha256(b"fund:unsupported").hexdigest()
            _fund_conn.execute(
                "INSERT OR REPLACE INTO holding_macro_scores (ticker, scores, updated_at, run_id) VALUES (?,?,?,?)",
                (_ft, _fund_json, run_at, run_id)
            )
            _fund_conn.execute(
                "INSERT INTO holding_macro_scores_history "
                "(ticker, scores, scored_at, run_id, model_ver, schema_ver, evidence_hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (_ft, _fund_json, run_at, run_id,
                 ollama_client.DEFAULT_MODEL, MACRO_SCORE_SCHEMA_VERSION, _ev_hash_fund)
            )
            results[_ft] = _fund_rec
            scored_n += 1
            unsupported_n += 1
        _fund_conn.commit()
        _fund_conn.close()
    else:
        company_tickers = [t for t in to_score if not is_fund(t)]

    for i in range(0, len(company_tickers), BATCH):
        batch = company_tickers[i:i + BATCH]
        ticker_list = ", ".join(batch)

        # Build evidence and betas per ticker; prompt built via canonical function (0529)
        betas_by_ticker = {}
        evidence_by_ticker = {}
        for tk in batch:
            ev = _fetch_company_evidence(tk, _evidence_conn)
            evidence_by_ticker[tk] = ev
            betas = _compute_equity_betas(tk)
            if betas:
                betas_by_ticker[tk] = betas

        _tk_single = batch[0]
        prompt = _build_macro_score_request(
            _tk_single,
            evidence_by_ticker[_tk_single],
            betas_by_ticker.get(_tk_single),
        )

        # Wait for server to be ready before each batch (it may have restarted)
        for _attempt in range(30):
            if ollama_client.available():
                break
            time.sleep(5)
        else:
            msg = f"Server not ready for batch {i//BATCH+1} ({ticker_list})"
            print(f"[MacroScores] {msg}")
            failed_n += len(batch)
            run_errors.append({"tickers": batch, "error": msg})
            continue

        # 0507: adaptive N per dimension based on stability class
        _n_per_dim = {
            _d: (_n_samples_for_dim(_tk_single, _d, _evidence_conn) if _evidence_conn else 3)
            for _d in _MACRO_SCORE_DIMS
        }
        _n_max = max(_n_per_dim.values())
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

        _raw_per_dim: dict[str, list[int]] = {_d: [] for _d in _MACRO_SCORE_DIMS}
        _raw_reasons: dict[str, str] = {}
        _raw_note = ""
        _n_successful = 0
        for _si in range(_n_max):
            _ft = ""
            try:
                for tok in ollama_client.stream_generate(
                    prompt, model=ollama_client.DEFAULT_MODEL,
                    temperature=_MACRO_SCORE_TEMPERATURE, num_predict=_MACRO_SCORE_NUM_PREDICT
                ):
                    _ft += tok
            except Exception as e:
                print(f"[MacroScores] Sample {_si+1}/{_n_max} stream failed for {_tk_single}: {e}")
                break
            try:
                _tk_s = _parse_and_validate_macro_score_response(_ft, _tk_single)
            except ValueError:
                continue
            for _d in _MACRO_SCORE_DIMS:
                _sv = _score_val(_tk_s.get(_d))
                if _sv is not None:
                    _raw_per_dim[_d].append(_sv)
                    if _d not in _raw_reasons:
                        _raw_reasons[_d] = (_tk_s.get(_d) or {}).get("reason", "")
            if not _raw_note and "note" in _tk_s:
                _raw_note = _tk_s["note"]
            _n_successful += 1
            if _si < _n_max - 1:
                time.sleep(5)

        if _n_successful == 0:
            msg = f"All {_n_max} LLM samples failed or malformed"
            print(f"[MacroScores] Batch {i//BATCH+1} ({ticker_list}) {msg}")
            failed_n += len(batch)
            run_errors.append({"tickers": batch, "error": msg})
            time.sleep(20)
            continue

        # Aggregate per-dim using exactly n_per_dim samples
        _agg_dims: dict = {}
        for _d in _MACRO_SCORE_DIMS:
            _used = _raw_per_dim[_d][:_n_per_dim[_d]]
            if not _used:
                continue
            _med = int(round(statistics.median(_used)))
            _mn  = round(sum(_used) / len(_used), 2)
            _sd  = round(statistics.stdev(_used) if len(_used) > 1 else 0.0, 3)
            _agg_dims[_d] = {
                "score":    _med,
                "reason":   _raw_reasons.get(_d, ""),
                "median":   _med,
                "mean":     _mn,
                "stddev":   _sd,
                "min":      min(_used),
                "max":      max(_used),
                "n_samples": len(_used),
            }
        _agg_dims["note"] = _raw_note
        batch_result = {_tk_single: _agg_dims}

        # Ensure expected ticker is in result
        if not _agg_dims.get(_MACRO_SCORE_DIMS[0]):
            msg = "Ticker absent from all LLM samples"
            print(f"[MacroScores] Batch {i//BATCH+1} {msg}")
            failed_n += len(batch)
            run_errors.append({"tickers": batch, "error": msg})
            continue

        # Ticker was confirmed present (checked above in the early-exit)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            for ticker, scores in batch_result.items():
                ticker = _normalize_ticker(ticker)
                if ticker not in tickers:
                    continue
                try:
                    _validate_macro_score_response(scores, ticker)
                except ValueError as ve:
                    print(f"[MacroScores] Validation failed for {ticker}: {ve}")
                    failed_n += 1
                    run_errors.append({"tickers": [ticker], "error": f"validation: {ve}"})
                    continue
                scores["schema_version"] = MACRO_SCORE_SCHEMA_VERSION
                scores["interaction_version"] = MACRO_INTERACTION_VERSION
                # Attach evidence quality (per-dimension + overall) and betas (0473, 0476, 0483)
                ev = evidence_by_ticker.get(ticker) or _fetch_company_evidence(ticker, _evidence_conn)
                scores["evidence_quality"]           = ev.get("evidence_quality", "none")
                scores["evidence_quality_rate"]      = ev.get("evidence_quality_rate", "none")
                scores["evidence_quality_dollar"]    = ev.get("evidence_quality_dollar", "none")
                scores["evidence_quality_inflation"] = ev.get("evidence_quality_inflation", "none")
                scores["evidence_quality_geo"]       = ev.get("evidence_quality_geo", "none")
                scores["is_fund"] = ev.get("is_fund", False)
                if ticker in betas_by_ticker:
                    b = betas_by_ticker[ticker]
                    scores["rate_beta_100bp_return_pct"] = b.get("rate_beta_100bp_return_pct")
                    scores["usd_beta_1pct_return_pct"]   = b.get("usd_beta_1pct_return_pct")
                    scores["market_beta"]                = b.get("market_beta")
                    scores["rate_beta_confidence"]       = b.get("rate_beta_confidence")
                    scores["usd_beta_confidence"]        = b.get("usd_beta_confidence")
                    scores["beta_r_squared"]             = b.get("r_squared")
                    scores["beta_n_weeks"]               = b.get("n_weeks")
                    # Concordance check: negative rate_beta should agree with HIGH rate_sensitivity (0483)
                    rate_score = _score_val(scores.get("rate_sensitivity"))
                    rb = b.get("rate_beta_100bp_return_pct")
                    if rb is not None and rate_score is not None:
                        if _is_concordance_warning(rb, rate_score):
                            print(f"[MacroScores] CONCORDANCE WARNING {ticker}: rate_beta={rb:.3f}%/100bps disagrees with LLM rate_sensitivity={rate_score}")
                        else:
                            print(f"[MacroScores] {ticker}: rate_beta={rb:.3f}%/100bps concordant with LLM rate_sensitivity={rate_score}")

                # 0506/0511/0512: attach per-dim stability class and usable_for_attribution.
                # Stability class comes from the current sample set (runtime).
                # usable_for_attribution requires BOTH a formal accepted_validation stability row
                # AND evidence quality meeting the per-dim minimum.
                for _sdim in _MACRO_SCORE_DIMS:
                    _dim_data = scores.get(_sdim)
                    if isinstance(_dim_data, dict):
                        _sd_val  = _dim_data.get("stddev")
                        _scls    = _stability_class(_sd_val)
                        _ev_key  = _DIM_EV_KEY.get(_sdim, "evidence_quality")
                        _ev_qual = scores.get(_ev_key) or ev.get(_ev_key, "none")
                        _usable  = _usable_for_attribution(ticker, _sdim, _ev_qual, conn)
                        _dim_data["stability_class"]        = _scls
                        _dim_data["usable_for_attribution"] = _usable
                # Also expose flat keys for attribution filter (0511: include validated vs runtime)
                for _sdim in _MACRO_SCORE_DIMS:
                    _dim_data = scores.get(_sdim)
                    if isinstance(_dim_data, dict):
                        scores[f"{_sdim}_usable_for_attribution"] = _dim_data.get("usable_for_attribution")
                        scores[f"{_sdim}_stability_class"]        = _dim_data.get("stability_class")
                        scores[f"{_sdim}_runtime_stability"]   = _dim_data.get("stability_class")
                        # 0525: validated_stability from active acceptance contract only
                        _ads = _accepted_dim_state(ticker, _sdim, conn)
                        scores[f"{_sdim}_validated_stability"] = _ads["stability_class"]
                        scores[f"{_sdim}_acceptance_record_id"] = _ads["record_id"]

                # Compute evidence hash (full SHA-256, no truncation) for provenance (0475, 0484)
                _ev_meta = {"evidence_quality", "evidence_quality_rate", "evidence_quality_dollar",
                            "evidence_quality_inflation", "evidence_quality_geo", "is_fund", "fund_note"}
                ev_fields = {k: v for k, v in ev.items() if k not in _ev_meta}
                evidence_hash = hashlib.sha256(
                    json.dumps(ev_fields, sort_keys=True, default=str).encode()
                ).hexdigest()  # full 64-char SHA-256

                # Attach full provenance to score dict (0484)
                scores["evidence_hash"]  = evidence_hash
                scores["run_id"]         = run_id
                scores["model_version"]  = ollama_client.DEFAULT_MODEL
                scores["prompt_hash"]    = prompt_hash
                scores["scorer_contract_hash"] = scorer_contract_hash
                scores["scored_at"]      = now_str

                scores_json = json.dumps(scores)
                conn.execute(
                    "INSERT OR REPLACE INTO holding_macro_scores (ticker, scores, updated_at, run_id) VALUES (?,?,?,?)",
                    (ticker, scores_json, now_str, run_id)
                )
                conn.execute(
                    "INSERT INTO holding_macro_scores_history "
                    "(ticker, scores, scored_at, run_id, model_ver, schema_ver, evidence_hash) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (ticker, scores_json, now_str, run_id,
                     ollama_client.DEFAULT_MODEL, MACRO_SCORE_SCHEMA_VERSION, evidence_hash)
                )
                # Persist per-dim stability to runtime table (0517); scorer rows never make a
                # ticker formally usable for attribution — only accepted_validation rows do.
                for _sdim in _MACRO_SCORE_DIMS:
                    _dim_data = scores.get(_sdim)
                    if isinstance(_dim_data, dict) and _dim_data.get("n_samples", 0) > 1:
                        try:
                            conn.execute(
                                "INSERT OR REPLACE INTO macro_dimension_runtime_stability "
                                "(ticker, dimension, mean_score, stddev, n_samples, stability_class, updated_at) "
                                "VALUES (?,?,?,?,?,?,?)",
                                (ticker, _sdim,
                                 _dim_data.get("mean"),
                                 _dim_data.get("stddev"),
                                 _dim_data.get("n_samples"),
                                 _dim_data.get("stability_class"),
                                 now_str)
                            )
                        except Exception:
                            pass

                results[ticker] = scores
                scored_n += 1
                supported_scored_n += 1
            conn.commit()
            conn.close()

        print(f"[MacroScores] Scored {len(batch_result)} tickers in batch {i//BATCH+1}")
        time.sleep(25)  # give server time to recover before next batch

    if _evidence_conn:
        try:
            _evidence_conn.close()
        except Exception:
            pass

    # Update ledger row with final counts — COMPLETE only when scored_n == expected_n (0478, 0485).
    cov = round(scored_n / len(to_score) * 100, 1) if to_score else 100.0
    if scored_n == len(to_score):
        status = "COMPLETE"
    elif scored_n > 0:
        status = "PARTIAL"
    else:
        status = "FAILED"
    errors_json_str = json.dumps(run_errors) if run_errors else None

    # Accounting invariant: every ticker in to_score must appear in scored_n or failed_n (0515).
    # Mismatch means a code path dropped a ticker silently — persist FAILED and raise.
    if scored_n + failed_n != len(to_score):
        _acct_msg = (
            f"[MacroScores] FATAL accounting mismatch — "
            f"expected={len(to_score)}, scored={scored_n}, failed={failed_n}, "
            f"sum={scored_n + failed_n}"
        )
        print(_acct_msg)
        try:
            _fc = sqlite3.connect(str(DB_PATH), timeout=10)
            _fc.execute(
                "UPDATE macro_scoring_runs SET status='FAILED', errors_json=? WHERE run_id=?",
                (json.dumps([_acct_msg]), run_id)
            )
            _fc.commit()
            _fc.close()
        except Exception:
            pass
        raise RuntimeError(_acct_msg)

    # Sub-accounting invariant: supported + unsupported must equal total processed (0520).
    if supported_scored_n + unsupported_n != scored_n:
        _sub_msg = (
            f"[MacroScores] FATAL sub-accounting mismatch — "
            f"supported={supported_scored_n}, unsupported={unsupported_n}, "
            f"sum={supported_scored_n + unsupported_n}, processed={scored_n}"
        )
        print(_sub_msg)
        try:
            _fc = sqlite3.connect(str(DB_PATH), timeout=10)
            _fc.execute(
                "UPDATE macro_scoring_runs SET status='FAILED', errors_json=? WHERE run_id=?",
                (json.dumps([_sub_msg]), run_id)
            )
            _fc.commit()
            _fc.close()
        except Exception:
            pass
        raise RuntimeError(_sub_msg)

    # Retry twice; raise on exhaustion — never silently drop (0478, 0485).
    for _upd_attempt in range(2):
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.execute(
                "UPDATE macro_scoring_runs "
                "SET scored_n=?, failed_n=?, supported_scored_n=?, unsupported_n=?, "
                "coverage_pct=?, status=?, errors_json=? WHERE run_id=?",
                (scored_n, failed_n, supported_scored_n, unsupported_n,
                 cov, status, errors_json_str, run_id)
            )
            conn.commit()
            conn.close()
            print(
                f"[MacroScores] Run {run_id[:8]}: {scored_n}/{len(to_score)} processed "
                f"({supported_scored_n} LLM-scored, {unsupported_n} unsupported), "
                f"{cov:.1f}% — {status}"
            )
            break
        except Exception as e:
            print(f"[MacroScores] WARNING: ledger UPDATE failed (attempt {_upd_attempt+1}): {e}")
            if _upd_attempt == 1:
                raise RuntimeError(f"[MacroScores] FATAL: run {run_id} ledger UPDATE failed after 2 attempts") from e
            time.sleep(3)

    if to_score and results:
        generate_macro_score_summary(results, macro)

    # Capture health snapshot (0492)
    try:
        snap_conn = sqlite3.connect(str(DB_PATH), timeout=10)
        snap = _compute_macro_health_snapshot(run_id, snap_conn)
        snap_id = str(uuid.uuid4())
        snap_conn.execute(
            "INSERT OR REPLACE INTO macro_health_snapshots "
            "(snapshot_id, run_id, captured_at, supported_count, unsupported_count, "
            "portfolio_coverage_pct, stale_series_json, unknown_regime_fields_json, "
            "weak_beta_count, unexplained_drift_count, stale_failed_count, health_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (snap_id, run_id, snap.get("captured_at"), snap.get("supported_count", 0),
             snap.get("unsupported_count", 0), snap.get("portfolio_coverage_pct", 0.0),
             snap.get("stale_series_json"), snap.get("unknown_regime_fields_json"),
             snap.get("weak_beta_count", 0), snap.get("unexplained_drift_count", 0),
             snap.get("stale_failed_count", 0), snap.get("health_json")),
        )
        snap_conn.commit()
        snap_conn.close()
    except Exception as e:
        print(f"[MacroScores] WARNING: health snapshot write failed: {e}")

    return results


def generate_macro_score_summary(current_scores: dict, macro: dict) -> None:
    """
    After a scoring run, generate a per-layer AI narrative explaining structural score changes.
    Structural scores should only change when company evidence changes — this function
    classifies each change as evidence-driven, version-artefact, or unexplained instability.
    The current macro regime is reported separately and is NOT used to explain score changes.
    """
    if not DB_PATH.exists() or not current_scores:
        return
    if not ollama_client.available():
        return

    # ── Load previous scores + provenance from history ──────────────────────
    prev_scores: dict = {}
    prev_evidence_hash: dict = {}
    prev_model_ver: dict = {}
    prev_schema_ver: dict = {}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, scores, evidence_hash, model_ver, schema_ver "
            "FROM holding_macro_scores_history "
            "ORDER BY ticker, scored_at DESC"
        ).fetchall()
        conn.close()
        ticker_runs: dict = {}
        for r in rows:
            ticker_runs.setdefault(r["ticker"], []).append(r)
        for t, run_list in ticker_runs.items():
            if len(run_list) >= 2:
                try:
                    prev_row = run_list[1]
                    prev_scores[t]       = json.loads(prev_row["scores"])
                    prev_evidence_hash[t] = prev_row["evidence_hash"]
                    prev_model_ver[t]     = prev_row["model_ver"]
                    prev_schema_ver[t]    = prev_row["schema_ver"]
                except Exception:
                    pass
    except Exception:
        pass

    def _composite(scores: dict):
        DIMS = [
            ("rate_sensitivity",   False),
            ("inflation_hedge",    True),
            ("dollar_sensitivity", False),
            ("geopolitical_risk",  False),
        ]
        parts = []
        for dim, is_benefit in DIMS:
            sv = _score_val(scores.get(dim))
            if sv is None:
                return None
            parts.append((sv - 1) / 9 if is_benefit else (10 - sv) / 9)
        return round(sum(parts) / len(parts) * 100) if parts else None

    # ── Load holdings to map ticker → layer number ───────────────────────────
    holdings_csv = _load_holdings_csv()
    ticker_layer: dict = {}
    for h in holdings_csv:
        t = _normalize_ticker(h.get("Stock", ""))
        if t:
            try:
                ticker_layer[t] = int(h.get("Layer", 0))
            except (TypeError, ValueError):
                pass

    # ── Group deltas by layer with change classification ─────────────────────
    layer_changes: dict = {}
    for ticker, scores in current_scores.items():
        layer_num = ticker_layer.get(ticker)
        if not layer_num:
            continue
        curr_c = _composite(scores)
        prev_s = prev_scores.get(ticker)
        prev_c = _composite(prev_s) if prev_s is not None else None
        delta_c = (curr_c - prev_c) if (curr_c is not None and prev_c is not None) else None

        # Classify the source of score changes (0480, 0484 — use model_version not schema_version)
        curr_ev_hash    = scores.get("evidence_hash")
        prev_ev_hash    = prev_evidence_hash.get(ticker)
        curr_model_ver  = scores.get("model_version", "unknown")
        prev_model_ver_ = prev_model_ver.get(ticker, "unknown")
        curr_schema_ver = scores.get("schema_version", MACRO_SCORE_SCHEMA_VERSION)
        prev_schema_ver_ = prev_schema_ver.get(ticker, "unknown")
        version_changed = (curr_model_ver != prev_model_ver_) or (curr_schema_ver != prev_schema_ver_)

        if prev_s is None:
            change_class = "first_score"
        elif curr_ev_hash is None or prev_ev_hash is None:
            change_class = "evidence_unverifiable"
        elif curr_ev_hash != prev_ev_hash:
            change_class = "evidence_driven"
        elif version_changed:
            change_class = "version_artefact"
        elif delta_c is not None and abs(delta_c) > 5:
            change_class = "unexplained_instability"
        else:
            change_class = "stable"

        dim_changes = []
        for dim in ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk"):
            cv = _score_val(scores.get(dim))
            pv = _score_val(prev_s.get(dim)) if prev_s is not None else None
            if cv is not None and pv is not None and cv != pv:
                dim_changes.append({
                    "dim":    dim,
                    "prev":   pv,
                    "curr":   cv,
                    "delta":  cv - pv,
                    "reason": _score_reason(scores.get(dim)),
                    "class":  change_class,
                })

        layer_changes.setdefault(layer_num, []).append({
            "ticker":          ticker,
            "curr_composite":  curr_c,
            "prev_composite":  prev_c,
            "delta_composite": delta_c,
            "change_class":    change_class,
            "dim_changes":     dim_changes,
            "note":            scores.get("note", ""),
        })

    if not layer_changes:
        return

    # ── Build changes block — no macro conditions in this section (0480) ────
    changes_block = ""
    for layer_num in sorted(layer_changes.keys()):
        layer_label = LAYER_NAMES.get(layer_num, f"L{layer_num}")
        changes_block += f"\nLayer {layer_num} — {layer_label}:\n"
        for item in layer_changes[layer_num]:
            prev_str  = str(item["prev_composite"]) if item["prev_composite"] is not None else "—"
            delta_str = ""
            if item["delta_composite"] is not None:
                sign = "+" if item["delta_composite"] > 0 else ""
                delta_str = f" ({sign}{item['delta_composite']})"
            elif item["prev_composite"] is None:
                delta_str = " (first score)"
            changes_block += (
                f"  {item['ticker']}: composite {prev_str} → {item['curr_composite']}{delta_str} "
                f"[{item['change_class']}]\n"
            )
            for dc in item["dim_changes"]:
                sign = "+" if dc["delta"] > 0 else ""
                changes_block += f"    {dc['dim']}: {dc['prev']} → {dc['curr']} ({sign}{dc['delta']}) [{dc['class']}]"
                if dc["reason"]:
                    reason_short = dc["reason"][:80] + ("…" if len(dc["reason"]) > 80 else "")
                    changes_block += f" — {reason_short}"
                changes_block += "\n"
            if item.get("note"):
                changes_block += f"    Overall: {item['note']}\n"

    # ── Regime commentary (separate section — explains interactions, NOT score changes) ──
    regime = macro.get("regime", {})
    directional = regime.get("directional_states", {})
    regime_block = (
        f"Current regime context (for interaction commentary only, does NOT explain score changes):\n"
        f"  Rates: {directional.get('rates','unknown')} (10Y={macro.get('yield_10y','N/A')}%)\n"
        f"  Dollar: {directional.get('dollar','unknown')}\n"
        f"  Volatility: {directional.get('volatility','unknown')} (VIX={macro.get('vix','N/A')})\n"
        f"  Curve: {directional.get('curve','unknown')}\n"
        f"  Inflation: {directional.get('inflation','unknown')} (CPI={macro.get('cpi_yoy','N/A')}% YoY)\n"
    )

    layer_json_template = ",\n    ".join(
        f'"{n}": "<2-3 sentences for layer {n}>"' for n in sorted(layer_changes.keys())
    )
    prompt = f"""You are a macro risk analyst reviewing structural exposure score changes for a layered portfolio.

IMPORTANT: Structural exposure scores measure company sensitivity to macro factors based on business model,
revenue geography, and balance sheet. They should only change when company fundamentals change, NOT when
market conditions change. Each score change is labelled with its classification:
- evidence_driven: company data changed between runs
- version_artefact: model or schema version changed
- unexplained_instability: neither evidence nor version changed — treat as scoring noise
- first_score: no prior score exists for comparison
- evidence_unverifiable: provenance data unavailable (pre-0475 history)
- stable: no material change

STRUCTURAL SCORE CHANGES (do NOT explain these using macro conditions):
{changes_block}

{regime_block}
Write a structured weekly summary with TWO clearly labelled sections per layer:
1. STRUCTURAL CHANGES — what changed, which classification it falls into, which holdings drove it.
   For unexplained_instability changes: note they may be scoring noise, not fundamental shifts.
   Do NOT attribute structural score changes to macro conditions (e.g. "rose because rates increased").
2. REGIME IMPACT — given the UNCHANGED structural exposure, how does the current macro regime
   affect each layer's effective risk? This section MAY reference macro conditions.

Return ONLY valid JSON, no extra text:
{{
  "portfolio": "<1-2 sentences on overall portfolio structural health and any regime interactions>",
  "layers": {{
    {layer_json_template}
  }}
}}
"""

    for _attempt in range(3):
        if ollama_client.available():
            break
        time.sleep(5)
    else:
        print("[MacroSummary] Server not ready, skipping summary.")
        return

    try:
        result = ollama_client.generate_structured(
            prompt,
            schema={"portfolio": "", "layers": {}},
            model=ollama_client.DEFAULT_MODEL,
            temperature=0.3,
            num_predict=8000,
            retries=2,
        )
    except ollama_client.StructuredOutputError as e:
        print(f"[MacroSummary] AI call failed: {e}")
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "portfolio":    result.get("portfolio", ""),
        "layers":       result.get("layers", {}),
        "scored_date":  date.today().isoformat(),
        "scored_count": sum(len(v) for v in layer_changes.values()),
    }
    conn = None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "INSERT INTO macro_score_summaries (summary_json, created_at) VALUES (?,?)",
            (json.dumps(payload), now_str)
        )
        conn.commit()
        print(f"[MacroSummary] Summary stored ({payload['scored_count']} holdings scored).")
    except Exception as e:
        print(f"[MacroSummary] DB write failed: {e}")
    finally:
        if conn:
            conn.close()


# ── Regime stress scalars (0482) ─────────────────────────────────────────────

def compute_regime_stress(regime: dict) -> dict:
    """Compute per-dimension regime stress scalars (0488).

    Signed scalars: +1 = strongly adverse, 0 = neutral, -1 = strongly favorable.
    For rate_sensitivity: adverse = rising rates (positive rate_stress).
    For dollar_sensitivity: adverse = strengthening dollar (positive dollar_stress).
    vol_stress: unsigned 0–1 (VIX high is generically adverse).
    geopolitical_stress: None — no real signal source yet.
    Returns None per dimension when input data is unavailable (0487: missing ≠ benign).
    EXPERIMENTAL — research only. NOT used in any trading or risk-gate logic.
    """
    if not regime:
        return {}

    # Rate stress: +1 when 63d yield change is strongly rising (+150bps), -1 when falling (-150bps)
    rate_63d = regime.get("rate", {}).get("yield_10y_63d_chg_bps")
    rate_stress = round(max(-1.0, min(1.0, rate_63d / 150.0)), 3) if rate_63d is not None else None

    # Dollar stress: +1 when dollar is strongly strengthening (+5%), -1 when weakening (-5%)
    dollar_63d = regime.get("dollar", {}).get("uup_63d_pct")
    dollar_stress = round(max(-1.0, min(1.0, dollar_63d / 5.0)), 3) if dollar_63d is not None else None

    # Vol stress: unsigned 0–1 based on VIX level (15=0, 35=1)
    vix_level = regime.get("volatility", {}).get("vix_level")
    vol_stress = round(max(0.0, min(1.0, (vix_level - 15) / 20.0)), 3) if vix_level is not None else None

    # Geopolitical: no real signal — remains None rather than zero (0487)
    return {
        "rate_stress":         rate_stress,
        "dollar_stress":       dollar_stress,
        "vol_stress":          vol_stress,
        "geopolitical_stress": None,
        "note":                "EXPERIMENTAL — research only; not used in trading or risk gates",
    }


def compute_regime_adjusted_risk(scores: dict, regime_stress: dict):
    """Compute experimental signed regime-adjusted risk per dimension (0488).

    signed_interaction = structural_exposure_normalised × regime_stress_signed
      +1 = structural exposure fully amplified by adverse regime
       0 = neutral regime
      -1 = structural exposure fully offset by favorable regime

    When regime_stress for a dimension is None, that dimension's result is None.
    EXPERIMENTAL — research only. Do not use for recommendations or sizing.

    Sign convention (macro_interaction_v1):
      rate:            positive = adverse (rising rates hurt rate-sensitive names)
      dollar:          positive = adverse (strong dollar hurts dollar-sensitive names)
      inflation_hedge: negative = favorable (strong hedge offsets inflation pressure)
      geopolitical:    None until real signal source exists
    All interactions: +1 = max adverse, 0 = neutral, -1 = max favorable
    """
    if not scores or not regime_stress:
        return None
    result = {}

    # Rate and dollar: positive stress = adverse for high-sensitivity names
    for dim, stress_key in (("rate_sensitivity", "rate_stress"), ("dollar_sensitivity", "dollar_stress")):
        sv = _score_val(scores.get(dim))
        stress = regime_stress.get(stress_key)
        if sv is None or stress is None:
            result[f"{dim}_regime_risk"] = None
        else:
            struct_norm = (sv - 1) / 9.0
            result[f"{dim}_regime_risk"] = round(struct_norm * stress, 3)

    # Inflation hedge: high score = favorable; rising rates offset by inflation protection
    inf_sv = _score_val(scores.get("inflation_hedge"))
    rate_stress = regime_stress.get("rate_stress")
    if inf_sv is None or rate_stress is None:
        result["inflation_hedge_regime_risk"] = None
    else:
        struct_norm = (inf_sv - 1) / 9.0
        result["inflation_hedge_regime_risk"] = round(struct_norm * (-rate_stress), 3)

    # Geopolitical: no signal yet
    result["geopolitical_risk_regime_risk"] = None
    result["interaction_version"] = MACRO_INTERACTION_VERSION
    result["note"] = "EXPERIMENTAL — research only"
    return result


# ── Portfolio chat ────────────────────────────────────────────────────────────

def build_portfolio_system_prompt() -> str:
    """Build the system prompt for portfolio-level AI chat."""
    import macro_context
    macro = macro_context.fetch()

    holdings = _load_holdings_csv()
    prices   = _get_holding_prices_from_db()
    layer_weights = _get_layer_weights_from_db()
    drift_alerts  = _get_drift_alerts(layer_weights)

    # Load macro scores for context (compact=True omits per-dim reasons to keep prompt short)
    _, scores_block = _get_macro_scores_block(compact=True)

    cc_block       = _get_cc_context()
    lot_block      = _get_lot_context()
    realized_block = _get_realized_context()
    patterns_block = _get_behavior_patterns()
    personal_blocks = "\n\n".join(b for b in [cc_block, lot_block, realized_block, patterns_block] if b)

    framework = "\n".join(f"  {k}: {v}" for k, v in _LAYER_NAMES_LONG.items())

    system = f"""You are a sophisticated investment advisor helping the investor understand and manage their personal portfolio. You have deep knowledge of macro economics, geopolitics, tax strategy, and the portfolio framework below.

INVESTMENT FRAMEWORK:
{framework}

{_build_portfolio_block(holdings, prices)}

{_build_layer_block(layer_weights, drift_alerts)}

{macro.get('formatted_block', 'Macro data unavailable.')}
{scores_block}
{personal_blocks}

Rules for your responses:
- Always ground analysis in THIS specific portfolio — cite actual held tickers and their layers
- When discussing macro risks, connect them to specific positions the investor holds
- For CC questions, reference actual open positions by ticker and strike price
- For tax questions, reference actual lot dates and LT thresholds you have above
- Be direct and actionable; avoid vague generalities
- Keep responses focused and under ~300 words unless asked to elaborate"""

    return system


# ── CLI for standalone testing ────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", action="store_true", help="Generate macro scores for all holdings")
    parser.add_argument("--force",  action="store_true", help="Force regeneration even if cached")
    args = parser.parse_args()

    _init_ai_tables()

    if args.scores:
        print("Generating holding macro scores…")
        scores = generate_holding_macro_scores(force=args.force)
        for ticker, s in sorted(scores.items()):
            print(f"\n{ticker}:")
            for dim in SCORE_DIMS:
                raw = s.get(dim, '?')
                score = raw.get('score', '?') if isinstance(raw, dict) else raw
                reason = raw.get('reason', '') if isinstance(raw, dict) else ''
                line = f"  {SCORE_LABELS[dim]}: {score}/10"
                if reason:
                    line += f" — {reason}"
                print(line)
            print(f"  Note: {s.get('note', '')}")
    else:
        print("Generating daily portfolio insight…")
        insight = generate_daily_insight(force=args.force)
        if "error" in insight:
            print(f"ERROR: {insight['error']}")
        else:
            print(json.dumps(insight, indent=2))
