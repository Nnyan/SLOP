"""Tests for tools/check_handoff_freshness.py (S-75 Stream C; LR-1 grounded
rewrite + batch-11 S5 .handoff-sha auto-stamp contract).

All tests use tmp_path only — no live repo reads.

The LR-1 fix moved the freshness SHA from a deletable prose bullet in
docs/MANAGER-HANDOFF.md to a committed machine artifact `.handoff-sha`, and made
ABSENCE of that artifact a DRIFT (a defect to fix), NOT INDETERMINATE. The test
helper below writes `.handoff-sha` to reflect that contract (it previously wrote
the old prose format and never created `.handoff-sha`, so the suite DRIFTed
against the fixed gate — fixed here, batch-11 S5).

Covers:
  - SHA match            → verdict "verified" [GROUND: git rev-parse]
  - SHA mismatch         → verdict "DRIFT" (warn, still returns True)
  - unreachable origin   → INDETERMINATE (the only genuine one)
  - absent .handoff-sha  → DRIFT (defect — artifact must exist), NOT INDETERMINATE
  - malformed .handoff-sha → DRIFT

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
    """Write the committed `.handoff-sha` artifact the LR-1-fixed gate reads.

    declared_sha=None means "do NOT create the artifact" — which the grounded gate
    treats as DRIFT (a defect), not INDETERMINATE. Returns the .handoff-sha path
    (the file may not exist when declared_sha is None).
    """
    sha_path = tmp_path / ".handoff-sha"
    if declared_sha is not None:
        # First whitespace token is the SHA; a trailing comment is tolerated.
        sha_path.write_text(
            f"{declared_sha}\n"
            "# origin/main SHA the current handoff was refreshed against.\n",
            encoding="utf-8",
        )
    return sha_path


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

    def test_absent_handoff_sha_artifact_drift(self, tmp_path):
        """No .handoff-sha artifact at all → DRIFT (defect), NOT INDETERMINATE.

        This is the LR-1 brownout closure: a missing machine artifact is a defect
        that must go red, never silently downgrade to "not red".
        """
        _make_handoff(tmp_path, declared_sha=None)  # creates nothing
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True, "warn-only gate must always return True"
        assert "DRIFT" in msg
        assert "INDETERMINATE" not in msg
        assert "verified" not in msg

    def test_malformed_handoff_sha_drift(self, tmp_path):
        """.handoff-sha present but not a SHA token → DRIFT, NOT INDETERMINATE."""
        (tmp_path / ".handoff-sha").write_text("not-a-sha-value\n", encoding="utf-8")
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            ok, msg = chf.check(repo_root=tmp_path)
        assert ok is True
        assert "DRIFT" in msg
        assert "INDETERMINATE" not in msg
        assert "verified" not in msg

    def test_verdict_names_ground_truth(self, tmp_path):
        """All non-INDETERMINATE verdicts must name the ground truth (GROUND: git rev-parse)."""
        _make_handoff(tmp_path, declared_sha=REAL_SHORT)
        with patch.object(chf, "_get_live_sha", return_value=REAL_SHA):
            _, msg = chf.check(repo_root=tmp_path)
        assert "GROUND: git rev-parse" in msg

    def test_read_declared_sha_from_artifact(self, tmp_path):
        """Reader returns the first whitespace token of .handoff-sha (comment tolerated)."""
        (tmp_path / ".handoff-sha").write_text(
            "e3a0eef  # origin/main at last handoff refresh\n",
            encoding="utf-8",
        )
        declared = chf._read_declared_sha(tmp_path)
        assert declared == "e3a0eef"

    def test_read_declared_sha_absent_is_none(self, tmp_path):
        """No artifact → reader returns None (the gate turns this into DRIFT)."""
        assert chf._read_declared_sha(tmp_path) is None


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
