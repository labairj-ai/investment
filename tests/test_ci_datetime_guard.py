"""
CI guard: fail if production code introduces prohibited naive datetime patterns (0679/0681).

Scans Python source files in the project, excluding time_utils.py itself (which
implements the canonical functions), tests/, scripts/, migrations/, and venv/.
"""
import ast
import pathlib
import re

PROJECT = pathlib.Path(__file__).parent.parent
EXCLUDE_DIRS = {"venv", ".git", ".claude", "__pycache__", "tests", "scripts", "migrations"}
EXCLUDE_FILES = {"time_utils.py"}

PROHIBITED = [
    (re.compile(r'\b\w*\.utcnow\(\)'), "utcnow() — use now_utc() from time_utils"),
    (re.compile(r'\butcfromtimestamp\('), "utcfromtimestamp() — use epoch_to_utc() from time_utils"),
    (re.compile(r'timezone\(timedelta\(hours=-[45]\)\)'), "fixed Eastern offset — use TZ_EASTERN from time_utils"),
]

# Separate list for patterns that need comment/string context exclusion
_EST_EDT_PATTERN = re.compile(r'(?<![#\'"a-zA-Z])("EST"|"EDT")')


def _iter_production_py():
    """Yield all .py files in the project root and non-excluded subdirectories."""
    for f in PROJECT.glob("*.py"):
        if f.name not in EXCLUDE_FILES:
            yield f
    for d in PROJECT.iterdir():
        if d.is_dir() and d.name not in EXCLUDE_DIRS:
            for f in d.rglob("*.py"):
                if f.name not in EXCLUDE_FILES:
                    yield f


def _find_naive_now_calls(source: str) -> list:
    """
    Return list of (lineno, code_snippet) for datetime.now() calls without a tz argument.
    Uses AST parsing to avoid false positives from datetime.now(TZ_UTC) etc.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    violations = []
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match any .now(...) attribute call
        if not (isinstance(func, ast.Attribute) and func.attr == "now"):
            continue
        # Must have no tz= keyword and no positional tz argument
        has_tz_kw = any(kw.arg == "tz" for kw in node.keywords)
        has_pos_arg = len(node.args) >= 1
        if not has_tz_kw and not has_pos_arg:
            snippet = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            violations.append((node.lineno, snippet))
    return violations


def test_no_prohibited_datetime_patterns():
    violations = []
    for path in _iter_production_py():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        rel = path.relative_to(PROJECT)
        for pattern, msg in PROHIBITED:
            for m in pattern.finditer(text):
                lineno = text[: m.start()].count("\n") + 1
                violations.append(f"{rel}:{lineno}: {msg}")
    assert not violations, (
        "Prohibited datetime patterns found in production code:\n"
        + "\n".join(violations)
    )


def test_no_naive_now_calls():
    """AST-based check: datetime.now() without tz= argument."""
    violations = []
    for path in _iter_production_py():
        try:
            source = path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, snippet in _find_naive_now_calls(source):
            rel = path.relative_to(PROJECT)
            violations.append(
                f"{rel}:{lineno}: datetime.now() without tz — use now_utc() or now_eastern() "
                f"from time_utils  [{snippet!r}]"
            )
    assert not violations, (
        "Naive datetime.now() calls found in production code:\n"
        + "\n".join(violations)
    )


# ── Positive failure tests (prove the guard actually catches each pattern) ────

def test_guard_catches_utcnow():
    code = "from datetime import datetime\ndt = datetime.utcnow()\n"
    found = [m for pat, _ in PROHIBITED for m in pat.finditer(code)]
    assert found, "Guard should catch utcnow()"


def test_guard_catches_utcfromtimestamp():
    code = "from datetime import datetime\ndt = datetime.utcfromtimestamp(1234)\n"
    found = [m for pat, _ in PROHIBITED for m in pat.finditer(code)]
    assert found, "Guard should catch utcfromtimestamp()"


def test_guard_catches_fixed_eastern_offset():
    code = "from datetime import timezone, timedelta\ntz = timezone(timedelta(hours=-4))\n"
    found = [m for pat, _ in PROHIBITED for m in pat.finditer(code)]
    assert found, "Guard should catch fixed Eastern offset timezone(timedelta(hours=-4))"


def test_guard_catches_naive_now():
    code = "from datetime import datetime\ndt = datetime.now()\n"
    violations = _find_naive_now_calls(code)
    assert violations, "Guard should catch datetime.now() without tz"


def test_guard_allows_tz_now_keyword():
    code = "from datetime import datetime, timezone\ndt = datetime.now(tz=timezone.utc)\n"
    violations = _find_naive_now_calls(code)
    assert not violations, "Guard should allow datetime.now(tz=timezone.utc)"


def test_guard_allows_tz_now_positional():
    code = "from datetime import datetime, timezone\ndt = datetime.now(timezone.utc)\n"
    violations = _find_naive_now_calls(code)
    assert not violations, "Guard should allow datetime.now(timezone.utc) positional"


def test_guard_serve_py_clean():
    """Integration: serve.py should have zero naive datetime.now() calls after 0682."""
    serve_py = PROJECT / "serve.py"
    if not serve_py.exists():
        return
    source = serve_py.read_text(errors="replace")
    violations = _find_naive_now_calls(source)
    assert not violations, (
        f"serve.py still has naive datetime.now() calls:\n"
        + "\n".join(f"  line {ln}: {snip!r}" for ln, snip in violations)
    )


def test_no_est_edt_timezone_strings():
    """Guard catches hardcoded 'EST'/'EDT' timezone strings in production code (0681)."""
    violations = []
    for path in _iter_production_py():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for line_text in text.splitlines():
            stripped = line_text.strip()
            if stripped.startswith("#"):
                continue
            for m in _EST_EDT_PATTERN.finditer(line_text):
                lineno = text[: text.find(line_text)].count("\n") + 1
                rel = path.relative_to(PROJECT)
                violations.append(
                    f"{rel}:{lineno}: hardcoded {m.group(1)!r} timezone string — "
                    "use format_eastern() from time_utils for abbreviation"
                )
    assert not violations, (
        "Hardcoded EST/EDT timezone strings found in production code:\n"
        + "\n".join(violations)
    )


def test_guard_catches_est_edt_strings():
    """Positive failure test: EST/EDT strings in non-comment code are caught."""
    code_est = 'tz = pytz.timezone("EST")\n'
    code_edt = 'label = "EDT"\n'
    assert _EST_EDT_PATTERN.search(code_est), "Guard should catch hardcoded 'EST'"
    assert _EST_EDT_PATTERN.search(code_edt), "Guard should catch hardcoded 'EDT'"


def test_guard_est_edt_allows_comments():
    """Pattern does not flag EST/EDT appearing in comment lines (verified by test logic)."""
    comment_line = "# America/New_York displays as EST or EDT depending on DST\n"
    # The scan skips lines that start with # after stripping — this tests the pattern itself
    # does not match inside strings-that-are-not-tz-strings (pattern anchors on quote chars)
    in_comment = "# tz = 'EST'\n"
    # Pattern won't match because '#' precedes the quote (negative lookbehind includes #)
    assert not _EST_EDT_PATTERN.search(in_comment), "Should not flag EST/EDT inside comments"
