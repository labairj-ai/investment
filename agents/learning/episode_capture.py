"""Decision Episode capture layer (0327).

Stores an immutable feature snapshot for every scored candidate in the
Opportunity Hunter before sorting or thresholding. These rows are the
training corpus for the future Strategy Learning Loop.

Call order from opportunity_agent.run_opportunity_hunter():
  1. capture_candidate_episode(run_id, candidate) → episode_id
     Called for every scored candidate, before sort.
  2. update_episode_ranks([(episode_id, rank), ...])
     Called once after scored list is sorted (rank 1 = best composite).
  3. mark_episode_selected(episode_id, llm_why=...)
     Called once after the LLM or fallback picks the winner.

Rows are append-only after capture. Only candidate_rank, selected, llm_why,
and llm_conviction are updated after initial insert.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import agent_db

_FEATURE_SCHEMA_VERSION = "v1"


def _build_macro_snapshot(ticker: str, conn, captured_at=None) -> str:
    """Freeze accepted macro context using the episode's connection and timestamp."""
    from .macro_provenance import snapshot
    try:
        return json.dumps(snapshot(ticker, conn, time.time() if captured_at is None else captured_at))
    except Exception as exc:
        return json.dumps({"macro_supported": False, "coverage_state": "provenance_unavailable",
                           "usable_dimensions": [], "reason": str(exc)})


def _build_news_state(ticker: str, conn) -> Optional[str]:
    """Freeze today's news intelligence state for the ticker (0586+0594, observe-only)."""
    try:
        import datetime
        from agents.news.intelligence import NEWS_INTELLIGENCE_VERSION, PROMPT_VERSION as _NP_VER
        today = datetime.date.today().isoformat()
        rows = conn.execute(
            "SELECT event_type, direction, magnitude, signal_strength, portfolio_priority, "
            "confirmation_class, thesis_relevance, pillar_name, trend_status, "
            "occurrence_count_30d, event_fingerprint, causal_driver, news_intelligence_version, "
            "news_snapshot_hash "
            "FROM news_events WHERE ticker=? AND day=? ORDER BY portfolio_priority DESC LIMIT 5",
            (ticker, today),
        ).fetchall()
        if not rows:
            return None
        events = [dict(r) for r in rows]
        fingerprints = [e.get("event_fingerprint") for e in events if e.get("event_fingerprint")]
        # 0601d: include news_snapshot_hash to close the invariant:
        # summaries hash == events hash == episode hash
        snapshot_hash = events[0].get("news_snapshot_hash") if events else None
        # 0610: resolve snapshot_id/captured_at from news_snapshots via hash join.
        # Avoids the race where persist_events() writes news_events before the
        # news_summaries row is updated — episode always reads the atomic provenance table.
        snapshot_id = None
        snapshot_captured_at = None
        if snapshot_hash:
            try:
                snap_row = conn.execute(
                    "SELECT snapshot_id, captured_at FROM news_snapshots WHERE snapshot_hash=?",
                    (snapshot_hash,)
                ).fetchone()
                if snap_row:
                    snapshot_id = snap_row[0]
                    snapshot_captured_at = snap_row[1]
            except Exception:
                pass
        return json.dumps({
            "as_of":                     today,
            "news_intelligence_version":  NEWS_INTELLIGENCE_VERSION,
            "news_prompt_version":        _NP_VER,
            "news_snapshot_hash":         snapshot_hash,
            "snapshot_id":               snapshot_id,
            "snapshot_captured_at":      snapshot_captured_at,
            "events":                    events,
            "event_fingerprints":         fingerprints,
            "top_signal_strength":       max(e.get("signal_strength") or 0 for e in events),
            "top_confirmation":          events[0].get("confirmation_class") if events else None,
            "has_thesis_event":          any(e.get("thesis_relevance", 0) > 0.3 for e in events),
            "event_types":               list({e["event_type"] for e in events}),
        })
    except Exception:
        return None


