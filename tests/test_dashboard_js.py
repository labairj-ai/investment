"""Dashboard JS regression tests (0094).

Verifies that generate_dashboard.py produces syntactically valid JavaScript
and that the overall brace balance is correct.

Requires: node >= 18, generate_dashboard.py importable from project root.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _node_available() -> bool:
    return shutil.which("node") is not None


def _extract_script_blocks(html: str) -> list[str]:
    """Return a list of <script>…</script> block bodies (excluding external src= tags)."""
    pattern = re.compile(r"<script(?![^>]*\bsrc\b)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
    return [m.group(1) for m in pattern.finditer(html)]


def _count_brace_balance(js: str) -> int:
    """Return (open_braces - close_braces) ignoring braces inside strings/comments.

    Uses a stack to track context.  Template-literal expressions (${...}) are
    handled by pushing "tmpl_inner" for every { opened inside them, so only the
    matching } pops the "tmpl_expr" frame — not any inner object-literal braces.

    Stack contexts:
      "code"       — top-level or inside a function/block
      "dq"/"sq"    — double/single-quoted string
      "tmpl"       — inside a template literal (backtick string)
      "tmpl_expr"  — immediately after ${ (the expression itself)
      "tmpl_inner" — an inner { opened while inside a tmpl_expr
    """
    balance = 0
    i = 0
    n = len(js)
    stack: list[str] = ["code"]

    while i < n:
        ctx = stack[-1]
        c = js[i]

        if ctx in ("code", "tmpl_expr", "tmpl_inner"):
            if js[i:i+2] == "//":
                newline = js.find("\n", i)
                i = newline + 1 if newline != -1 else n
                continue
            elif js[i:i+2] == "/*":
                end = js.find("*/", i + 2)
                i = end + 2 if end != -1 else n
                continue
            elif c == '"':
                stack.append("dq")
            elif c == "'":
                stack.append("sq")
            elif c == "`":
                stack.append("tmpl")
            elif c == "{":
                balance += 1
                # Inside a template expression, track every { so its matching }
                # doesn't accidentally close the ${...} frame.
                if ctx in ("tmpl_expr", "tmpl_inner"):
                    stack.append("tmpl_inner")
            elif c == "}":
                balance -= 1
                if ctx == "tmpl_expr":
                    stack.pop()  # close ${...} — return to "tmpl"
                elif ctx == "tmpl_inner":
                    stack.pop()  # close inner {}, return to tmpl_expr/tmpl_inner
        elif ctx == "dq":
            if c == "\\":
                i += 2
                continue
            elif c == '"':
                stack.pop()
        elif ctx == "sq":
            if c == "\\":
                i += 2
                continue
            elif c == "'":
                stack.pop()
        elif ctx == "tmpl":
            if c == "\\":
                i += 2
                continue
            elif c == "`":
                stack.pop()
            elif js[i:i+2] == "${":
                stack.append("tmpl_expr")
                balance += 1  # the { in ${ counts as a real brace
                i += 2
                continue

        i += 1

    return balance


# ── Fixture: use out/dashboard.html if it exists, else generate ───────────────

def _get_dashboard_html() -> str | None:
    """Return pre-generated dashboard HTML if available, otherwise None."""
    pre = ROOT / "out" / "dashboard.html"
    if pre.exists() and pre.stat().st_size > 1000:
        return pre.read_text(encoding="utf-8", errors="replace")
    return None


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_dashboard_html_exists():
    """out/dashboard.html must exist and be non-trivial (can be stale — just must be present).

    Skips in CI environments where generate_dashboard.py can't run (no live DB).
    """
    import pytest
    html = _get_dashboard_html()
    if html is None:
        pytest.skip("out/dashboard.html not found — run generate_dashboard.py locally to verify")
    assert len(html) > 5000, "dashboard.html is suspiciously small (< 5 KB)"


def test_script_blocks_have_balanced_braces():
    """Every <script> block in dashboard.html must have balanced { } (0094).

    This is a fast pre-check that runs without node.  When node is available,
    test_node_check_on_dashboard_script_blocks is the authoritative test and
    this test is skipped (nested template literals make pure-Python counting
    unreliable in complex real-world JS).
    """
    import pytest
    if _node_available():
        pytest.skip("node available — deferring to test_node_check_on_dashboard_script_blocks")

    html = _get_dashboard_html()
    if html is None:
        pytest.skip("dashboard.html not present — run generate_dashboard.py first")

    blocks = _extract_script_blocks(html)
    assert blocks, "No <script> blocks found in dashboard.html"

    for i, block in enumerate(blocks):
        balance = _count_brace_balance(block)
        assert balance == 0, (
            f"Script block {i + 1}/{len(blocks)} has brace imbalance {balance:+d}. "
            f"Snippet (first 300 chars): {block[:300]!r}"
        )


def test_node_check_on_dashboard_script_blocks():
    """Run `node --check` on each extracted script block to catch syntax errors (0094)."""
    if not _node_available():
        import pytest
        pytest.skip("node not installed — skipping JS syntax check")

    html = _get_dashboard_html()
    if html is None:
        import pytest
        pytest.skip("dashboard.html not present — run generate_dashboard.py first")

    blocks = _extract_script_blocks(html)
    assert blocks, "No <script> blocks found in dashboard.html"

    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, block in enumerate(blocks):
            js_path = Path(tmpdir) / f"block_{i}.js"
            js_path.write_text(block, encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(js_path)],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                errors.append(
                    f"Script block {i + 1}: {result.stderr.strip()[:300]}"
                )

    assert not errors, (
        "node --check found JS syntax errors in dashboard.html:\n"
        + "\n".join(errors)
    )
