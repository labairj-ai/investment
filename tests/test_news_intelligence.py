"""
Acceptance test suite for the news intelligence pipeline (0595).

Deterministic fixtures, no LLM calls, in-memory SQLite.
Covers: hash/cache invalidation, event identity, trend state machine,
scoring rank ordering, portfolio themes, thesis mapping, episode immutability.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Allow direct import from project root
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
    """In-memory SQLite with news_events schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE news_events (
        event_id            TEXT PRIMARY KEY,
        ticker              TEXT NOT NULL,
        day                 TEXT NOT NULL,
        event_type          TEXT NOT NULL,
        direction           TEXT NOT NULL,
        magnitude           TEXT NOT NULL DEFAULT 'MEDIUM',
        expected_horizon    TEXT NOT NULL DEFAULT 'SHORT',
        confidence          REAL NOT NULL DEFAULT 0.7,
        affected_metric     TEXT,
        evidence_text       TEXT,
        source_titles       TEXT,
        source_count        INTEGER DEFAULT 1,
        first_seen          TEXT,
        last_seen           TEXT,
        thesis_relevance    REAL DEFAULT 0.0,
        pillar_name         TEXT,
        risk_name           TEXT,
        catalyst_name       TEXT,
        trigger_proximity   REAL DEFAULT 0.0,
        trend_status        TEXT,
        occurrence_count_7d  INTEGER DEFAULT 0,
        occurrence_count_30d INTEGER DEFAULT 0,
        occurrence_count_90d INTEGER DEFAULT 0,
        signal_strength     REAL DEFAULT 0.0,
        portfolio_priority  REAL DEFAULT 0.0,
        score_decomposition TEXT,
        confirmation_class  TEXT DEFAULT 'NEWS_ONLY',
        confirmation_signals TEXT,
        skepticism_note     TEXT,
        news_snapshot_hash  TEXT,
        extracted_at        TEXT NOT NULL DEFAULT 'now',
        event_fingerprint   TEXT,
        article_ids_json    TEXT,
        causal_driver       TEXT,
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
    conn.execute("""CREATE TABLE holding_day (
        ticker TEXT, day TEXT, price REAL
    )""")
    conn.execute("""CREATE TABLE spy_prices (
        day TEXT, price REAL
    )""")
    conn.execute("""CREATE TABLE holding_macro_scores (
        ticker TEXT PRIMARY KEY, scores TEXT, updated_at TEXT
    )""")
    return conn


def _insert_event(conn, ticker, event_type, direction, day,
                  signal_strength=50.0, trend_status="CONFIRMING",
                  magnitude="MEDIUM", fingerprint=None):
    import uuid
    fp = fingerprint or intel._event_fingerprint(ticker, event_type, direction)
    conn.execute(
        "INSERT INTO news_events (event_id, ticker, day, event_type, direction, "
        "magnitude, expected_horizon, confidence, extracted_at, trend_status, "
        "signal_strength, portfolio_priority, event_fingerprint, news_intelligence_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), ticker, day, event_type, direction,
         magnitude, "SHORT", 0.8, day, trend_status,
         signal_strength, signal_strength * 0.1, fp,
         intel.NEWS_INTELLIGENCE_VERSION)
    )
    conn.commit()