def capture_candidate_episode(
    run_id: int,
    candidate: dict,
    portfolio_snapshot: dict | None = None,
    captured_at: float | None = None,
    macro_epoch: str | None = None,
) -> str:
    """Insert one immutable episode row for a scored candidate.

    Returns the new episode_id. Failures are logged and swallowed so
    a DB error never interrupts the main recommendation flow.
    """
    episode_id = str(uuid.uuid4())
    captured_at = time.time() if captured_at is None else captured_at
    base_score = candidate.get("_composite")  # 0331: explicit base score before any challenger
    try:
        snapshot_json = json.dumps(portfolio_snapshot) if portfolio_snapshot else None
        conn = agent_db._connect()
        conn.execute(
            """
            INSERT OR IGNORE INTO decision_episodes (
                episode_id, run_id, ticker, captured_at,
                candidate_rank, selected,
                q_score, v_score, pf_score, c_score, ec_score, composite_score,
                buffett_score, pe_ratio, p_fcf, ev_ebitda,
                gross_margin, net_income_margin, sga_margin, capex_margin,
                market_cap, layer_rec, sector, industry, value_trap_risk,
                llm_model, prompt_version, feature_schema_version,
                portfolio_snapshot_json, base_score, code_commit_sha
            ) VALUES (
                ?,?,?,?,
                NULL,0,
                ?,?,?,?,?,?,
                ?,?,?,?,
                ?,?,?,?,
                ?,?,?,?,?,
                ?,?,?,
                ?,?,?
            )
            """,
            (
                episode_id, run_id, candidate["ticker"], captured_at,
                candidate.get("_q"), candidate.get("_v"),
                candidate.get("_pf"), candidate.get("_c"),
                candidate.get("_ec"), candidate.get("_composite"),
                candidate.get("quality_score"), candidate.get("pe_ratio"),
                candidate.get("p_fcf"), candidate.get("ev_ebitda"),
                candidate.get("gross_margin"), candidate.get("net_income_margin"),
                candidate.get("sga_margin"), candidate.get("capex_margin"),
                candidate.get("market_cap"), candidate.get("layer_rec"),
                candidate.get("sector"), candidate.get("industry"),
                candidate.get("value_trap_risk"),
                "mlx-community/Qwen3.6-35B-A3B-4bit",
                "opportunity_hunter_v1",
                _FEATURE_SCHEMA_VERSION,
                snapshot_json, base_score, agent_db.CODE_COMMIT_SHA,
            ),
        )
        # Attach macro snapshot read-only (0494) — never influences scoring/ranking
        try:
            macro_snap_json = _build_macro_snapshot(candidate["ticker"], conn, captured_at)
            conn.execute(
                "UPDATE decision_episodes SET macro_snapshot=? "
                "WHERE episode_id=? AND macro_snapshot IS NULL",
                (macro_snap_json, episode_id),
            )
            ms = json.loads(macro_snap_json)
            conn.execute(
                """UPDATE decision_episodes SET macro_acceptance_record_id=?,
                   macro_scorer_contract_hash=?, macro_config_version=?,
                   macro_score_timestamp=?, macro_prompt_hash=?, macro_evidence_hash=?,
                   macro_usable_dimensions=?, macro_coverage_state=?, macro_epoch=?
                   WHERE episode_id=?""",
                (ms.get("macro_validation_record_id"), ms.get("scorer_contract_hash"),
                 ms.get("macro_config_version"), ms.get("scored_at"), ms.get("prompt_hash"),
                 ms.get("evidence_hash"), json.dumps(ms.get("usable_dimensions", [])),
                 ms.get("coverage_state"), macro_epoch, episode_id),
            )
        except Exception as snap_e:
            print(f"[episode_capture] WARNING: macro_snapshot attachment failed for "
                  f"{candidate.get('ticker')}: {snap_e}")
        # Attach news intelligence state (0586 — observe-only, never influences scoring)
        try:
            news_state_json = _build_news_state(candidate["ticker"], conn)
            if news_state_json:
                conn.execute(
                    "UPDATE decision_episodes SET news_state=? WHERE episode_id=? AND news_state IS NULL",
                    (news_state_json, episode_id),
                )
        except Exception:
            pass
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to capture episode for "
              f"{candidate.get('ticker')}: {e}")
    return episode_id


def update_episode_ranks(episodes: list[tuple[str, int]]) -> None:
    """Set candidate_rank on each episode after the scored list is sorted.

    episodes: [(episode_id, rank), ...] where rank 1 = highest composite.
    """
    if not episodes:
        return
    try:
        conn = agent_db._connect()
        for episode_id, rank in episodes:
            conn.execute(
                "UPDATE decision_episodes SET candidate_rank=? WHERE episode_id=?",
                (rank, episode_id),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to update episode ranks: {e}")


def mark_episode_selected(
    episode_id: str,
    llm_why: str | None = None,
    llm_conviction: int | None = None,
    challenger_score: float | None = None,
    challenger_model_version: str | None = None,
) -> None:
    """Mark the winner episode as selected=1 and store LLM rationale and challenger info."""
    try:
        conn = agent_db._connect()
        conn.execute(
            """UPDATE decision_episodes
               SET selected=1, llm_why=?, llm_conviction=?,
                   challenger_score=?, challenger_model_version=?
               WHERE episode_id=?""",
            (llm_why, llm_conviction, challenger_score, challenger_model_version, episode_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to mark episode selected: {e}")


def update_episode_challenger_info(
    episode_id: str,
    challenger_score: float | None,
    challenger_model_version: str | None,
) -> None:
    """Update challenger score and model version on any episode after the challenger runs."""
    try:
        conn = agent_db._connect()
        conn.execute(
            """UPDATE decision_episodes
               SET challenger_score=?, challenger_model_version=?
               WHERE episode_id=?""",
            (challenger_score, challenger_model_version, episode_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to update challenger info: {e}")
