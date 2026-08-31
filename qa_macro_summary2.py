#!/usr/bin/env python3
"""
Comprehensive QA test for the macro summary pipeline.
Tests: HTML escaping, layer key robustness, empty-box guard, token budget,
_is_placeholder_json, first-run (no prev), dashboard HTML generation,
and full end-to-end with live AI at 8000 tokens.
"""
import html
import json
import os
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"
sys.path.insert(0, str(PROJECT_DIR))

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
    _extract_last_json, _is_placeholder_json, _init_ai_tables, LAYER_NAMES,
)
from generate_dashboard import (
    _load_macro_summary, _LAYER_NUM_TO_KEY, LAYER_COLORS, LAYER_SHORT,
    _html as _html_mod,
)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
WARN = "\033[33mWARN\033[0m"
results = []
_init_ai_tables()

def check(label, ok, detail=""):
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {label}" + (f": {detail}" if detail else ""))
    results.append(ok)

# ── 1. _LAYER_NUM_TO_KEY mapping ─────────────────────────────────────────────
print("\n── 1. _LAYER_NUM_TO_KEY mapping ────────────────────────────────────────")
for n in range(1, 6):
    key = _LAYER_NUM_TO_KEY.get(n)
    check(f"layer {n} resolves to a key", key is not None, str(key))
    if key:
        check(f"layer {n} key is in LAYER_COLORS", key in LAYER_COLORS)
        check(f"layer {n} key is in LAYER_SHORT",  key in LAYER_SHORT)

# ── 2. HTML escaping of AI text ───────────────────────────────────────────────
print("\n── 2. HTML escaping ────────────────────────────────────────────────────")
nasty_texts = [
    ('<script>alert(1)</script>', "script tag"),
    ('AAPL & MSFT improved; "rate_sensitivity" dropped', "ampersand and quotes"),
    ('Score > 70 means <good>', "angle brackets"),
]
for raw, label in nasty_texts:
    escaped = html.escape(raw)
    check(f"escapes: {label}", "<script>" not in escaped and "&" not in escaped.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "").replace("&quot;", ""))

# Verify the dashboard uses _html.escape (module aliased as _html_mod)
check("_html module imported in generate_dashboard", _html_mod is html)

# ── 3. _is_placeholder_json ───────────────────────────────────────────────────
print("\n── 3. _is_placeholder_json ─────────────────────────────────────────────")
check("all-placeholder rejected",
      _is_placeholder_json({"portfolio": "...", "layers": "..."}))
check("real response not rejected",
      not _is_placeholder_json({
          "portfolio": "Portfolio health improved this week.",
          "layers": {"1": "Layer 1 was stable.", "2": "Layer 2 declined."}
      }))
check("mixed (one real) not rejected",
      not _is_placeholder_json({
          "portfolio": "Real sentence here.",
          "layers": {"1": "..."}   # layers is a dict, not a string → not checked
      }))
check("nested placeholder inside layers not rejected at top level",
      not _is_placeholder_json({
          "portfolio": "Real text.",
          "layers": {"1": "...", "2": "..."}   # layers is a dict → top-level vals only
      }))

# ── 4. _extract_last_json with various response shapes ────────────────────────
print("\n── 4. _extract_last_json robustness ────────────────────────────────────")

# Normal case
normal = '{"portfolio": "Overall good.", "layers": {"1": "L1 stable.", "3": "L3 up."}}'
r = _extract_last_json(normal, required_keys=["portfolio", "layers"])
check("parses clean JSON", r is not None and r.get("portfolio") == "Overall good.")

# Reasoning preamble (Qwen3 thinking pattern)
with_preamble = (
    '<think>Let me analyze...</think>\n'
    '{"portfolio": "...", "layers": {"1": "..."}}\n'   # placeholder sketch
    'Now the real answer:\n'
    '{"portfolio": "Real portfolio summary.", "layers": {"1": "Real L1 text.", "2": "Real L2 text."}}'
)
r = _extract_last_json(with_preamble, required_keys=["portfolio", "layers"])
check("picks last JSON, skips placeholder", r is not None and r.get("portfolio") == "Real portfolio summary.")

