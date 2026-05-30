"""tests/test_backlog_park_triad.py — BATCH-11 S3 red-path tests for park-rule
triad enforcement + batch-ref landed check in tools/audit_backlog_stale.py.

Mandatory red-path tests per the S3 assignment:
  * [park] with no date              -> DRIFT (park-date-missing)
  * [park] with a PAST date          -> DRIFT (park-date-past)
  * [→ batch-NN] for a landed batch  -> DRIFT (batch-ref-landed)
  * vague trigger                    -> INCONSISTENT (park-vague-trigger)
  * missing owner                    -> INCONSISTENT (park-missing-owner)

Also covers:
  * [park] with a FUTURE date        -> no DRIFT on date leg
  * [park] with a non-vague trigger  -> no INCONSISTENT on vague leg
  * [park] with an owner token       -> no INCONSISTENT on owner leg
  * batch-ref NOT yet landed         -> no DRIFT
  * MERGE-LOG absent                 -> no batch DRIFT (conservative)
"""
from __future__ import annotations

import datetime
import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "audit_backlog_stale.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_backlog_stale", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else sys.executable


def _run_cli(repo: Path, today: str = "2026-06-15") -> tuple[int, str]:
    """Run the scanner CLI and return (rc, combined_output)."""
    result = subprocess.run(
        [_py(), str(SCANNER), "--repo", str(repo), "--today", today],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


def _make_backlog(repo: Path, content: str) -> None:
    docs = repo / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "BACKLOG.md").write_text(content, encoding="utf-8")


def _make_merge_log(repo: Path, content: str) -> None:
    docs = repo / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "MERGE-LOG.md").write_text(content, encoding="utf-8")


TODAY = datetime.date(2026, 6, 15)
PAST_DATE = "2026-01-01"    # in the past relative to TODAY
FUTURE_DATE = "2026-12-31"  # in the future relative to TODAY

_BACKLOG_PREAMBLE = textwrap.dedent("""\
    # SLOP Backlog

    ---

    ## Open

""")


# ---------------------------------------------------------------------------
# RED-PATH: Leg 1 — backstop re-eval date
# ---------------------------------------------------------------------------

