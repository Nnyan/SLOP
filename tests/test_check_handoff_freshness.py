"""Tests for tools/check_handoff_freshness.py (S-75 Stream C).

All tests use tmp_path only — no live repo reads.
Covers:
  - SHA match        → verdict "verified" [GROUND: git rev-parse]
  - SHA mismatch     → verdict "DRIFT" (warn, still returns True)
  - unreachable origin → INDETERMINATE (warn, still returns True)
  - absent SHA line  → INDETERMINATE (warn, still returns True)
  - missing handoff file → INDETERMINATE (warn, still returns True)

Promotion-reconciliation tests:
  - finding referenced in tracked doc → no warning
  - finding NOT referenced in any tracked doc → warning emitted
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ── import tools under test ───────────────────────────────────────────────────

_FRESHNESS_TOOL = Path(__file__).parent.parent / "tools" / "check_handoff_freshness.py"
_MERGE_TOOL = Path(__file__).parent.parent / "tools" / "merge_wave_to_main.py"


def _load_freshness():
    spec = importlib.util.spec_from_file_location("check_handoff_freshness", _FRESHNESS_TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_merge():
    spec = importlib.util.spec_from_file_location("merge_wave_to_main_test", _MERGE_TOOL)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["merge_wave_to_main_test"] = mod
    spec.loader.exec_module(mod)
    return mod


chf = _load_freshness()
mwm = _load_merge()


# ── fixtures ──────────────────────────────────────────────────────────────────

REAL_SHA = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
REAL_SHORT = "a1b2c3d"


def _make_handoff(tmp_path: Path, declared_sha: str | None = REAL_SHORT) -> Path:
    """Write a minimal MANAGER-HANDOFF.md with the given declared SHA (or no SHA line if None)."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    handoff = docs_dir / "MANAGER-HANDOFF.md"
    if declared_sha is not None:
        content = (
            "# SLOP Manager Session — Handoff\n\n"
            f"- **origin/main at `{declared_sha}`** — CONFIRM LIVE "
            "(`git rev-parse origin/main`); do NOT trust this number.\n"
        )
    else:
        content = (
            "# SLOP Manager Session — Handoff\n\n"
            "Some content without any SHA declaration.\n"
        )
    handoff.write_text(content, encoding="utf-8")
    return handoff


# ── handoff freshness tests ───────────────────────────────────────────────────

class TestHandoffFreshness:
    def test_sha_match_verified(self, tmp_path):
        """SHA match → verdict contains 'verified' and names git rev-parse ground truth."""
        _make_handoff(tmp_path, declared_sha=REAL_SHORT)
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True, "warn-only gate must always return True"
        assert "verified" in msg
        assert REAL_SHORT in msg
        assert "GROUND: git rev-parse" in msg

    def test_sha_mismatch_drift(self, tmp_path):
        """SHA mismatch → verdict contains 'DRIFT' and names both SHAs."""
        other_short = "deadbee"
        other_full = "deadbee0deadbee0deadbee0deadbee0deadbee0"
        _make_handoff(tmp_path, declared_sha=REAL_SHORT)
        with patch.object(chf, "_get_live_sha", return_value=other_full):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True, "warn-only gate must always return True"
        assert "DRIFT" in msg
        assert REAL_SHORT in msg
        assert other_short in msg or other_full[:7] in msg
        assert "GROUND: git rev-parse" in msg

    def test_unreachable_origin_indeterminate(self, tmp_path):
        """Unreachable origin/main → INDETERMINATE, never silent OK."""
        _make_handoff(tmp_path, declared_sha=REAL_SHORT)
        with patch.object(chf, "_get_live_sha", return_value=None):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True, "warn-only gate must always return True"
        assert "INDETERMINATE" in msg
        # Must never say 'verified' on unreachable origin
        assert "verified" not in msg.lower() or "INDETERMINATE" in msg

    def test_absent_sha_line_indeterminate(self, tmp_path):
        """Handoff file present but no SHA line → INDETERMINATE."""
        _make_handoff(tmp_path, declared_sha=None)  # no SHA line
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True
        assert "INDETERMINATE" in msg

    def test_missing_handoff_file_indeterminate(self, tmp_path):
        """Missing handoff file → INDETERMINATE."""
        # Don't create any handoff file
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True
        assert "INDETERMINATE" in msg
        # Never a silent OK
        assert "verified" not in msg

    def test_verdict_names_ground_truth(self, tmp_path):
        """All non-INDETERMINATE verdicts must name the ground truth (GROUND: git rev-parse)."""
        _make_handoff(tmp_path, declared_sha=REAL_SHORT)
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            _, msg = chf.check(repo_root=tmp_path)
        assert "GROUND: git rev-parse" in msg

    def test_parse_declared_sha_real_format(self, tmp_path):
        """Parser handles the exact format from the real MANAGER-HANDOFF.md."""
        docs = tmp_path / "docs"
        docs.mkdir()
        handoff = docs / "MANAGER-HANDOFF.md"
        handoff.write_text(
            "## Current state\n\n"
            "- **origin/main at `e3a0eef`** — CONFIRM LIVE (`git rev-parse origin/main`);"
            " do NOT trust this number, it goes stale.\n",
            encoding="utf-8",
        )
        declared = chf._parse_declared_sha(handoff)
        assert declared == "e3a0eef"