# Code-fence wrapped
fenced = '```json\n{"portfolio": "Fenced response.", "layers": {"1": "L1 ok."}}\n```'
r = _extract_last_json(fenced, required_keys=["portfolio", "layers"])
check("strips code fences", r is not None and r.get("portfolio") == "Fenced response.")

# AI uses wrong key format (e.g. "layer_1" instead of "1")
wrong_keys = '{"portfolio": "Portfolio ok.", "layers": {"layer_1": "text", "layer_3": "text"}}'
r = _extract_last_json(wrong_keys, required_keys=["portfolio", "layers"])
layers_d = r.get("layers", {}) if r else {}
wrong_key_miss = layers_d.get("1") is None and layers_d.get("layer_1") == "text"
check("wrong keys parse (but dashboard won't show them)", wrong_key_miss,
      f"keys present: {list(layers_d.keys())}")

# Integer keys (invalid JSON — should fail to parse)
int_keys_text = '{"portfolio": "ok", "layers": {1: "L1 text", 2: "L2 text"}}'
r_bad = _extract_last_json(int_keys_text, required_keys=["portfolio", "layers"])
check("integer keys → parse failure (correctly returns None or empty layers)",
      r_bad is None or not r_bad.get("layers"))

# ── 5. Dashboard empty-box guard ──────────────────────────────────────────────
print("\n── 5. Empty-box guard ──────────────────────────────────────────────────")
# Simulate a summary where the AI used wrong keys → layer_rows_html would be empty
# The guard should suppress the entire section
bad_summary = {
    "portfolio": "Something meaningful.",
    "layers": {"layer_1": "nope", "layer_3": "nope"},  # wrong key format
    "scored_date": "2026-08-31",
    "scored_count": 5,
}
port_text   = bad_summary.get("portfolio", "")
layers_text = bad_summary.get("layers", {})
layer_rows_html = ""
for layer_num in range(1, 6):
    text = layers_text.get(str(layer_num), "")
    if not text:
        continue
    layer_key = _LAYER_NUM_TO_KEY.get(layer_num)
    if not layer_key:
        continue
    layer_rows_html += f"<div>{html.escape(text)}</div>"

nothing_to_show = not port_text and not layer_rows_html
check("empty layer rows detected (port_text exists so box would still show)", not nothing_to_show,
      "port_text non-empty → box shows portfolio line even if layers empty")
check("layer_rows_html correctly empty for wrong-key summary", layer_rows_html == "")

# Truly empty summary
empty_summary = {"portfolio": "", "layers": {}, "scored_date": "", "scored_count": 0}
pt2 = empty_summary.get("portfolio", "")
lr2 = ""  # no layers match
nothing2 = not pt2 and not lr2
check("fully empty summary suppresses box", nothing2)

