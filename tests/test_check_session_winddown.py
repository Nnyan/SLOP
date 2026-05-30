"""tests/test_check_session_winddown.py — Red-path tests for the S4 wind-down aggregator.

check_session_winddown.py is ADVISORY (warn-only): it never forces a write and
the harness Stop hook only re-prompts.  These tests therefore assert on the
per-leg VERDICT tokens (the K-L vocabulary) rather than relying solely on exit
codes, and they prove the NEW memory-index GROUND leg can go RED against real
filesystem physics — the mandatory red-path requirement.

Legs covered:
  * memory-index GROUND leg: orphan file present -> DRIFT (red path);
    all indexed -> verified; memory dir unreachable -> INDETERMINATE
    (loud, never a silent OK).
  * aggregate exit code: any attention leg -> rc 1 (re-prompt), all clean -> 0.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "check_session_winddown.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_session_winddown", SCRIPT)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _write_memory(dir_: Path, index_body: str, files: dict[str, str]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "MEMORY.md").write_text(index_body, encoding="utf-8")
    for name, body in files.items():
        (dir_ / name).write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# memory-index GROUND leg — the new red-eligible leg
# ---------------------------------------------------------------------------

def test_memory_index_orphan_drifts(tmp_path, monkeypatch):
    """RED PATH: a memory *.md with no MEMORY.md line -> DRIFT."""
    mod = _load_module()
    memdir = tmp_path / "memory"
    _write_memory(
        memdir,
        index_body="# Index\n- [Kept](project_kept.md)\n",
        files={
            "project_kept.md": "kept",
            "project_orphan.md": "ORPHAN — not referenced in the index",
        },
    )
    monkeypatch.setattr(mod, "MEMORY_DIR", memdir)
    verdict, line = mod._leg_memory_index()
    assert verdict == "DRIFT", line
    assert "project_orphan.md" in line


def test_memory_index_all_indexed_verified(tmp_path, monkeypatch):
    """GREEN PATH: every memory file referenced -> verified."""
    mod = _load_module()
    memdir = tmp_path / "memory"
    _write_memory(
        memdir,
        index_body="# Index\n- [A](project_a.md)\n- [B](feedback_b.md)\n",
        files={"project_a.md": "a", "feedback_b.md": "b"},
    )
    monkeypatch.setattr(mod, "MEMORY_DIR", memdir)
    verdict, line = mod._leg_memory_index()
    assert verdict == "verified", line


def test_memory_index_unreachable_is_indeterminate_not_ok(tmp_path, monkeypatch):
    """The K-L 'no silent pass' rule: unreachable dir -> INDETERMINATE, never OK."""
    mod = _load_module()
    monkeypatch.setattr(mod, "MEMORY_DIR", tmp_path / "does-not-exist")
    verdict, line = mod._leg_memory_index()
    assert verdict == "INDETERMINATE", line
    assert verdict != "OK"


def test_memory_index_missing_index_is_indeterminate(tmp_path, monkeypatch):
    """Dir present but MEMORY.md absent -> INDETERMINATE (ground partially unreachable)."""
    mod = _load_module()
    memdir = tmp_path / "memory"
    memdir.mkdir()
    (memdir / "project_x.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mod, "MEMORY_DIR", memdir)
    verdict, line = mod._leg_memory_index()
    assert verdict == "INDETERMINATE", line


# ---------------------------------------------------------------------------
# aggregate exit-code semantics (advisory re-prompt)
# ---------------------------------------------------------------------------

def test_classify_output_detects_drift():
    mod = _load_module()
    assert mod._classify_output("WARNING: DRIFT — handoff trails") == "DRIFT"
    assert mod._classify_output("OK: all fresh") == "OK"
    assert mod._classify_output("INDETERMINATE: host down") == "INDETERMINATE"
