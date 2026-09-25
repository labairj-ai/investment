"""
CI guard: fail if production code introduces prohibited naive datetime patterns (0679).

Scans Python source files in the project, excluding time_utils.py itself (which
implements the canonical functions), tests/, scripts/, migrations/, and venv/.
"""
import pathlib
import re

PROJECT = pathlib.Path(__file__).parent.parent
EXCLUDE_DIRS = {"venv", ".git", ".claude", "__pycache__", "tests", "scripts", "migrations"}
EXCLUDE_FILES = {"time_utils.py"}

PROHIBITED = [
    (re.compile(r'\b\w*\.utcnow\(\)'), "utcnow() — use now_utc() from time_utils"),
    (re.compile(r'\butcfromtimestamp\('), "utcfromtimestamp() — use epoch_to_utc() from time_utils"),
]


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


def test_no_prohibited_datetime_patterns():
    violations = []
    for path in _iter_production_py():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for pattern, msg in PROHIBITED:
            for m in pattern.finditer(text):
                lineno = text[: m.start()].count("\n") + 1
                violations.append(
                    f"{path.relative_to(PROJECT)}:{lineno}: {msg}"
                )
    assert not violations, (
        "Prohibited datetime patterns found in production code:\n"
        + "\n".join(violations)
    )
