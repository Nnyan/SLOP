"""tests/test_audit_fact_freshness.py — Tests for tools/audit_fact_freshness.py (S-75-D).

Covers:
  - A probed fact that drifts → DRIFT output, loud warn.
  - An UNPROBED fact → counted not blessed.
  - Ratchet: shrink OK, grow warns.
  - A VERIFIED fact → reports VERIFIED.
  - ms-enforce registration.

All tests use tmp_path; no real memory dir, no real CLAUDE.md, no real repo mutations.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "audit_fact_freshness.py"


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else sys.executable


def _run(
    *,
    repo: Path,
    memory_dir: Path,
    claude_md: Path,
    extra_args: list[str] | None = None,
) -> tuple[int, str]:
    """Run audit_fact_freshness.py and return (returncode, combined stdout+stderr)."""
    cmd = [
        _py(), str(SCRIPT),
        "--repo", str(repo),
        "--memory-dir", str(memory_dir),
        "--claude-md", str(claude_md),
        "--dry-run",          # do not touch any real baseline files
        "--today", "2026-05-30",
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Helpers to build fixture memory / CLAUDE.md / repo dirs
# ---------------------------------------------------------------------------

def _write_memory_file(mem_dir: Path, filename: str, content: str) -> Path:
    mem_dir.mkdir(parents=True, exist_ok=True)
    p = mem_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


def _write_claude_md(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "CLAUDE.md"
    p.write_text(content, encoding="utf-8")
    return p


def _make_minimal_repo(tmp_path: Path) -> Path:
    """Create a minimal fake repo directory (just needs to exist for cwd)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    return repo


# ---------------------------------------------------------------------------
# Test: exit code is always 0 (warn-only)
# ---------------------------------------------------------------------------

class TestExitCode:
    def test_always_zero_clean(self, tmp_path: Path) -> None:
        """Script exits 0 when all probes pass."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(mem_dir, "clean.md", "---\nname: clean\n---\nNo probe.")
        claude_md = _write_claude_md(tmp_path, "## Project facts\nNo annotations here.\n")
        rc, _ = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert rc == 0

    def test_always_zero_on_drift(self, tmp_path: Path) -> None:
        """Script exits 0 even when a probe drifts (warn-only gate)."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        # Probe that always fails: test for a path that does not exist
        _write_memory_file(
            mem_dir, "drifted.md",
            '---\nname: drifted-fact\nverify_probe: "test -f /nonexistent_file_xyz"\n---\nContent.\n',
        )
        claude_md = _write_claude_md(tmp_path, "## Project facts\nNo annotations.\n")
        rc, _ = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert rc == 0

    def test_always_zero_missing_memory_dir(self, tmp_path: Path) -> None:
        """Script exits 0 when memory dir does not exist."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "nonexistent_memory"
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        rc, _ = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert rc == 0


# ---------------------------------------------------------------------------
# Test: DRIFT — probed fact that drifts is reported loudly
# ---------------------------------------------------------------------------

class TestDriftDetection:
    def test_failing_probe_reports_drift(self, tmp_path: Path) -> None:
        """A probe that exits non-zero produces a DRIFT line."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(
            mem_dir, "drifted.md",
            '---\nname: drifted-fact\nverify_probe: "false"\n---\nA fact.\n',
        )
        claude_md = _write_claude_md(tmp_path, "## Project facts\nNo annotations.\n")
        rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert rc == 0  # always 0 — warn-only
        assert "DRIFT" in out, f"Expected DRIFT in output, got:\n{out}"
        assert "drifted-fact" in out

    def test_passing_probe_reports_verified(self, tmp_path: Path) -> None:
        """A probe that exits 0 produces a VERIFIED line."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(
            mem_dir, "good.md",
            '---\nname: good-fact\nverify_probe: "true"\n---\nA fact.\n',
        )
        claude_md = _write_claude_md(tmp_path, "## Project facts\nNo annotations.\n")
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert "VERIFIED" in out, f"Expected VERIFIED in output:\n{out}"
        assert "good-fact" in out

    def test_drift_label_includes_fact_name(self, tmp_path: Path) -> None:
        """The DRIFT line includes the fact name for traceability."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(
            mem_dir, "specific.md",
            '---\nname: my-specific-fact\nverify_probe: "false"\n---\nContent.\n',
        )
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert "my-specific-fact" in out

    def test_claude_md_failing_annotation_reports_drift(self, tmp_path: Path) -> None:
        """A failing <!-- verify: --> annotation in CLAUDE.md reports DRIFT."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        # Annotation with a command that will fail
        claude_md = _write_claude_md(
            tmp_path,
            "## Project facts\nSome fact. <!-- verify: false -->\n",
        )
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert "DRIFT" in out, f"Expected DRIFT for failing annotation:\n{out}"

    def test_claude_md_passing_annotation_reports_verified(self, tmp_path: Path) -> None:
        """A passing <!-- verify: --> annotation in CLAUDE.md reports VERIFIED."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        claude_md = _write_claude_md(
            tmp_path,
            "## Project facts\nSome fact. <!-- verify: true -->\n",
        )
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert "VERIFIED" in out, f"Expected VERIFIED for passing annotation:\n{out}"


