"""tests/test_audit_probe_aging.py — Tests for tools/audit_probe_aging.py (BATCH-11 S1, P0).

The MANDATORY RED-PATH test: a probe stuck INDETERMINATE for N runs makes the
aging engine emit DRIFT / a non-zero aged count. This proves the GROUND-gate
brownout detector can go red against physics.

Also covers:
  - A ground-touching probe never ages (streak resets).
  - configured-host rc127 -> immediate DRIFT; no-host rc127 -> quiet.
  - WRONG-target value -> immediate DRIFT (LR-2 class).
  - Missing baseline = establish-not-alarm.
  - Exit code always 0 (warn-only).
  - ms-enforce registration.

All tests use tmp_path; no real baseline / registry mutation.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "audit_probe_aging.py"


def _load_engine():
    """Import the aging engine module from the tool path."""
    spec = importlib.util.spec_from_file_location("audit_probe_aging", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _py() -> str:
    venv_py = REPO / ".venv" / "bin" / "python3"
    return str(venv_py) if venv_py.exists() else sys.executable


def _write_registry(tmp_path: Path, probes: list[dict]) -> Path:
    p = tmp_path / "probe_registry.json"
    p.write_text(json.dumps({"_schema_version": 1, "probes": probes}), encoding="utf-8")
    return p


def _run_n(engine, repo: Path, registry: Path, baseline: Path, n: int, runs_to_red: int):
    """Run the engine n times in --record mode; return the final (ok, summary, lines)."""
    result = (True, "", [])
    for _ in range(n):
        result = engine.run(
            repo, registry, baseline,
            runs_to_red=runs_to_red, record=True,
        )
    return result


# ---------------------------------------------------------------------------
# THE RED-PATH TEST — a probe stuck INDETERMINATE for N runs -> DRIFT
# ---------------------------------------------------------------------------

class TestRedPath:
    def test_indeterminate_for_n_runs_ages_to_drift(self, tmp_path: Path) -> None:
        engine = _load_engine()
        runs_to_red = 5
        # A probe that ALWAYS browns out: it prints an INDETERMINATE token and
        # never a ground token. (echo'd via a shell command — no host touched.)
        registry = _write_registry(tmp_path, [{
            "id": "stuck_indeterminate",
            "physics": "nothing reachable — a deliberately stuck probe",
            "cmd": "echo INDETERMINATE",
            "ground_tokens": ["verified", "DRIFT"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"

        # First (establishing) run: should NOT alarm even though it browns out.
        ok, summary, _ = engine.run(
            tmp_path, registry, baseline, runs_to_red=runs_to_red, record=True,
        )
        assert ok is True
        assert "establish" in summary.lower()
        assert "DRIFT:" not in summary  # establish-not-alarm

        # Run it until the streak reaches N. Establishing run was streak 1; need
        # runs_to_red total brownout runs to hit DRIFT.
        ok, summary, lines = _run_n(
            engine, tmp_path, registry, baseline,
            n=runs_to_red - 1, runs_to_red=runs_to_red,
        )

        # RED: the engine now reports the probe aged to DRIFT.
        assert ok is True  # still warn-only
        assert "stuck_indeterminate" in summary
        assert "DRIFT" in summary
        drift_lines = [ln for ln in lines if ln.startswith("DRIFT:")]
        assert any("stuck_indeterminate" in ln for ln in drift_lines)
        assert any(f"N={runs_to_red}" in ln for ln in drift_lines)

    def test_streak_below_n_does_not_drift(self, tmp_path: Path) -> None:
        engine = _load_engine()
        runs_to_red = 5
        registry = _write_registry(tmp_path, [{
            "id": "stuck_indeterminate",
            "physics": "nothing",
            "cmd": "echo INDETERMINATE",
            "ground_tokens": ["verified"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        # 3 runs total < N=5 -> no DRIFT.
        ok, summary, lines = _run_n(
            engine, tmp_path, registry, baseline, n=3, runs_to_red=runs_to_red,
        )
        assert ok is True
        assert not any(ln.startswith("DRIFT:") for ln in lines)


# ---------------------------------------------------------------------------
# Ground-touch resets the streak
# ---------------------------------------------------------------------------

class TestGroundResets:
    def test_ground_touch_never_ages(self, tmp_path: Path) -> None:
        engine = _load_engine()
        registry = _write_registry(tmp_path, [{
            "id": "healthy",
            "physics": "echoes a verified token",
            "cmd": "echo verified",
            "ground_tokens": ["verified"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        ok, summary, lines = _run_n(engine, tmp_path, registry, baseline, n=10, runs_to_red=5)
        assert ok is True
        assert "GROUND-TOUCH" in "\n".join(lines)
        assert not any(ln.startswith("DRIFT:") for ln in lines)


# ---------------------------------------------------------------------------
# rc127 discriminator: configured-host -> DRIFT; no-host -> quiet
# ---------------------------------------------------------------------------

class TestRc127Discriminator:
    def test_configured_host_rc127_immediate_drift(self, tmp_path: Path) -> None:
        engine = _load_engine()
        registry = _write_registry(tmp_path, [{
            "id": "configured_missing",
            "physics": "a host probe that should be installed",
            "cmd": "this_command_does_not_exist_xyz",  # rc 127
            "ground_tokens": ["verified"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": True,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        # Even on the first (establishing) data the subclass is configured-rc127;
        # establish-not-alarm suppresses the summary DRIFT on run 1, so run twice.
        engine.run(tmp_path, registry, baseline, record=True)
        ok, summary, lines = engine.run(tmp_path, registry, baseline, record=True)
        assert ok is True
        assert any("configured_missing" in ln and ln.startswith("DRIFT:") for ln in lines)
        assert any("rc127" in ln for ln in lines)

    def test_no_host_rc127_is_quiet(self, tmp_path: Path) -> None:
        engine = _load_engine()
        registry = _write_registry(tmp_path, [{
            "id": "no_host",
            "physics": "a host probe with no host configured (headless)",
            "cmd": "this_command_does_not_exist_xyz",  # rc 127
            "ground_tokens": ["verified"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        engine.run(tmp_path, registry, baseline, record=True)
        ok, summary, lines = engine.run(tmp_path, registry, baseline, record=True)
        assert ok is True
        # no-host rc127 does NOT immediately DRIFT (it is quiet, ages slowly).
        assert not any("no_host" in ln and "rc127" in ln and ln.startswith("DRIFT:") for ln in lines)


# ---------------------------------------------------------------------------
# WRONG-target value -> immediate DRIFT (LR-2 class)
# ---------------------------------------------------------------------------

class TestWrongTarget:
    def test_wrong_target_value_drifts(self, tmp_path: Path) -> None:
        engine = _load_engine()
        # Probe emits JSON with bound_port:22 (sshd) — the WRONG target.
        registry = _write_registry(tmp_path, [{
            "id": "wrong_port",
            "physics": "/proc/net/tcp for SLOP's port",
            "cmd": 'echo {\\"bound_port\\": 22}',
            "ground_tokens": ["bound_port"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
            "wrong_target": {"json_field": "bound_port", "wrong_values": [22]},
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        engine.run(tmp_path, registry, baseline, record=True)
        ok, summary, lines = engine.run(tmp_path, registry, baseline, record=True)
        assert ok is True
        assert any("wrong_port" in ln and ln.startswith("DRIFT:") for ln in lines)
        assert any("WRONG" in ln for ln in lines)

    def test_correct_target_value_grounds(self, tmp_path: Path) -> None:
        engine = _load_engine()
        registry = _write_registry(tmp_path, [{
            "id": "right_port",
            "physics": "/proc/net/tcp for SLOP's port",
            "cmd": 'echo {\\"bound_port\\": 8080}',
            "ground_tokens": ["bound_port"],
            "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
            "wrong_target": {"json_field": "bound_port", "wrong_values": [22]},
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        ok, summary, lines = engine.run(tmp_path, registry, baseline, record=True)
        assert ok is True
        assert any("right_port" in ln and ln.startswith("GROUND-TOUCH:") for ln in lines)


# ---------------------------------------------------------------------------
# Establish-not-alarm + missing baseline
# ---------------------------------------------------------------------------

class TestEstablishNotAlarm:
    def test_missing_baseline_establishes(self, tmp_path: Path) -> None:
        engine = _load_engine()
        registry = _write_registry(tmp_path, [{
            "id": "p", "physics": "x", "cmd": "echo verified",
            "ground_tokens": ["verified"], "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        assert not baseline.exists()
        ok, summary, _ = engine.run(tmp_path, registry, baseline, record=True)
        assert ok is True
        assert baseline.exists()
        assert "establish" in summary.lower()


# ---------------------------------------------------------------------------
# CLI exit code always 0
# ---------------------------------------------------------------------------

class TestExitCode:
    def test_cli_exit_zero_on_drift(self, tmp_path: Path) -> None:
        registry = _write_registry(tmp_path, [{
            "id": "stuck", "physics": "x", "cmd": "echo INDETERMINATE",
            "ground_tokens": ["verified"], "brownout_tokens": ["INDETERMINATE"],
            "host_configured": False,
        }])
        baseline = tmp_path / ".probe-health-baseline.json"
        # Pre-seed a baseline at the red threshold by running enough times.
        for _ in range(6):
            r = subprocess.run(
                [_py(), str(SCRIPT), "--repo", str(tmp_path),
                 "--registry", str(registry), "--baseline", str(baseline),
                 "--record", "--runs-to-red", "3"],
                capture_output=True, text=True, timeout=60,
            )
        assert r.returncode == 0  # always 0 — warn-only
        assert "DRIFT" in (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# ms-enforce registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_registered_in_ms_enforce(self) -> None:
        text = (REPO / "ms-enforce").read_text(encoding="utf-8")
        assert "def check_probe_aging" in text
        assert "check_probe_aging)" in text  # appears in a TIER_1 tuple

    def test_registry_and_doc_exist(self) -> None:
        assert (REPO / "tools" / "probe_registry.json").exists()
        assert (REPO / "docs" / "PROBE-REGISTRY.md").exists()

    def test_registry_enumerates_named_brownout_probes(self) -> None:
        data = json.loads((REPO / "tools" / "probe_registry.json").read_text())
        ids = {p["id"] for p in data["probes"]}
        # report §4g named probes + the LR-2 port probe.
        assert "check_handoff_freshness" in ids
        assert "audit_doc_reality" in ids
        assert "audit_status_file_freshness" in ids
        assert "audit_backlog_stale_dateless" in ids
        assert "slop_reality_probe_port" in ids
