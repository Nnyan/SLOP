"""Tests for tools/independent_review.py + the check_independent_review gate (S7, P7).

Red-path tests build throwaway git repos in tmp_path (no live repo writes):

  (a) floor-tripping commit citing a NON-EXISTENT review record  → DRIFT
  (b) legitimately-reviewed commit (cites an existing REVIEW-LOG entry) → verified
  (c) ACYCLICITY: a commit touching ONLY docs/REVIEW-LOG.md does NOT trip the floor
  (d) ACYCLICITY: adding the gate's own def check_independent_review does NOT trip
  (e) non-floor commit → OK (honest "nothing to check", not a green verified)
  (f) the PINNED artifact_exists helper grounds on the filesystem
  (g) walk-back GROUND leg: doctrine removal citing token but +0 to WALK-BACK-LOG → DRIFT

Vocabulary asserted verbatim: verified / DRIFT / INDETERMINATE / OK.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_TOOL = Path(__file__).parent.parent / "tools" / "independent_review.py"


def _load():
    spec = importlib.util.spec_from_file_location("independent_review", _TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ir = _load()


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return r.stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    # seed an initial unrelated commit
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _commit(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


# ── (a) floor tripped, NO committed review record → DRIFT ──────────────────
def test_floor_tripped_no_review_record_is_drift(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "CLAUDE.md").write_text("doctrine v1\n" * 5)
    _commit(repo, "doctrine: tweak a rule (no review cited)")
    verdict, detail = ir.evaluate(repo)
    assert verdict == "DRIFT", detail
    assert "REVIEW-LOG" in detail


# ── (b) floor tripped + cites an existing REVIEW-LOG addition → verified ────
def test_floor_tripped_with_committed_review_record_is_verified(tmp_path):
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    (repo / "CLAUDE.md").write_text("doctrine v1\n" * 5)
    (docs / "REVIEW-LOG.md").write_text(
        "# Review Log\n\n## 2026-05-30 — a real review\n- reviewer + charge + reconciliation\n"
    )
    _commit(repo, "doctrine: add a rule; REVIEW-LOG entry records the reconciliation")
    verdict, detail = ir.evaluate(repo)
    assert verdict == "verified", detail
    assert "GROUND" in detail


def test_floor_tripped_cite_token_but_no_log_addition_is_drift(tmp_path):
    # Message cites REVIEW-LOG but HEAD adds NOTHING to it (file pre-exists,
    # untouched this commit) → fabrication → DRIFT.
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    (docs / "REVIEW-LOG.md").write_text("# Review Log\n\n## old entry\n")
    _commit(repo, "seed review log")
    (repo / "CLAUDE.md").write_text("doctrine v1\n" * 5)
    _commit(repo, "doctrine: change; see REVIEW-LOG (but added nothing to it)")
    verdict, detail = ir.evaluate(repo)
    assert verdict == "DRIFT", detail


# ── (c) ACYCLICITY: REVIEW-LOG-only commit does NOT trip the floor ─────────
def test_acyclicity_review_log_only_does_not_trip(tmp_path):
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    (docs / "REVIEW-LOG.md").write_text("# Review Log\n\n## 2026-05-30 — a review\n")
    _commit(repo, "review: record an independent review")
    tripped, reasons = ir.floor_triggers(repo)
    assert tripped is False, reasons
    verdict, detail = ir.evaluate(repo)
    assert verdict == "OK", detail


# ── (d) ACYCLICITY: adding the gate's own def does NOT trip ────────────────
def test_acyclicity_adding_own_check_def_does_not_trip(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "ms-enforce").write_text(
        "def check_independent_review() -> tuple[bool, str]:\n    return True, 'ok'\n"
    )
    _commit(repo, "add the independent-review gate itself")
    tripped, reasons = ir.floor_triggers(repo)
    assert tripped is False, reasons


def test_adding_other_check_def_does_trip(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "ms-enforce").write_text(
        "def check_something_new() -> tuple[bool, str]:\n    return True, 'ok'\n"
    )
    _commit(repo, "add a new gate (no review)")
    tripped, reasons = ir.floor_triggers(repo)
    assert tripped is True
    assert any("def check_" in r for r in reasons)


def test_new_sanctioned_tool_trips(tmp_path):
    repo = _init_repo(tmp_path)
    sdir = repo / "tools" / "sanctioned"
    sdir.mkdir(parents=True)
    (sdir / "new_tool.py").write_text("# sanctioned\n")
    _commit(repo, "add a sanctioned tool (no review)")
    tripped, reasons = ir.floor_triggers(repo)
    assert tripped is True
    assert any("sanctioned" in r for r in reasons)


# ── (e) non-floor commit → OK ──────────────────────────────────────────────
def test_non_floor_commit_is_ok(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend_thing.py").write_text("x = 1\n")
    _commit(repo, "feat: unrelated change")
    verdict, detail = ir.evaluate(repo)
    assert verdict == "OK", detail


# ── (f) PINNED artifact_exists helper (consumed by S11) ────────────────────
def test_artifact_exists_helper(tmp_path):
    repo = tmp_path
    (repo / "present.md").write_text("hi\n")
    assert ir.artifact_exists("present.md", repo) is True
    assert ir.artifact_exists("absent.md", repo) is False
    assert ir.artifact_exists(repo / "present.md") is True
    # a directory is not a regular-file artifact
    (repo / "adir").mkdir()
    assert ir.artifact_exists("adir", repo) is False


def test_cited_record_exists_requires_token_and_addition(tmp_path):
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    (docs / "REVIEW-LOG.md").write_text("# Review Log\n\n## entry\n")
    (repo / "CLAUDE.md").write_text("d\n" * 5)
    _commit(repo, "doctrine: change; REVIEW-LOG entry added")
    ok, msg = ir._head_message(repo)
    assert ok
    assert ir.cited_record_exists(msg, repo) is True
    # no token in message → False even if file present
    assert ir.cited_record_exists("doctrine: no citation here", repo) is False


# ── (g) walk-back-log GROUND leg (check_walkback_log in ms-enforce) ────────
def _load_msenforce(repo: Path):
    """Load ms-enforce as a module with REPO patched to a throwaway repo."""
    import importlib.machinery

    src = str(Path(__file__).parent.parent / "ms-enforce")
    loader = importlib.machinery.SourceFileLoader("ms_enforce_under_test", src)
    spec = importlib.util.spec_from_loader("ms_enforce_under_test", loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REPO = repo  # _run uses cwd=str(REPO)
    return mod


def test_walkback_ground_leg_token_without_entry_is_drift(tmp_path):
    repo = _init_repo(tmp_path)
    # remove >=3 lines from a doctrine file but cite walk-back-log with NO entry
    (repo / "CLAUDE.md").write_text("a\nb\nc\nd\ne\nf\n")
    _commit(repo, "doctrine: seed")
    (repo / "CLAUDE.md").write_text("a\n")  # removes 5 lines
    _commit(repo, "doctrine: soften rule per walk-back-log (but no entry added)")
    me = _load_msenforce(repo)
    passed, detail = me.check_walkback_log()
    assert passed is True  # warn-only
    assert "DRIFT" in detail, detail


def test_walkback_ground_leg_with_entry_is_clean(tmp_path):
    repo = _init_repo(tmp_path)
    docs = repo / "docs"
    docs.mkdir()
    (docs / "WALK-BACK-LOG.md").write_text("# Walk-Back Log\n")
    (repo / "CLAUDE.md").write_text("a\nb\nc\nd\ne\nf\n")
    _commit(repo, "doctrine: seed")
    (repo / "CLAUDE.md").write_text("a\n")  # removes 5 lines
    (docs / "WALK-BACK-LOG.md").write_text(
        "# Walk-Back Log\n\n## 2026-05-30 — softened rule X\n- need / why / new mech / failure\n"
    )
    _commit(repo, "doctrine: soften rule X; see docs/WALK-BACK-LOG.md entry")
    me = _load_msenforce(repo)
    passed, detail = me.check_walkback_log()
    assert passed is True
    assert "DRIFT" not in detail, detail
    assert "GROUND" in detail, detail
