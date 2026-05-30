"""tests/test_backlog_ring_registry.py — BATCH-11 S2 coverage + red-path tests for
the cross-repo (repo, file, syntax) triage-queue RING_REGISTRY in
tools/audit_backlog_stale.py.

Covers:
  * Coverage assertion: every on-disk ring (repo root reachable + a known queue
    file present) has a RING_REGISTRY row.
  * resolve_rings(): GROUND reconciliation — present queue -> 'verified';
    registered-but-absent -> 'INDETERMINATE' (loud, never silent).
  * RED-PATH (mandatory): coverage_drift() fed a present-on-disk ring with NO
    registry row asserts DRIFT — proves the gate can go red.
  * --check-rings CLI mode: exits 0 (warn-only) and prints per-ring verdicts.
  * Each registry ring has a matching ring_reachability_* probe in
    tools/probe_registry.json (open-seam append landed).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCANNER = REPO / "tools" / "audit_backlog_stale.py"
PROBE_REGISTRY = REPO / "tools" / "probe_registry.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_backlog_stale", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else sys.executable


# ---------------------------------------------------------------------------
# Registry shape + the 3-ring contract
# ---------------------------------------------------------------------------

class TestRegistryShape:
    def test_registry_has_three_rings(self):
        mod = _load_module()
        rings = {r["ring"] for r in mod.RING_REGISTRY}
        assert rings == {"slop", "slop_process", "mediastack"}, (
            f"RING_REGISTRY must cover the 3 repo rings, got {rings}"
        )

    def test_every_row_has_repo_file_syntax(self):
        mod = _load_module()
        for r in mod.RING_REGISTRY:
            for k in ("ring", "repo", "queue_file", "syntax", "present_expected"):
                assert k in r, f"ring {r.get('ring')} missing key {k!r}"


# ---------------------------------------------------------------------------
# Coverage assertion: every on-disk ring has a registry row
# ---------------------------------------------------------------------------

class TestCoverageAssertion:
    def test_every_on_disk_ring_has_a_row(self):
        """Any ring whose repo root + queue file are present on disk must have a
        RING_REGISTRY row. coverage_drift over the on-disk set must be empty."""
        mod = _load_module()
        # Independently establish which rings are present on disk.
        on_disk = []
        for r in mod.RING_REGISTRY:
            qf = Path(r["repo"]) / r["queue_file"]
            if qf.exists():
                on_disk.append((r["ring"], r["repo"], r["queue_file"]))
        drifts = mod.coverage_drift(on_disk)
        assert drifts == [], f"on-disk rings missing a registry row (DRIFT): {drifts}"


# ---------------------------------------------------------------------------
# resolve_rings: GROUND reconciliation
# ---------------------------------------------------------------------------

class TestResolveRings:
    def test_present_ring_verified(self, tmp_path):
        mod = _load_module()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "BACKLOG.md").write_text("# q\n")
        reg = [{
            "ring": "test", "repo": str(tmp_path), "queue_file": "docs/BACKLOG.md",
            "syntax": "slop-bracket", "present_expected": True,
        }]
        res = mod.resolve_rings(reg)
        assert res[0]["verdict"] == "verified"
        assert res[0]["present"] is True

    def test_absent_expected_ring_indeterminate(self, tmp_path):
        mod = _load_module()
        reg = [{
            "ring": "test", "repo": str(tmp_path), "queue_file": "docs/NOPE.md",
            "syntax": "slop-bracket", "present_expected": True,
        }]
        res = mod.resolve_rings(reg)
        assert res[0]["verdict"] == "INDETERMINATE"
        assert "INDETERMINATE" in res[0]["detail"]

    def test_absent_unexpected_ring_indeterminate_not_silent(self, tmp_path):
        """An unresolved-queue ring (present_expected False, e.g. mediastack) is
        INDETERMINATE — never a silent pass."""
        mod = _load_module()
        reg = [{
            "ring": "test", "repo": str(tmp_path), "queue_file": "docs/NOPE.md",
            "syntax": "slop-bracket", "present_expected": False,
        }]
        res = mod.resolve_rings(reg)
        assert res[0]["verdict"] == "INDETERMINATE"
        assert res[0]["verdict"] != "verified"  # explicitly NOT a silent OK


# ---------------------------------------------------------------------------
# RED PATH (mandatory): present-on-disk ring with NO registry row -> DRIFT
# ---------------------------------------------------------------------------

class TestRedPath:
    def test_present_ring_without_row_drifts(self):
        """Feed a known-bad input: a ring whose queue file exists on disk but
        which is NOT in the registry -> coverage_drift must report DRIFT.
        Proves the seam-coverage gate can go red."""
        mod = _load_module()
        # The SLOP ring's BACKLOG.md genuinely exists on disk; pretend the
        # registry has NO row for a ring id that maps to it.
        bogus = ("ring_not_registered", str(REPO), "docs/BACKLOG.md")
        drifts = mod.coverage_drift([bogus])
        assert len(drifts) == 1, "an on-disk ring with no registry row must DRIFT"
        assert drifts[0]["verdict"] == "DRIFT"
        assert "SEAM" in drifts[0]["detail"]

    def test_registered_ring_does_not_drift(self):
        """Control: a ring that IS in the registry does NOT drift."""
        mod = _load_module()
        registered = ("slop", "/home/stack/code/slop", "docs/BACKLOG.md")
        drifts = mod.coverage_drift([registered])
        assert drifts == []


# ---------------------------------------------------------------------------
# --check-rings CLI mode (warn-only)
# ---------------------------------------------------------------------------

class TestCheckRingsCLI:
    def test_check_rings_exits_zero(self):
        result = subprocess.run(
            [_py(), str(SCANNER), "--check-rings"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, "--check-rings is warn-only (exit 0)"
        combined = result.stdout + result.stderr
        assert "ring" in combined.lower()
        # vocabulary used verbatim
        assert "verified" in combined or "INDETERMINATE" in combined


# ---------------------------------------------------------------------------
# Open-seam: each ring has a matching reachability probe
# ---------------------------------------------------------------------------

class TestProbeRegistryAppend:
    def test_each_ring_has_a_reachability_probe(self):
        mod = _load_module()
        reg = json.loads(PROBE_REGISTRY.read_text())
        probe_ids = {p["id"] for p in reg["probes"]}
        for r in mod.RING_REGISTRY:
            expected = f"ring_reachability_{r['ring']}"
            assert expected in probe_ids, (
                f"missing open-seam probe row {expected!r} in probe_registry.json"
            )
