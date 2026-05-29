"""tests/test_access_requests_processor.py — Tests for tools/process_access_requests.py

Covers:
- Parser round-trips: four categories + three status markers.
- list shows only pending entries.
- process --dry-run proposes actions without writing the fixture file.
- Idempotency: already-applied ([x]) entry is a no-op.
- [deny] entry is skipped without --allow-deny-additions, processed with it.
- Halt-on-first-failure ordering.
- Entry validation (missing fields).
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import pytest

# ---------------------------------------------------------------------------
# Load the tool module (hyphen-free name — tool uses underscore)
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent
_TOOL = _REPO / "tools" / "process_access_requests.py"


def _load_processor():
    spec = importlib.util.spec_from_file_location("process_access_requests", _TOOL)
    assert spec and spec.loader, f"Could not load {_TOOL}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


proc = _load_processor()

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_PENDING   = "[ ]"
_APPLIED   = "[x]"
_DENIED_M  = "[—]"   # em-dash marker for "denied/superseded"

_ENTRY_TEMPLATE = (
    "- `{marker}` **[{cat}] {subject}** — {desc}\n"
    "  Requested by: {source} ({date}). Status: {status_text}."
)


def _make_queue(entries_by_section: dict) -> str:
    """Build a minimal ACCESS-REQUESTS.md fixture string.

    entries_by_section: {category: [(marker, subject, desc, source, date, status_text), ...]}
    """
    sections = {
        "install": "## `[install]` — New packages / tools to install",
        "upgrade": "## `[upgrade]` — Dep upgrades blocked or pending external action",
        "allow":   "## `[allow]` — Settings allow-list additions",
        "deny":    "## `[deny]` — Settings deny-list additions",
    }
    lines = ["# Access Requests Queue\n"]
    for cat, heading in sections.items():
        lines.append(heading)
        for marker, subject, desc, source, date, status_text in entries_by_section.get(cat, []):
            lines.append(
                f"- `{marker}` **[{cat}] {subject}** — {desc}\n"
                f"  Requested by: {source} ({date}). Status: {status_text}."
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests: parser round-trips
# ---------------------------------------------------------------------------


class TestParser:
    def test_parses_all_four_categories(self, tmp_path: Path) -> None:
        content = _make_queue(
            {
                "install": [(_PENDING, "pkg-a", "install pkg-a", "wave-S-59", "2026-05-01", "pending")],
                "upgrade": [(_PENDING, "starlette", "upgrade starlette", "session-1", "2026-05-02", "pending")],
                "allow":   [(_PENDING, "WebFetch(domain:example.com)", "allow domain", "S-60", "2026-05-03", "pending")],
                "deny":    [(_PENDING, "Bash(rm -rf *)", "block dangerous rm", "S-60", "2026-05-04", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        entries = proc.parse_queue_file(qf)
        assert len(entries) == 4
        cats = {e["category"] for e in entries}
        assert cats == {"install", "upgrade", "allow", "deny"}

    def test_parses_three_status_markers(self, tmp_path: Path) -> None:
        content = _make_queue(
            {
                "install": [
                    (_PENDING,  "pkg-pending",  "desc", "src", "2026-05-01", "pending"),
                    (_APPLIED,  "pkg-applied",  "desc", "src", "2026-05-02", "applied"),
                    (_DENIED_M, "pkg-denied",   "desc", "src", "2026-05-03", "denied"),
                ],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        entries = proc.parse_queue_file(qf)
        statuses = {e["subject"]: e["status"] for e in entries}
        assert statuses["pkg-pending"] == "pending"
        assert statuses["pkg-applied"] == "applied"
        assert statuses["pkg-denied"] == "denied"

    def test_parses_date_and_source(self, tmp_path: Path) -> None:
        content = _make_queue(
            {
                "allow": [(_PENDING, "WebFetch(domain:nvd.nist.gov)", "CVE lookups", "wave-S-59-A", "2026-05-29", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        entries = proc.parse_queue_file(qf)
        assert len(entries) == 1
        assert entries[0]["date"] == "2026-05-29"
        assert "wave-S-59-A" in str(entries[0]["source"])


# ---------------------------------------------------------------------------
# Tests: list command
# ---------------------------------------------------------------------------


class TestList:
    def test_list_shows_only_pending(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "install": [
                    (_PENDING, "pkg-pending", "desc", "src", "2026-05-01", "pending"),
                    (_APPLIED, "pkg-done",    "desc", "src", "2026-05-02", "applied"),
                ],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        rc = proc.cmd_list(qf)
        out = capsys.readouterr().out

        assert rc == 0
        assert "PENDING_COUNT=1" in out
        assert "pkg-pending" in out
        assert "pkg-done" not in out

    def test_list_no_pending(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "install": [(_APPLIED, "pkg-done", "desc", "src", "2026-05-01", "applied")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        rc = proc.cmd_list(qf)
        out = capsys.readouterr().out

        assert rc == 0
        assert "PENDING_COUNT=0" in out

    def test_list_groups_by_category(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "install": [(_PENDING, "pkg-a", "desc", "src", "2026-05-01", "pending")],
                "allow":   [(_PENDING, "WebFetch(domain:x.com)", "desc", "src", "2026-05-01", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        rc = proc.cmd_list(qf)
        out = capsys.readouterr().out

        assert "[install]" in out
        assert "[allow]" in out


# ---------------------------------------------------------------------------
# Tests: process --dry-run
# ---------------------------------------------------------------------------


class TestProcessDryRun:
    def test_dry_run_does_not_modify_file(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "allow": [(_PENDING, "WebFetch(domain:example.com)", "test domain", "wave-S-59", "2026-05-29", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")
        original = qf.read_text(encoding="utf-8")

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "settings.local.json",
            "requirements": tmp_path / "requirements.txt",
            "requirements_dev": tmp_path / "requirements-dev.txt",
        }
        rc = proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=True,
            allow_deny=False,
            target_paths=target_paths,
        )
        after = qf.read_text(encoding="utf-8")

        assert rc == 0
        assert after == original, "dry-run must not modify the queue file"

    def test_dry_run_reports_proposed_action(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "install": [(_PENDING, "my-package", "install it", "S-59", "2026-05-29", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "settings.local.json",
            "requirements": tmp_path / "requirements.txt",
            "requirements_dev": tmp_path / "requirements-dev.txt",
        }
        proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=True,
            allow_deny=False,
            target_paths=target_paths,
        )
        out = capsys.readouterr().out
        assert "DRY_RUN" in out
        assert "my-package" in out


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_already_applied_entry_is_noop(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "install": [(_APPLIED, "pkg-already-done", "desc", "src", "2026-05-01", "applied")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")
        original = qf.read_text(encoding="utf-8")

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "settings.local.json",
            "requirements": tmp_path / "requirements.txt",
            "requirements_dev": tmp_path / "requirements-dev.txt",
        }
        rc = proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=False,
            allow_deny=False,
            target_paths=target_paths,
        )
        after = qf.read_text(encoding="utf-8")

        assert rc == 0
        assert after == original, "already-applied entry must not be re-processed"
        out = capsys.readouterr().out
        assert "SUMMARY processed=0" in out

    def test_running_twice_is_noop(self, tmp_path: Path) -> None:
        """Process once (applies), then process again — second run is a no-op."""
        content = _make_queue(
            {
                "install": [(_PENDING, "pkg-once", "desc", "src", "2026-05-01", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "settings.local.json",
            "requirements": tmp_path / "requirements.txt",
            "requirements_dev": tmp_path / "requirements-dev.txt",
        }
        # First run — should apply
        proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=False,
            allow_deny=False,
            target_paths=target_paths,
        )
        after_first = qf.read_text(encoding="utf-8")
        assert "[x]" in after_first  # status was flipped

        # Second run — should be a no-op
        proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=False,
            allow_deny=False,
            target_paths=target_paths,
        )
        after_second = qf.read_text(encoding="utf-8")
        assert after_second == after_first, "second run must not change the file"


# ---------------------------------------------------------------------------
# Tests: deny entries
# ---------------------------------------------------------------------------


class TestDenyEntries:
    def _make_deny_queue(self, tmp_path: Path) -> Path:
        content = _make_queue(
            {
                "deny": [(_PENDING, "Bash(rm -rf *)", "block dangerous", "S-60", "2026-05-29", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")
        return qf

    def test_deny_skipped_without_flag(self, tmp_path: Path, capsys) -> None:
        qf = self._make_deny_queue(tmp_path)
        original = qf.read_text(encoding="utf-8")

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "s.json",
            "requirements": tmp_path / "r.txt",
            "requirements_dev": tmp_path / "rd.txt",
        }
        rc = proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=False,
            allow_deny=False,  # ← no flag
            target_paths=target_paths,
        )
        out = capsys.readouterr().out

        assert rc == 0
        assert "SKIP" in out and "deny" in out
        assert qf.read_text(encoding="utf-8") == original, "deny entry must not be applied without flag"

    def test_deny_processed_with_flag(self, tmp_path: Path, capsys) -> None:
        qf = self._make_deny_queue(tmp_path)

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "s.json",
            "requirements": tmp_path / "r.txt",
            "requirements_dev": tmp_path / "rd.txt",
        }
        rc = proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=False,
            allow_deny=True,  # ← explicit flag
            target_paths=target_paths,
        )
        out = capsys.readouterr().out
        after = qf.read_text(encoding="utf-8")

        assert rc == 0
        # Should have been applied (echo applier)
        assert "APPLIED" in out or "SUMMARY processed=1" in out
        assert "[x]" in after


# ---------------------------------------------------------------------------
# Tests: halt on first failure
# ---------------------------------------------------------------------------


class TestHaltOnFirstFailure:
    def test_halt_on_validation_failure(self, tmp_path: Path, capsys) -> None:
        """An entry missing 'Requested by' should halt before processing later entries."""
        # Build a custom queue: first entry has no source/date, second is valid
        lines = [
            "# Access Requests Queue",
            "",
            "## `[install]` — New packages / tools to install",
            "- `[ ]` **[install] bad-entry** — no source or date here.",
            "- `[ ]` **[install] good-entry** — valid entry.\n  Requested by: S-59 (2026-05-29). Status: pending.",
            "",
        ]
        content = "\n".join(lines)
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "s.json",
            "requirements": tmp_path / "r.txt",
            "requirements_dev": tmp_path / "rd.txt",
        }
        rc = proc.cmd_process(
            queue_file=qf,
            category_filter=None,
            dry_run=False,
            allow_deny=False,
            target_paths=target_paths,
        )
        out = capsys.readouterr().out

        assert rc == 1, "should return non-zero on validation failure"
        assert "HALT" in out
        # Second entry must NOT have been applied
        after = qf.read_text(encoding="utf-8")
        assert "good-entry" in after
        # The good entry's marker should not have been flipped
        good_line = [l for l in after.splitlines() if "good-entry" in l][0]
        assert "[ ]" in good_line, "good-entry must not have been applied after halt"

    def test_halt_on_applier_failure(self, tmp_path: Path, capsys) -> None:
        """When the applier returns ok=False the processor halts."""
        content = _make_queue(
            {
                "install": [
                    (_PENDING, "failing-pkg", "will fail", "S-59", "2026-05-29", "pending"),
                    (_PENDING, "next-pkg",    "should not run", "S-59", "2026-05-29", "pending"),
                ],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        # Patch the applier to return a failure for the first entry
        def _failing_applier(entry, *, dry_run, target_paths):
            if entry["subject"] == "failing-pkg":
                return {"ok": False, "action": "tried to install", "error": "simulated failure"}
            return {"ok": True, "action": "installed", "error": ""}

        original_appliers = proc._get_appliers

        def _patched_appliers():
            result = original_appliers()
            result["install"] = _failing_applier
            return result

        proc._get_appliers = _patched_appliers  # type: ignore[assignment]

        target_paths = {
            "queue_file": qf,
            "settings_local": tmp_path / "s.json",
            "requirements": tmp_path / "r.txt",
            "requirements_dev": tmp_path / "rd.txt",
        }
        try:
            rc = proc.cmd_process(
                queue_file=qf,
                category_filter=None,
                dry_run=False,
                allow_deny=False,
                target_paths=target_paths,
            )
            out = capsys.readouterr().out
            assert rc == 1
            assert "HALT" in out
            # next-pkg must not have been applied
            after = qf.read_text(encoding="utf-8")
            next_line = [l for l in after.splitlines() if "next-pkg" in l][0]
            assert "[ ]" in next_line
        finally:
            proc._get_appliers = original_appliers  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tests: archive command
# ---------------------------------------------------------------------------


class TestArchive:
    def test_archive_removes_old_applied_entries(self, tmp_path: Path, capsys) -> None:
        old_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        new_date = datetime.now().strftime("%Y-%m-%d")
        content = _make_queue(
            {
                "install": [
                    (_APPLIED, "old-pkg", "applied long ago", "src", old_date, "applied"),
                    (_APPLIED, "new-pkg", "applied recently", "src", new_date, "applied"),
                ],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        rc = proc.cmd_archive(qf, older_than_days=60)
        out = capsys.readouterr().out
        after = qf.read_text(encoding="utf-8")

        assert rc == 0
        assert "ARCHIVE_REMOVED=1" in out
        assert "old-pkg" not in after
        assert "new-pkg" in after

    def test_archive_keeps_pending_entries(self, tmp_path: Path, capsys) -> None:
        old_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        content = _make_queue(
            {
                "install": [
                    (_PENDING, "pending-pkg", "still pending", "src", old_date, "pending"),
                ],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        proc.cmd_archive(qf, older_than_days=60)
        after = qf.read_text(encoding="utf-8")

        assert "pending-pkg" in after, "pending entries must not be archived"


# ---------------------------------------------------------------------------
# Tests: entry validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_validates_required_fields(self) -> None:
        entry_ok = {
            "category": "install",
            "status": "pending",
            "subject": "my-package",
            "raw_line": "- `[ ]` **[install] my-package** — desc. Requested by: S-59 (2026-05-29).",
            "date": "2026-05-29",
            "source": "S-59",
            "line_index": 0,
        }
        errors = proc.validate_entry(entry_ok)
        assert errors == []

    def test_missing_source_flagged(self) -> None:
        entry = {
            "category": "install",
            "status": "pending",
            "subject": "pkg",
            "raw_line": "- `[ ]` **[install] pkg** — desc.",
            "date": "2026-05-29",
            "source": None,
            "line_index": 0,
        }
        errors = proc.validate_entry(entry)
        assert any("source" in e for e in errors)

    def test_missing_date_flagged(self) -> None:
        entry = {
            "category": "install",
            "status": "pending",
            "subject": "pkg",
            "raw_line": "- `[ ]` **[install] pkg** — desc. Requested by: S-59.",
            "date": None,
            "source": "S-59",
            "line_index": 0,
        }
        errors = proc.validate_entry(entry)
        assert any("date" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: CLI main() entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_list_via_main(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "allow": [(_PENDING, "WebFetch(domain:example.com)", "test", "S-59", "2026-05-29", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")

        rc = proc.main(["--queue-file", str(qf), "list"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "PENDING_COUNT=1" in out

    def test_process_dry_run_via_main(self, tmp_path: Path, capsys) -> None:
        content = _make_queue(
            {
                "install": [(_PENDING, "pkg-x", "desc", "S-59", "2026-05-29", "pending")],
            }
        )
        qf = tmp_path / "queue.md"
        qf.write_text(content, encoding="utf-8")
        original = qf.read_text(encoding="utf-8")

        rc = proc.main(["--queue-file", str(qf), "process", "--dry-run"])
        after = qf.read_text(encoding="utf-8")
        out = capsys.readouterr().out

        assert rc == 0
        assert after == original
        assert "DRY_RUN" in out

    def test_missing_queue_file_returns_2(self, tmp_path: Path) -> None:
        rc = proc.main(["--queue-file", str(tmp_path / "nonexistent.md"), "list"])
        assert rc == 2
