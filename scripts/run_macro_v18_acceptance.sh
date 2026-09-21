#!/bin/bash
# Authorized defect reacceptance. Never modifies experiment/production weights.
set -euo pipefail
cd "$(dirname "$0")/.."
export LLM_URL="${LLM_URL:-http://100.73.128.40:8080}"
export PYTHONPATH="$PWD"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
artifact="out/macro_validation_v18_${stamp}.json"
state="out/macro_v18_rollout.state"
trap 'printf "FAILED\n" >> "$state"' EXIT
printf 'CERTIFYING\n' > "$state"
venv/bin/python -u portfolio_ai.py --scores --force
printf 'VALIDATING\n' >> "$state"
venv/bin/python -u scripts/validate_macro_scorer.py --live --out "$artifact"
venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["activated"] is True and d["verdict"]=="PASS" and d["validation_config_version"]=="v1.8", d.get("verdict")' "$artifact"
printf 'POST_ACCEPTANCE_REFRESH\n' >> "$state"
venv/bin/python -u portfolio_ai.py --scores --force
venv/bin/python -c 'import sqlite3,portfolio_ai as p; c=sqlite3.connect(str(p.DB_PATH)); c.row_factory=sqlite3.Row; r=c.execute("SELECT * FROM macro_scoring_runs ORDER BY run_at DESC LIMIT 1").fetchone(); assert r["status"]=="COMPLETE" and r["failed_n"]==0 and r["expected_n"]==r["scored_n"] and r["scorer_contract_hash"]==p._compute_scorer_contract_hash(),dict(r); print(dict(r))'
printf 'COMPLETE\n' >> "$state"
trap - EXIT
