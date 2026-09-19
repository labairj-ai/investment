#!/usr/bin/env bash
# Canary audit for the learning pipeline (0423/0426/0435).
# 0435: anchors on the LATEST ledger attempt (not latest COMPLETED), then audits
#       every model sweep belonging to that OH invocation.
# Exit 0 = all pass, 1 = one or more failures.

DB="${1:-/home/optiplex/investment/out/investment.db}"
FAIL=0

echo ""
echo "=== Investment Learning Canary Audit ==="
echo "DB: $DB"
echo ""

# ── Anchor: latest ledger row (any status) ─────────────────────────────────────
# 0435: No status filter. If the most recent sweep failed, the canary must fail too.
ANCHOR=$(sqlite3 "$DB" \
    "SELECT id||'|'||COALESCE(agent_run_id,'')||'|'||cohort_id||'|'||model_version||'|'||status||'|'||expected_candidates||'|'||scored_candidates \
     FROM learning_sweep_runs ORDER BY id DESC LIMIT 1" \
    2>/dev/null)

if [ -z "$ANCHOR" ]; then
    echo "  FAIL  No ledger rows found — no sweep has been recorded yet"
    echo "=== CANARY FAILURES DETECTED ==="
    exit 1
fi

LEDGER_ID=$(echo "$ANCHOR"    | cut -d'|' -f1)
AGENT_RUN_ID=$(echo "$ANCHOR" | cut -d'|' -f2)
COHORT_ID=$(echo "$ANCHOR"    | cut -d'|' -f3)
MV=$(echo "$ANCHOR"           | cut -d'|' -f4)
LATEST_STATUS=$(echo "$ANCHOR"| cut -d'|' -f5)
EXP_CANDS=$(echo "$ANCHOR"    | cut -d'|' -f6)
SCO_CANDS=$(echo "$ANCHOR"    | cut -d'|' -f7)

echo "Latest ledger row ID:  $LEDGER_ID"
echo "Agent run ID:          ${AGENT_RUN_ID:-(not set)}"
echo "Cohort ID:             $COHORT_ID"
echo "Model version:         $MV"
echo "Status:                $LATEST_STATUS"
echo "Candidates:            expected=$EXP_CANDS  scored=$SCO_CANDS"
echo ""

# 1. Latest sweep must be COMPLETED with exact count
if [ "$LATEST_STATUS" != "COMPLETED" ]; then
    echo "  FAIL  Latest sweep status=$LATEST_STATUS (must be COMPLETED)"
    FAIL=1
elif [ "$EXP_CANDS" != "$SCO_CANDS" ]; then
    echo "  FAIL  Latest sweep count mismatch (expected=$EXP_CANDS scored=$SCO_CANDS)"
    FAIL=1
else
    echo "  PASS  Latest sweep COMPLETED with exact count ($SCO_CANDS)"
fi

# 0435: post-0434 all sweeps carry agent_run_id; missing = failure, not a skip.
if [ -z "$AGENT_RUN_ID" ]; then
    echo "  FAIL  agent_run_id not set — post-0434 every sweep must carry agent_run_id"
    FAIL=1
