#!/usr/bin/env bash
# Backs up investment.db, buffett.db, and holdings.csv to a private GitHub repo.
# Repo: https://github.com/labairj-ai/investment-data
# Local clone: ~/.investment-backup

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$HOME/.investment-backup"
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# ── Ensure backup repo is present ─────────────────────────────────────────────
if [ ! -d "$BACKUP_DIR/.git" ]; then
  echo "[backup] Cloning investment-data repo…"
  git clone https://github.com/labairj-ai/investment-data.git "$BACKUP_DIR"
fi

# ── Copy files ────────────────────────────────────────────────────────────────
cp "$PROJECT_DIR/out/investment.db"  "$BACKUP_DIR/investment.db"
cp "$PROJECT_DIR/holdings.csv"       "$BACKUP_DIR/holdings.csv"

# Buffett DB is large but contains weeks of cached financials — worth keeping
if [ -f "$PROJECT_DIR/out/buffett.db" ]; then
  cp "$PROJECT_DIR/out/buffett.db" "$BACKUP_DIR/buffett.db"
fi

# ── Commit and push if anything changed ───────────────────────────────────────
cd "$BACKUP_DIR"
git add investment.db holdings.csv buffett.db 2>/dev/null || git add investment.db holdings.csv

if git diff --cached --quiet; then
  echo "[backup] No changes — nothing to push."
else
  git commit -m "Data backup — $TIMESTAMP"
  git push origin main
  echo "[backup] Pushed to investment-data."
fi
