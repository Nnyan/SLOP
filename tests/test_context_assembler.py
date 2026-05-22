"""Regression tests for backend.health.context_assembler.

Step 1.4.d — refactor of `_build` (cyclomatic complexity 136 → ≤ 15)
into per-section helpers. These tests lock in behaviour of the public
entry point and the pure helpers so that future edits to any single
section cannot silently change the assembled output.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.state import init_db  # noqa: E402
from backend.health.context_assembler import (  # noqa: E402
    assemble_context,
    _section_runtime_state,
    _section_network_checks,
    _section_app_category,
    _profile_os,
    _profile_cpu,
    _profile_ram,
    _profile_gpu,
    _profile_docker,
    _profile_user,
)


@pytest.fixture(autouse=True, scope="module")
def _fresh_state_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide a freshly-migrated empty StateDB for the whole module.

    `assemble_context` opens StateDB() during _build; without a configured
    path it raises StateError and the wrapper swallows it as `""`. We point
    state at a tmp DB so DB-less helpers and the public API can both run.
    """
    db_path = tmp_path_factory.mktemp("ctx_asm") / "state.db"
    init_db(db_path)
    return db_path


# ── Public API ─────────────────────────────────────────────────────


def test_assemble_context_returns_marked_block_for_unknown_app() -> None:
    """Even when nothing matches in the DB, the wrapper markers must appear
    so the LLM can recognise the structure."""
    out = assemble_context("nonexistent_app_xyz_1.4d", "http_check")
    assert out.startswith("=== DIAGNOSTIC CONTEXT ===")
    assert out.endswith("=== END CONTEXT ===")


def test_assemble_context_never_raises_on_garbage_input() -> None:
    """Per docstring contract, assemble_context returns "" or a context
    block on any input — never raises."""
    out = assemble_context("", "")
    assert isinstance(out, str)
    out2 = assemble_context("with spaces & symbols!@#", "")
    assert isinstance(out2, str)


def test_assemble_context_surfaces_runtime_signals() -> None:
    """Runtime crash-loop / OOM / disk signals must round-trip through the
    public API end-to-end (covers section 2 + section 15 in the orchestrator)."""
    out = assemble_context(
        "nonexistent_app_xyz_1.4d", "http_check",
        runtime={
            "restart_count": 15,
            "exit_code": 137,
            "oom_killed": True,
            "config_disk_pct": 92,
            "network_checks": {"google.com": True, "internal-svc": False},
        },
    )
    assert "restarts: 15" in out
    assert "crash-looping" in out
    assert "last exit code: 137" in out
    assert "OOM killed: YES" in out
    assert "Config disk: 92% full" in out
    assert "Network reachability from container:" in out
    assert "✓ google.com" in out
    assert "✗ internal-svc" in out


# ── Pure helpers — no DB / fs needed ───────────────────────────────


def test_section_runtime_state_handles_empty_runtime() -> None:
    lines: list[str] = []
    _section_runtime_state({}, lines)
    assert lines == []


def test_section_runtime_state_emits_crash_loop_warning() -> None:
    lines: list[str] = []
    _section_runtime_state(
        {"restart_count": 11, "exit_code": 1, "oom_killed": False}, lines
    )
    out = "\n".join(lines)
    assert "restarts: 11" in out
    assert "crash-looping" in out
    assert "last exit code: 1" in out
    assert "OOM killed" not in out


def test_section_runtime_state_no_crash_loop_under_threshold() -> None:
    lines: list[str] = []
    _section_runtime_state({"restart_count": 5}, lines)
    out = "\n".join(lines)
    assert "restarts: 5" in out
    assert "crash-looping" not in out


def test_section_network_checks_renders_marks() -> None:
    lines: list[str] = []
    _section_network_checks({"network_checks": {"a": True, "b": False}}, lines)
    out = "\n".join(lines)
    assert "Network reachability from container:" in out
    assert "✓ a" in out
    assert "✗ b" in out


def test_section_network_checks_quiet_when_absent() -> None:
    lines: list[str] = []
    _section_network_checks({}, lines)
    assert lines == []
    _section_network_checks({"network_checks": {}}, lines)
    assert lines == []


@pytest.mark.parametrize("app_key,expected_substr", [
    ("sonarr", "ARR APP"),
    ("radarr", "ARR APP"),
    ("ollama", "LLM/AI APP"),
    ("decypharr", "DEBRID APP"),
    ("immich", "PHOTO/IMMICH APP"),
    ("jellyfin", "MEDIA SERVER"),
    ("plex", "MEDIA SERVER"),
])
def test_section_app_category_branches(app_key: str, expected_substr: str) -> None:
    lines: list[str] = []
    _section_app_category(app_key, lines)
    assert any(expected_substr in line for line in lines), \
        f"missing {expected_substr!r} for {app_key!r}: {lines}"