class TestParkDateLeg:
    """Red-path: [park] with no date -> DRIFT; [park] with past date -> DRIFT."""

    def test_park_no_date_is_drift(self, tmp_path: Path) -> None:
        """RED-PATH: a [park] entry with no re-eval date emits DRIFT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            "- `[park]` **[task]** No re-eval date. "
            "Trigger: some trigger. Owner: Manager. Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        drift = [f for f in findings if f["verdict"] == "DRIFT"]
        assert len(drift) >= 1, "a dateless [park] must DRIFT"
        assert any(f["leg"] == "park-date-missing" for f in drift), (
            "the date-missing leg must fire"
        )

    def test_park_past_date_is_drift(self, tmp_path: Path) -> None:
        """RED-PATH: a [park] entry with a past re-eval date emits DRIFT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            f"- `[park: re-eval {PAST_DATE}]` **[task]** Past backstop. "
            f"Trigger: measurable trigger. Owner: Manager. Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        drift = [f for f in findings if f["verdict"] == "DRIFT"]
        assert len(drift) >= 1, "a [park] with a past date must DRIFT"
        assert any(f["leg"] == "park-date-past" for f in drift), (
            "the date-past leg must fire"
        )

    def test_park_future_date_no_drift(self) -> None:
        """[park] with a future date has no date-leg DRIFT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            f"- `[park: re-eval {FUTURE_DATE}]` **[task]** Future backstop. "
            f"Trigger: measurable trigger. Owner: Manager. Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        date_drifts = [
            f for f in findings
            if f["verdict"] == "DRIFT" and "park-date" in f["leg"]
        ]
        assert len(date_drifts) == 0, (
            f"a future-dated [park] must not DRIFT on date leg, got {date_drifts}"
        )

    def test_park_no_date_via_cli(self, tmp_path: Path) -> None:
        """RED-PATH via CLI: dateless [park] emits DRIFT line to stdout."""
        _make_backlog(
            tmp_path,
            _BACKLOG_PREAMBLE + (
                "- `[park]` **[task]** No date. Owner: Manager. Date added: 2026-01-01.\n"
            ),
        )
        rc, out = _run_cli(tmp_path, today="2026-06-15")
        assert rc == 0  # warn-only
        assert "DRIFT" in out, "dateless [park] must emit a DRIFT line"
        assert "park-date-missing" in out


# ---------------------------------------------------------------------------
# RED-PATH: [→ batch-NN] for a landed batch -> DRIFT
# ---------------------------------------------------------------------------

class TestBatchRefLanded:
    """Red-path: [→ batch-NN] for a landed batch -> DRIFT."""

    def test_landed_batch_ref_is_drift(self) -> None:
        """RED-PATH: [→ batch-5] DRIFT when batch-5 is in the landed set."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            "- `[→ batch-5]` **[enforcement] Some gate.** Date added: 2026-01-01.\n"
        )
        findings = mod.check_batch_refs(text, landed_batches={5})
        assert len(findings) == 1, "a landed batch-ref must DRIFT"
        assert findings[0]["verdict"] == "DRIFT"
        assert findings[0]["leg"] == "batch-ref-landed"

    def test_active_batch_ref_no_drift(self) -> None:
        """[→ batch-99] does NOT DRIFT when batch-99 is not in the landed set."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            "- `[→ batch-99]` **[enforcement] Some future gate.** Date added: 2026-01-01.\n"
        )
        findings = mod.check_batch_refs(text, landed_batches={5, 6, 7})
        assert len(findings) == 0, "an active (not-landed) batch-ref must not DRIFT"

    def test_no_merge_log_no_drift(self, tmp_path: Path) -> None:
        """If MERGE-LOG is absent, no batch-ref DRIFTs (conservative)."""
        mod = _load_module()
        # No MERGE-LOG.md file in tmp_path -> empty landed set.
        landed = mod._load_landed_batches(tmp_path)
        assert landed == set(), "absent MERGE-LOG must yield empty landed set"

        text = _BACKLOG_PREAMBLE + (
            "- `[→ batch-5]` **[enforcement] gate.** Date added: 2026-01-01.\n"
        )
        findings = mod.check_batch_refs(text, landed)
        assert len(findings) == 0, "absent MERGE-LOG must not DRIFT any batch-ref"

    def test_landed_batch_via_cli(self, tmp_path: Path) -> None:
        """RED-PATH via CLI: a landed batch-ref emits DRIFT line."""
        _make_backlog(
            tmp_path,
            _BACKLOG_PREAMBLE + (
                "- `[→ batch-5]` **[old task]** Date added: 2026-01-01.\n"
            ),
        )
        # Add a MERGE-LOG indicating batch-5 landed.
        _make_merge_log(
            tmp_path,
            "# Wave Merge Log\n\n---\n\n"
            "## 2026-01-15 — batch-5: S-59 + S-63 + S-64\n\n"
            "- **Notes:** batch-5 completed.\n",
        )
        rc, out = _run_cli(tmp_path, today="2026-06-15")
        assert rc == 0  # warn-only
        assert "DRIFT" in out
        assert "batch-ref-landed" in out


# ---------------------------------------------------------------------------
# RED-PATH: vague trigger -> INCONSISTENT
# ---------------------------------------------------------------------------

class TestParkVagueTrigger:
    """Red-path: [park] with vague trigger -> INCONSISTENT."""

    def test_vague_trigger_is_inconsistent(self) -> None:
        """RED-PATH: a [park] entry with a vague trigger emits INCONSISTENT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            f"- `[park: re-eval {FUTURE_DATE}]` **[task]** "
            f"Trigger: someday when convenient. Owner: Manager. Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        incon = [f for f in findings if f["verdict"] == "INCONSISTENT"]
        assert any(f["leg"] == "park-vague-trigger" for f in incon), (
            "a vague trigger must emit INCONSISTENT"
        )

    def test_measurable_trigger_no_vague_finding(self) -> None:
        """A measurable trigger does NOT trigger the vague-trigger INCONSISTENT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            f"- `[park: re-eval {FUTURE_DATE}]` **[task]** "
            f"Trigger: queue file exists on disk. Owner: Manager. Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        vague = [f for f in findings if f["leg"] == "park-vague-trigger"]
        assert len(vague) == 0, (
            f"a measurable trigger must not emit vague-trigger INCONSISTENT, got {vague}"
        )


# ---------------------------------------------------------------------------
# RED-PATH: missing owner -> INCONSISTENT
# ---------------------------------------------------------------------------

class TestParkMissingOwner:
    """Red-path: [park] with no owner token -> INCONSISTENT."""

    def test_missing_owner_is_inconsistent(self) -> None:
        """RED-PATH: a [park] entry with no owner token emits INCONSISTENT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            f"- `[park: re-eval {FUTURE_DATE}]` **[task]** "
            f"Trigger: queue file exists on disk. No owner here. Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        incon = [f for f in findings if f["verdict"] == "INCONSISTENT"]
        assert any(f["leg"] == "park-missing-owner" for f in incon), (
            "a missing owner must emit INCONSISTENT"
        )

    def test_entry_with_owner_no_owner_finding(self) -> None:
        """A [park] entry with an owner token does NOT emit owner INCONSISTENT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            f"- `[park: re-eval {FUTURE_DATE}]` **[task]** "
            f"Trigger: queue file exists. Owner: Manager at batch retro. "
            f"Date added: 2026-01-01.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        owner_incon = [f for f in findings if f["leg"] == "park-missing-owner"]
        assert len(owner_incon) == 0, (
            f"an entry with owner token must not emit owner INCONSISTENT, got {owner_incon}"
        )


# ---------------------------------------------------------------------------
# Exit code (always 0) with new findings
# ---------------------------------------------------------------------------

class TestExitCodeWithParkFindings:
    def test_exit_zero_with_park_drift(self, tmp_path: Path) -> None:
        """Exit code is always 0 even with DRIFT park findings (warn-only)."""
        _make_backlog(
            tmp_path,
            _BACKLOG_PREAMBLE + "- `[park]` **[task]** No date at all.\n",
        )
        rc, _ = _run_cli(tmp_path, today="2026-06-15")
        assert rc == 0

    def test_exit_zero_with_batch_ref_drift(self, tmp_path: Path) -> None:
        """Exit code is always 0 even with DRIFT batch-ref findings (warn-only)."""
        _make_backlog(
            tmp_path,
            _BACKLOG_PREAMBLE + "- `[→ batch-5]` **[old task]** Date added: 2026-01-01.\n",
        )
        _make_merge_log(
            tmp_path,
            "# Wave Merge Log\n\n---\n\n"
            "## 2026-01-15 — batch-5: S-59 + S-63\n\n"
            "- **Notes:** batch-5.\n",
        )
        rc, _ = _run_cli(tmp_path, today="2026-06-15")
        assert rc == 0


# ---------------------------------------------------------------------------
# Dateless-skip escape hatch closed
# ---------------------------------------------------------------------------

class TestDatelessSkipHatchClosed:
    """Verify the dateless-skip escape hatch is closed for [park] entries.

    Previously, a [park] entry with no date would silently pass (excluded by
    _TRIAGED_TOKENS from the bare-[ ] check, no park-specific gate). Now it
    emits DRIFT [park-date-missing].
    """

    def test_dateless_park_not_silently_ok(self) -> None:
        """A dateless [park] entry must NOT get a clean pass — it gets DRIFT."""
        mod = _load_module()
        text = _BACKLOG_PREAMBLE + (
            "- `[park]` **[task]** Trigger: some trigger. Owner: Manager.\n"
        )
        findings = mod.check_park_triad(text, TODAY)
        assert len(findings) > 0, (
            "a dateless [park] must NOT silently pass — "
            "the dateless-skip escape hatch must be closed"
        )
        assert any(
            f["verdict"] == "DRIFT" and f["leg"] == "park-date-missing"
            for f in findings
        ), "DRIFT [park-date-missing] must fire on a dateless [park]"


# ---------------------------------------------------------------------------
# load_landed_batches: GROUND leg test
# ---------------------------------------------------------------------------

class TestLoadLandedBatches:
    def test_batch_completion_header_detected(self, tmp_path: Path) -> None:
        """A 'batch-N:' header in MERGE-LOG is detected as a landed batch."""
        mod = _load_module()
        _make_merge_log(
            tmp_path,
            "# Merge Log\n\n---\n\n"
            "## 2026-01-15 — batch-5: S-59 + S-63\n\n"
            "## 2026-02-01 — wave/S-71-test-data-hygiene\n\n"
            "- **Notes:** batch-8. S-71.\n",
        )
        landed = mod._load_landed_batches(tmp_path)
        assert 5 in landed, "batch-5 header must be detected"
        assert 8 in landed, "batch-8 end-of-sentence must be detected"

    def test_batch_draft_not_detected_as_landed(self, tmp_path: Path) -> None:
        """'batch-NN drafts' in MERGE-LOG must NOT be detected as a landed batch."""
        mod = _load_module()
        _make_merge_log(
            tmp_path,
            "# Merge Log\n\n---\n\n"
            "## 2026-05-30 — Coverage+Handoff audit + batch-11 drafts\n\n"
            "- **Notes:** batch-11 drafts landed.\n",
        )
        landed = mod._load_landed_batches(tmp_path)
        assert 11 not in landed, (
            "batch-11 referenced only as 'drafts' must NOT be in the landed set"
        )
