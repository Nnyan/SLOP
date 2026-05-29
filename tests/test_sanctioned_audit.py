"""tests/test_sanctioned_audit.py — Unit tests for tools/sanctioned/_audit.py.

Verifies the public contract as pinned in S-68 Stream B:
  - SANCTIONED_OPS_LOG path constant
  - write_entry() public signature and behaviour

All tests operate on tmp_path fixtures — the real docs/SANCTIONED-OPS-LOG.md
is never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the tools package importable when tests run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.sanctioned._audit import (
    SANCTIONED_OPS_LOG,
    write_entry,
)


# ── constant contract ─────────────────────────────────────────────────────────


def test_sanctioned_ops_log_constant() -> None:
    """SANCTIONED_OPS_LOG must be exactly docs/SANCTIONED-OPS-LOG.md."""
    assert SANCTIONED_OPS_LOG == Path("docs/SANCTIONED-OPS-LOG.md")


# ── first write creates file with header ─────────────────────────────────────


def test_first_write_creates_file_with_header(tmp_path: Path) -> None:
    """First call to write_entry must create the log file from scratch,
    including a descriptive header block and a --- divider line."""
    log = tmp_path / "OPS-LOG.md"
    assert not log.exists()

    write_entry(
        tool="test_tool",
        op="test-op",
        pre_sha="abc123",
        post_sha="def456",
        result="OK",
        notes="first entry",
        caller="tester",
        timestamp="2026-05-29T12:00:00Z",
        log_path=log,
    )

    assert log.exists()
    content = log.read_text(encoding="utf-8")

    # Header block must be present
    assert "# Sanctioned-Ops Log" in content
    # Divider must be present
    assert "\n---\n" in content
    # The entry itself must be present
    assert "## 2026-05-29T12:00:00Z — test_tool: test-op" in content
    assert "- **Result:** OK" in content


def test_first_write_entry_fields_rendered(tmp_path: Path) -> None:
    """All fields of the entry must appear verbatim in the rendered output."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="robot_settings",
        op="lift push",
        pre_sha="aaa111",
        post_sha="bbb222",
        result="OK",
        notes="operator-initiated push after wave S-68",
        caller="stack",
        timestamp="2026-05-29T08:30:00Z",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    assert "- **Tool:** robot_settings" in content
    assert "- **Op:** lift push" in content
    assert "- **Pre-SHA:** aaa111" in content
    assert "- **Post-SHA:** bbb222" in content
    assert "- **Result:** OK" in content
    assert "- **Caller:** stack" in content
    assert "- **Notes:** operator-initiated push after wave S-68" in content


# ── subsequent writes prepend below divider ───────────────────────────────────


def test_subsequent_writes_prepend_below_divider(tmp_path: Path) -> None:
    """Second and later writes prepend newest-first below the --- divider,
    so the most-recent entry always appears at the top of the entries section."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="tool_a",
        op="op-first",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="first",
        caller="u",
        timestamp="2026-05-29T10:00:00Z",
        log_path=log,
    )
    write_entry(
        tool="tool_b",
        op="op-second",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="second",
        caller="u",
        timestamp="2026-05-29T11:00:00Z",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    pos_first = content.find("op-first")
    pos_second = content.find("op-second")

    # Newest (second) must appear before oldest (first)
    assert pos_second < pos_first, (
        "newest entry must be prepended above older entries"
    )

    # Both entries are present
    assert "tool_a" in content
    assert "tool_b" in content

    # File still has exactly one divider
    assert content.count("\n---\n") == 1


def test_three_writes_ordering(tmp_path: Path) -> None:
    """Three writes: newest last-written entry must be topmost."""
    log = tmp_path / "OPS-LOG.md"
    for i in range(3):
        write_entry(
            tool="tool",
            op=f"op-{i}",
            pre_sha=None,
            post_sha=None,
            result="OK",
            notes=f"write {i}",
            caller="u",
            timestamp=f"2026-05-29T0{i}:00:00Z",
            log_path=log,
        )

    content = log.read_text(encoding="utf-8")
    pos_0 = content.find("op-0")
    pos_1 = content.find("op-1")
    pos_2 = content.find("op-2")

    assert pos_2 < pos_1 < pos_0, "entries must be newest-first"


# ── ABORTED / result fields ───────────────────────────────────────────────────


def test_aborted_result_renders(tmp_path: Path) -> None:
    """An ABORTED result is stored verbatim with the full reason string."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="force_push_tag",
        op="force-push",
        pre_sha="pre000",
        post_sha=None,
        result="ABORTED: conflict detected",
        notes="push refused — conflict on remote ref",
        caller="agent",
        timestamp="2026-05-29T09:15:00Z",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    assert "- **Result:** ABORTED: conflict detected" in content
    assert "- **Post-SHA:** n/a" in content


