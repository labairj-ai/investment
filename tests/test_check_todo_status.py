"""Tests for scripts/check_todo_status.py"""
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from check_todo_status import check_consistency, parse_todo_file


def _write_todo(tmp_path, folder, filename, todo_id, status, extra_content=''):
    folder_path = tmp_path / folder
    folder_path.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        # Example TODO

        - **ID:** {todo_id}
        - **Status:** {status}
        - **Created:** 2026-01-01
        - **Priority:** normal
        - **Depends:** none

        {extra_content}
    """)
    (folder_path / filename).write_text(content)
    return folder_path


class TestParseTodoFile:
    def test_parses_id_and_status(self, tmp_path):
        _write_todo(tmp_path, '.', 'test.md', '0001', 'backlog')
        meta = parse_todo_file(tmp_path / 'test.md')
        assert meta is not None
        assert meta['todo_id'] == '0001'
        assert meta['status'] == 'backlog'

    def test_returns_none_for_non_todo(self, tmp_path):
        f = tmp_path / 'readme.md'
        f.write_text('# Just a readme\nNo structured fields here.\n')
        assert parse_todo_file(f) is None

    def test_returns_none_when_id_missing(self, tmp_path):
        f = tmp_path / 'partial.md'
        f.write_text('# Partial\n\n- **Status:** backlog\n')
        assert parse_todo_file(f) is None

    def test_returns_none_when_status_missing(self, tmp_path):
        f = tmp_path / 'partial.md'
        f.write_text('# Partial\n\n- **ID:** 0001\n')
        assert parse_todo_file(f) is None

    def test_status_normalized_to_lowercase(self, tmp_path):
        f = tmp_path / 'test.md'
        f.write_text('# T\n\n- **ID:** 0002\n- **Status:** Backlog\n')
        meta = parse_todo_file(f)
        assert meta['status'] == 'backlog'


class TestCheckConsistency:
    def test_done_folder_with_open_status_flagged(self, tmp_path):
        done_dir = tmp_path / 'done'
        _write_todo(tmp_path, 'done', '0001-test.md', '0001', 'backlog')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert not result['passed']
        violations = result['violations']
        assert len(violations) == 1
        assert violations[0]['rule'] == 'DONE_FOLDER_OPEN_STATUS'
        assert violations[0]['todo_id'] == '0001'
        assert violations[0]['status'] == 'backlog'

    def test_done_folder_with_in_progress_flagged(self, tmp_path):
        done_dir = tmp_path / 'done'
        _write_todo(tmp_path, 'done', '0002-test.md', '0002', 'in-progress')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert not result['passed']
        assert result['violations'][0]['status'] == 'in-progress'

    def test_done_folder_with_done_status_passes(self, tmp_path):
        done_dir = tmp_path / 'done'
        _write_todo(tmp_path, 'done', '0003-test.md', '0003', 'done')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert result['passed']
        assert result['violations'] == []

    def test_open_folder_with_done_status_flagged(self, tmp_path):
        done_dir = tmp_path / 'done'
        done_dir.mkdir()
        _write_todo(tmp_path, '.', '0004-test.md', '0004', 'done')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert not result['passed']
        violations = result['violations']
        assert len(violations) == 1
        assert violations[0]['rule'] == 'OPEN_FOLDER_DONE_STATUS'
        assert violations[0]['todo_id'] == '0004'

    def test_open_folder_with_backlog_passes(self, tmp_path):
        done_dir = tmp_path / 'done'
        done_dir.mkdir()
        _write_todo(tmp_path, '.', '0005-test.md', '0005', 'backlog')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert result['passed']

    def test_non_todo_markdown_is_ignored(self, tmp_path):
        done_dir = tmp_path / 'done'
        done_dir.mkdir()
        # Non-TODO in done/ (no ID field)
        f = done_dir / 'notes.md'
        f.write_text('# Notes\nJust documentation, no structured fields.\n')
        # Non-TODO in open todos/
        f2 = tmp_path / 'readme.md'
        f2.write_text('# Readme\nGeneral notes.\n')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert result['passed']
        assert result['violations'] == []

    def test_multiple_violations_all_reported(self, tmp_path):
        done_dir = tmp_path / 'done'
        _write_todo(tmp_path, 'done', '0010-test.md', '0010', 'backlog')
        _write_todo(tmp_path, 'done', '0011-test.md', '0011', 'in-progress')
        _write_todo(tmp_path, '.', '0012-test.md', '0012', 'done')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert not result['passed']
        assert len(result['violations']) == 3

    def test_missing_done_dir_no_crash(self, tmp_path):
        done_dir = tmp_path / 'done'  # does not exist
        _write_todo(tmp_path, '.', '0020-test.md', '0020', 'backlog')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert result['passed']

    def test_clean_state_passes(self, tmp_path):
        done_dir = tmp_path / 'done'
        _write_todo(tmp_path, 'done', '0030-test.md', '0030', 'done')
        _write_todo(tmp_path, '.', '0031-test.md', '0031', 'backlog')
        result = check_consistency(todos_dir=tmp_path, done_dir=done_dir)
        assert result['passed']

    def test_real_repo_passes(self):
        """Current repo state should pass with no violations."""
        result = check_consistency()
        assert result['passed'], (
            f"Real repo has {len(result['violations'])} violation(s): "
            + ', '.join(f"{v['path']} ({v['rule']})" for v in result['violations'])
        )
