#!/usr/bin/env bash
# Canary audit for the learning pipeline after a live OH sweep.
# Run on optiplex after the morning investment run to verify end-to-end integrity.
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

# 1. Most recent OH run_id and cohort_id
RUN_ID=$(sqlite3 "$DB" "SELECT run_id FROM decision_episodes ORDER BY captured_at DESC LIMIT 1")
COHORT_ID=$(sqlite3 "$DB" "SELECT decision_cohort_id FROM model_observations ORDER BY rowid DESC LIMIT 1")
MV=$(sqlite3 "$DB" "SELECT model_version FROM learning_models WHERE lifecycle_state IN ('OBSERVE','PAPER_ACTIVE') ORDER BY created_at DESC LIMIT 1")

echo "Latest run_id:    $RUN_ID"
echo "Latest cohort_id: $COHORT_ID"
echo "Active model:     $MV"
echo ""

# 2. Sweep ledger — expected == scored
if [ -n "$COHORT_ID" ] && [ -n "$MV" ]; then
    EXP=$(sqlite3 "$DB" "SELECT expected_candidates FROM learning_sweep_runs WHERE cohort_id='$COHORT_ID' AND model_version='$MV' ORDER BY id DESC LIMIT 1")
    SCO=$(sqlite3 "$DB" "SELECT scored_candidates FROM learning_sweep_runs WHERE cohort_id='$COHORT_ID' AND model_version='$MV' ORDER BY id DESC LIMIT 1")
    STA=$(sqlite3 "$DB" "SELECT status FROM learning_sweep_runs WHERE cohort_id='$COHORT_ID' AND model_version='$MV' ORDER BY id DESC LIMIT 1")
    echo "  Sweep ledger: expected=$EXP scored=$SCO status=$STA"
    if [ "$STA" = "COMPLETED" ] && [ "$EXP" = "$SCO" ] && [ -n "$EXP" ]; then
        echo "  PASS  sweep ledger (expected == scored, COMPLETED)"
    else
        echo "  FAIL  sweep ledger mismatch or not COMPLETED"
        FAIL=1
    fi
fi
echo ""

# 3. Decision episodes exist for latest run
check "decision_episodes exist for run" \
    "SELECT COUNT(*) > 0 FROM decision_episodes WHERE run_id=$RUN_ID" \
    "1"

# 4. Exactly one model_observation with would_select=1 per cohort
if [ -n "$COHORT_ID" ] && [ -n "$MV" ]; then
    N_CH=$(sqlite3 "$DB" "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV' AND would_select=1")
    if [ "$N_CH" = "1" ]; then
        echo "  PASS  exactly one challenger winner (would_select=1)"
    else
        echo "  FAIL  expected 1 challenger winner, got $N_CH"
        FAIL=1
    fi
fi

# 5. Exactly one model_observation with base_would_select=1 per cohort
if [ -n "$COHORT_ID" ] && [ -n "$MV" ]; then
    N_BASE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV' AND base_would_select=1")
    if [ "$N_BASE" = "1" ]; then
        echo "  PASS  exactly one base winner (base_would_select=1)"
    else
        echo "  FAIL  expected 1 base winner, got $N_BASE"
        FAIL=1
    fi
fi

# 6. decision_variants challenger_episode_id matches shadow observation episode_id
if [ -n "$COHORT_ID" ] && [ -n "$MV" ]; then
    SHADOW_EP=$(sqlite3 "$DB" "SELECT episode_id FROM model_observations WHERE decision_cohort_id='$COHORT_ID' AND model_version='$MV' AND would_select=1 LIMIT 1")
    VARIANT_EP=$(sqlite3 "$DB" "SELECT challenger_episode_id FROM decision_variants WHERE decision_cohort_id='$COHORT_ID' AND challenger_model_version='$MV' LIMIT 1")
    if [ -z "$VARIANT_EP" ]; then
        echo "  SKIP  no decision_variant row (model not PAPER_ACTIVE or not eligible)"
    elif [ "$SHADOW_EP" = "$VARIANT_EP" ]; then
        echo "  PASS  shadow episode matches decision_variant challenger_episode_id"
    else
        echo "  FAIL  shadow ep=$SHADOW_EP vs variant ep=$VARIANT_EP"
        FAIL=1
    fi
fi

# 7. Integrity audit — no BLOCK
echo ""
echo "Running full integrity audit..."
AUDIT=$(cd "$(dirname "$DB")/.." && python3 check_integrity.py --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['overall'])")
if [ "$AUDIT" = "ok" ]; then
    echo "  PASS  integrity audit overall=ok"
elif [ "$AUDIT" = "WARN" ]; then
    echo "  WARN  integrity audit has warnings (not blocking)"
else
    echo "  FAIL  integrity audit overall=$AUDIT"
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
