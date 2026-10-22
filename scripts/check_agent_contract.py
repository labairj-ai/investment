"""Read-only governance guard. Deliberate contract changes require human review.

Required clauses are exact, active Markdown content, not substring matches inside
comments or code examples. This detects accidental removal/weakening, not semantic
proof of arbitrary prose or enforcement of a future autonomous runner.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {
    '__preamble__': ('This contract applies equally to Codex, Claude and every other approved model, tool or runner working in this repository.',),
    'Mission': ('Implement approved, evidence-backed repository improvements with the smallest necessary change.',),
    'Source of record': (
        'The OptiPlex production database is authoritative for investment state.',
        'Development tasks must not write authoritative production data.',
        'Do not write investment data to a Mac development database or generate production artifacts (including dashboard.html) locally.',
    ),
    'Required workflow': (
        'Plan before code for non-trivial work:',
        'Run focused tests and required regression tests.',
        'Run the existing TODO consistency, exact release-baseline and CC behavioral contract gates unchanged,',
        '`pytest tests/ -v --tb=short --junitxml=test-results.xml`.',
        'Review the complete candidate diff,',
        'Record exact implementation SHA, commands, results, skip/waiver inventory and real CI workflow URL before claiming PR readiness.',
        'Move a TODO to `.todos/done/` only after every acceptance and QA requirement is met with implementation and CI evidence.',
    ),
    'Authority boundaries': ('This is not permission to deploy, schedule autonomous execution, access secrets, call external brokers, mutate accounts or alter live trading state.',),
    'Forbidden actions': (
        'Do not implement directly on main or push implementation directly to main.',
        'Do not self-approve or bypass independent review or required human approval.',
        'Do not delete or weaken tests to obtain PASS.',
        'Do not silently rewrite baselines or reduce acceptance thresholds.',
        'Do not modify secrets or log credentials.',
        'Do not call brokers or change live trading state.',
        'Do not deploy or mutate authoritative production data from development work.',
        'Do not treat missing evidence, user silence or model judgment as approval.',
        'Existing release, CI, production, canary and investment safety controls remain mandatory.',
    ),
    'Solo-owner governance': (
        'A second human reviewer is optional unless explicitly required by the owner',
        'Coding agents cannot approve their own work.',
        'Authorship is not approval; a new head invalidates prior approval.',
        'auto_merge=false and required_human_merge=true remain mandatory.',
        'The owner performs the final merge.',
    ),
    'Investment-sensitive changes': (
        'Recommendations, risk policy, position sizing, covered calls, learning/promotion, order/fill generation and account mutation are elevated-risk domains.',
        'Investment-sensitive changes require explicit human review before merge.',
    ),
    'Precedence and escalation': (
        'On safety-relevant conflicts, fail closed and escalate to the human.',
        'Changes to this contract or its validation require human review;',
    ),
    'Representative applications': ('A CSS-only mobile layout fix', 'A covered-call sizing or risk-policy change'),
}


def validate_contract(text: str) -> list[str]:
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = re.sub(r'^```[^\n]*\n.*?^```[^\n]*$', '', text, flags=re.M | re.S)
    sections = {'__preamble__': []}
    errors = []
    current = '__preamble__'
    for line in text.splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
            if current in sections:
                errors.append(f'duplicate section: {current}')
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    for title, clauses in REQUIRED.items():
        if title not in sections:
            errors.append(f'missing section: {title}')
            continue
        body = ' '.join(' '.join(sections[title]).split())
        for clause in clauses:
            if clause not in body:
                errors.append(f'{title}: missing required clause: {clause}')
    return errors


if __name__ == '__main__':
    try:
        errors = validate_contract((ROOT / 'AGENTS.md').read_text(encoding='utf-8'))
    except OSError as exc:
        errors = [str(exc)]
    for error in errors:
        print(f'[AGENT_CONTRACT] FAIL: {error}')
    if not errors:
        print('[AGENT_CONTRACT] OK')
    raise SystemExit(bool(errors))
