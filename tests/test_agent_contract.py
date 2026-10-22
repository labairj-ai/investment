"""Mutation coverage for the shared repository contract; no production access."""
from pathlib import Path

import pytest

from scripts.check_agent_contract import REQUIRED, validate_contract

CONTRACT = (Path(__file__).resolve().parents[1] / 'AGENTS.md').read_text()


def test_repository_contract():
    assert validate_contract(CONTRACT) == []


@pytest.mark.parametrize('title', [title for title in REQUIRED if title != '__preamble__'])
def test_required_section_cannot_disappear(title):
    assert validate_contract(CONTRACT.replace('## ' + title, '## Removed', 1))


@pytest.mark.parametrize('title,clause', [(title, clause) for title, clauses in REQUIRED.items() for clause in clauses])
def test_required_clause_cannot_be_removed_or_hidden(title, clause):
    # Flatten Markdown wrapping without changing the meaning of the original.
    flat = '\n'.join(' '.join(block.split()) for block in CONTRACT.split('\n\n'))
    assert clause in flat
    for replacement in ('', '<!-- ' + clause + ' -->', 'Optional policy.'):
        assert validate_contract(flat.replace(clause, replacement, 1)), (title, clause)


@pytest.mark.parametrize('old,new', [
    ('Do not delete or weaken tests', 'You may delete or weaken tests'),
    ('Do not silently rewrite baselines', 'You may silently rewrite baselines'),
    ('require explicit human review before merge', 'may skip human review before merge'),
    ('fail closed and escalate to the human', 'continue without human review'),
])
def test_weakened_safety_language_fails(old, new):
    assert validate_contract(CONTRACT.replace(old, new))


def test_empty_or_example_only_contract_fails():
    assert validate_contract('')
    assert validate_contract('```markdown\n' + CONTRACT + '\n```')
    assert validate_contract('<!--\n' + CONTRACT + '\n-->')


def test_duplicate_sections_fail():
    assert validate_contract(CONTRACT + '\n## Forbidden actions\nOptional.\n')


def test_low_and_high_risk_applications_preserve_controls():
    examples = CONTRACT.split('## Representative applications\n', 1)[1]
    assert 'CSS-only' in examples and 'viewport checks' in examples
    assert 'SHA-bound evidence and a PR' in examples
    assert 'covered-call sizing or risk-policy change' in examples
    assert 'requires explicit human review' in examples
    assert 'preserve the existing thresholds' in examples