def test_section_app_category_unknown_app_silent() -> None:
    lines: list[str] = []
    _section_app_category("totally_unknown_thing", lines)
    assert lines == []


# ── _profile_* helpers (system profile sub-sections) ───────────────


def test_profile_os_arm_warning() -> None:
    lines: list[str] = []
    _profile_os(
        {"distro": "Debian", "version": "12", "arch": "arm64", "kernel": "6.1.0"},
        lines,
    )
    out = "\n".join(lines)
    assert "Host OS: Debian 12 (arm64)" in out
    assert "ARM architecture" in out


def test_profile_os_x86_no_warning() -> None:
    lines: list[str] = []
    _profile_os(
        {"distro": "Ubuntu", "version": "24.04", "arch": "x86_64", "kernel": "6.5"},
        lines,
    )
    out = "\n".join(lines)
    assert "Host OS: Ubuntu 24.04 (x86_64)" in out
    assert "ARM architecture" not in out


def test_profile_os_silent_without_distro() -> None:
    lines: list[str] = []
    _profile_os({}, lines)
    assert lines == []


def test_profile_cpu_avx2_warning_when_missing() -> None:
    lines: list[str] = []
    _profile_cpu({"avx2": False}, "Some CPU", 8, lines)
    out = "\n".join(lines)
    assert "CPU: Some CPU · 8 cores" in out
    assert "lacks AVX2" in out


def test_profile_cpu_no_warning_with_avx2() -> None:
    lines: list[str] = []
    _profile_cpu({"avx2": True}, "Modern CPU", 16, lines)
    out = "\n".join(lines)
    assert "CPU: Modern CPU · 16 cores" in out
    assert "lacks AVX2" not in out


def test_profile_ram_critically_low() -> None:
    lines: list[str] = []
    _profile_ram(8.0, 0.5, lines)
    out = "\n".join(lines)
    assert "RAM: 8GB total" in out
    assert "CRITICALLY LOW" in out


def test_profile_ram_low() -> None:
    lines: list[str] = []
    _profile_ram(16.0, 1.5, lines)
    out = "\n".join(lines)
    assert "RAM low" in out


def test_profile_ram_healthy() -> None:
    lines: list[str] = []
    _profile_ram(32.0, 8.0, lines)
    out = "\n".join(lines)
    assert "RAM: 32GB total, 8.0GB available" in out
    assert "RAM low" not in out
    assert "CRITICALLY LOW" not in out


def test_profile_gpu_nvidia_with_cuda() -> None:
    lines: list[str] = []
    _profile_gpu(
        {"model": "RTX 4090", "vram_gb": 24, "vendor": "Nvidia",
         "cuda": "12.4", "inference_capable": True},
        lines,
    )
    out = "\n".join(lines)
    assert "GPU: RTX 4090 · 24GB VRAM · CUDA 12.4" in out
    assert "GPU inference capable" in out


def test_profile_gpu_amd_rocm() -> None:
    lines: list[str] = []
    _profile_gpu(
        {"model": "Radeon", "vram_gb": 16, "vendor": "AMD", "backend": "5.7"},
        lines,
    )
    assert any("ROCm 5.7" in line for line in lines)


def test_profile_gpu_apple_metal() -> None:
    lines: list[str] = []
    _profile_gpu({"model": "M2 Pro", "vram_gb": 32, "vendor": "Apple"}, lines)
    assert any("Metal (Apple Silicon)" in line for line in lines)


def test_profile_gpu_silent_without_model() -> None:
    lines: list[str] = []
    _profile_gpu({}, lines)
    assert lines == []


def test_profile_docker_saturation_warning() -> None:
    lines: list[str] = []
    _profile_docker(
        {"engine": "27.0.0", "compose": "v2", "containers_running": 80},
        16.0,
        lines,
    )
    out = "\n".join(lines)
    assert "Docker: v27.0.0" in out
    assert "CONTAINER SATURATION" in out


def test_profile_docker_no_saturation_at_normal_density() -> None:
    lines: list[str] = []
    _profile_docker(
        {"engine": "27.0.0", "compose": "v2", "containers_running": 20},
        32.0,
        lines,
    )
    out = "\n".join(lines)
    assert "Docker: v27.0.0" in out
    assert "CONTAINER SATURATION" not in out


def test_profile_user_renders_puid_pgid() -> None:
    lines: list[str] = []
    _profile_user({"puid": 1000, "pgid": 1000, "username": "stack"}, lines)
    out = "\n".join(lines)
    assert "PUID=1000 PGID=1000" in out
    assert "(stack)" in out
    assert "Permission denied" in out


def test_profile_user_silent_without_puid() -> None:
    lines: list[str] = []
    _profile_user({}, lines)
    assert lines == []
