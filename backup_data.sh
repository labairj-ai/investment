#!/usr/bin/env bash
# Backs up investment.db, buffett.db, holdings.csv, and a human-readable
# thesis JSON export to the private investment-data repo.
# Repo: https://github.com/labairj-ai/investment-data
# Local clone: ~/.investment-backup

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PROJECT_DIR
BACKUP_DIR="$HOME/.investment-backup"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# ── Ensure backup repo is present ─────────────────────────────────────────────
if [ ! -d "$BACKUP_DIR/.git" ]; then
  echo "[backup] Cloning investment-data repo…"
  git clone https://github.com/labairj-ai/investment-data.git "$BACKUP_DIR"
fi

# ── Copy binary files ─────────────────────────────────────────────────────────
cp "$PROJECT_DIR/out/investment.db"  "$BACKUP_DIR/investment.db"
cp "$PROJECT_DIR/holdings.csv"       "$BACKUP_DIR/holdings.csv"

if [ -f "$PROJECT_DIR/out/buffett.db" ]; then
  cp "$PROJECT_DIR/out/buffett.db" "$BACKUP_DIR/buffett.db"
fi

# ── Export thesis data as human-readable JSON ─────────────────────────────────
"$PROJECT_DIR/venv/bin/python3" - <<'PYEOF'
import json, sqlite3, os, sys

db_path = os.path.join(os.environ.get("PROJECT_DIR", "."), "out", "investment.db")
out_path = os.path.join(os.path.expanduser("~"), ".investment-backup", "theses.json")

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    theses = [dict(r) for r in conn.execute(
        "SELECT * FROM investment_theses ORDER BY ticker, version"
    ).fetchall()]

    # Parse JSON blob columns so the file is fully readable
    for t in theses:
        for col in ("intake_json", "draft_json"):
            if t.get(col):
                try:
                    t[col] = json.loads(t[col])
                except Exception:
                    pass

    claims = [dict(r) for r in conn.execute(
        "SELECT * FROM thesis_claims ORDER BY thesis_id, id"
    ).fetchall()]

    # Attach claims to their parent thesis
    claims_by_thesis = {}
    for c in claims:
        claims_by_thesis.setdefault(c["thesis_id"], []).append(c)
    for t in theses:
        t["_claims"] = claims_by_thesis.get(t["id"], [])

    conn.close()

    with open(out_path, "w") as f:
        json.dump(theses, f, indent=2, default=str)

    print(f"[backup] Thesis export: {len(theses)} theses written to theses.json")
except Exception as e:
    print(f"[backup] Thesis export failed (non-fatal): {e}", file=sys.stderr)
PYEOF

# ── Commit and push if anything changed ───────────────────────────────────────
cd "$BACKUP_DIR"
git add investment.db holdings.csv theses.json 2>/dev/null
git add buffett.db 2>/dev/null || true

if git diff --cached --quiet; then
  echo "[backup] No changes — nothing to push."
else
  git commit -m "Data backup — $TIMESTAMP"
  git push origin main
  echo "[backup] Pushed to investment-data."
fi