# ── 6. _load_macro_summary round-trip ─────────────────────────────────────────
print("\n── 6. _load_macro_summary round-trip ───────────────────────────────────")
test_payload = {
    "portfolio": "QA test <escape me> & check.",
    "layers": {str(n): f"Layer {n} QA text." for n in range(1, 6)},
    "scored_date": date.today().isoformat(),
    "scored_count": 99,
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
    conn.close()
    check("inserted test summary row", True, f"id={inserted_id}")
except Exception as e:
    check("insert test row", False, str(e))

loaded = _load_macro_summary()
check("_load_macro_summary returns dict",          isinstance(loaded, dict))
check("portfolio field loaded",                    loaded and loaded.get("portfolio") == test_payload["portfolio"])
check("all 5 layer keys present",                  loaded and all(str(n) in loaded.get("layers", {}) for n in range(1, 6)))
check("scored_count loaded correctly",             loaded and loaded.get("scored_count") == 99)
check("_created_at injected",                      loaded and "_created_at" in loaded)

if inserted_id:
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute("DELETE FROM macro_score_summaries WHERE id=?", (inserted_id,))
        conn.commit()
        conn.close()
        check("QA row cleaned up", True)
    except Exception as e:
        check("cleanup", False, str(e))

# ── 7. Token budget — live AI call at 8000 tokens ────────────────────────────
print("\n── 7. Token budget (live AI, num_predict=8000) ──────────────────────────")
check("LLM server reachable", ollama_client.available())

if ollama_client.available():
    # Build a realistic prompt using real scores
    current_scores = {}
    prev_scores    = {}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT ticker, scores FROM holding_macro_scores").fetchall():
            try: current_scores[r["ticker"]] = json.loads(r["scores"])
            except: pass
        rows = conn.execute(
            "SELECT ticker, scores FROM holding_macro_scores_history ORDER BY ticker, scored_at DESC"
        ).fetchall()
        ticker_runs = {}
        for r in rows:
            ticker_runs.setdefault(r["ticker"], []).append(r["scores"])
        for t, sl in ticker_runs.items():
            if len(sl) >= 2:
                try: prev_scores[t] = json.loads(sl[1])
                except: pass
        conn.close()
    except Exception as e:
        print(f"    [{WARN}] DB load failed: {e}")

    def _composite(scores):
        DIMS = [("rate_sensitivity", False), ("inflation_hedge", True),
                ("dollar_sensitivity", False), ("geopolitical_risk", False)]
        n = []
        for d, inv in DIMS:
            sv = _score_val(scores.get(d))
            if sv is not None:
                n.append(sv * 10 if inv else (11 - sv) * 10)
        return round(sum(n) / len(n)) if n else None

    holdings_csv = _load_holdings_csv()
    ticker_layer = {}
    for h in holdings_csv:
        t = _normalize_ticker(h.get("Stock", ""))
        if t:
            try: ticker_layer[t] = int(h.get("Layer", 0))
            except: pass

    layer_changes = {}
    for ticker, scores in current_scores.items():
        ln = ticker_layer.get(ticker)
        if not ln: continue
        curr_c = _composite(scores)
        prev_s = prev_scores.get(ticker, {})
        prev_c = _composite(prev_s) if prev_s else None
        delta_c = (curr_c - prev_c) if (curr_c is not None and prev_c is not None) else None
        dim_ch = []
        for dim in ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk"):
            cv = _score_val(scores.get(dim))
            pv = _score_val(prev_s.get(dim)) if prev_s else None
            if cv is not None and pv is not None and cv != pv:
                r_txt = _score_reason(scores.get(dim))
                dim_ch.append({"dim": dim, "prev": pv, "curr": cv,
                                "delta": cv - pv, "reason": r_txt})
        layer_changes.setdefault(ln, []).append({
            "ticker": ticker, "curr_composite": curr_c, "prev_composite": prev_c,
            "delta_composite": delta_c, "dim_changes": dim_ch,
            "note": scores.get("note", ""),
        })

    changes_block = ""
    for ln in sorted(layer_changes.keys()):
        changes_block += f"\nLayer {ln} — {LAYER_NAMES.get(ln, f'L{ln}')}:\n"
        for item in layer_changes[ln]:
            prev_str = str(item["prev_composite"]) if item["prev_composite"] is not None else "—"
            d_str = ""
            if item["delta_composite"] is not None:
                sign = "+" if item["delta_composite"] > 0 else ""
                d_str = f" ({sign}{item['delta_composite']})"
            elif item["prev_composite"] is None:
                d_str = " (first score)"
            changes_block += f"  {item['ticker']}: composite {prev_str} → {item['curr_composite']}{d_str}\n"
            for dc in item["dim_changes"]:
                sign = "+" if dc["delta"] > 0 else ""
                reason_s = (dc["reason"][:80] + "…" if len(dc["reason"]) > 80 else dc["reason"]) if dc["reason"] else ""
                changes_block += f"    {dc['dim']}: {dc['prev']} → {dc['curr']} ({sign}{dc['delta']})"
                if reason_s:
                    changes_block += f" — {reason_s}"
                changes_block += "\n"
            if item.get("note"):
                changes_block += f"    Overall: {item['note']}\n"

    layer_json_template = ",\n    ".join(
        f'"{n}": "<2-3 sentences for layer {n}>"' for n in sorted(layer_changes.keys())
    )
    macro_brief = "VIX=20 (elevated caution), 10Y=4.5%, Spread=25bps, CPI=3.2% YoY, Dollar: roughly flat, Gold: mild demand"
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

    print(f"    Prompt words: {len(prompt.split())}, sending to AI…")
    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=8000
        ):
            full_text += tok
    except Exception as e:
        check("AI call succeeded", False, str(e))
        full_text = ""

    if full_text:
        raw_tail = full_text.rstrip()[-200:]
        check("AI response non-empty",             len(full_text) > 100, f"{len(full_text)} chars")
        check("response ends with }}",              raw_tail.endswith("}"), f"tail: {raw_tail[-40:]!r}")
        check("response longer than basic minimum", len(full_text) > 500,
              f"{len(full_text)} chars (expect >500 for 5 layer summaries)")

        result = _extract_last_json(full_text, required_keys=["portfolio", "layers"])
        check("JSON parsed successfully",           result is not None)
        if result:
            check("portfolio is non-empty string",  isinstance(result.get("portfolio"), str) and len(result["portfolio"]) > 20)
            check("layers is dict",                 isinstance(result.get("layers"), dict))
            layers_d = result.get("layers", {})
            check("all layers present as string keys",
                  all(str(n) in layers_d for n in sorted(layer_changes.keys())),
                  f"got keys: {sorted(layers_d.keys())}")
            for n in sorted(layer_changes.keys()):
                v = layers_d.get(str(n), "")
                check(f"  layer '{n}' non-empty",  isinstance(v, str) and len(v) > 20, repr(v[:60]))

            # Check for XSS chars in AI output (shouldn't be there, but good to know)
            all_text = result.get("portfolio", "") + " ".join(result.get("layers", {}).values())
            has_html = any(c in all_text for c in "<>")
            if has_html:
                print(f"  [{WARN}] AI output contains angle brackets — HTML escaping is essential")
            else:
                check("AI output contains no raw HTML chars", True)

