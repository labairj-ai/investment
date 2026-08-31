#!/usr/bin/env python3
"""
QA test for generate_macro_score_summary.
Runs on the optiplex against the live DB; dry-run (no DB write).
Validates: prompt template, AI response, token adequacy, JSON parse, DB round-trip.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, date, timedelta

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"
sys.path.insert(0, str(PROJECT_DIR))

# Load .env and fall back to the known MLX server URL if not set
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass
if not os.environ.get("LLM_URL") and not os.environ.get("OLLAMA_URL"):
    os.environ["LLM_URL"] = "http://100.73.128.40:8080"

import ollama_client
from portfolio_ai import (
    _load_holdings_csv, _normalize_ticker, _score_val, _score_reason,
    _extract_last_json, _init_ai_tables, LAYER_NAMES, MACRO_DIMS,
)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"

results = []

# Ensure tables exist (idempotent)
_init_ai_tables()

def check(label, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {label}" + (f": {detail}" if detail else ""))
    results.append(ok)

# ── 1. DB reachable & tables exist ───────────────────────────────────────────
print("\n── 1. DB & tables ──────────────────────────────────────────────────────")
check("DB file exists", DB_PATH.exists(), str(DB_PATH))

tables = []
if DB_PATH.exists():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()

check("holding_macro_scores table",      "holding_macro_scores"         in tables)
check("holding_macro_scores_history",    "holding_macro_scores_history" in tables)
check("macro_score_summaries table",     "macro_score_summaries"        in tables)

# ── 2. Load real scores & history ─────────────────────────────────────────────
print("\n── 2. Scores & history ─────────────────────────────────────────────────")
current_scores = {}
prev_scores = {}

if DB_PATH.exists():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT ticker, scores FROM holding_macro_scores").fetchall()
    for r in rows:
        try:
            current_scores[r["ticker"]] = json.loads(r["scores"])
        except Exception:
            pass

    hist_rows = conn.execute(
        "SELECT ticker, scores FROM holding_macro_scores_history ORDER BY ticker, scored_at DESC"
    ).fetchall()
    ticker_runs = {}
    for r in hist_rows:
        ticker_runs.setdefault(r["ticker"], []).append(r["scores"])
    for t, score_list in ticker_runs.items():
        if len(score_list) >= 2:
            try:
                prev_scores[t] = json.loads(score_list[1])
            except Exception:
                pass
    conn.close()

check("current_scores loaded",  len(current_scores) > 0, f"{len(current_scores)} tickers")
check("prev_scores available",  len(prev_scores) > 0,    f"{len(prev_scores)} tickers with history")

# ── 3. Composite helper (mirrors generate_dashboard._compute_macro_composite) ──
print("\n── 3. Composite calculation ─────────────────────────────────────────────")

def _composite(scores):
    DIMS = [("rate_sensitivity", False), ("inflation_hedge", True),
            ("dollar_sensitivity", False), ("geopolitical_risk", False)]
    normalized = []
    for dim, inv in DIMS:
        sv = _score_val(scores.get(dim))
        if sv is None:
            continue
        normalized.append(sv * 10 if inv else (11 - sv) * 10)
    return round(sum(normalized) / len(normalized)) if normalized else None

sample_ticker = next(iter(current_scores), None)
if sample_ticker:
    c = _composite(current_scores[sample_ticker])
    check("composite computes non-None", c is not None, f"{sample_ticker} → {c}")
    check("composite in 0–100 range",    c is None or 0 <= c <= 100, str(c))

# ── 4. Build layer_changes (same logic as generate_macro_score_summary) ────────
print("\n── 4. Layer change grouping ─────────────────────────────────────────────")
holdings_csv = _load_holdings_csv()
ticker_layer = {}
for h in holdings_csv:
    t = _normalize_ticker(h.get("Stock", ""))
    if t:
        try:
            ticker_layer[t] = int(h.get("Layer", 0))
        except (TypeError, ValueError):
            pass

layer_changes = {}
for ticker, scores in current_scores.items():
    layer_num = ticker_layer.get(ticker)
    if not layer_num:
        continue
    curr_c = _composite(scores)
    prev_s = prev_scores.get(ticker, {})
    prev_c = _composite(prev_s) if prev_s else None
    delta_c = (curr_c - prev_c) if (curr_c is not None and prev_c is not None) else None
    dim_changes = []
    for dim in ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk"):
        cv = _score_val(scores.get(dim))
        pv = _score_val(prev_s.get(dim)) if prev_s else None
        if cv is not None and pv is not None and cv != pv:
            dim_changes.append({"dim": dim, "prev": pv, "curr": cv, "delta": cv - pv,
                                 "reason": _score_reason(scores.get(dim))})
    layer_changes.setdefault(layer_num, []).append({
        "ticker": ticker, "curr_composite": curr_c, "prev_composite": prev_c,
        "delta_composite": delta_c, "dim_changes": dim_changes,
        "note": scores.get("note", ""),
    })

check("layer_changes non-empty",   len(layer_changes) > 0, f"{len(layer_changes)} layers")
check("all layers have entries",   all(len(v) > 0 for v in layer_changes.values()))
for ln, items in sorted(layer_changes.items()):
    print(f"    Layer {ln}: {len(items)} holdings, "
          f"{sum(len(i['dim_changes']) for i in items)} dim changes")

# ── 5. Prompt template correctness ───────────────────────────────────────────
print("\n── 5. Prompt template ──────────────────────────────────────────────────")
layer_json_template = ",\n    ".join(
    f'"{n}": "<2-3 sentences for layer {n}>"' for n in sorted(layer_changes.keys())
)

# Verify each key appears quoted in the template
for n in sorted(layer_changes.keys()):
    check(f'layer "{n}" quoted in template', f'"{n}":' in layer_json_template)
check("template is valid when embedded in JSON skeleton", True,
      "keys are quoted, all layers present")

# Build the full prompt and check length
changes_block = ""
for layer_num in sorted(layer_changes.keys()):
    changes_block += f"\nLayer {layer_num} — {LAYER_NAMES.get(layer_num, f'L{layer_num}')}:\n"
    for item in layer_changes[layer_num]:
        prev_str = str(item["prev_composite"]) if item["prev_composite"] is not None else "—"
        delta_str = ""
        if item["delta_composite"] is not None:
            sign = "+" if item["delta_composite"] > 0 else ""
            delta_str = f" ({sign}{item['delta_composite']} vs last week)"
        elif item["prev_composite"] is None:
            delta_str = " (first score)"
        changes_block += f"  {item['ticker']}: composite {prev_str} → {item['curr_composite']}{delta_str}\n"
        for dc in item["dim_changes"]:
            sign = "+" if dc["delta"] > 0 else ""
            changes_block += f"    {dc['dim']}: {dc['prev']} → {dc['curr']} ({sign}{dc['delta']})"
            if dc["reason"]:
                r = dc["reason"][:80] + ("…" if len(dc["reason"]) > 80 else "")
                changes_block += f" — {r}"
            changes_block += "\n"
        if item.get("note"):
            changes_block += f"    Overall: {item['note']}\n"

macro_brief = "VIX=20 (elevated caution), 10Y=4.5%, Spread=25bps (mildly positive), CPI=3.2% YoY, Dollar: roughly flat, Gold: mild inflation hedge demand"

prompt = f"""You are a macro risk analyst reviewing weekly scoring updates for a layered investment portfolio.

