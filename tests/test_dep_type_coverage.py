"""Test: every dependency_type emitted in agents/ is registered in KNOWN_DEP_TYPES (0121).

Prevents regressions where a new dep type is added to an agent without a
corresponding checker entry — those silently supersede valid recommendations.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_PATTERN = re.compile(r'"dependency_type"\s*:\s*"([A-Z_]+)"')


def _collect_emitted_dep_types() -> set[str]:
    """Scan all .py files under agents/ for dependency_type string literals."""
    found: set[str] = set()
    for py_file in (ROOT / "agents").glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        found.update(_PATTERN.findall(text))
    return found


def test_all_dep_types_have_registered_checker():
    """Every dependency_type emitted anywhere in agents/ must be in KNOWN_DEP_TYPES."""
    from agents.dependency_checker import KNOWN_DEP_TYPES

    emitted = _collect_emitted_dep_types()
    assert emitted, "No dependency_type literals found — regex pattern may need updating"

    unknown = emitted - KNOWN_DEP_TYPES
    assert not unknown, (
        f"Unregistered dependency type(s): {sorted(unknown)}. "
        "Add to _KNOWN_DEPENDENCY_TYPES in agents/dependency_checker.py or fix the typo."
    )


def test_known_dep_types_is_nonempty_frozenset():
    """KNOWN_DEP_TYPES is a non-empty frozenset — sanity check on the export."""
    from agents.dependency_checker import KNOWN_DEP_TYPES

    assert isinstance(KNOWN_DEP_TYPES, frozenset)
    assert len(KNOWN_DEP_TYPES) >= 10, "Unexpectedly few known dep types — export may be broken"
