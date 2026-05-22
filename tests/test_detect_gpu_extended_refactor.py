"""Regression tests for the detect_gpu_extended refactor (step 2.7.f).

`detect_gpu_extended` previously had cyclomatic complexity 17 — three
inline detection blocks (ROCm / AMD iGPU / Apple Metal), each wrapped
in try/except with nested loops + conditionals.

The refactor extracts each block into its own helper and walks them
via `_GPU_EXTENDED_DETECTORS` (a tuple of callables). The orchestrator
drops to ≤ 4.

These tests focus on the dispatch chain — per-detector subprocess
interactions are environment-dependent and out of scope for unit tests.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import system_eval  # noqa: E402
from backend.core.system_eval import (  # noqa: E402
    _GPU_EXTENDED_DETECTORS,
    _amd_igpu_vram_mb,
    _detect_gpu_amd_igpu,
    _detect_gpu_apple_metal,
    _detect_gpu_rocm,
    detect_gpu_extended,
)


# ── chain composition / drift guard ────────────────────────────────


def test_detector_chain_order() -> None:
    """ROCm → AMD iGPU → Apple Metal — chain order matters because
    discrete AMD (ROCm) is preferred over its iGPU on the same box."""
    assert _GPU_EXTENDED_DETECTORS == (
        _detect_gpu_rocm,
        _detect_gpu_amd_igpu,
        _detect_gpu_apple_metal,
    )


# ── _amd_igpu_vram_mb ──────────────────────────────────────────────


def test_amd_igpu_vram_returns_minus_one_when_no_drm_files(monkeypatch) -> None:
    """No /sys/class/drm hits → -1 sentinel (shared memory APU)."""
    import glob
    monkeypatch.setattr(glob, "glob", lambda _pat: [])
    assert _amd_igpu_vram_mb() == -1


# ── orchestrator: detect_gpu_extended ──────────────────────────────


def _fake_base(name: str | None) -> dict:
    return {
        "vendor": None, "name": name, "vram_mb": 0,
        "inference_capable": False, "cuda_version": None, "backend": None,
    }


def test_orchestrator_short_circuits_when_base_has_name() -> None:
    """If detect_gpu() already found something (NVIDIA, etc), the
    extended detectors must not run — they're slow subprocess calls."""
    fake_base = _fake_base("NVIDIA RTX 4090")
    called: list[str] = []
    fake_chain = (
        lambda: (called.append("a"), None)[1],
        lambda: (called.append("b"), None)[1],
    )
    with patch.object(system_eval, "detect_gpu", return_value=fake_base), \
         patch.object(system_eval, "_GPU_EXTENDED_DETECTORS", fake_chain):
        result = detect_gpu_extended()
    assert result == fake_base
    assert called == [], "detectors must not run when base.name is set"


def test_orchestrator_returns_first_detector_hit() -> None:
    """First detector returning non-None wins; later detectors must not run."""
    fake_base = _fake_base(None)
    rocm_hit = {"vendor": "AMD", "name": "MI300", "vram_mb": 192_000,
                "inference_capable": True, "cuda_version": None,
                "backend": "rocm"}
    later_called: list[str] = []
    fake_chain = (
        lambda: rocm_hit,
        lambda: (later_called.append("igpu"), None)[1],
    )
    with patch.object(system_eval, "detect_gpu", return_value=fake_base), \
         patch.object(system_eval, "_GPU_EXTENDED_DETECTORS", fake_chain):
        result = detect_gpu_extended()
    assert result == rocm_hit
    assert later_called == [], \
        "later detectors must not run after first hit"


def test_orchestrator_falls_through_to_base_when_no_detector_hits() -> None:
    """All detectors return None → orchestrator returns the base
    (i.e. the no-GPU result from detect_gpu())."""
    fake_base = _fake_base(None)
    fake_chain = (lambda: None, lambda: None, lambda: None)
    with patch.object(system_eval, "detect_gpu", return_value=fake_base), \
         patch.object(system_eval, "_GPU_EXTENDED_DETECTORS", fake_chain):
        assert detect_gpu_extended() == fake_base


def test_orchestrator_walks_detectors_in_declared_order() -> None:
    """Drift guard — the chain must be walked in the order the tuple
    declares (matters because of preference: ROCm > iGPU on AMD)."""
    fake_base = _fake_base(None)
    order: list[str] = []
    fake_chain = (
        lambda: (order.append("first"), None)[1],
        lambda: (order.append("second"), None)[1],
        lambda: (order.append("third"), None)[1],
    )
    with patch.object(system_eval, "detect_gpu", return_value=fake_base), \
         patch.object(system_eval, "_GPU_EXTENDED_DETECTORS", fake_chain):
        detect_gpu_extended()
    assert order == ["first", "second", "third"]


# ── _detect_gpu_rocm ───────────────────────────────────────────────


def test_rocm_detector_returns_none_when_subprocess_raises() -> None:
    """rocm-smi missing → FileNotFoundError → detector returns None."""
    import subprocess
    with patch.object(subprocess, "run",
                      side_effect=FileNotFoundError("rocm-smi")):
        assert _detect_gpu_rocm() is None


def test_apple_metal_detector_returns_none_off_apple_silicon() -> None:
    """Linux box → detector skips even if system_profiler somehow returns 0."""
    import subprocess
    fake_proc = type("P", (), {"returncode": 0, "stdout": "{}"})()
    with patch.object(subprocess, "run", return_value=fake_proc), \
         patch("platform.system", return_value="Linux"):
        assert _detect_gpu_apple_metal() is None