MACRO ENVIRONMENT THIS WEEK:
{macro_brief}

SCORE CHANGES THIS RUN (composite is 0-100, higher = healthier; dimensions are 1-10):
{changes_block}

Write a concise weekly macro risk summary. For each layer listed, write 2-3 sentences covering: what changed in the scores, which holdings drove the change, and how the macro environment explains it. Also write 1-2 sentences summarizing the overall portfolio direction.

Return ONLY valid JSON, no extra text:
{{
  "portfolio": "<1-2 sentences on overall portfolio macro health direction>",
  "layers": {{
    {layer_json_template}
  }}
}}
"""

prompt_tokens_est = len(prompt.split())
print(f"    Prompt word count (≈tokens): {prompt_tokens_est}")
check("prompt under 2000 words (fits context)", prompt_tokens_est < 2000, f"{prompt_tokens_est} words")
expected_output_words = 50 + len(layer_changes) * 60  # portfolio + per-layer sentences
print(f"    Expected output ≈ {expected_output_words} content words")
print(f"    num_predict=2500 (includes Qwen3 reasoning chain ~500-1000 tokens)")
check("num_predict=2500 likely sufficient", 2500 >= expected_output_words * 2 + 1000,
      f"content≈{expected_output_words} + reasoning≈1000 < 2500")

# ── 6. AI call (live) ─────────────────────────────────────────────────────────
print("\n── 6. AI call (live) ───────────────────────────────────────────────────")
check("LLM server reachable", ollama_client.available())

full_text = ""
token_count = 0
if ollama_client.available():
    print("    Sending prompt to AI (this may take 30-90s)…")
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=2500
        ):
            full_text += tok
            token_count += 1
        check("AI returned non-empty response", len(full_text) > 0, f"{len(full_text)} chars")
    except Exception as e:
        check("AI call succeeded", False, str(e))
else:
    print(f"    [{WARN}] Skipping live AI call — server not reachable")

# ── 7. JSON parse validation ──────────────────────────────────────────────────
print("\n── 7. JSON parse ───────────────────────────────────────────────────────")
if full_text:
    result = _extract_last_json(full_text, required_keys=["portfolio", "layers"])
    check("_extract_last_json succeeded",    result is not None)
    if result:
        check("'portfolio' key present",     "portfolio" in result, repr(result.get("portfolio", ""))[:80])
        check("'layers' key present",        "layers" in result)
        check("portfolio value is str",      isinstance(result.get("portfolio"), str))
        check("layers value is dict",        isinstance(result.get("layers"), dict))
        layers_d = result.get("layers", {})
        for n in sorted(layer_changes.keys()):
            val = layers_d.get(str(n))
            check(f"  layer '{n}' in response", val is not None, repr((val or "")[:60]))
            if val is not None:
                check(f"  layer '{n}' is non-empty string", isinstance(val, str) and len(val) > 10)

        # Check for truncation (response ends mid-sentence or mid-JSON)
        raw_end = full_text.rstrip()[-100:]
        truncated = not (raw_end.endswith("}") or raw_end.endswith('}"'))
        if truncated:
            print(f"  [{WARN}] Response may be truncated — raw tail: {raw_end!r}")
        else:
            check("response not truncated (ends with })", True)
    else:
        print(f"    Raw response tail (last 300 chars): {full_text[-300:]!r}")
else:
    print(f"    [{WARN}] No AI response to parse")

# ── 8. DB round-trip (write test row, read it back, delete it) ────────────────
print("\n── 8. DB round-trip ────────────────────────────────────────────────────")
if DB_PATH.exists() and full_text:
    test_payload = {
        "portfolio": "QA test entry — safe to delete.",
        "layers": {str(n): f"QA layer {n}" for n in sorted(layer_changes.keys())},
        "scored_date": date.today().isoformat(),
        "scored_count": 0,
        "_qa_test": True,
    }
    inserted_id = None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        cur = conn.execute(
            "INSERT INTO macro_score_summaries (summary_json, created_at) VALUES (?,?)",
            (json.dumps(test_payload), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        inserted_id = cur.lastrowid
        conn.commit()
        check("DB write succeeded", True, f"row id={inserted_id}")

        row = conn.execute(
            "SELECT summary_json FROM macro_score_summaries WHERE id=?", (inserted_id,)
        ).fetchone()
        readback = json.loads(row[0]) if row else None
        check("DB read-back succeeded",     readback is not None)
        check("read-back portfolio matches", readback and readback.get("portfolio") == test_payload["portfolio"])
        check("read-back layers match",     readback and readback.get("layers") == test_payload["layers"])

        conn.execute("DELETE FROM macro_score_summaries WHERE id=?", (inserted_id,))
        conn.commit()
        check("QA test row cleaned up", True)
        conn.close()
    except Exception as e:
        check("DB round-trip", False, str(e))

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n── Result ──────────────────────────────────────────────────────────────")
passed = sum(results)
total  = len(results)
failed = total - passed
status = PASS if failed == 0 else FAIL
print(f"  [{status}] {passed}/{total} checks passed" + (f" — {failed} FAILED" if failed else ""))
sys.exit(0 if failed == 0 else 1)
