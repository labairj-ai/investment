import ast
import sqlite3
from pathlib import Path
from types import SimpleNamespace


def test_expired_call_assignment_preserves_premium_and_rejects_stale_close(tmp_path):
    (tmp_path / "out").mkdir()
    db_path = tmp_path / "out" / "investment.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE cc_positions (
                id INTEGER PRIMARY KEY, status TEXT, close_type TEXT, closed_date TEXT,
                closed_price REAL, contracts INTEGER, premium_per_contract REAL, net_premium REAL
            )
        """)
        conn.execute("INSERT INTO cc_positions VALUES (1, 'expired', 'expired', '2026-11-20', NULL, 2, 0.25, 50)")

    body = {
        "expected_status": "expired",
        "status": "assigned",
        "close_type": "assigned",
        "closed_date": "2026-11-21",
        "closed_price": None,
    }
    responses = []
    # Load only the handler so importing the server cannot initialize a runtime DB.
    source = Path(__file__).resolve().parents[1] / "serve.py"
    tree = ast.parse(source.read_text())
    handler_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Handler")
    update = next(node for node in handler_class.body if isinstance(node, ast.FunctionDef) and node.name == "_handle_cc_update")
    namespace = {"PROJECT_DIR": tmp_path, "sqlite3": sqlite3}
    exec(compile(ast.Module(body=[update], type_ignores=[]), str(source), "exec"), namespace)
    handler = SimpleNamespace()
    handler._read_body = lambda: body
    handler._json = lambda payload: responses.append(payload)
    handler._json_error = lambda status, message: responses.append(status)

    namespace["_handle_cc_update"](handler, 1)
    namespace["_handle_cc_update"](handler, 1)
    assert responses == [{"ok": True}, 409]

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("""
            SELECT status, close_type, closed_date, closed_price, net_premium FROM cc_positions
        """).fetchone() == ("assigned", "assigned", "2026-11-21", None, 50)