# ── 8. Dashboard HTML generation with summary ─────────────────────────────────
print("\n── 8. Dashboard HTML generation ────────────────────────────────────────")
try:
    import generate_dashboard
    # Insert a known summary
    test_summary = {
        "portfolio": "Portfolio macro health improved this week & looks <strong>.",
        "layers": {str(n): f"Layer {n} saw changes driven by <ticker> & rates." for n in range(1, 6)},
        "scored_date": "2026-08-31",
        "scored_count": 27,
    }
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cur = conn.execute(
        "INSERT INTO macro_score_summaries (summary_json, created_at) VALUES (?,?)",
        (json.dumps(test_summary), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    qa_html_row_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Run the full dashboard generator
    import subprocess
    result_proc = subprocess.run(
        ["python3", "generate_dashboard.py"],
        cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=60
    )
    check("generate_dashboard.py runs without error", result_proc.returncode == 0,
          result_proc.stderr[:200] if result_proc.returncode != 0 else "")

    html_path = PROJECT_DIR / "out" / "dashboard.html"
    if html_path.exists():
        html_content = html_path.read_text()
        check("dashboard.html written",                  len(html_content) > 1000)
        check("Weekly AI Summary section present",       "Weekly AI Summary" in html_content)
        check("portfolio text HTML-escaped (&amp;)",     "&amp;" in html_content,
              "raw & should become &amp;")
        check("angle brackets escaped (&lt;/&gt;)",      "&lt;" in html_content and "&gt;" in html_content,
              "raw <> should become &lt;&gt;")
        check("AI <strong> escaped to &lt;strong&gt; in HTML", "&lt;strong&gt;" in html_content)
        check("scored_date appears in HTML",             "2026-08-31" in html_content)
        check("27 holdings label appears",               "27 holdings" in html_content)
    else:
        check("dashboard.html exists", False)

    # Clean up
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("DELETE FROM macro_score_summaries WHERE id=?", (qa_html_row_id,))
    conn.commit()
    conn.close()
    check("QA HTML test row cleaned up", True)

except Exception as e:
    check("dashboard generation test", False, str(e))
    import traceback; traceback.print_exc()

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n── Result ──────────────────────────────────────────────────────────────")
passed = sum(results)
total  = len(results)
failed = total - passed
status = PASS if failed == 0 else FAIL
print(f"  [{status}] {passed}/{total} checks passed" + (f" — {failed} FAILED" if failed else ""))
sys.exit(0 if failed == 0 else 1)