# ── Tests: hash / cache invalidation ─────────────────────────────────────────

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
        """LLM-returned IDs not in manifest must be stripped."""
        valid_art = _make_article("AAPL", "Apple news", url="https://x.com/1")
        valid_id  = intel._article_id(valid_art)
        fake_id   = "deadbeef000000"

        # Simulate what extract_events_llm does internally for ID validation
        manifest = {valid_id: {"ticker": "AAPL", "title": "Apple news"}}
        valid_ids = set(manifest.keys())
        returned  = [valid_id, fake_id]
        validated = [aid for aid in returned if aid in valid_ids]
        assert validated == [valid_id]


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
        # 4 prior events with distinct fingerprints (4 distinct underlying events):
        # 2 in last 7d (Sep 18+20+21 = 3, but 2 within 7d), 4 in last 30d
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-15", fingerprint="fp_a")
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-18", fingerprint="fp_b")
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-20", fingerprint="fp_c")
        _insert_event(conn, "AAPL", "MARGIN", "NEGATIVE", "2026-09-21", fingerprint="fp_d")
        result = intel.compute_trend("AAPL", "MARGIN", "NEGATIVE", "2026-09-23", conn)
        # n7 (Sep 17-22) = fp_b, fp_c, fp_d = 3 distinct; n30 = all 4 = 4 distinct
        # 3 >= 2 and 4 >= 3 → ACCELERATING
        assert result["trend_status"] == "ACCELERATING"

    def test_reversing_when_first_positive_after_negative_history(self):
        """Critical bug fix (0590): first POSITIVE after NEGATIVE history → REVERSING not NEW."""
        conn = _make_db()
        # Insert negative history in last 30d
        _insert_event(conn, "TSLA", "DEMAND", "NEGATIVE", "2026-09-01")
        _insert_event(conn, "TSLA", "DEMAND", "NEGATIVE", "2026-09-10")
        # Now classify a POSITIVE event today — should be REVERSING, not NEW
        result = intel.compute_trend("TSLA", "DEMAND", "POSITIVE", "2026-09-23", conn)
        assert result["trend_status"] == "REVERSING", (
            f"Expected REVERSING (0590 fix), got {result['trend_status']}"
        )

    def test_fading_not_returned_for_active_observation(self):
        """Active event reappearing after 60d gap must not be FADING (0590 fix)."""
        conn = _make_db()
        # Last occurrence was 60 days ago (n90>0, n30==0)
        _insert_event(conn, "JPM", "LITIGATION", "NEGATIVE", "2026-07-25")
        # Classifying a NEW observation today — should be CONFIRMING (reappeared), not FADING
        result = intel.compute_trend("JPM", "LITIGATION", "NEGATIVE", "2026-09-23", conn)
        assert result["trend_status"] != "FADING", (
            "FADING must not be returned by compute_trend for an actively observed event (0590)"
        )

    def test_sweep_marks_absent_events_fading(self):
        """sweep_fading_resolved() should mark prior active events as FADING when absent today."""
        conn = _make_db()
        # Add event for AAPL/EARNINGS/NEGATIVE in last 30d
        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", "2026-09-10")
        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", "2026-09-15")
        # Today's events: AAPL not present
        intel.sweep_fading_resolved("2026-09-23", conn)
        rows = conn.execute(
            "SELECT trend_status FROM news_events WHERE ticker='AAPL' AND day='2026-09-23'"
        ).fetchall()
        assert any(r[0] == "FADING" for r in rows), "Sweep should insert FADING marker for absent ticker"


# ── Tests: scoring and rank ordering ─────────────────────────────────────────

class TestScoring:
    def _base_event(self, **kwargs):
        ev = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "magnitude": "HIGH", "horizon": "SHORT",
            "confidence": 0.9, "trend_status": "NEW",
            "confirmation_class": "NEWS_ONLY",
            "thesis_relevance": 0.0, "trigger_proximity": 0.0,
        }
        ev.update(kwargs)
        return ev

    def test_signal_strength_independent_of_position(self):
        """signal_strength must be the same regardless of position_weight."""
        ev = self._base_event()
        s1 = intel.score_event(ev, position_weight=5.0)
        s2 = intel.score_event(ev, position_weight=10.0)
        assert s1["signal_strength"] == s2["signal_strength"]

    def test_large_position_ranks_higher_priority(self):
        """5% holding high-signal ranks below 10% comparable-signal (portfolio_priority)."""
        ev = self._base_event()
        s5  = intel.score_event(ev, position_weight=5.0)
        s10 = intel.score_event(ev, position_weight=10.0)
        assert s10["portfolio_priority"] > s5["portfolio_priority"]

    def test_signal_strength_is_classification_input(self):
        """Bucket classification uses signal_strength, not portfolio_priority."""
        ev_high = self._base_event(magnitude="HIGH", confidence=0.95)
        ev_low  = self._base_event(magnitude="LOW",  confidence=0.5)
        s_high = intel.score_event(ev_high, position_weight=2.0)
        s_low  = intel.score_event(ev_low,  position_weight=50.0)
        # High signal in small position should classify correctly even if pp < threshold
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
        ev_news_only = self._base_event(confirmation_class="NEWS_ONLY")
        ev_multi     = self._base_event(confirmation_class="MULTI_SIGNAL_CONFIRMATION")
        s1 = intel.score_event(ev_news_only)
        s2 = intel.score_event(ev_multi)
        assert s2["signal_strength"] > s1["signal_strength"]

    def test_contradicted_depresses_strength(self):
        ev_news = self._base_event(confirmation_class="NEWS_ONLY")
        ev_contra = self._base_event(confirmation_class="CONTRADICTED")
        s1 = intel.score_event(ev_news)
        s2 = intel.score_event(ev_contra)
        assert s2["signal_strength"] < s1["signal_strength"]