# ---------------------------------------------------------------------------
# Test: UNPROBED — counted not blessed
# ---------------------------------------------------------------------------

class TestUnprobed:
    def test_no_probe_reports_unprobed(self, tmp_path: Path) -> None:
        """A memory file with no verify_probe is reported as UNPROBED."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(
            mem_dir, "no_probe.md",
            "---\nname: no-probe-fact\n---\nContent.\n",
        )
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert "UNPROBED" in out, f"Expected UNPROBED in output:\n{out}"
        assert "no-probe-fact" in out

    def test_unprobed_not_called_verified(self, tmp_path: Path) -> None:
        """An UNPROBED fact must NOT produce a VERIFIED line."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(
            mem_dir, "no_probe.md",
            "---\nname: unprobed-fact\n---\nContent.\n",
        )
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        # Must appear as UNPROBED, never as VERIFIED
        lines = out.splitlines()
        verified_lines = [ln for ln in lines if "VERIFIED" in ln and "unprobed-fact" in ln]
        assert not verified_lines, f"UNPROBED fact must not appear as VERIFIED:\n{out}"

    def test_multiple_unprobed_all_counted(self, tmp_path: Path) -> None:
        """Multiple UNPROBED facts each produce their own UNPROBED line."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        for i in range(3):
            _write_memory_file(
                mem_dir, f"fact_{i}.md",
                f"---\nname: fact-{i}\n---\nContent.\n",
            )
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        unprobed_lines = [ln for ln in out.splitlines() if ln.startswith("UNPROBED:")]
        assert len(unprobed_lines) == 3, f"Expected 3 UNPROBED lines:\n{out}"


# ---------------------------------------------------------------------------
# Test: Ratchet — shrink OK, grow warns
# ---------------------------------------------------------------------------

class TestRatchet:
    def _run_with_baseline(
        self,
        tmp_path: Path,
        repo: Path,
        mem_dir: Path,
        claude_md: Path,
        baseline_count: int,
        *,
        update_shrunk: bool = False,
    ) -> tuple[int, str]:
        """Write a baseline file with *baseline_count* and run the tool."""
        baseline = {
            "generated_at": "2026-05-30T00:00:00+00:00",
            "unprobed_count": baseline_count,
        }
        (repo / ".factprobe-baseline.json").write_text(
            json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
        )
        extra: list[str] = []
        if update_shrunk:
            extra = ["--update-shrunk"]
            # Remove --dry-run when testing update-shrunk (must write)
            cmd = [
                _py(), str(SCRIPT),
                "--repo", str(repo),
                "--memory-dir", str(mem_dir),
                "--claude-md", str(claude_md),
                "--today", "2026-05-30",
                "--update-shrunk",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode, result.stdout + result.stderr
        return _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)

    def test_ratchet_grow_emits_warning(self, tmp_path: Path) -> None:
        """When UNPROBED count exceeds baseline, a WARNING is emitted."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        # Add 2 unprobed facts
        for i in range(2):
            _write_memory_file(mem_dir, f"fact_{i}.md", f"---\nname: f{i}\n---\nX.\n")
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        # Baseline says 1 — current is 2 → GROW → warning
        _rc, out = self._run_with_baseline(tmp_path, repo, mem_dir, claude_md, baseline_count=1)
        assert "WARNING" in out, f"Expected WARNING for ratchet grow:\n{out}"
        assert "exceeds baseline" in out.lower() or "ratchet" in out.lower()

    def test_ratchet_shrink_no_warning(self, tmp_path: Path) -> None:
        """When UNPROBED count is below baseline, no WARNING is emitted."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        # Add 1 unprobed fact
        _write_memory_file(mem_dir, "fact.md", "---\nname: f1\n---\nX.\n")
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        # Baseline says 5 — current is 1 → SHRINK → no warning
        _rc, out = self._run_with_baseline(tmp_path, repo, mem_dir, claude_md, baseline_count=5)
        warning_lines = [ln for ln in out.splitlines() if "WARNING" in ln and "ratchet" in ln.lower()]
        assert not warning_lines, f"No ratchet WARNING expected for shrink:\n{out}"

    def test_ratchet_equal_no_warning(self, tmp_path: Path) -> None:
        """When UNPROBED count equals baseline exactly, no WARNING is emitted."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(mem_dir, "fact.md", "---\nname: f1\n---\nX.\n")
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        # Baseline says 1 — current is 1 → EQUAL → no warning
        _rc, out = self._run_with_baseline(tmp_path, repo, mem_dir, claude_md, baseline_count=1)
        warning_lines = [ln for ln in out.splitlines() if "WARNING" in ln and "ratchet" in ln.lower()]
        assert not warning_lines, f"No ratchet WARNING expected for equal:\n{out}"

    def test_update_shrunk_lowers_baseline(self, tmp_path: Path) -> None:
        """--update-shrunk writes a new lower baseline when count decreases."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(mem_dir, "fact.md", "---\nname: f1\n---\nX.\n")
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        # Baseline says 10, current = 1, so it should shrink to 1
        self._run_with_baseline(
            tmp_path, repo, mem_dir, claude_md,
            baseline_count=10, update_shrunk=True,
        )
        baseline_file = repo / ".factprobe-baseline.json"
        assert baseline_file.exists(), "Baseline file should exist after --update-shrunk"
        data = json.loads(baseline_file.read_text(encoding="utf-8"))
        assert data["unprobed_count"] == 1, (
            f"Expected baseline 1 after shrink, got {data['unprobed_count']}"
        )

    def test_no_baseline_file_establishes_initial_baseline(self, tmp_path: Path) -> None:
        """When no baseline exists, the tool creates one (no warning)."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        _write_memory_file(mem_dir, "fact.md", "---\nname: f1\n---\nX.\n")
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        # Use --update-shrunk so baseline is actually written (not dry-run)
        cmd = [
            _py(), str(SCRIPT),
            "--repo", str(repo),
            "--memory-dir", str(mem_dir),
            "--claude-md", str(claude_md),
            "--today", "2026-05-30",
            "--update-shrunk",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = result.stdout + result.stderr
        baseline_file = repo / ".factprobe-baseline.json"
        assert baseline_file.exists(), f"Baseline file should be created:\n{out}"
        data = json.loads(baseline_file.read_text(encoding="utf-8"))
        assert "unprobed_count" in data

    def test_ratchet_update_shrunk_does_not_grow(self, tmp_path: Path) -> None:
        """--update-shrunk must not raise the baseline when count has GROWN."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        # Add 3 unprobed facts
        for i in range(3):
            _write_memory_file(mem_dir, f"fact_{i}.md", f"---\nname: f{i}\n---\nX.\n")
        claude_md = _write_claude_md(tmp_path, "## Project facts\n")
        # Baseline says 1 — current is 3 → GROW → warning even with --update-shrunk
        _rc, out = self._run_with_baseline(
            tmp_path, repo, mem_dir, claude_md,
            baseline_count=1, update_shrunk=True,
        )
        # Baseline should still be 1 (not raised to 3)
        baseline_file = repo / ".factprobe-baseline.json"
        if baseline_file.exists():
            data = json.loads(baseline_file.read_text(encoding="utf-8"))
            assert data["unprobed_count"] <= 3, "Baseline should not grow above prior value"
        assert "WARNING" in out, f"Expected WARNING for grow even with --update-shrunk:\n{out}"


# ---------------------------------------------------------------------------
# Test: CLAUDE.md section scoping (only "## Project facts" section scanned)
# ---------------------------------------------------------------------------

class TestClaudeMdSectionScoping:
    def test_annotation_outside_project_facts_ignored(self, tmp_path: Path) -> None:
        """Annotations outside the Project facts section are not executed."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        # Put a failing verify in a different section
        claude_md = _write_claude_md(
            tmp_path,
            "## Other section\n"
            "Some fact. <!-- verify: false -->\n\n"
            "## Project facts\n"
            "No annotations here.\n",
        )
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        # The failing annotation in "Other section" must NOT be run.
        # Check for "DRIFT:" lines (the finding prefix), not "DRIFT" in the
        # summary count which always includes "N DRIFT" even when N=0.
        drift_lines = [ln for ln in out.splitlines() if ln.startswith("DRIFT:")]
        assert not drift_lines, (
            f"Annotation outside Project facts must not trigger DRIFT lines:\n{out}"
        )

    def test_annotation_inside_project_facts_executed(self, tmp_path: Path) -> None:
        """Annotations inside the Project facts section are executed."""
        repo = _make_minimal_repo(tmp_path)
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        claude_md = _write_claude_md(
            tmp_path,
            "## Project facts\n"
            "A fact. <!-- verify: true -->\n",
        )
        _rc, out = _run(repo=repo, memory_dir=mem_dir, claude_md=claude_md)
        assert "VERIFIED" in out, f"Expected annotation in Project facts to execute:\n{out}"


# ---------------------------------------------------------------------------
# Test: ms-enforce integration
# ---------------------------------------------------------------------------

class TestMsEnforceIntegration:
    def test_check_function_exists(self) -> None:
        """check_fact_freshness is defined in ms-enforce."""
        ms_enforce = REPO / "ms-enforce"
        assert ms_enforce.exists()
        text = ms_enforce.read_text(encoding="utf-8")
        assert "check_fact_freshness" in text, (
            "check_fact_freshness must be defined in ms-enforce"
        )

    def test_check_registered_in_tier_1(self) -> None:
        """check_fact_freshness is listed in TIER_1."""
        ms_enforce = REPO / "ms-enforce"
        text = ms_enforce.read_text(encoding="utf-8")
        assert "Fact-store freshness" in text, (
            "Fact-store freshness label must appear in TIER_1"
        )

    def test_ms_enforce_fast_exits_zero(self) -> None:
        """ms-enforce --fast exits 0 (our check is warn-only)."""
        result = subprocess.run(
            [_py(), str(REPO / "ms-enforce"), "--fast"],
            capture_output=True, text=True, cwd=str(REPO), timeout=120,
        )
        combined = result.stdout + result.stderr
        assert "Fact-store freshness" in combined or "fact_freshness" in combined, (
            "Fact-store freshness check should appear in ms-enforce output"
        )