else
    # ── Full invocation audit: all models in this OH run ─────────────────────────
    echo "--- Invocation audit for agent_run_id=$AGENT_RUN_ID ---"
    # 0439: include phase so parity check uses sweep-time state, not current lifecycle_state
    ALL_ROWS=$(sqlite3 "$DB" \
        "SELECT model_version||'|'||cohort_id||'|'||expected_candidates||'|'||scored_candidates||'|'||status||'|'||COALESCE(phase,'') \
         FROM learning_sweep_runs WHERE agent_run_id='$AGENT_RUN_ID' ORDER BY id ASC" \
        2>/dev/null)

    if [ -z "$ALL_ROWS" ]; then
        echo "  FAIL  No ledger rows found for agent_run_id=$AGENT_RUN_ID"
        FAIL=1
    else
        N_MODELS=$(echo "$ALL_ROWS" | wc -l | tr -d ' ')
        echo "  Models in invocation: $N_MODELS"

        # 0439: exactly one cohort_id per OH invocation
        _N_COHORTS=$(sqlite3 "$DB" \
            "SELECT COUNT(DISTINCT cohort_id) FROM learning_sweep_runs WHERE agent_run_id='$AGENT_RUN_ID'" \
            2>/dev/null)
        if [ "$_N_COHORTS" = "1" ]; then
            echo "  PASS  single cohort per invocation (cohort_id distinct count=1)"
        else
            echo "  FAIL  multiple cohort_ids in invocation (got $_N_COHORTS, expected 1)"
            FAIL=1
        fi
        echo ""
        while IFS='|' read -r _MV _CID _EXP _SCO _STATUS _PHASE; do
            echo "  Model: $_MV"
            # 2. Each model sweep must be COMPLETED + exact
            if [ "$_STATUS" != "COMPLETED" ]; then
                echo "    FAIL  status=$_STATUS (must be COMPLETED)"
                FAIL=1
            elif [ "$_EXP" != "$_SCO" ]; then
                echo "    FAIL  count mismatch (expected=$_EXP scored=$_SCO)"
                FAIL=1
            else
                echo "    PASS  COMPLETED exact ($_SCO candidates)"
            fi
            # 3. Observation count matches
            _N_OBS=$(sqlite3 "$DB" \
                "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$_CID' AND model_version='$_MV'" \
                2>/dev/null)
            if [ "$_N_OBS" = "$_SCO" ]; then
                echo "    PASS  observation count=$_N_OBS matches scored=$_SCO"
            else
                echo "    FAIL  observation count=$_N_OBS vs scored=$_SCO"
                FAIL=1
            fi
            # 4. Exactly one challenger winner
            _N_CH=$(sqlite3 "$DB" \
                "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$_CID' AND model_version='$_MV' AND would_select=1" \
                2>/dev/null)
            if [ "$_N_CH" = "1" ]; then
                echo "    PASS  exactly one challenger winner"
            else
                echo "    FAIL  expected 1 challenger winner, got $_N_CH"
                FAIL=1
            fi
            # 5. Exactly one base winner
            _N_BASE=$(sqlite3 "$DB" \
                "SELECT COUNT(*) FROM model_observations WHERE decision_cohort_id='$_CID' AND model_version='$_MV' AND base_would_select=1" \
                2>/dev/null)
            if [ "$_N_BASE" = "1" ]; then
                echo "    PASS  exactly one base winner"
            else
                echo "    FAIL  expected 1 base winner, got $_N_BASE"
                FAIL=1
            fi
            # 6. Episode count == expected (decision_episodes for this run)
            _N_EP=$(sqlite3 "$DB" \
                "SELECT COUNT(*) FROM decision_episodes WHERE run_id='$AGENT_RUN_ID'" \
                2>/dev/null)
            if [ "$_N_EP" = "$_EXP" ]; then
                echo "    PASS  decision_episodes count=$_N_EP matches expected=$_EXP"
            else
                echo "    FAIL  decision_episodes count=$_N_EP vs expected=$_EXP"
                FAIL=1
            fi
            # 7. Row-level lineage: every observation episode belongs to this run
            _N_ORPHAN=$(sqlite3 "$DB" \
                "SELECT COUNT(*) FROM model_observations mo
                 LEFT JOIN decision_episodes de ON mo.episode_id=de.episode_id AND de.run_id='$AGENT_RUN_ID'
                 WHERE mo.decision_cohort_id='$_CID' AND mo.model_version='$_MV' AND de.episode_id IS NULL" \
                2>/dev/null)
            if [ "$_N_ORPHAN" = "0" ]; then
                echo "    PASS  all observation episodes belong to run_id"
            else
                echo "    FAIL  $_N_ORPHAN observation(s) not linked to run_id=$AGENT_RUN_ID"
                FAIL=1
            fi
            # 8. Variant parity (PAPER_ACTIVE only)
            # 0439: prefer phase from ledger row (sweep-time state); fall back to current lifecycle_state
            if [ -n "$_PHASE" ]; then
                _IS_PA="$_PHASE"
            else
                _IS_PA=$(sqlite3 "$DB" \
                    "SELECT lifecycle_state FROM learning_models WHERE model_version='$_MV'" \
                    2>/dev/null)
            fi
            if [ "$_IS_PA" = "PAPER_ACTIVE" ]; then
                _SHADOW_EP=$(sqlite3 "$DB" \
                    "SELECT episode_id FROM model_observations WHERE decision_cohort_id='$_CID' AND model_version='$_MV' AND would_select=1 LIMIT 1" \
                    2>/dev/null)
                _VARIANT_EP=$(sqlite3 "$DB" \
                    "SELECT challenger_episode_id FROM decision_variants WHERE decision_cohort_id='$_CID' AND challenger_model_version='$_MV' LIMIT 1" \
                    2>/dev/null)
                if [ -z "$_VARIANT_EP" ]; then
                    echo "    SKIP  no decision_variant row (model not yet eligible)"
                elif [ "$_SHADOW_EP" = "$_VARIANT_EP" ]; then
                    echo "    PASS  shadow episode matches decision_variant"
                else
                    echo "    FAIL  shadow ep=$_SHADOW_EP vs variant ep=$_VARIANT_EP"
                    FAIL=1
                fi
            fi
            echo ""
        done <<< "$ALL_ROWS"
    fi
fi

# ── Full integrity audit ───────────────────────────────────────────────────────
echo "Running full integrity audit..."
AUDIT=$(cd "$(dirname "$DB")/.." && python3 check_integrity.py --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['overall'])" 2>/dev/null)
if [ "$AUDIT" = "ok" ]; then
    echo "  PASS  integrity audit overall=ok"
elif [ "$AUDIT" = "WARN" ]; then
    echo "  WARN  integrity audit has warnings (not blocking)"
else
    echo "  FAIL  integrity audit overall=${AUDIT:-(unknown)}"
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