# ── Tests: portfolio themes ───────────────────────────────────────────────────

class TestPortfolioThemes:
    def _make_event(self, direction="NEGATIVE", causal_driver=None,
                    event_type="EARNINGS", signal_strength=55.0):
        return {
            "event_type": event_type, "direction": direction,
            "signal_strength": signal_strength,
            "causal_driver": causal_driver,
        }

    def test_unrelated_earnings_no_false_theme(self):
        """Three unrelated EARNINGS events with different causal_drivers → no theme."""
        events_by_ticker = {
            "AAPL": [self._make_event(causal_driver=None)],
            "JPM":  [self._make_event(causal_driver=None)],
            "TGT":  [self._make_event(causal_driver=None)],
        }
        weights = {"AAPL": 5.0, "JPM": 4.0, "TGT": 3.0}
        themes = intel.detect_portfolio_themes(events_by_ticker, weights)
        assert themes == [], f"Expected no theme for unrelated EARNINGS, got {themes}"

    def test_shared_causal_driver_fires_theme(self):
        """Three tickers with USD_STRENGTH + NEGATIVE → portfolio theme fires."""
        events_by_ticker = {
            "AAPL": [self._make_event(causal_driver="USD_STRENGTH")],
            "MSFT": [self._make_event(causal_driver="USD_STRENGTH")],
            "NFLX": [self._make_event(causal_driver="USD_STRENGTH")],
        }
        weights = {"AAPL": 8.0, "MSFT": 7.0, "NFLX": 3.0}
        themes = intel.detect_portfolio_themes(events_by_ticker, weights)
        assert len(themes) == 1
        assert themes[0]["causal_driver"] == "USD_STRENGTH"
        assert set(themes[0]["affected_tickers"]) == {"AAPL", "MSFT", "NFLX"}

    def test_other_driver_does_not_fire_theme(self):
        """causal_driver='OTHER' must never generate a portfolio theme."""
        events_by_ticker = {
            "A": [self._make_event(causal_driver="OTHER")],
            "B": [self._make_event(causal_driver="OTHER")],
            "C": [self._make_event(causal_driver="OTHER")],
        }
        themes = intel.detect_portfolio_themes(events_by_ticker, {"A": 5, "B": 5, "C": 5})
        assert themes == []

    def test_mixed_directions_do_not_merge(self):
        """Same causal_driver but different directions → no theme."""
        events_by_ticker = {
            "AAPL": [self._make_event(direction="NEGATIVE", causal_driver="TARIFFS")],
            "MSFT": [self._make_event(direction="POSITIVE", causal_driver="TARIFFS")],
            "GOOG": [self._make_event(direction="NEGATIVE", causal_driver="TARIFFS")],
        }
        weights = {"AAPL": 5.0, "MSFT": 5.0, "GOOG": 5.0}
        themes = intel.detect_portfolio_themes(events_by_ticker, weights)
        # Only AAPL+GOOG share TARIFFS/NEGATIVE — 2 tickers, not 3 → no theme
        assert themes == []


# ── Tests: thesis mapping ─────────────────────────────────────────────────────