# ── promotion-reconciliation tests ────────────────────────────────────────────

class TestPromotionReconciliation:
    """Tests for mwm.check_promotion_reconciliation().

    All fixtures are under tmp_path — no live repo reads.
    """

    def _make_tracked_docs(self, root: Path, content: str = "") -> None:
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "BACKLOG.md").write_text(content, encoding="utf-8")
        (docs / "MERGE-LOG.md").write_text("", encoding="utf-8")
        (docs / "WALK-BACK-LOG.md").write_text("", encoding="utf-8")
        (docs / "MAP.md").write_text("", encoding="utf-8")

    def _make_finding(self, batch_dir: Path, name: str, content: str) -> Path:
        obs_dir = batch_dir / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)
        f = obs_dir / name
        f.write_text(content, encoding="utf-8")
        return f

    def test_referenced_finding_no_warn(self, tmp_path):
        """Finding whose topic appears in BACKLOG.md → no warning."""
        self._make_tracked_docs(tmp_path, content="## deploy-hardening milestone tracked here\n")
        archive_base = tmp_path / "archive"
        batch_dir = archive_base / "batch1"
        self._make_finding(batch_dir, "obs1.md", (
            "---\nwave: S-74\ntype: observation\n---\n"
            "## deploy-hardening observation details\n"
            "Some additional text.\n"
        ))
        warns = mwm.check_promotion_reconciliation(
            tmp_path,
            run_dir=tmp_path / "run_nonexistent",
            archive_dirs=[archive_base],
        )
        assert warns == [], f"referenced finding should not warn; got: {warns}"

    def test_unreferenced_finding_warns(self, tmp_path):
        """Finding whose topic does NOT appear in any tracked doc → warning emitted."""
        # Tracked docs have no mention of the finding topic
        self._make_tracked_docs(tmp_path, content="## unrelated entry\n")
        archive_base = tmp_path / "archive"
        batch_dir = archive_base / "batch1"
        self._make_finding(batch_dir, "obs_orphan.md", (
            "---\nwave: S-99\ntype: observation\n---\n"
            "## xyzzy-unique-token-never-in-tracked-docs-7f3q\n"
            "Details that were never promoted.\n"
        ))
        warns = mwm.check_promotion_reconciliation(
            tmp_path,
            run_dir=tmp_path / "run_nonexistent",
            archive_dirs=[archive_base],
        )
        assert len(warns) == 1, f"orphan finding should warn once; got: {warns}"
        assert "promotion-reconciliation" in warns[0]
        assert "obs_orphan.md" in warns[0]

    def test_empty_finding_no_warn(self, tmp_path):
        """Finding with only frontmatter and no content → no warning (nothing to promote)."""
        self._make_tracked_docs(tmp_path)
        archive_base = tmp_path / "archive"
        batch_dir = archive_base / "batch1"
        self._make_finding(batch_dir, "obs_empty.md", (
            "---\nwave: S-99\ntype: observation\n---\n"
        ))
        warns = mwm.check_promotion_reconciliation(
            tmp_path,
            run_dir=tmp_path / "run_nonexistent",
            archive_dirs=[archive_base],
        )
        assert warns == [], f"empty finding should not warn; got: {warns}"

    def test_decisions_subdir_scanned(self, tmp_path):
        """Decisions subdir (not just observations) is also scanned."""
        self._make_tracked_docs(tmp_path, content="")
        archive_base = tmp_path / "archive"
        batch_dir = archive_base / "batch1"
        dec_dir = batch_dir / "decisions"
        dec_dir.mkdir(parents=True)
        f = dec_dir / "dec1.md"
        f.write_text(
            "---\nwave: S-99\ntype: decision\n---\n"
            "## xyzzy-unique-decision-never-promoted-99zz\n",
            encoding="utf-8",
        )
        warns = mwm.check_promotion_reconciliation(
            tmp_path,
            run_dir=tmp_path / "run_nonexistent",
            archive_dirs=[archive_base],
        )
        assert len(warns) == 1, f"unpromoted decision should warn; got: {warns}"
        assert "dec1.md" in warns[0]

    def test_scans_backlog_merge_log_walkback_map(self, tmp_path):
        """Confirmed: all four tracked docs are scanned for the topic token."""
        # Put the unique token only in MAP.md
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "BACKLOG.md").write_text("", encoding="utf-8")
        (docs / "MERGE-LOG.md").write_text("", encoding="utf-8")
        (docs / "WALK-BACK-LOG.md").write_text("", encoding="utf-8")
        (docs / "MAP.md").write_text("## xyzzy-unique-map-token\n", encoding="utf-8")
        archive_base = tmp_path / "archive"
        batch_dir = archive_base / "batch1"
        self._make_finding(batch_dir, "obs_map.md", (
            "---\nwave: S-99\ntype: observation\n---\n"
            "## xyzzy-unique-map-token observation\n"
        ))
        warns = mwm.check_promotion_reconciliation(
            tmp_path,
            run_dir=tmp_path / "run_nonexistent",
            archive_dirs=[archive_base],
        )
        assert warns == [], f"finding referenced in MAP.md should not warn; got: {warns}"
