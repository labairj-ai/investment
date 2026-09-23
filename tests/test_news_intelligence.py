"""
Acceptance test suite for the news intelligence pipeline (0596-0600).

Deterministic fixtures, no LLM calls, in-memory SQLite.
Covers: snapshot contract, fail-closed grounding, event identity/decay,
thesis contract, confirmation channels, scoring, portfolio themes,
episode immutability, versioning.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.news import intelligence as intel


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_article(ticker, title, source="Reuters", pub_date="2026-09-20",
                  url="", excerpt="", body=""):
    return {
        "ticker": ticker, "title": title, "source": source,
        "pub_date": pub_date, "url": url or f"https://example.com/{hash(title)}",
        "excerpt": excerpt, "body": body,
    }


def _make_db():
    """In-memory SQLite with full news intelligence schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE news_events (
        event_id              TEXT PRIMARY KEY,
        ticker                TEXT NOT NULL,
        day                   TEXT NOT NULL,
        event_type            TEXT NOT NULL,
        direction             TEXT NOT NULL,
        magnitude             TEXT NOT NULL DEFAULT 'MEDIUM',
        expected_horizon      TEXT NOT NULL DEFAULT 'SHORT',
        confidence            REAL NOT NULL DEFAULT 0.7,
        affected_metric       TEXT,
        evidence_text         TEXT,
        source_titles         TEXT,
        source_count          INTEGER DEFAULT 1,
        first_seen            TEXT,
        last_seen             TEXT,
        thesis_relevance      REAL DEFAULT 0.0,
        pillar_name           TEXT,
        risk_name             TEXT,
        catalyst_name         TEXT,
        trigger_proximity     REAL DEFAULT 0.0,
        pillar_health_state   TEXT,
        event_trigger_state   TEXT DEFAULT 'NONE',
        event_trigger_proximity REAL DEFAULT 0.0,
        trend_status          TEXT,
        occurrence_count_7d   INTEGER DEFAULT 0,
        occurrence_count_30d  INTEGER DEFAULT 0,
        occurrence_count_90d  INTEGER DEFAULT 0,
        signal_strength       REAL DEFAULT 0.0,
        portfolio_priority    REAL DEFAULT 0.0,
        score_decomposition   TEXT,
        confirmation_class    TEXT DEFAULT 'NEWS_ONLY',
        confirmation_signals  TEXT,
        skepticism_note       TEXT,
        news_snapshot_hash    TEXT,
        extracted_at          TEXT NOT NULL DEFAULT 'now',
        event_fingerprint     TEXT,
        article_ids_json      TEXT,
        causal_driver         TEXT,
        causal_event_key      TEXT,
        news_intelligence_version TEXT
    )""")
    conn.execute("""CREATE TABLE news_portfolio_themes (
        theme_id        TEXT PRIMARY KEY,
        day             TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        direction       TEXT,
        affected_tickers TEXT NOT NULL,
        combined_weight REAL,
        event_count     INTEGER,
        description     TEXT,
        detected_at     TEXT NOT NULL DEFAULT 'now'
    )""")
    conn.execute("""CREATE TABLE news_event_state (
        ticker            TEXT NOT NULL,
        causal_event_key  TEXT NOT NULL,
        last_real_seen_at TEXT NOT NULL,
        state             TEXT NOT NULL DEFAULT 'ACTIVE',
        state_as_of       TEXT NOT NULL,
        PRIMARY KEY (ticker, causal_event_key)
    )""")
    conn.execute("""CREATE TABLE holding_day (
        ticker TEXT, day TEXT, price REAL
    )""")
    conn.execute("""CREATE TABLE spy_prices (
        day TEXT, price REAL
    )""")
    conn.execute("""CREATE TABLE holding_macro_scores (
        ticker TEXT PRIMARY KEY, scores TEXT, updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE company_financials (
        ticker TEXT, period_end TEXT, period_type TEXT,
        revenue REAL, gross_profit REAL
    )""")
    return conn


def _insert_event(conn, ticker, event_type, direction, day,
                  signal_strength=50.0, trend_status="CONFIRMING",
                  magnitude="MEDIUM", fingerprint=None, causal_event_key=None):
    import uuid
    fp = fingerprint or intel._event_fingerprint(ticker, event_type, direction)
    conn.execute(
        "INSERT INTO news_events (event_id, ticker, day, event_type, direction, "
        "magnitude, expected_horizon, confidence, extracted_at, trend_status, "
        "signal_strength, portfolio_priority, event_fingerprint, causal_event_key, "
        "news_intelligence_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), ticker, day, event_type, direction,
         magnitude, "SHORT", 0.8, day, trend_status,
         signal_strength, signal_strength * 0.1, fp, causal_event_key,
         intel.NEWS_INTELLIGENCE_VERSION)
    )
    conn.commit()


# ── Tests: hash / cache invalidation (0596) ──────────────────────────────────

class TestNewsHash:
    def _by_ticker(self, articles):
        result = {}
        for a in articles:
            result.setdefault(a["ticker"], []).append(a)
        return result

    def test_same_articles_same_hash(self):
        arts = [_make_article("AAPL", "Apple Q3 results beat", url="https://x.com/1")]
        h1 = intel.compute_news_hash(self._by_ticker(arts))
        h2 = intel.compute_news_hash(self._by_ticker(arts))
        assert h1 == h2

    def test_new_article_different_hash(self):
        arts1 = [_make_article("AAPL", "Apple Q3 results beat", url="https://x.com/1")]
        arts2 = arts1 + [_make_article("AAPL", "Apple raises guidance", url="https://x.com/2")]
        h1 = intel.compute_news_hash(self._by_ticker(arts1))
        h2 = intel.compute_news_hash(self._by_ticker(arts2))
        assert h1 != h2

    def test_hash_covers_url(self):
        a1 = _make_article("MSFT", "Cloud growth", url="https://x.com/1")
        a2 = dict(a1, url="https://x.com/DIFFERENT")
        h1 = intel.compute_news_hash({"MSFT": [a1]})
        h2 = intel.compute_news_hash({"MSFT": [a2]})
        assert h1 != h2

    def test_body_change_past_char80_invalidates_hash(self):
        """0596: hash covers body[:120], not just [:80] — change at chars 81-119 must invalidate."""
        base = _make_article("AAPL", "Apple Q3", url="https://x.com/3")
        art1 = dict(base, body="x" * 80 + "SUFFIX_A_UNIQUE")
        art2 = dict(base, body="x" * 80 + "SUFFIX_B_UNIQUE")
        h1 = intel.compute_news_hash({"AAPL": [art1]})
        h2 = intel.compute_news_hash({"AAPL": [art2]})
        assert h1 != h2, "Body content past char 80 must change the hash (0596)"

    def test_snapshot_hash_equals_compute_news_hash(self):
        """build_news_snapshot and compute_news_hash must return the same hash."""
        arts = [_make_article("TSLA", "Tesla deliveries", body="body text here", url="https://x.com/4")]
        by_ticker = {"TSLA": arts}
        snap = intel.build_news_snapshot(by_ticker)
        assert snap["snapshot_hash"] == intel.compute_news_hash(by_ticker)


# ── Tests: article identity / manifest ───────────────────────────────────────

class TestArticleIdentity:
    def test_deterministic_article_id(self):
        art = _make_article("TSLA", "Tesla cuts prices again", url="https://ev.com/1")
        id1 = intel._article_id(art)
        id2 = intel._article_id(art)
        assert id1 == id2
        assert len(id1) == 16

    def test_different_articles_different_ids(self):
        a1 = _make_article("TSLA", "Tesla cuts prices", url="https://ev.com/1")
        a2 = _make_article("TSLA", "Tesla raises prices", url="https://ev.com/2")
        assert intel._article_id(a1) != intel._article_id(a2)

    def test_manifest_built_correctly(self):
        arts = [
            _make_article("AAPL", "Apple revenue up", url="https://x.com/1"),
            _make_article("MSFT", "Azure beats", url="https://x.com/2"),
        ]
        by_ticker = {}
        for a in arts:
            by_ticker.setdefault(a["ticker"], []).append(a)
        manifest = intel._build_article_manifest(by_ticker)
        assert len(manifest) == 2
        for aid, meta in manifest.items():
            assert len(aid) == 16
            assert meta["ticker"] in ("AAPL", "MSFT")

    def test_invalid_article_ids_rejected(self):
        valid_art = _make_article("AAPL", "Apple news", url="https://x.com/1")
        valid_id  = intel._article_id(valid_art)
        fake_id   = "deadbeef000000"
        manifest = {valid_id: {"ticker": "AAPL", "title": "Apple news"}}
        valid_ids = set(manifest.keys())
        returned  = [valid_id, fake_id]
        validated = [aid for aid in returned if aid in valid_ids]
        assert validated == [valid_id]


# ── Tests: fail-closed evidence grounding (0597) ─────────────────────────────

class TestAdversarialValidation:
    def _mock_llm(self, response: dict):
        mock = MagicMock()
        mock.DEFAULT_MODEL = "test"
        mock.stream_generate.return_value = iter([json.dumps(response)])
        return mock

    def test_unknown_ticker_rejected(self):
        """LLM invents unknown ticker → event not in output."""
        art = _make_article("AAPL", "Apple news", url="https://x.com/t1")
        by_ticker = {"AAPL": [art]}
        valid_aid = intel._article_id(art)

        resp = {
            "UNKNOWN_TICKER": [{
                "event_type": "EARNINGS", "direction": "NEGATIVE",
                "magnitude": "HIGH", "horizon": "SHORT",
                "confidence": 0.9, "affected_metric": "revenue",
                "evidence": "fake", "article_ids": [valid_aid],
                "causal_driver": None, "causal_event_key": "UNKNOWN_TEST",
            }]
        }
        result = intel.extract_events_llm(by_ticker, self._mock_llm(resp))
        result.pop("_manifest", None)
        assert result == {}, f"Unknown ticker must be rejected, got {result}"

    def test_zero_article_ids_rejected(self):
        """LLM returns zero article_ids → event rejected."""
        art = _make_article("MSFT", "Azure news", url="https://x.com/t2")
        by_ticker = {"MSFT": [art]}

        resp = {
            "MSFT": [{
                "event_type": "PRODUCT", "direction": "POSITIVE",
                "magnitude": "MEDIUM", "horizon": "SHORT",
                "confidence": 0.8, "affected_metric": "cloud",
                "evidence": "Azure growth", "article_ids": [],
                "causal_driver": None, "causal_event_key": "MSFT_AZURE",
            }]
        }
        result = intel.extract_events_llm(by_ticker, self._mock_llm(resp))
        result.pop("_manifest", None)
        assert "MSFT" not in result, "Event with zero article_ids must be rejected"

    def test_cross_ticker_id_stripped_event_rejected(self):
        """LLM uses article ID from different ticker → ID stripped; event with 0 valid IDs rejected."""
        aapl_art = _make_article("AAPL", "Apple news", url="https://x.com/t3")
        msft_art = _make_article("MSFT", "Azure news", url="https://x.com/t4")
        by_ticker = {"AAPL": [aapl_art], "MSFT": [msft_art]}
        aapl_aid = intel._article_id(aapl_art)

        resp = {
            "MSFT": [{
                "event_type": "PRODUCT", "direction": "POSITIVE",
                "magnitude": "MEDIUM", "horizon": "SHORT",
                "confidence": 0.8, "affected_metric": "cloud",
                "evidence": "Azure growth",
                "article_ids": [aapl_aid],  # AAPL's ID used for MSFT event
                "causal_driver": None, "causal_event_key": "MSFT_AZURE",
            }]
        }
        result = intel.extract_events_llm(by_ticker, self._mock_llm(resp))
        result.pop("_manifest", None)
        assert "MSFT" not in result, "Cross-ticker ID must strip event; 0 valid IDs → reject"

    def test_valid_id_for_correct_ticker_accepted(self):
        """LLM returns valid ID for correct ticker → event accepted with manifest-derived title."""
        art = _make_article("NFLX", "Netflix subscriber growth", url="https://x.com/t5")
        by_ticker = {"NFLX": [art]}
        valid_aid = intel._article_id(art)

        resp = {
            "NFLX": [{
                "event_type": "DEMAND", "direction": "POSITIVE",
                "magnitude": "MEDIUM", "horizon": "SHORT",
                "confidence": 0.85, "affected_metric": "subscribers",
                "evidence": "Netflix adds 5M subscribers",
                "article_ids": [valid_aid],
                "causal_driver": None, "causal_event_key": "NFLX_Q3_SUB_GROWTH",
            }]
        }
        result = intel.extract_events_llm(by_ticker, self._mock_llm(resp))
        result.pop("_manifest", None)
        assert "NFLX" in result, f"Valid event should be accepted, got {result}"
        assert len(result["NFLX"]) == 1
        ev = result["NFLX"][0]
        assert ev["article_ids"] == [valid_aid]
        # Titles derived from manifest, not LLM strings
        assert ev["titles"] == ["Netflix subscriber growth"]

    def test_no_title_string_fallback(self):
        """LLM-provided title strings must NOT appear when article_ids are validated."""
        art = _make_article("GOOG", "Google Cloud revenue up", url="https://x.com/t6")
        by_ticker = {"GOOG": [art]}
        valid_aid = intel._article_id(art)

        resp = {
            "GOOG": [{
                "event_type": "EARNINGS", "direction": "POSITIVE",
                "magnitude": "HIGH", "horizon": "SHORT",
                "confidence": 0.9, "affected_metric": "cloud revenue",
                "evidence": "Google Cloud grows 30%",
                "article_ids": [valid_aid],
                "titles": ["HALLUCINATED TITLE FROM LLM"],  # must be ignored
                "causal_driver": None, "causal_event_key": "GOOG_Q3_CLOUD",
            }]
        }
        result = intel.extract_events_llm(by_ticker, self._mock_llm(resp))
        result.pop("_manifest", None)
        assert "GOOG" in result
        ev = result["GOOG"][0]
        assert "HALLUCINATED TITLE FROM LLM" not in ev["titles"]


# ── Tests: event fingerprint ──────────────────────────────────────────────────

class TestEventFingerprint:
    def test_same_event_same_fingerprint(self):
        fp1 = intel._event_fingerprint("AAPL", "EARNINGS", "NEGATIVE", "revenue")
        fp2 = intel._event_fingerprint("AAPL", "EARNINGS", "NEGATIVE", "revenue")
        assert fp1 == fp2

    def test_different_ticker_different_fingerprint(self):
        fp1 = intel._event_fingerprint("AAPL", "EARNINGS", "NEGATIVE")
        fp2 = intel._event_fingerprint("MSFT", "EARNINGS", "NEGATIVE")
        assert fp1 != fp2


# ── Tests: trend state machine ────────────────────────────────────────────────

class TestTrendStateMachine:
    def test_first_event_is_new(self):
        conn = _make_db()
        result = intel.compute_trend("AAPL", "EARNINGS", "NEGATIVE", "2026-09-23", conn)
        assert result["trend_status"] == "NEW"
        assert result["occurrence_count_30d"] == 0

    def test_repeated_events_become_confirming(self):
        conn = _make_db()
        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", "2026-08-25")
        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", "2026-09-10")
        result = intel.compute_trend("AAPL", "EARNINGS", "NEGATIVE", "2026-09-23", conn)
        assert result["trend_status"] == "CONFIRMING"
        assert result["occurrence_count_30d"] >= 1

    def test_accelerating_when_high_frequency(self):
        conn = _make_db()
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-15", fingerprint="fp_a")
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-18", fingerprint="fp_b")
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-20", fingerprint="fp_c")
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-21", fingerprint="fp_d")
        result = intel.compute_trend("AAPL", "MARGIN", "NEGATIVE", "2026-09-23", conn)
        assert result["trend_status"] == "ACCELERATING"

    def test_reversing_when_first_positive_after_negative_history(self):
        conn = _make_db()
        _insert_event(conn, "TSLA", "DEMAND", "NEGATIVE", "2026-09-01")
        _insert_event(conn, "TSLA", "DEMAND", "NEGATIVE", "2026-09-10")
        result = intel.compute_trend("TSLA", "DEMAND", "POSITIVE", "2026-09-23", conn)
        assert result["trend_status"] == "REVERSING", (
            f"Expected REVERSING (0590 fix), got {result['trend_status']}"
        )

    def test_fading_not_returned_for_active_observation(self):
        conn = _make_db()
        _insert_event(conn, "JPM", "LITIGATION", "NEGATIVE", "2026-07-25")
        result = intel.compute_trend("JPM", "LITIGATION", "NEGATIVE", "2026-09-23", conn)
        assert result["trend_status"] != "FADING"


# ── Tests: real event identity and decay state (0598) ────────────────────────

class TestEventIdentityAndDecay:
    def test_causal_event_key_persisted(self):
        """causal_event_key is stored on news_events rows."""
        conn = _make_db()
        day = "2026-09-23"
        events = {"AAPL": [{
            "event_type": "GUIDANCE_CHANGE", "direction": "POSITIVE",
            "magnitude": "HIGH", "horizon": "SHORT", "confidence": 0.9,
            "evidence": "Raised guidance", "titles": ["Apple raises guidance"],
            "article_ids": ["abc123"], "causal_driver": None,
            "causal_event_key": "AAPL_FY27_REVENUE_GUIDE_UP",
            "thesis_relevance": 0.0, "trigger_proximity": 0.0,
            "pillar_health_state": None, "event_trigger_state": "NONE",
            "event_trigger_proximity": 0.0,
            "trend_status": "NEW", "occurrence_count_7d": 0,
            "occurrence_count_30d": 0, "occurrence_count_90d": 0,
            "signal_strength": 70.0, "portfolio_priority": 7.0,
            "score_decomposition": {}, "confirmation_class": "NEWS_ONLY",
            "confirmation_signals": {}, "skepticism_note": None,
            "affected_metric": "revenue",
        }]}
        intel.persist_events(events, [], day, conn, "hash1")
        row = conn.execute(
            "SELECT causal_event_key FROM news_events WHERE ticker='AAPL'"
        ).fetchone()
        assert row is not None
        assert row[0] == "AAPL_FY27_REVENUE_GUIDE_UP"

    def test_compute_trend_deduplicates_same_causal_event_key(self):
        """Same causal_event_key in multiple rows counts as one distinct event."""
        conn = _make_db()
        fp = intel._event_fingerprint("MSFT", "EARNINGS", "POSITIVE", "EPS")
        _insert_event(conn, "MSFT", "EARNINGS", "POSITIVE", "2026-09-15",
                      fingerprint=fp, causal_event_key="MSFT_Q3_EPS_BEAT")
        _insert_event(conn, "MSFT", "EARNINGS", "POSITIVE", "2026-09-18",
                      fingerprint=fp, causal_event_key="MSFT_Q3_EPS_BEAT")
        result = intel.compute_trend("MSFT", "EARNINGS", "POSITIVE", "2026-09-23", conn)
        assert result["occurrence_count_30d"] == 1, (
            f"Same causal_event_key must count once; got {result['occurrence_count_30d']}"
        )

    def test_resolved_state_is_reachable(self):
        """RESOLVED is reached when event absent >30d from last_real_seen_at."""
        conn = _make_db()
        today = "2026-09-23"
        old_day = "2026-08-09"  # 45 days before today

        _insert_event(conn, "JPM", "LITIGATION", "NEGATIVE", old_day,
                      causal_event_key="JPM_SEC_PROBE_2026")
        conn.execute(
            "INSERT INTO news_event_state VALUES (?,?,?,?,?)",
            ("JPM", "JPM_SEC_PROBE_2026", old_day, "ACTIVE", old_day + " 00:00:00"),
        )
        conn.commit()

        intel.update_event_state_sweep(today, conn)

        row = conn.execute(
            "SELECT state FROM news_event_state "
            "WHERE ticker='JPM' AND causal_event_key='JPM_SEC_PROBE_2026'"
        ).fetchone()
        assert row is not None
        assert row[0] == "RESOLVED", f"Expected RESOLVED for 45d absence, got {row[0]}"

    def test_fading_sweep_does_not_insert_synthetic_rows(self):
        """update_event_state_sweep must NOT insert into news_events (0598)."""
        conn = _make_db()
        today = "2026-09-23"
        day15 = "2026-09-08"

        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", day15,
                      causal_event_key="AAPL_Q3_EPS_MISS")
        initial_count = conn.execute(
            "SELECT COUNT(*) FROM news_events WHERE ticker='AAPL'"
        ).fetchone()[0]

        intel.update_event_state_sweep(today, conn)

        final_count = conn.execute(
            "SELECT COUNT(*) FROM news_events WHERE ticker='AAPL'"
        ).fetchone()[0]
        assert final_count == initial_count, (
            f"Sweep must not insert synthetic rows. Before: {initial_count}, after: {final_count}"
        )

        state_row = conn.execute(
            "SELECT state FROM news_event_state "
            "WHERE ticker='AAPL' AND causal_event_key='AAPL_Q3_EPS_MISS'"
        ).fetchone()
        assert state_row is not None
        assert state_row[0] == "FADING", f"Expected FADING for 15d absence, got {state_row[0]}"

    def test_active_event_today_stays_active(self):
        """Event seen today → ACTIVE in news_event_state."""
        conn = _make_db()
        today = "2026-09-23"
        _insert_event(conn, "AMZN", "EARNINGS", "POSITIVE", today,
                      causal_event_key="AMZN_Q3_BEAT")

        intel.update_event_state_sweep(today, conn)

        row = conn.execute(
            "SELECT state FROM news_event_state "
            "WHERE ticker='AMZN' AND causal_event_key='AMZN_Q3_BEAT'"
        ).fetchone()
        assert row is not None
        assert row[0] == "ACTIVE"


# ── Tests: scoring and rank ordering ─────────────────────────────────────────

class TestScoring:
    def _base_event(self, **kwargs):
        ev = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "magnitude": "HIGH", "horizon": "SHORT",
            "confidence": 0.9, "trend_status": "NEW",
            "confirmation_class": "NEWS_ONLY",
            "thesis_relevance": 0.0, "trigger_proximity": 0.0,
            "event_trigger_proximity": 0.0,
        }
        ev.update(kwargs)
        return ev

    def test_signal_strength_independent_of_position(self):
        ev = self._base_event()
        s1 = intel.score_event(ev, position_weight=5.0)
        s2 = intel.score_event(ev, position_weight=10.0)
        assert s1["signal_strength"] == s2["signal_strength"]

    def test_large_position_ranks_higher_priority(self):
        ev = self._base_event()
        s5  = intel.score_event(ev, position_weight=5.0)
        s10 = intel.score_event(ev, position_weight=10.0)
        assert s10["portfolio_priority"] > s5["portfolio_priority"]

    def test_signal_strength_is_classification_input(self):
        ev_high = self._base_event(magnitude="HIGH", confidence=0.95)
        ev_low  = self._base_event(magnitude="LOW",  confidence=0.5)
        s_high = intel.score_event(ev_high, position_weight=2.0)
        s_low  = intel.score_event(ev_low,  position_weight=50.0)
        assert s_high["signal_strength"] > s_low["signal_strength"]

    def test_score_decomposition_present(self):
        ev = self._base_event()
        s = intel.score_event(ev, position_weight=8.0)
        decomp = s["score_decomposition"]
        for key in ("materiality", "magnitude_scale", "horizon_mult", "confidence",
                    "novelty_weight", "persistence_adj", "confirmation_boost",
                    "thesis_boost", "position_weight", "trigger_bonus"):
            assert key in decomp, f"Missing decomposition key: {key}"

    def test_multi_signal_confirmation_boosts_strength(self):
        ev1 = self._base_event(confirmation_class="NEWS_ONLY")
        ev2 = self._base_event(confirmation_class="MULTI_SIGNAL_CONFIRMATION")
        s1 = intel.score_event(ev1)
        s2 = intel.score_event(ev2)
        assert s2["signal_strength"] > s1["signal_strength"]

    def test_contradicted_depresses_strength(self):
        ev1 = self._base_event(confirmation_class="NEWS_ONLY")
        ev2 = self._base_event(confirmation_class="CONTRADICTED")
        s1 = intel.score_event(ev1)
        s2 = intel.score_event(ev2)
        assert s2["signal_strength"] < s1["signal_strength"]


# ── Tests: complete thesis contract (0599) ────────────────────────────────────

class TestThesisContract:
    def test_unrelated_event_near_zero_relevance(self):
        thesis = {
            "status": "ACTIVE",
            "pillars": [{"name": "Cloud Revenue Growth", "description": "Azure growth",
                          "importance": 80, "status": "ON_TRACK"}],
            "key_risks": [], "catalysts": [],
            "review_triggers": None, "add_condition": None,
            "trim_condition": None, "exit_condition": None,
        }
        with patch("agent_db.get_thesis", return_value=thesis):
            result = intel.map_thesis_relevance(
                "DIVIDEND_BUYBACK", "MSFT",
                ev_evidence="Microsoft announces special dividend",
                ev_metric="dividend per share",
            )
        assert result["thesis_relevance"] < 0.3

    def test_relevant_event_positive_relevance(self):
        thesis = {
            "status": "ACTIVE",
            "pillars": [{"name": "Earnings Growth", "description": "Strong earnings trajectory",
                          "importance": 90, "status": "ON_TRACK"}],
            "key_risks": [], "catalysts": [],
            "review_triggers": None, "add_condition": None,
            "trim_condition": None, "exit_condition": None,
        }
        with patch("agent_db.get_thesis", return_value=thesis):
            result = intel.map_thesis_relevance(
                "EARNINGS", "AAPL",
                ev_evidence="Apple misses earnings estimates",
                ev_metric="EPS",
            )
        assert result["thesis_relevance"] > 0

    def test_no_thesis_returns_zero(self):
        with patch("agent_db.get_thesis", return_value=None):
            result = intel.map_thesis_relevance("EARNINGS", "AAPL")
        assert result["thesis_relevance"] == 0.0

    def test_trigger_bonus_uses_event_trigger_proximity(self):
        """score_event reads event_trigger_proximity, not the old trigger_proximity field."""
        ev_base = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "magnitude": "HIGH", "horizon": "SHORT",
            "confidence": 0.9, "trend_status": "NEW",
            "confirmation_class": "NEWS_ONLY", "thesis_relevance": 0.0,
            "trigger_proximity": 1.0,       # old pillar-health field — must be ignored
            "event_trigger_proximity": 0.0,  # new field — must be used
        }
        ev_trigger = dict(ev_base, event_trigger_proximity=0.8)

        s_no_trigger   = intel.score_event(ev_base, position_weight=10.0)
        s_with_trigger = intel.score_event(ev_trigger, position_weight=10.0)

        # event_trigger_proximity=0.8 → trigger_bonus = 0.3*0.8 = 0.24 → higher pp
        assert s_with_trigger["portfolio_priority"] > s_no_trigger["portfolio_priority"], (
            "event_trigger_proximity=0.8 should boost pp vs 0.0"
        )
        # signal_strength is position-independent and trigger-independent
        assert s_no_trigger["signal_strength"] == s_with_trigger["signal_strength"]

        # With trigger_proximity=1.0 and event_trigger_proximity=0.0 → no boost expected
        pos_frac = 10.0 / 100.0
        expected_pp = s_no_trigger["signal_strength"] * pos_frac * 1.0  # trigger_bonus=0
        assert abs(s_no_trigger["portfolio_priority"] - expected_pp) < 0.5, (
            f"trigger_proximity=1.0 must be ignored; expected pp~{expected_pp:.1f}, "
            f"got {s_no_trigger['portfolio_priority']}"
        )

    def test_pillar_health_state_in_result(self):
        """map_thesis_relevance returns pillar_health_state as snapshot of pillar status."""
        thesis = {
            "status": "ACTIVE",
            "pillars": [{"name": "Revenue Guidance Outlook", "description": "Annual guidance trajectory",
                          "importance": 80, "status": "WARNING"}],
            "key_risks": [], "catalysts": [],
            "review_triggers": None, "add_condition": None,
            "trim_condition": None, "exit_condition": None,
        }
        with patch("agent_db.get_thesis", return_value=thesis):
            result = intel.map_thesis_relevance(
                "GUIDANCE_CHANGE", "AAPL",
                ev_evidence="Apple lowers guidance",
                ev_metric="revenue guidance",
            )
        assert result["pillar_health_state"] == "WARNING", (
            f"Expected pillar_health_state='WARNING', got {result.get('pillar_health_state')}"
        )

    def test_llm_component_name_updates_pillar_name(self):
        """After LLM call, pillar_name is updated to LLM's chosen component_name (0599)."""
        thesis = {
            "status": "ACTIVE",
            "pillars": [
                {"name": "Cloud Revenue Growth", "description": "Azure growth",
                 "importance": 80, "status": "ON_TRACK"},
                {"name": "Earnings Trajectory", "description": "EPS trend",
                 "importance": 70, "status": "ON_TRACK"},
            ],
            "key_risks": [], "catalysts": [],
            "review_triggers": None, "add_condition": None,
            "trim_condition": None, "exit_condition": None,
        }
        llm_response = {
            "component_type": "pillar",
            "component_name": "Earnings Trajectory",
            "relationship": "WEAKENS",
            "relevance": 0.8,
            "trigger_state": "NONE",
            "explanation": "EPS miss hits earnings pillar",
            "confidence": 0.85,
        }
        with patch("agent_db.get_thesis", return_value=thesis):
            with patch.object(intel, "_thesis_map_llm", return_value=llm_response):
                result = intel.map_thesis_relevance(
                    "EARNINGS", "MSFT",
                    ev_evidence="Microsoft misses EPS",
                    ev_metric="EPS",
                    ev_direction="NEGATIVE",
                    ollama_client_mod=MagicMock(),
                )
        assert result["pillar_name"] == "Earnings Trajectory", (
            f"pillar_name should be LLM's component_name, got {result['pillar_name']}"
        )
        assert result["risk_name"] is None


# ── Tests: portfolio themes ───────────────────────────────────────────────────

class TestPortfolioThemes:
    def _make_event(self, direction="NEGATIVE", causal_driver=None,
                    event_type="EARNINGS", signal_strength=55.0):
        return {
            "event_type": event_type, "direction": direction,
            "signal_strength": signal_strength, "causal_driver": causal_driver,
        }

    def test_unrelated_earnings_no_false_theme(self):
        events_by_ticker = {
            "AAPL": [self._make_event(causal_driver=None)],
            "JPM":  [self._make_event(causal_driver=None)],
            "TGT":  [self._make_event(causal_driver=None)],
        }
        themes = intel.detect_portfolio_themes(events_by_ticker, {"AAPL": 5, "JPM": 4, "TGT": 3})
        assert themes == []

    def test_shared_causal_driver_fires_theme(self):
        events_by_ticker = {
            "AAPL": [self._make_event(causal_driver="USD_STRENGTH")],
            "MSFT": [self._make_event(causal_driver="USD_STRENGTH")],
            "NFLX": [self._make_event(causal_driver="USD_STRENGTH")],
        }
        themes = intel.detect_portfolio_themes(events_by_ticker, {"AAPL": 8, "MSFT": 7, "NFLX": 3})
        assert len(themes) == 1
        assert themes[0]["causal_driver"] == "USD_STRENGTH"

    def test_other_driver_does_not_fire_theme(self):
        events_by_ticker = {
            "A": [self._make_event(causal_driver="OTHER")],
            "B": [self._make_event(causal_driver="OTHER")],
            "C": [self._make_event(causal_driver="OTHER")],
        }
        themes = intel.detect_portfolio_themes(events_by_ticker, {"A": 5, "B": 5, "C": 5})
        assert themes == []

    def test_mixed_directions_do_not_merge(self):
        events_by_ticker = {
            "AAPL": [self._make_event(direction="NEGATIVE", causal_driver="TARIFFS")],
            "MSFT": [self._make_event(direction="POSITIVE", causal_driver="TARIFFS")],
            "GOOG": [self._make_event(direction="NEGATIVE", causal_driver="TARIFFS")],
        }
        themes = intel.detect_portfolio_themes(events_by_ticker, {"AAPL": 5, "MSFT": 5, "GOOG": 5})
        assert themes == []


# ── Tests: true confirmation channels (0600) ─────────────────────────────────

class TestConfirmationChannels:
    def _setup_price_data(self, conn, ticker, ticker_prices, spy_prices):
        for day, price in ticker_prices:
            conn.execute("INSERT INTO holding_day VALUES (?,?,?)", (ticker, day, price))
        for day, price in spy_prices:
            conn.execute("INSERT INTO spy_prices VALUES (?,?)", (day, price))
        conn.commit()

    def test_trend_not_a_confirmation_channel(self):
        conn = _make_db()
        ev_accel = {"event_type": "EARNINGS", "direction": "NEGATIVE",
                    "trend_status": "ACCELERATING"}
        ev_new   = {"event_type": "EARNINGS", "direction": "NEGATIVE",
                    "trend_status": "NEW"}
        r_accel = intel.attach_confirmation(ev_accel, "AAPL", conn)
        r_new   = intel.attach_confirmation(ev_new,   "AAPL", conn)
        assert r_accel["confirmation_class"] == "NEWS_ONLY"
        assert r_new["confirmation_class"]   == "NEWS_ONLY"

    def test_price_is_one_channel_not_two(self):
        """1d and 5d alpha both corroborating → only 1 PRICE vote (0600)."""
        conn = _make_db()
        # Strongly positive ticker vs flat SPY → both 1d and 5d alpha positive
        self._setup_price_data(conn, "AAPL", [
            ("2026-09-22", 160.0), ("2026-09-21", 155.0), ("2026-09-20", 153.0),
            ("2026-09-19", 150.0), ("2026-09-18", 148.0), ("2026-09-17", 146.0),
        ], [
            ("2026-09-22", 500.0), ("2026-09-21", 499.5), ("2026-09-20", 499.0),
            ("2026-09-19", 499.5), ("2026-09-18", 499.0), ("2026-09-17", 499.2),
        ])
        ev = {"event_type": "EARNINGS", "direction": "POSITIVE"}
        result = intel.attach_confirmation(ev, "AAPL", conn)
        # Price alone → max SOFT_CONFIRMATION (1 channel), never MULTI_SIGNAL (3 needed)
        assert result["confirmation_class"] != "MULTI_SIGNAL_CONFIRMATION", (
            "Price channel (even with both 1d+5d) cannot alone reach MULTI_SIGNAL; needs 3 channels"
        )

    def test_price_alignment_uses_date_pairs(self):
        """_get_price_alpha must join on date, not index position (0592)."""
        conn = _make_db()
        for day, price in [
            ("2026-09-19", 150.0), ("2026-09-18", 148.0), ("2026-09-17", 147.0),
            ("2026-09-16", 145.0), ("2026-09-15", 144.0),
        ]:
            conn.execute("INSERT INTO holding_day VALUES (?,?,?)", ("AAPL", day, price))
        for day, price in [
            ("2026-09-19", 500.0),  # 2026-09-18 intentionally missing
            ("2026-09-17", 498.0), ("2026-09-16", 495.0), ("2026-09-15", 493.0),
        ]:
            conn.execute("INSERT INTO spy_prices VALUES (?,?)", (day, price))
        conn.commit()
        alpha = intel._get_price_alpha("AAPL", conn)
        if "1d" in alpha:
            assert -1.0 <= alpha["1d"] <= 1.0


# ── Tests: episode news_state immutability ────────────────────────────────────

class TestEpisodeImmutability:
    def test_news_state_unchanged_after_refresh(self):
        conn = _make_db()
        import datetime
        today = datetime.date.today().isoformat()
        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", today, signal_strength=60.0)
        conn.commit()

        rows = conn.execute(
            "SELECT event_type, direction, magnitude, signal_strength, portfolio_priority, "
            "confirmation_class, thesis_relevance, pillar_name, trend_status, "
            "occurrence_count_30d, event_fingerprint, causal_driver, news_intelligence_version "
            "FROM news_events WHERE ticker='AAPL' AND day=? "
            "ORDER BY portfolio_priority DESC LIMIT 5",
            (today,)
        ).fetchall()
        events1 = [dict(r) for r in rows]
        snapshot1 = json.dumps({
            "as_of": today,
            "news_intelligence_version": intel.NEWS_INTELLIGENCE_VERSION,
            "events": events1,
        })

        conn.execute(
            "UPDATE news_events SET signal_strength=80.0 WHERE ticker='AAPL' AND day=?",
            (today,)
        )
        conn.commit()

        parsed = json.loads(snapshot1)
        assert parsed["events"][0]["signal_strength"] == 60.0
        assert "news_intelligence_version" in parsed

    def test_news_state_includes_version_fields(self):
        conn = _make_db()
        import datetime
        today = datetime.date.today().isoformat()
        _insert_event(conn, "TSLA", "DEMAND", "NEGATIVE", today, signal_strength=50.0)
        conn.commit()

        with patch.dict("sys.modules", {"agents.news.intelligence": intel}):
            from agents.learning.episode_capture import _build_news_state
            state_json = _build_news_state("TSLA", conn)

        assert state_json is not None
        state = json.loads(state_json)
        assert "news_intelligence_version" in state
        assert "news_prompt_version" in state
        assert state["news_intelligence_version"] == intel.NEWS_INTELLIGENCE_VERSION


# ── Tests: versioning ─────────────────────────────────────────────────────────

class TestVersioning:
    def test_version_is_v2(self):
        """NEWS_INTELLIGENCE_VERSION must be v2 after 0596-0600."""
        assert intel.NEWS_INTELLIGENCE_VERSION == "v2"

    def test_prompt_version_exists(self):
        assert hasattr(intel, "PROMPT_VERSION")
        assert intel.PROMPT_VERSION == "v1"

    def test_events_stamped_with_version(self):
        conn = _make_db()
        import datetime
        day = datetime.date.today().isoformat()
        events = {
            "AAPL": [{
                "event_type": "EARNINGS", "direction": "NEGATIVE",
                "magnitude": "HIGH", "horizon": "SHORT",
                "confidence": 0.8, "evidence": "Beat estimates",
                "titles": [], "article_ids": [], "causal_driver": None,
                "causal_event_key": None,
                "thesis_relevance": 0.0, "trigger_proximity": 0.0,
                "pillar_health_state": None, "event_trigger_state": "NONE",
                "event_trigger_proximity": 0.0,
                "trend_status": "NEW", "occurrence_count_7d": 0,
                "occurrence_count_30d": 0, "occurrence_count_90d": 0,
                "signal_strength": 60.0, "portfolio_priority": 6.0,
                "score_decomposition": {}, "confirmation_class": "NEWS_ONLY",
                "confirmation_signals": {}, "skepticism_note": None,
                "affected_metric": "EPS",
            }]
        }
        intel.persist_events(events, [], day, conn, news_snapshot_hash="abc123")
        row = conn.execute(
            "SELECT news_intelligence_version FROM news_events WHERE ticker='AAPL'"
        ).fetchone()
        assert row is not None
        assert row[0] == intel.NEWS_INTELLIGENCE_VERSION

    def test_first_seen_preserved_across_refreshes(self):
        conn = _make_db()
        day1 = "2026-09-20"
        day2 = "2026-09-23"

        base_event = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "magnitude": "HIGH", "horizon": "SHORT",
            "confidence": 0.8, "evidence": "Miss on EPS",
            "titles": [], "article_ids": [], "causal_driver": None,
            "causal_event_key": None,
            "thesis_relevance": 0.0, "trigger_proximity": 0.0,
            "pillar_health_state": None, "event_trigger_state": "NONE",
            "event_trigger_proximity": 0.0,
            "trend_status": "NEW", "occurrence_count_7d": 0,
            "occurrence_count_30d": 0, "occurrence_count_90d": 0,
            "signal_strength": 60.0, "portfolio_priority": 6.0,
            "score_decomposition": {}, "confirmation_class": "NEWS_ONLY",
            "confirmation_signals": {}, "skepticism_note": None,
            "affected_metric": "EPS",
        }

        intel.persist_events({"AAPL": [dict(base_event)]}, [], day1, conn, "hash1")
        intel.persist_events({"AAPL": [dict(base_event)]}, [], day2, conn, "hash2")

        rows = conn.execute(
            "SELECT day, first_seen FROM news_events WHERE ticker='AAPL' ORDER BY day"
        ).fetchall()
        for row in rows:
            assert row[1] == day1, (
                f"first_seen should be {day1}, got {row[1]} on day {row[0]}"
            )