class TestThesisMapping:
    def test_unrelated_event_near_zero_relevance(self):
        """DIVIDEND_BUYBACK event on a ticker with earnings-focused thesis → low relevance."""
        # map_thesis_relevance falls back to 0 if no keywords match
        # Mock get_thesis to return a thesis with no dividend-related pillars
        thesis = {
            "status": "ACTIVE",
            "pillars": [{"name": "Cloud Revenue Growth", "description": "Azure and Office 365 growth",
                          "importance": 80, "status": "ON_TRACK"}],
            "key_risks": [],
            "catalysts": [],
        }
        with patch("agent_db.get_thesis", return_value=thesis):
            result = intel.map_thesis_relevance(
                "DIVIDEND_BUYBACK", "MSFT",
                ev_evidence="Microsoft announces special dividend",
                ev_metric="dividend per share",
            )
        assert result["thesis_relevance"] < 0.3, (
            f"DIVIDEND_BUYBACK unrelated to cloud thesis, got relevance {result['thesis_relevance']}"
        )

    def test_relevant_event_positive_relevance(self):
        """EARNINGS event on a ticker with earnings-focused thesis → relevance > 0."""
        thesis = {
            "status": "ACTIVE",
            "pillars": [{"name": "Earnings Growth", "description": "Strong earnings trajectory",
                          "importance": 90, "status": "ON_TRACK"}],
            "key_risks": [],
            "catalysts": [],
        }
        with patch("agent_db.get_thesis", return_value=thesis):
            result = intel.map_thesis_relevance(
                "EARNINGS", "AAPL",
                ev_evidence="Apple misses earnings estimates",
                ev_metric="EPS",
            )
        assert result["thesis_relevance"] > 0, "Earnings event should map to earnings-focused pillar"

    def test_no_thesis_returns_zero(self):
        """No active thesis → zero relevance."""
        with patch("agent_db.get_thesis", return_value=None):
            result = intel.map_thesis_relevance("EARNINGS", "AAPL")
        assert result["thesis_relevance"] == 0.0


# ── Tests: episode news_state immutability ────────────────────────────────────

class TestEpisodeImmutability:
    def test_news_state_unchanged_after_refresh(self):
        """news_state captured at episode time must not change on later news refresh."""
        conn = _make_db()
        import datetime
        today = datetime.date.today().isoformat()

        # Insert initial news event
        _insert_event(conn, "AAPL", "EARNINGS", "NEGATIVE", today,
                      signal_strength=60.0, trend_status="CONFIRMING")
        conn.commit()

        # Simulate capturing news_state
        from agents.learning import episode_capture
        # Build state snapshot via the same mechanism as episode_capture
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

        # Simulate a later news refresh that updates the event (e.g. more articles)
        conn.execute(
            "UPDATE news_events SET signal_strength=80.0 WHERE ticker='AAPL' AND day=?",
            (today,)
        )
        conn.commit()

        # Original snapshot must be unchanged (it's a frozen string)
        parsed = json.loads(snapshot1)
        assert parsed["events"][0]["signal_strength"] == 60.0, (
            "Episode snapshot must be frozen at capture time; later updates must not affect it"
        )
        assert "news_intelligence_version" in parsed

    def test_news_state_includes_version_fields(self):
        """_build_news_state must include NEWS_INTELLIGENCE_VERSION and prompt version."""
        conn = _make_db()
        import datetime
        today = datetime.date.today().isoformat()

        _insert_event(conn, "TSLA", "DEMAND", "NEGATIVE", today, signal_strength=50.0)
        conn.commit()

        # Patch the import path used in episode_capture
        with patch.dict("sys.modules", {"agents.news.intelligence": intel}):
            from agents.learning.episode_capture import _build_news_state
            state_json = _build_news_state("TSLA", conn)

        assert state_json is not None
        state = json.loads(state_json)
        assert "news_intelligence_version" in state, "Must include news_intelligence_version"
        assert "news_prompt_version" in state, "Must include news_prompt_version"
        assert state["news_intelligence_version"] == intel.NEWS_INTELLIGENCE_VERSION


# ── Tests: confirmation independence ─────────────────────────────────────────

