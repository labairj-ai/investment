"""Tests for agents/learning/episode_capture.py (0327)."""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _make_candidate(ticker="ANET", composite=72, rank=None):
    return {
        "ticker": ticker,
        "company": "Arista Networks",
        "quality_score": 88,
        "pe_ratio": 30.0,
        "p_fcf": 28.0,
        "ev_ebitda": 20.0,
        "gross_margin": 0.62,
        "net_income_margin": 0.30,
        "sga_margin": 0.12,
        "capex_margin": 0.03,
        "market_cap": 60_000_000_000.0,
        "layer_rec": 3,
        "sector": "Technology",
        "industry": "Networking",
        "value_trap_risk": "low",
        "_q": 88.0,
        "_v": 70.0,
        "_pf": 65.0,
        "_c": 60.0,
        "_ec": 55.0,
        "_composite": composite,
    }


def _fetch_all_episodes(db_file):
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM decision_episodes").fetchall()
    conn.close()
    return [dict(r) for r in rows]


class TestCaptureEpisode:
    def test_creates_row(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import capture_candidate_episode

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        ep_id = capture_candidate_episode(run_id=1, candidate=_make_candidate())

        rows = _fetch_all_episodes(mem_db)
        assert len(rows) == 1
        row = rows[0]
        assert row["episode_id"] == ep_id
        assert row["ticker"] == "ANET"
        assert row["selected"] == 0
        assert row["candidate_rank"] is None
        assert row["q_score"] == pytest.approx(88.0)
        assert row["composite_score"] == 72
        assert row["buffett_score"] == 88
        assert row["feature_schema_version"] == "v1"
        assert row["prompt_version"] == "opportunity_hunter_v1"

    def test_captures_fundamentals(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import capture_candidate_episode

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        capture_candidate_episode(run_id=1, candidate=_make_candidate())
        rows = _fetch_all_episodes(mem_db)
        row = rows[0]
        assert row["pe_ratio"] == pytest.approx(30.0)
        assert row["p_fcf"] == pytest.approx(28.0)
        assert row["gross_margin"] == pytest.approx(0.62)
        assert row["sector"] == "Technology"
        assert row["layer_rec"] == 3
        assert row["value_trap_risk"] == "low"

    def test_portfolio_snapshot_stored(self, mem_db, monkeypatch):
        import agent_db
        import json
        from agents.learning.episode_capture import capture_candidate_episode

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        snapshot = {"layer_weights": {"1": 15.0, "3": 22.0}, "held_tickers": ["BRK-B"]}
        capture_candidate_episode(run_id=1, candidate=_make_candidate(), portfolio_snapshot=snapshot)
        rows = _fetch_all_episodes(mem_db)
        stored = json.loads(rows[0]["portfolio_snapshot_json"])
        assert stored["held_tickers"] == ["BRK-B"]

    def test_multiple_candidates(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import capture_candidate_episode

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        ep1 = capture_candidate_episode(run_id=1, candidate=_make_candidate("ANET", 72))
        ep2 = capture_candidate_episode(run_id=1, candidate=_make_candidate("GRMN", 68))
        ep3 = capture_candidate_episode(run_id=1, candidate=_make_candidate("SNA", 64))

        rows = _fetch_all_episodes(mem_db)
        assert len(rows) == 3
        ids = {r["episode_id"] for r in rows}
        assert ep1 in ids and ep2 in ids and ep3 in ids

    def test_failure_is_swallowed(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import capture_candidate_episode

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        # Patch _connect to raise so we can verify the call doesn't propagate
        monkeypatch.setattr(agent_db, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

        ep_id = capture_candidate_episode(run_id=1, candidate=_make_candidate())
        # Returns an episode_id string even when DB fails
        assert isinstance(ep_id, str) and len(ep_id) == 36


class TestUpdateEpisodeRanks:
    def test_sets_ranks(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import (
            capture_candidate_episode,
            update_episode_ranks,
        )

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        ep1 = capture_candidate_episode(run_id=1, candidate=_make_candidate("ANET", 82))
        ep2 = capture_candidate_episode(run_id=1, candidate=_make_candidate("GRMN", 79))
        ep3 = capture_candidate_episode(run_id=1, candidate=_make_candidate("SNA", 75))

        update_episode_ranks([(ep1, 1), (ep2, 2), (ep3, 3)])

        rows = {r["episode_id"]: r for r in _fetch_all_episodes(mem_db)}
        assert rows[ep1]["candidate_rank"] == 1
        assert rows[ep2]["candidate_rank"] == 2
        assert rows[ep3]["candidate_rank"] == 3

    def test_empty_list_is_noop(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import update_episode_ranks

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        update_episode_ranks([])  # should not raise


class TestMarkEpisodeSelected:
    def test_marks_selected(self, mem_db, monkeypatch):
        import agent_db
        from agents.learning.episode_capture import (
            capture_candidate_episode,
            update_episode_ranks,
            mark_episode_selected,
        )

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        ep1 = capture_candidate_episode(run_id=1, candidate=_make_candidate("ANET", 82))
        ep2 = capture_candidate_episode(run_id=1, candidate=_make_candidate("GRMN", 79))

        update_episode_ranks([(ep1, 1), (ep2, 2)])
        mark_episode_selected(ep1, llm_why="Strong quality at reasonable valuation.")

        rows = {r["episode_id"]: r for r in _fetch_all_episodes(mem_db)}
        assert rows[ep1]["selected"] == 1
        assert rows[ep1]["llm_why"] == "Strong quality at reasonable valuation."
        assert rows[ep2]["selected"] == 0

    def test_immutability_of_scored_fields(self, mem_db, monkeypatch):
        """Fundamental fields must not change after capture."""
        import agent_db
        from agents.learning.episode_capture import (
            capture_candidate_episode,
            mark_episode_selected,
        )

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        ep = capture_candidate_episode(run_id=1, candidate=_make_candidate("ANET", 72))
        mark_episode_selected(ep, llm_why="why text")

        rows = _fetch_all_episodes(mem_db)
        assert len(rows) == 1
        row = rows[0]
        # Scored fields unchanged
        assert row["q_score"] == pytest.approx(88.0)
        assert row["composite_score"] == 72
        assert row["feature_schema_version"] == "v1"


class TestOpportunityAgentWiring:
    """Verify that run_opportunity_hunter populates decision_episodes."""

    def test_episodes_created_per_scored_candidate(self, mem_db, monkeypatch, sample_snapshot):
        import agent_db
        from agents import opportunity_agent
        from agents.contracts import AgentContext

        monkeypatch.setattr(agent_db, "DB_PATH", mem_db)
        monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(mem_db))

        # Stub buffett winners
        winners = [
            {"ticker": "ANET", "company": "Arista", "quality_score": 88,
             "pe_ratio": 30.0, "p_fcf": 28.0, "ev_ebitda": 20.0,
             "gross_margin": 0.62, "net_income_margin": 0.30, "sga_margin": 0.12,
             "capex_margin": 0.03, "market_cap": 60e9, "layer_rec": 3,
             "sector": "Technology", "industry": "Networking",
             "value_trap_risk": "low", "ai_analysis": None, "scanned_at": "2026-09-01",
             "dividend_yield": None, "exchange": "NYSE", "ai_layer_rank": None,
             "ai_layer_rank_at": None, "country": "US",
             "price": 300.0, "last_quarter_date": "2026-06-30",
             "value_trap_flags": None, "layer_reason": None},
            {"ticker": "GRMN", "company": "Garmin", "quality_score": 80,
             "pe_ratio": 22.0, "p_fcf": 20.0, "ev_ebitda": 14.0,
             "gross_margin": 0.58, "net_income_margin": 0.20, "sga_margin": 0.15,
             "capex_margin": 0.04, "market_cap": 25e9, "layer_rec": 2,
             "sector": "Consumer", "industry": "Electronics",
             "value_trap_risk": "low", "ai_analysis": None, "scanned_at": "2026-09-01",
             "dividend_yield": None, "exchange": "NASDAQ", "ai_layer_rank": None,
             "ai_layer_rank_at": None, "country": "US",
             "price": 130.0, "last_quarter_date": "2026-06-30",
             "value_trap_flags": None, "layer_reason": None},
        ]
        monkeypatch.setattr(opportunity_agent, "_get_buffett_winners", lambda: winners)
        monkeypatch.setattr(opportunity_agent, "_get_manual_candidates", lambda: [])
        monkeypatch.setattr(opportunity_agent, "_get_current_tickers", lambda: set())
        monkeypatch.setattr(opportunity_agent, "_get_layer_weights", lambda: {1: 0, 2: 10, 3: 15})
        monkeypatch.setattr(opportunity_agent, "_get_holding_sectors", lambda h: {})
        # Stub LLM to pick ANET
        monkeypatch.setattr(
            opportunity_agent, "_llm_select",
            lambda cands, lw: {"action": "RESEARCH", "ticker": "ANET",
                                "why": "best quality", "portfolio_rationale": "fills layer 3",
                                "main_risk": "competition", "no_action_case": "overvalued"},
        )

        ctx = AgentContext(run_id=42, snapshot=sample_snapshot, trigger_type="scheduled")
        opportunity_agent.run_opportunity_hunter(ctx)

        rows = _fetch_all_episodes(mem_db)
        assert len(rows) == 2
        tickers = {r["ticker"] for r in rows}
        assert tickers == {"ANET", "GRMN"}

        anet = next(r for r in rows if r["ticker"] == "ANET")
        grmn = next(r for r in rows if r["ticker"] == "GRMN")

        assert anet["selected"] == 1
        assert grmn["selected"] == 0
        assert anet["llm_why"] == "best quality"
        # Ranks must be assigned and distinct (actual values depend on computed scores)
        assert anet["candidate_rank"] is not None
        assert grmn["candidate_rank"] is not None
        assert anet["candidate_rank"] != grmn["candidate_rank"]
        assert anet["run_id"] == 42


# ---------------------------------------------------------------------------
# Helper (mirrors conftest._make_conn — can't import conftest directly)
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3

def _make_conn(db_file):
    conn = _sqlite3.connect(str(db_file), timeout=10)
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
