"""Shared test fixtures — in-memory DB, sample snapshots, mocked LLM."""
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make the project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Mock LLM so no real network calls happen in tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """Replace ollama_client.generate_structured with a deterministic stub."""
    import ollama_client
    monkeypatch.setattr(
        ollama_client, "generate_structured",
        lambda prompt, schema, **kw: {k: ("stub" if isinstance(v, str) else v) for k, v in schema.items()},
    )


# ---------------------------------------------------------------------------
# In-memory SQLite DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    """Patch agent_db.DB_PATH to point to a fresh in-memory-style temp DB."""
    db_file = tmp_path / "test_investment.db"
    db_file.touch()  # migrate() guards on DB_PATH.exists(); create first
    import agent_db
    monkeypatch.setattr(agent_db, "DB_PATH", db_file)
    monkeypatch.setattr(agent_db, "_connect", lambda: _make_conn(db_file))
    agent_db.migrate()
    return db_file


def _make_conn(db_file: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_file), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Sample snapshot factory
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_snapshot():
    from agents.contracts import HoldingSnapshot, PortfolioSnapshot
    return PortfolioSnapshot(
        date="2026-09-06",
        total_value=100_000.0,
        holdings=[
            HoldingSnapshot("ANET", layer=3, shares=120, avg_cost=130.0,
                            current_price=180.0, market_value=21_600.0, weight_pct=21.6),
            HoldingSnapshot("BRK-B", layer=1, shares=50, avg_cost=300.0,
                            current_price=350.0, market_value=17_500.0, weight_pct=17.5),
            HoldingSnapshot("SCHD", layer=2, shares=200, avg_cost=75.0,
                            current_price=80.0, market_value=16_000.0, weight_pct=16.0),
        ],
        layer_weights={1: 17.5, 2: 16.0, 3: 21.6},
        macro_scores={},
        generated_at=1_700_000_000.0,
        price_as_of="2026-09-05",
        portfolio_as_of="2026-09-05",
    )
