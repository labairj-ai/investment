#!/usr/bin/env bash
# Canary audit for the learning pipeline after a live OH sweep (0423/0426).
# 0426: anchored on one COMPLETED ledger row — all assertions derived from the same
#       agent_run_id, cohort_id, and model_version to eliminate cross-run timing assumptions.
# Exit 0 = all assertions pass, 1 = one or more failures.

DB="${1:-/home/optiplex/investment/out/investment.db}"
FAIL=0

check() {
    local label="$1"
    local sql="$2"
    local expect="$3"
    local actual
    actual=$(sqlite3 "$DB" "$sql" 2>&1)
    if [ "$actual" = "$expect" ]; then
        echo "  PASS  $label"
    else
        echo "  FAIL  $label (expected='$expect' got='$actual')"
        FAIL=1
    fi
}

echo ""
echo "=== Investment Learning Canary Audit ==="
echo "DB: $DB"
echo ""

# ── Anchor: latest COMPLETED ledger row ────────────────────────────────────────
# 0426: Start from a single ledger row so agent_run_id, cohort_id, and model_version
# all come from the same OH invocation — no independent "latest" queries that could
# produce a cross-run mismatch.
LEDGER=$(sqlite3 "$DB" \
    "SELECT id||'|'||COALESCE(agent_run_id,'')||'|'||cohort_id||'|'||model_version||'|'||COALESCE(phase,'')||'|'||expected_candidates||'|'||scored_candidates||'|'||COALESCE(base_recommendation_eligible,'') FROM learning_sweep_runs WHERE status='COMPLETED' ORDER BY id DESC LIMIT 1" \
    2>/dev/null)

if [ -z "$LEDGER" ]; then
    echo "  FAIL  No COMPLETED ledger row found — no sweep has been recorded yet"
    echo ""
    echo "=== CANARY FAILURES DETECTED — investigate before next cycle ==="
    exit 1
fi

LEDGER_ID=$(echo "$LEDGER"  | cut -d'|' -f1)
AGENT_RUN_ID=$(echo "$LEDGER" | cut -d'|' -f2)
COHORT_ID=$(echo "$LEDGER"  | cut -d'|' -f3)
MV=$(echo "$LEDGER"         | cut -d'|' -f4)
PHASE=$(echo "$LEDGER"      | cut -d'|' -f5)
EXP_CANDS=$(echo "$LEDGER"  | cut -d'|' -f6)
SCO_CANDS=$(echo "$LEDGER"  | cut -d'|' -f7)
BASE_ELIG=$(echo "$LEDGER"  | cut -d'|' -f8)

echo "Ledger row ID:      $LEDGER_ID"
echo "Agent run ID:       ${AGENT_RUN_ID:-(not set — pre-0424 sweep)}"
echo "Cohort ID:          $COHORT_ID"
echo "Model version:      $MV"
echo "Phase:              ${PHASE:-(null)}"
echo "Candidates:         expected=$EXP_CANDS  scored=$SCO_CANDS"
echo "Base eligible:      ${BASE_ELIG:-(not recorded)}"
echo ""

# 1. Sweep ledger expected == scored
if [ "$EXP_CANDS" = "$SCO_CANDS" ]; then
    echo "  PASS  sweep ledger (expected=$EXP_CANDS == scored=$SCO_CANDS, COMPLETED)"
else
    echo "  FAIL  sweep ledger mismatch (expected=$EXP_CANDS vs scored=$SCO_CANDS)"
    FAIL=1
fi

# 2. Observation count in model_observations matches ledger scored_candidates
N_OBS=$(sqlite3 "$DB" \
    "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV'" \
    2>/dev/null)
if [ "$N_OBS" = "$SCO_CANDS" ]; then
    echo "  PASS  observation count matches ledger ($N_OBS = $SCO_CANDS)"
else
    echo "  FAIL  observation count=$N_OBS vs ledger scored=$SCO_CANDS"
    FAIL=1
fi

# 3. decision_episodes exist for agent_run_id (when populated)
if [ -n "$AGENT_RUN_ID" ]; then
    check "decision_episodes exist for agent_run_id" \
        "SELECT COUNT(*) > 0 FROM decision_episodes WHERE run_id='$AGENT_RUN_ID'" \
        "1"
else
    echo "  SKIP  decision_episodes check (agent_run_id not set — pre-0424 sweep)"
fi

# 4. Exactly one would_select=1 per cohort
N_CH=$(sqlite3 "$DB" \
    "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV' AND would_select=1" \
    2>/dev/null)
if [ "$N_CH" = "1" ]; then
    echo "  PASS  exactly one challenger winner (would_select=1)"
else
    echo "  FAIL  expected 1 challenger winner, got $N_CH"
    FAIL=1
fi

# 5. Exactly one base_would_select=1 per cohort
N_BASE=$(sqlite3 "$DB" \
    "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV' AND base_would_select=1" \
    2>/dev/null)
if [ "$N_BASE" = "1" ]; then
    echo "  PASS  exactly one base winner (base_would_select=1)"
else
    echo "  FAIL  expected 1 base winner, got $N_BASE"
    FAIL=1
fi

# 6. decision_variants challenger_episode_id matches shadow observation episode_id
SHADOW_EP=$(sqlite3 "$DB" \
    "SELECT episode_id FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV' AND would_select=1 LIMIT 1" \
    2>/dev/null)
VARIANT_EP=$(sqlite3 "$DB" \
    "SELECT challenger_episode_id FROM decision_variants WHERE decision_cohort_id='$COHORT_ID' AND challenger_model_version='$MV' LIMIT 1" \
    2>/dev/null)
if [ -z "$VARIANT_EP" ]; then
    echo "  SKIP  no decision_variant row (model not PAPER_ACTIVE or not eligible)"
elif [ "$SHADOW_EP" = "$VARIANT_EP" ]; then
    echo "  PASS  shadow episode matches decision_variant challenger_episode_id"
else
    echo "  FAIL  shadow ep=$SHADOW_EP vs variant ep=$VARIANT_EP"
    FAIL=1
fi

# 7. Full integrity audit
echo ""
echo "Running full integrity audit..."
AUDIT=$(cd "$(dirname "$DB")/.." && python3 check_integrity.py --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['overall'])" 2>/dev/null)
if [ "$AUDIT" = "ok" ]; then
    echo "  PASS  integrity audit overall=ok"
elif [ "$AUDIT" = "WARN" ]; then
    echo "  WARN  integrity audit has warnings (not blocking)"
else
    echo "  FAIL  integrity audit overall=${AUDIT:-(unknown — check_integrity.py failed)}"
    FAIL=1
fi

echo ""
if [ $FAIL -eq 0 ]; then
    echo "=== All canary checks PASSED ==="
    exit 0
else
    echo "=== CANARY FAILURES DETECTED — investigate before next cycle ==="
    exit 1
fi
