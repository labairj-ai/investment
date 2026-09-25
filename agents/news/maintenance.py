"""
Daily news event-state maintenance sweep (0605).
No dependency on portfolio_ai, ollama_client, or news_fetcher.
Callable from systemd or from portfolio_ai.run_news_maintenance().
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path
from time_utils import now_utc_space

PROJECT_DIR = Path(__file__).resolve().parents[2]
_DB_PATH = PROJECT_DIR / "out" / "investment.db"


def _ensure_log_table(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS news_maintenance_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at         TEXT NOT NULL,
        day            TEXT NOT NULL,
        active_count   INTEGER DEFAULT 0,
        fading_count   INTEGER DEFAULT 0,
        resolved_count INTEGER DEFAULT 0,
        status         TEXT NOT NULL DEFAULT 'ok',
        error          TEXT
    )""")


def run_daily_sweep(day=None) -> dict:
    """
    Run news event-state sweep and log one row to news_maintenance_log.
    Safe to call multiple times per day (sweep is idempotent).
    Returns {"status", "day", "active", "fading", "resolved"}.
    """
    if day is None:
        day = date.today().isoformat()
    if not _DB_PATH.exists():
        return {"status": "skipped", "reason": "db_not_found", "day": day,
                "active": 0, "fading": 0, "resolved": 0}

    run_at = now_utc_space()
    status = "ok"
    error_msg = None
    counts: dict = {"active": 0, "fading": 0, "resolved": 0}
    conn = None

    try:
        sys.path.insert(0, str(PROJECT_DIR))
        from agents.news.intelligence import update_event_state_sweep
        conn = sqlite3.connect(str(_DB_PATH), timeout=15)
        _ensure_log_table(conn)
        result = update_event_state_sweep(day, conn)
        if isinstance(result, dict):
            counts = result
    except Exception as exc:
        status = "error"
        error_msg = str(exc)

    try:
        if conn is None:
            conn = sqlite3.connect(str(_DB_PATH), timeout=15)
        _ensure_log_table(conn)
        conn.execute(
            """INSERT INTO news_maintenance_log
               (run_at, day, active_count, fading_count, resolved_count, status, error)
               VALUES (?,?,?,?,?,?,?)""",
            (run_at, day,
             counts.get("active", 0), counts.get("fading", 0), counts.get("resolved", 0),
             status, error_msg),
        )
        conn.commit()
    except Exception as log_exc:
        print(f"[NewsMaintenance] Log write failed: {log_exc}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return {"status": status, "day": day, **counts}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="News event-state maintenance sweep")
    parser.add_argument("--day", default=None, help="Date YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    out = run_daily_sweep(day=args.day)
    print(f"[NewsMaintenance] {out}")
    if out.get("status") == "error":
        sys.exit(1)