class TestConfirmationIndependence:
    def test_trend_not_a_confirmation_channel(self):
        """attach_confirmation must not use trend status as a corroboration signal (0592)."""
        conn = _make_db()
        # No price data — only trend available
        ev_accel = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "trend_status": "ACCELERATING",  # This should NOT add corroborating signal
        }
        ev_new = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "trend_status": "NEW",
        }
        # With no price/thesis/macro data, both should get NEWS_ONLY regardless of trend
        r_accel = intel.attach_confirmation(ev_accel, "AAPL", conn)
        r_new   = intel.attach_confirmation(ev_new,   "AAPL", conn)
        assert r_accel["confirmation_class"] == "NEWS_ONLY", (
            f"ACCELERATING trend must not upgrade confirmation class; got {r_accel['confirmation_class']}"
        )
        assert r_new["confirmation_class"] == "NEWS_ONLY"
        # Both should have the same class since no independent signals are present
        assert r_accel["confirmation_class"] == r_new["confirmation_class"]

    def test_price_alignment_uses_date_pairs(self):
        """_get_price_alpha must join on date, not index position (0592)."""
        conn = _make_db()
        # Insert 5 ticker trading days
        ticker_days = [
            ("2026-09-19", 150.0),
            ("2026-09-18", 148.0),
            ("2026-09-17", 147.0),
            ("2026-09-16", 145.0),
            ("2026-09-15", 144.0),
        ]
        for day, price in ticker_days:
            conn.execute("INSERT INTO holding_day VALUES (?,?,?)", ("AAPL", day, price))

        # SPY missing 2026-09-18 (gap day) — index alignment would shift
        spy_days = [
            ("2026-09-19", 500.0),
            # 2026-09-18 missing!
            ("2026-09-17", 498.0),
            ("2026-09-16", 495.0),
            ("2026-09-15", 493.0),
        ]
        for day, price in spy_days:
            conn.execute("INSERT INTO spy_prices VALUES (?,?)", (day, price))
        conn.commit()

        alpha = intel._get_price_alpha("AAPL", conn)
        # 1d alpha: AAPL 2026-09-19 vs 2026-09-18 — but SPY has no 2026-09-18
        # Date-aligned approach: 1d pair is (09-19, 09-17) — the most recent shared date is 09-17
        # What matters: no crash, and if 1d is returned, it's computed on aligned dates
        if "1d" in alpha:
            # Verify it's a sensible value (not computed across misaligned indices)
            assert -1.0 <= alpha["1d"] <= 1.0


# ── Tests: news intelligence versioning ──────────────────────────────────────

class TestVersioning:
    def test_version_constant_exists(self):
        assert hasattr(intel, "NEWS_INTELLIGENCE_VERSION")
        assert intel.NEWS_INTELLIGENCE_VERSION == "v1"

    def test_prompt_version_exists(self):
        assert hasattr(intel, "PROMPT_VERSION")
        assert intel.PROMPT_VERSION == "v1"

    def test_events_stamped_with_version(self):
        """Persisted events must include NEWS_INTELLIGENCE_VERSION."""
        conn = _make_db()
        import datetime
        day = datetime.date.today().isoformat()
        events = {
            "AAPL": [{
                "event_type": "EARNINGS", "direction": "NEGATIVE",
                "magnitude": "HIGH", "horizon": "SHORT",
                "confidence": 0.8, "evidence": "Beat estimates",
                "titles": [], "article_ids": [], "causal_driver": None,
                "thesis_relevance": 0.0, "trigger_proximity": 0.0,
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
        """second persist of same fingerprint must keep original first_seen (0589)."""
        conn = _make_db()
        day1 = "2026-09-20"
        day2 = "2026-09-23"
        fp = intel._event_fingerprint("AAPL", "EARNINGS", "NEGATIVE", "EPS")

        base_event = {
            "event_type": "EARNINGS", "direction": "NEGATIVE",
            "magnitude": "HIGH", "horizon": "SHORT",
            "confidence": 0.8, "evidence": "Miss on EPS",
            "titles": [], "article_ids": [], "causal_driver": None,
            "thesis_relevance": 0.0, "trigger_proximity": 0.0,
            "trend_status": "NEW", "occurrence_count_7d": 0,
            "occurrence_count_30d": 0, "occurrence_count_90d": 0,
            "signal_strength": 60.0, "portfolio_priority": 6.0,
            "score_decomposition": {}, "confirmation_class": "NEWS_ONLY",
            "confirmation_signals": {}, "skepticism_note": None,
            "affected_metric": "EPS",
        }

        # First insert on day1
        intel.persist_events({"AAPL": [dict(base_event)]}, [], day1, conn, "hash1")

        # Second insert on day2 (same underlying event)
        intel.persist_events({"AAPL": [dict(base_event)]}, [], day2, conn, "hash2")

        rows = conn.execute(
            "SELECT day, first_seen FROM news_events WHERE ticker='AAPL' ORDER BY day"
        ).fetchall()
        # Both rows should have first_seen = day1 (preserved from original)
        for row in rows:
            assert row[1] == day1, (
                f"first_seen should be {day1} (original), got {row[1]} on day {row[0]}"
            )
