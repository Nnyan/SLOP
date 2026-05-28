"""
Tests for tools.ms_deps.diff — lockfile diff tool.

All tests use synthetic uv.lock content (no network, no real lockfile mutations).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

from tools.ms_deps.diff import (
    DiffRow,
    _classify_change,
    _load_packages,
    compute_diff,
    main,
    _format_markdown,
    _format_json,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal valid uv.lock content
# ---------------------------------------------------------------------------

def _write_lock(content: str) -> Path:
    """Write content to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        suffix=".lock", mode="w", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


LOCK_ALPHA_1_0_0 = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "alpha"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.3.4"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_ALPHA_1_0_1 = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "alpha"
version = "1.0.1"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.3.4"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_ALPHA_MINOR = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "alpha"
version = "1.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.3.4"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_ALPHA_MAJOR = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "alpha"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.3.4"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_WITH_GAMMA = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "alpha"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "beta"
version = "2.3.4"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "gamma"
version = "0.5.0"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_WITHOUT_BETA = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "alpha"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }
"""

LOCK_INVALID_TOML = """\
version = 1
this is not valid TOML !!!
[[broken
"""

LOCK_NO_PACKAGES = """\
version = 1
requires-python = ">=3.12"

[metadata]
lock-version = "1"
"""


# ---------------------------------------------------------------------------
# Unit tests for _classify_change
# ---------------------------------------------------------------------------

class TestClassifyChange:
    def test_unchanged(self):
        assert _classify_change("1.2.3", "1.2.3") == "unchanged"

    def test_patch_up(self):
        assert _classify_change("1.0.0", "1.0.1") == "patch↑"

    def test_patch_down(self):
        assert _classify_change("1.0.5", "1.0.2") == "patch↓"

    def test_minor_up(self):
        assert _classify_change("1.0.3", "1.1.0") == "minor↑"

    def test_minor_down(self):
        assert _classify_change("1.2.0", "1.1.0") == "minor↓"

    def test_major_up(self):
        assert _classify_change("1.5.3", "2.0.0") == "major↑"

    def test_major_down(self):
        assert _classify_change("3.0.0", "1.0.0") == "major↓"

    def test_exotic_version_falls_back(self):
        # Non-standard version strings should return "changed" (not error)
        result = _classify_change("1.0.0.post1", "1.0.0.post2")
        # Both can't be parsed as simple X.Y.Z → "changed"
        assert result == "changed"

    def test_two_part_version(self):
        # X.Y treated as X.Y.0 — minor bump
        assert _classify_change("1.0", "1.1") == "minor↑"


# ---------------------------------------------------------------------------
# Tests for _load_packages
# ---------------------------------------------------------------------------

class TestLoadPackages:
    def test_load_valid_lock(self):
        p = _write_lock(LOCK_ALPHA_1_0_0)
        pkgs = _load_packages(p)
        assert pkgs == {"alpha": "1.0.0", "beta": "2.3.4"}

    def test_missing_file_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            _load_packages(Path("/nonexistent/path/uv.lock"))
        assert exc_info.value.code == 1

    def test_invalid_toml_exits(self):
        p = _write_lock(LOCK_INVALID_TOML)
        with pytest.raises(SystemExit) as exc_info:
            _load_packages(p)
        assert exc_info.value.code == 1

    def test_no_package_tables_exits(self):
        p = _write_lock(LOCK_NO_PACKAGES)
        with pytest.raises(SystemExit) as exc_info:
            _load_packages(p)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Tests for compute_diff
# ---------------------------------------------------------------------------

class TestComputeDiff:
    def test_added_package(self):
        old = {"alpha": "1.0.0"}
        new = {"alpha": "1.0.0", "gamma": "0.5.0"}
        rows = compute_diff(old, new)
        gamma_row = next(r for r in rows if r.name == "gamma")
        assert gamma_row.old is None
        assert gamma_row.new == "0.5.0"
        assert gamma_row.change == "added"

    def test_removed_package(self):
        old = {"alpha": "1.0.0", "beta": "2.3.4"}
        new = {"alpha": "1.0.0"}
        rows = compute_diff(old, new)
        beta_row = next(r for r in rows if r.name == "beta")
        assert beta_row.old == "2.3.4"
        assert beta_row.new is None
        assert beta_row.change == "removed"

    def test_patch_bump(self):
        old = {"alpha": "1.0.0"}
        new = {"alpha": "1.0.1"}
        rows = compute_diff(old, new)
        assert rows[0].change == "patch↑"

    def test_minor_bump(self):
        old = {"alpha": "1.0.0"}
        new = {"alpha": "1.1.0"}
        rows = compute_diff(old, new)
        assert rows[0].change == "minor↑"

    def test_major_bump(self):
        old = {"alpha": "1.0.0"}
        new = {"alpha": "2.0.0"}
        rows = compute_diff(old, new)
        assert rows[0].change == "major↑"

    def test_no_changes_all_unchanged(self):
        packages = {"alpha": "1.0.0", "beta": "2.3.4"}
        rows = compute_diff(packages, packages.copy())
        assert all(r.change == "unchanged" for r in rows)

    def test_rows_are_sorted_alphabetically(self):
        old = {"zebra": "1.0.0", "apple": "2.0.0"}
        new = {"zebra": "1.0.0", "apple": "2.0.0"}
        rows = compute_diff(old, new)
        assert [r.name for r in rows] == ["apple", "zebra"]


# ---------------------------------------------------------------------------
# Tests for output formatters
# ---------------------------------------------------------------------------

class TestFormatMarkdown:
    def test_no_changes_returns_no_changes_message(self):
        rows = [DiffRow("pkg", "1.0.0", "1.0.0", "unchanged")]
        output = _format_markdown(rows, include_unchanged=False)
        assert output == "(no changes)"

    def test_changed_row_appears(self):
        rows = [DiffRow("starlette", "0.52.1", "1.0.2", "minor↑")]
        output = _format_markdown(rows, include_unchanged=False)
        assert "starlette" in output
        assert "0.52.1" in output
        assert "1.0.2" in output
        assert "minor↑" in output

    def test_unchanged_hidden_by_default(self):
        rows = [
            DiffRow("changed-pkg", "1.0.0", "1.0.1", "patch↑"),
            DiffRow("stable-pkg", "2.0.0", "2.0.0", "unchanged"),
        ]
        output = _format_markdown(rows, include_unchanged=False)
        assert "stable-pkg" not in output
        assert "changed-pkg" in output

    def test_include_unchanged_shows_all(self):
        rows = [
            DiffRow("changed-pkg", "1.0.0", "1.0.1", "patch↑"),
            DiffRow("stable-pkg", "2.0.0", "2.0.0", "unchanged"),
        ]
        output = _format_markdown(rows, include_unchanged=True)
        assert "stable-pkg" in output
        assert "changed-pkg" in output

    def test_added_shows_dash_for_old(self):
        rows = [DiffRow("newpkg", None, "0.1.0", "added")]
        output = _format_markdown(rows, include_unchanged=False)
        assert "—" in output  # em-dash placeholder for None

    def test_removed_shows_dash_for_new(self):
        rows = [DiffRow("oldpkg", "1.0.0", None, "removed")]
        output = _format_markdown(rows, include_unchanged=False)
        assert "—" in output


class TestFormatJson:
    def test_json_structure(self):
        rows = [DiffRow("starlette", "0.52.1", "1.0.2", "minor↑")]
        raw = _format_json(rows, include_unchanged=False)
        data = json.loads(raw)
        assert len(data) == 1
        assert data[0] == {"name": "starlette", "old": "0.52.1", "new": "1.0.2", "change": "minor↑"}

    def test_json_excludes_unchanged_by_default(self):
        rows = [
            DiffRow("changed", "1.0.0", "1.0.1", "patch↑"),
            DiffRow("stable", "2.0.0", "2.0.0", "unchanged"),
        ]
        data = json.loads(_format_json(rows, include_unchanged=False))
        names = [r["name"] for r in data]
        assert "changed" in names
        assert "stable" not in names

    def test_json_include_unchanged(self):
        rows = [
            DiffRow("changed", "1.0.0", "1.0.1", "patch↑"),
            DiffRow("stable", "2.0.0", "2.0.0", "unchanged"),
        ]
        data = json.loads(_format_json(rows, include_unchanged=True))
        names = [r["name"] for r in data]
        assert "stable" in names


# ---------------------------------------------------------------------------
# CLI integration tests (call main() directly)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_same_file_no_changes(self):
        p = _write_lock(LOCK_ALPHA_1_0_0)
        rc = main([str(p), str(p)])
        assert rc == 0

    def test_patch_bump_shows_in_output(self, capsys):
        old_p = _write_lock(LOCK_ALPHA_1_0_0)
        new_p = _write_lock(LOCK_ALPHA_1_0_1)
        rc = main([str(old_p), str(new_p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "patch↑" in out
        assert "alpha" in out

    def test_minor_bump_shows_in_output(self, capsys):
        old_p = _write_lock(LOCK_ALPHA_1_0_0)
        new_p = _write_lock(LOCK_ALPHA_MINOR)
        rc = main([str(old_p), str(new_p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "minor↑" in out

    def test_major_bump_shows_in_output(self, capsys):
        old_p = _write_lock(LOCK_ALPHA_1_0_0)
        new_p = _write_lock(LOCK_ALPHA_MAJOR)
        rc = main([str(old_p), str(new_p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "major↑" in out

    def test_added_package_detected(self, capsys):
        old_p = _write_lock(LOCK_ALPHA_1_0_0)
        new_p = _write_lock(LOCK_WITH_GAMMA)
        rc = main([str(old_p), str(new_p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "gamma" in out
        assert "added" in out

    def test_removed_package_detected(self, capsys):
        old_p = _write_lock(LOCK_ALPHA_1_0_0)
        new_p = _write_lock(LOCK_WITHOUT_BETA)
        rc = main([str(old_p), str(new_p)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "beta" in out
        assert "removed" in out

    def test_json_format(self, capsys):
        old_p = _write_lock(LOCK_ALPHA_1_0_0)
        new_p = _write_lock(LOCK_ALPHA_1_0_1)
        rc = main([str(old_p), str(new_p), "--format=json"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert any(r["name"] == "alpha" for r in data)

    def test_include_unchanged_flag(self, capsys):
        p = _write_lock(LOCK_ALPHA_1_0_0)
        rc = main([str(p), str(p), "--include-unchanged"])
        out = capsys.readouterr().out
        assert rc == 0
        # With include_unchanged, should show packages (not just "(no changes)")
        assert "alpha" in out

    def test_malformed_toml_exits_1(self):
        p = _write_lock(LOCK_INVALID_TOML)
        valid_p = _write_lock(LOCK_ALPHA_1_0_0)
        with pytest.raises(SystemExit) as exc_info:
            main([str(p), str(valid_p)])
        assert exc_info.value.code == 1

    def test_missing_package_tables_exits_1(self):
        p = _write_lock(LOCK_NO_PACKAGES)
        valid_p = _write_lock(LOCK_ALPHA_1_0_0)
        with pytest.raises(SystemExit) as exc_info:
            main([str(p), str(valid_p)])
        assert exc_info.value.code == 1

    def test_nonexistent_file_exits_1(self):
        valid_p = _write_lock(LOCK_ALPHA_1_0_0)
        with pytest.raises(SystemExit) as exc_info:
            main(["/nonexistent/uv.lock", str(valid_p)])
        assert exc_info.value.code == 1
