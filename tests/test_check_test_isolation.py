"""Tests for tools/check_test_isolation.py — the warn-only test-data-isolation
scanner (S-71 Stream C).

These tests construct synthetic test files entirely under ``tmp_path`` (the
scanner's own fixtures must NOT trip the scanner) using string payloads, then
run the scanner against that throwaway tree. We assert:

  - a CLEAN test (tmp_path-rooted writes, read-only asserts on real paths) emits
    NO warnings;
  - a DIRTY test (writes ``docs/x.md``) emits a warning;
  - the canonical policy doc path is referenced by the scanner (contract pin).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_TOOL = Path(__file__).resolve().parent.parent / "tools" / "check_test_isolation.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_test_isolation", _TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Payloads are plain strings (NOT real files under docs/) so this test module
# itself cannot trip the scanner.
_CLEAN_TEST = '''\
from pathlib import Path


def test_clean(tmp_path):
    p = tmp_path / "out.md"
    p.write_text("hello")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("nested under tmp_path")
    # read-only assertions on the real tree are fine
    assert Path("docs/ARCHITECTURE.md").exists()
    _ = Path("requirements.txt").read_text()
'''

_DIRTY_TEST = '''\
from pathlib import Path


def test_dirty():
    Path("docs/x.md").write_text("pollutes the real tree")
'''


def _run_scanner(mod, repo: Path) -> list[str]:
    return mod.scan(repo / "tests", repo)


def test_clean_test_emits_no_warning(tmp_path):
    mod = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_clean_sample.py").write_text(_CLEAN_TEST, encoding="utf-8")

    warnings = _run_scanner(mod, tmp_path)
    assert warnings == [], f"clean test should not warn, got: {warnings}"


def test_dirty_test_emits_warning(tmp_path):
    mod = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dirty_sample.py").write_text(_DIRTY_TEST, encoding="utf-8")

    warnings = _run_scanner(mod, tmp_path)
    assert len(warnings) == 1, f"dirty test should warn exactly once, got: {warnings}"
    w = warnings[0]
    assert w.startswith("WARNING [test-isolation] ")
    assert "test_dirty_sample.py" in w
    assert "docs/x.md" in w


def test_open_write_mode_on_literal_warns(tmp_path):
    mod = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_open_sample.py").write_text(
        'def test_x():\n    f = open("docs/y.md", "w")\n    f.write("x")\n',
        encoding="utf-8",
    )
    warnings = _run_scanner(mod, tmp_path)
    assert any("docs/y.md" in w for w in warnings), warnings


def test_read_mode_open_does_not_warn(tmp_path):
    """Reading a real file (read mode) is an excluded false-positive class."""
    mod = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_read_sample.py").write_text(
        'def test_x():\n    data = open("docs/README.md").read()\n'
        '    data2 = open("docs/README.md", "r").read()\n',
        encoding="utf-8",
    )
    warnings = _run_scanner(mod, tmp_path)
    assert warnings == [], f"read-mode opens must not warn, got: {warnings}"


def test_tmp_path_joined_variable_does_not_warn(tmp_path):
    """A write whose receiver is a variable/BinOp (tmp_path-joined) is fine."""
    mod = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_var_sample.py").write_text(
        "def test_x(tmp_path):\n"
        '    docs = tmp_path / "docs"\n'
        "    docs.mkdir()\n"
        '    (docs / "BACKLOG.md").write_text("ok")\n'
        '    repo_doc = "docs/MERGE-LOG.md"  # a path STRING, not a write target\n'
        "    _ = repo_doc\n",
        encoding="utf-8",
    )
    warnings = _run_scanner(mod, tmp_path)
    assert warnings == [], f"tmp_path-joined writes must not warn, got: {warnings}"


def test_audit_redirect_optin_suppresses_sanctioned_log(tmp_path):
    """A file using the SLOP_AUDIT_LOG_PATH redirect convention is trusted for
    the SANCTIONED-OPS-LOG marker specifically (Stream B's contract)."""
    mod = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_redirect_sample.py").write_text(
        "def test_x(tmp_path, monkeypatch):\n"
        '    monkeypatch.setenv("SLOP_AUDIT_LOG_PATH", str(tmp_path / "log.md"))\n'
        '    Path("docs/SANCTIONED-OPS-LOG.md").write_text("via redirect")\n',
        encoding="utf-8",
    )
    warnings = _run_scanner(mod, tmp_path)
    assert warnings == [], f"redirect opt-in should suppress sanctioned-log, got: {warnings}"


def test_scanner_self_runs_clean_on_live_tree():
    """The scanner reports cleanly (or only documented FPs) against the live
    tests/** tree — the day-one no-flood acceptance property. A couple of
    residual warnings on not-yet-swept files (Stream D) are acceptable, so we
    assert a low ceiling rather than exactly zero."""
    mod = _load()
    repo = Path(__file__).resolve().parent.parent
    warnings = mod.scan(repo / "tests", repo)
    assert len(warnings) <= 3, "scanner floods the live tree: \n" + "\n".join(warnings)


def test_scanner_docstring_references_policy_adr():
    """Contract pin: the scanner's module docstring references Stream A's ADR."""
    src = _TOOL.read_text(encoding="utf-8")
    assert "docs/adr/0019-test-data-isolation.md" in src
