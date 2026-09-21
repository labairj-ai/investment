#!/bin/bash
# Continue only after repaired-contract acceptance and post-acceptance refresh.
set -euo pipefail
cd "$(dirname "$0")/.."
export LLM_URL="${LLM_URL:-http://100.73.128.40:8080}"
export PYTHONPATH="$PWD"
export PYTHONUNBUFFERED=1
exec 9>out/macro_coverage_rollout.lock
flock -n 9
state=out/macro_coverage_rollout.state
trap 'printf "FAILED\n" >> "$state"' EXIT
printf 'WAITING_FOR_V18_ACCEPTANCE\n' > "$state"
deadline=$((SECONDS + 21600))
while true; do
  prior=$(tail -1 out/macro_v18_rollout.state)
  if [ "$prior" = COMPLETE ]; then break; fi
  if [ "$prior" = FAILED ]; then exit 1; fi
  if [ "$SECONDS" -gt "$deadline" ]; then exit 1; fi
  sleep 30
done
printf 'PREPARING_CANDIDATE_COVERAGE\n' >> "$state"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
venv/bin/python scripts/prepare_macro_candidates.py --prepare --out "out/macro_coverage_${stamp}.json"
printf 'RUNNING_REAL_CANARY\n' >> "$state"
venv/bin/python scripts/run_macro_coverage_canary.py --out "out/macro_coverage_canary_${stamp}.json"
printf 'VERIFYING_LEARNING_LAB\n' >> "$state"
venv/bin/python generate_dashboard.py
sudo -n systemctl restart investment.service
venv/bin/python -c 'import json,time,urllib.request; time.sleep(2); d=json.load(urllib.request.urlopen("http://127.0.0.1:5001/api/learning/readiness",timeout=30)); m=d["report"]["macro_experiment"]; assert d["ok"] and m["observe_only"] and m["stage"]==0 and m["collection_started_at"] and m["coverage_canary_id"],m; print(json.dumps(m,indent=2)); html=urllib.request.urlopen("http://127.0.0.1:5001/",timeout=30).read().decode(); assert "macro-experiment-panel" in html and "Latest common dimensions" in html'
sudo -n install -m 644 systemd/macro-candidate-preparation.service systemd/macro-candidate-preparation.timer /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now macro-candidate-preparation.timer
printf 'COMPLETE\n' >> "$state"
trap - EXIT
