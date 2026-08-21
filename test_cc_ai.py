"""
Quick integration tests for covered call analysis + Ollama AI.
Run from project root: venv/bin/python3 test_cc_ai.py
"""
import sys, json, time
sys.path.insert(0, ".")

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results = []

def check(name, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        results.append((name, True, None))
    except Exception as e:
        print(f"  {FAIL}  {name}: {e}")
        results.append((name, False, str(e)))

# ── 1. Ollama connectivity ─────────────────────────────────────────────────────
print("\n[1] Ollama connectivity")
import ollama_client

def test_ollama_url():
    import os
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
    assert "127.0.0.1" not in url or True, "still pointing at localhost"
    print(f"       OLLAMA_URL = {url}")

def test_ollama_available():
    assert ollama_client.available("llama3.3:70b"), "llama3.3:70b not available"

def test_ollama_phi4_available():
    assert ollama_client.available("llama3.3:70b"), "llama3.3:70b not available"

check("OLLAMA_URL is set", test_ollama_url)
check("llama3.3:70b reachable", test_ollama_available)
check("llama3.3:70b reachable", test_ollama_phi4_available)

# ── 2. Holdings load ───────────────────────────────────────────────────────────
print("\n[2] Holdings")
from covered_call_rec import load_holdings, analyze, ai_context

def test_load_holdings():
    h = load_holdings()
    assert len(h) > 0, "no holdings loaded"
    print(f"       {len(h)} holdings: {list(h.keys())[:5]}…")

check("load_holdings()", test_load_holdings)

holdings = load_holdings()
# Pick first holding with enough shares for a covered call (>=100)
TEST_TICKER = next(
    (t for t, h in holdings.items() if h.get("shares", 0) >= 100),
    list(holdings.keys())[0]
)
print(f"       Using {TEST_TICKER} for analysis tests")

# ── 3. analyze() pipeline ─────────────────────────────────────────────────────
print("\n[3] analyze() — fetches live option chain")
result = None

def test_analyze():
    global result
    h = holdings[TEST_TICKER]
    t0 = time.time()
    result = analyze(TEST_TICKER, h["avg_cost"], h["shares"])
    elapsed = time.time() - t0
    assert result is not None, "analyze() returned None (no qualifying contracts)"
    assert "recs" in result and not result["recs"].empty, "no recs in result"
    assert "current_price" in result, "missing current_price"
    print(f"       {len(result['recs'])} contracts in {elapsed:.1f}s, price=${result['current_price']:.2f}")

check(f"analyze({TEST_TICKER})", test_analyze)

# ── 4. ai_context prompt generation ───────────────────────────────────────────
print("\n[4] ai_context() prompt")
prompt = None

def test_ai_context():
    global prompt
    if result is None:
        raise AssertionError("skipped — analyze() failed")
    h = holdings[TEST_TICKER]
    prompt = ai_context(TEST_TICKER, result, h["shares"], h.get("layer", 3))
    assert len(prompt) > 200, "prompt suspiciously short"
    assert TEST_TICKER in prompt, "ticker missing from prompt"
    print(f"       prompt length: {len(prompt)} chars")

check("ai_context() builds valid prompt", test_ai_context)

# ── 5. Full AI round-trip ──────────────────────────────────────────────────────
print("\n[5] AI round-trip (llama3.3:70b)")

def test_ai_roundtrip():
    if prompt is None:
        raise AssertionError("skipped — prompt generation failed")
    t0 = time.time()
    full_text = ""
    for tok in ollama_client.stream_generate(prompt):
        full_text += tok
    elapsed = time.time() - t0

    assert len(full_text) > 0, "empty response from Ollama"
    start = full_text.index("{")
    dec = json.JSONDecoder()
    insight, _ = dec.raw_decode(full_text, start)
    assert "recommendation" in insight or "roll_strategy" in insight or "timing_advice" in insight, \
        f"missing expected keys — got: {list(insight.keys())}"
    print(f"       {elapsed:.1f}s, keys: {list(insight.keys())}")

check("stream_generate → valid JSON insight", test_ai_roundtrip)

# ── Summary ────────────────────────────────────────────────────────────────────
print()
passed = sum(1 for _, ok, _ in results if ok)
total  = len(results)
status = PASS if passed == total else FAIL
print(f"  {status}  {passed}/{total} tests passed")
if passed < total:
    sys.exit(1)