def test_failed_result_renders(tmp_path: Path) -> None:
    """A FAILED result string is preserved exactly."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="rm_recursive_safe",
        op="rm-recursive",
        pre_sha=None,
        post_sha=None,
        result="FAILED: path outside repo root",
        notes="target /etc rejected by containment check",
        caller="agent",
        timestamp="2026-05-29T09:20:00Z",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    assert "FAILED: path outside repo root" in content


# ── missing optional fields tolerated ────────────────────────────────────────


def test_none_sha_renders_as_na(tmp_path: Path) -> None:
    """When pre_sha or post_sha is None, it renders as 'n/a', not 'None'."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="robot_settings",
        op="restore",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="settings restored to wave-mode profile",
        caller="agent",
        timestamp="2026-05-29T13:00:00Z",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    assert "- **Pre-SHA:** n/a" in content
    assert "- **Post-SHA:** n/a" in content
    # Python's "None" string must not appear in the entry lines
    entry_lines = [
        ln for ln in content.splitlines()
        if ln.startswith("- **Pre-SHA:**") or ln.startswith("- **Post-SHA:**")
    ]
    for line in entry_lines:
        assert "None" not in line, f"'None' literal found in: {line!r}"


def test_caller_defaults_to_env_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When caller is omitted, write_entry falls back to $USER."""
    monkeypatch.setenv("USER", "test_user_env")
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="t",
        op="o",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    assert "- **Caller:** test_user_env" in content


def test_timestamp_defaults_to_utc_now(tmp_path: Path) -> None:
    """When timestamp is omitted, write_entry uses UTC now (ISO-8601 with Z)."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="t",
        op="o",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    # A UTC-now timestamp ends in Z
    import re
    ts_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
    assert ts_pattern.search(content), "UTC timestamp with Z suffix must appear in entry"


def test_empty_notes_tolerated(tmp_path: Path) -> None:
    """Empty notes string must not break the entry — field renders as empty."""
    log = tmp_path / "OPS-LOG.md"

    write_entry(
        tool="t",
        op="o",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="",
        caller="u",
        timestamp="2026-05-29T00:00:00Z",
        log_path=log,
    )

    content = log.read_text(encoding="utf-8")
    assert "- **Notes:** " in content  # field present even if empty


# ── custom log_path is honoured ───────────────────────────────────────────────


def test_custom_log_path_used(tmp_path: Path) -> None:
    """write_entry must write to the log_path argument, not the default."""
    custom = tmp_path / "custom" / "audit.md"
    assert not custom.exists()

    write_entry(
        tool="t",
        op="o",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="custom path test",
        caller="u",
        timestamp="2026-05-29T00:00:00Z",
        log_path=custom,
    )

    assert custom.exists()
    assert "custom path test" in custom.read_text(encoding="utf-8")


# ── real log file untouched ───────────────────────────────────────────────────


def test_real_log_file_is_not_modified(tmp_path: Path) -> None:
    """Sanity check: all test writes go to tmp_path, not to the real log."""
    real_log = Path("docs/SANCTIONED-OPS-LOG.md")
    if real_log.exists():
        before = real_log.read_text(encoding="utf-8")
    else:
        before = None

    log = tmp_path / "isolated.md"
    write_entry(
        tool="t",
        op="o",
        pre_sha=None,
        post_sha=None,
        result="OK",
        notes="isolation check",
        caller="u",
        timestamp="2026-05-29T00:00:00Z",
        log_path=log,
    )

    if before is not None:
        after = real_log.read_text(encoding="utf-8")
        assert after == before, "real SANCTIONED-OPS-LOG.md must not be modified by tests"
