#!/usr/bin/env bash
# Backs up investment.db, buffett.db, holdings.csv, and a human-readable
# thesis JSON export to the private investment-data repo.
# Repo: https://github.com/labairj-ai/investment-data
# Local clone: ~/.investment-backup

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PROJECT_DIR
export BACKUP_DIR="${INVESTMENT_BACKUP_DIR:-$HOME/.investment-backup}"
export GIT_TERMINAL_PROMPT=0
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# ── Ensure backup repo is present ─────────────────────────────────────────────
if [ ! -d "$BACKUP_DIR/.git" ]; then
  echo "[backup] Cloning investment-data repo…"
  git clone https://github.com/labairj-ai/investment-data.git "$BACKUP_DIR"
fi

# Serialize database snapshots and Git writes when scheduler/manual runs overlap.
exec 9>"$BACKUP_DIR/.backup.lock"
flock -n 9 || { echo "[backup] Another backup is running; retry later." >&2; exit 1; }

# ── Copy binary files ─────────────────────────────────────────────────────────
# SQLite's online backup includes committed WAL content; raw cp can omit it.
"$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/scripts/watchdog_backup_snapshot.py" "$PROJECT_DIR/out/investment.db" "$BACKUP_DIR/investment.db"
# Optional authenticated provenance; absent signer config leaves backup unchanged.
# The key is provisioned by the operator, never committed or passed to the Builder.
if [ -n "${DEV_AGENT_BACKUP_SIGNING_KEY:-}" ]; then
  "$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/scripts/backup_provenance.py" "$BACKUP_DIR/investment.db"
fi
# GitHub rejects individual blobs over 100 MiB. Retain the raw consistent
# snapshot locally for provenance/restore, but publish its lossless gzip form.
gzip -n -c "$BACKUP_DIR/investment.db" > "$BACKUP_DIR/investment.db.gz.tmp"
gzip -t "$BACKUP_DIR/investment.db.gz.tmp"
mv "$BACKUP_DIR/investment.db.gz.tmp" "$BACKUP_DIR/investment.db.gz"
# Refuse a future oversized archive before creating an undeliverable commit.
test "$(wc -c < "$BACKUP_DIR/investment.db.gz")" -lt 104857600
cp "$PROJECT_DIR/holdings.csv"       "$BACKUP_DIR/holdings.csv"

if [ -f "$PROJECT_DIR/out/buffett.db" ]; then
  "$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/scripts/watchdog_backup_snapshot.py" "$PROJECT_DIR/out/buffett.db" "$BACKUP_DIR/buffett.db"
fi

# ── Export thesis data as human-readable JSON ─────────────────────────────────
"$PROJECT_DIR/venv/bin/python3" - <<'PYEOF'
import json, sqlite3, os, sys

db_path = os.path.join(os.environ.get("PROJECT_DIR", "."), "out", "investment.db")
out_path = os.path.join(os.environ["BACKUP_DIR"], "theses.json")

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
git rm --cached --ignore-unmatch investment.db
# Ignore raw local snapshots/sidecars and lock/temp files in this private clone.
for pattern in investment.db '*.db-shm' '*.db-wal' '*.tmp' .backup.lock; do
  grep -qxF "$pattern" .gitignore 2>/dev/null || printf '%s\n' "$pattern" >> .gitignore
done
git add .gitignore investment.db.gz holdings.csv theses.json
if [ -n "${DEV_AGENT_BACKUP_SIGNING_KEY:-}" ]; then
  git add investment.provenance.json
fi
git add buffett.db 2>/dev/null || true

if git diff --cached --quiet; then
  echo "[backup] No new changes — verifying destination is current."
else
  git commit -m "Data backup — $TIMESTAMP"
fi
# Push even with no new diff: an earlier commit may still be ahead after a failed push.
timeout 90s git push origin HEAD:main
BACKUP_LOCAL_HEAD="$(git rev-parse HEAD)"
BACKUP_REMOTE_HEAD="$(timeout 15s git ls-remote origin refs/heads/main | cut -f1)"
test "$BACKUP_LOCAL_HEAD" = "$BACKUP_REMOTE_HEAD"
echo "[backup] Destination verified at $BACKUP_LOCAL_HEAD"
