"""
tests/test_merge_wave_to_main.py — Tests for tools/merge_wave_to_main.py

Uses TEMPORARY git repositories (via tmp_path) and fixture settings files.
Does NOT touch the live SLOP repo, does NOT checkout main in the live repo,
does NOT modify live .claude/settings.local.json.

Test coverage:
- Empty branch merge → abort (non-zero exit).
- Wave status not COMPLETE → abort.
- Conflict during merge → abort cleanly + denies restored + audit entry "ABORTED".
- Happy path → merge commit landed, audit entry written, denies restored.
- Denies restored even when an exception raises mid-merge.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ── import the tool ──────────────────────────────────────────────────────────

_TOOL_PATH = Path(__file__).parent.parent / "tools" / "merge_wave_to_main.py"
_spec = importlib.util.spec_from_file_location("merge_wave_to_main", _TOOL_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["merge_wave_to_main"] = _mod
_spec.loader.exec_module(_mod)

merge_wave_to_main = _mod


# ── git fixture helpers ───────────────────────────────────────────────────────

def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def _make_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Create a minimal git repo with an initial commit on main."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@test.local")
    _git(repo, "config", "user.name", "Test")
    # Initial commit
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init: initial commit")
    return repo


def _make_wave_branch(repo: Path, branch: str, files: dict[str, str] | None = None) -> None:
    """Create a wave branch with optional file additions."""
    _git(repo, "checkout", "-b", branch)
    if files:
        for fname, content in files.items():
            path = repo / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            _git(repo, "add", fname)
        _git(repo, "commit", "-m", f"feat: add files on {branch}")
    _git(repo, "checkout", "main")


def _make_settings(repo: Path, include_denies: bool = True) -> Path:
    """Create a fixture .claude/settings.local.json in the repo."""
    settings_dir = repo / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    path = settings_dir / "settings.local.json"
    data: dict = {
        "permissions": {
            "allow": ["Bash(ls *)"],
            "deny": [],
        }
    }
    if include_denies:
        data["permissions"]["deny"] = list(merge_wave_to_main.DENY_RULES)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _make_status_file(repo: Path, wave_key: str, complete: bool = True, has_blocker: bool = False) -> Path:
    status_dir = repo / ".claude" / "run" / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"{wave_key}.md"
    blockers_line = "- S-99-A: BLOCKED (timeout)" if has_blocker else "- (none)"
    state = "COMPLETE" if complete else "IN PROGRESS"
    path.write_text(
        textwrap.dedent(f"""\
            # {wave_key} status
            **Started:** 2026-05-29T10:00:00Z
            **Wave branch:** wave/S-99-test

            ## Streams
            - A (test) — MERGED abc1234

            ## Blockers
            {blockers_line}

            ## Final state
            {state}. wave/{wave_key}-test ready for merge.
        """),
        encoding="utf-8",
    )
    return path


def _make_merge_log(repo: Path) -> Path:
    """Create a minimal docs/MERGE-LOG.md in the repo."""
    docs = repo / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "MERGE-LOG.md"
    path.write_text(
        textwrap.dedent("""\
            # Wave Merge Log

            Audit trail.

            ---

        """),
        encoding="utf-8",
    )
    return path


def _run_tool(repo: Path, branches: list[str], *, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the tool's main() with cwd patched to repo root."""
    import os
    original_cwd = os.getcwd()

    def fake_repo_root():
        return repo

    monkeypatch.setattr(merge_wave_to_main, "_repo_root", fake_repo_root)
    # Change into the repo so git commands use it
    os.chdir(repo)
    try:
        return merge_wave_to_main.main(branches)
    finally:
        os.chdir(original_cwd)


# ── tests ────────────────────────────────────────────────────────────────────

class TestEmptyBranchMerge:
    """Empty branch (no diff vs main) → abort with non-zero exit."""

    def test_empty_branch_aborts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        # Create branch with NO commits on top of main (no extra files)
        _git(repo, "checkout", "-b", "wave/S-99-empty")
        _git(repo, "checkout", "main")

        with pytest.raises(SystemExit) as exc_info:
            _run_tool(repo, ["wave/S-99-empty"], monkeypatch=monkeypatch)

        assert exc_info.value.code != 0

    def test_empty_branch_denies_still_restored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Denies should still exist after an abort (pre-flight kills before lift)."""
        repo = _make_repo(tmp_path)
        settings = _make_settings(repo)
        _make_merge_log(repo)
        _git(repo, "checkout", "-b", "wave/S-99-empty")
        _git(repo, "checkout", "main")

        with pytest.raises(SystemExit):
            _run_tool(repo, ["wave/S-99-empty"], monkeypatch=monkeypatch)

        # Denies should still be present (pre-flight aborted before lift)
        data = json.loads(settings.read_text())
        deny = data["permissions"]["deny"]
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in deny, f"Deny rule missing after empty-branch abort: {rule}"


class TestWaveStatusNotComplete:
    """Status file present but not COMPLETE → abort."""

    def test_incomplete_status_aborts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-topic", {"feature.txt": "feature content\n"})
        _make_status_file(repo, "S-99", complete=False)

        with pytest.raises(SystemExit) as exc_info:
            _run_tool(repo, ["wave/S-99-topic"], monkeypatch=monkeypatch)

        assert exc_info.value.code != 0

    def test_blocked_status_aborts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-topic", {"feature.txt": "feature content\n"})
        _make_status_file(repo, "S-99", complete=True, has_blocker=True)

        with pytest.raises(SystemExit) as exc_info:
            _run_tool(repo, ["wave/S-99-topic"], monkeypatch=monkeypatch)

        assert exc_info.value.code != 0

    def test_complete_status_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Complete status file should not abort the tool."""
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-topic", {"feature.txt": "feature content\n"})
        _make_status_file(repo, "S-99", complete=True, has_blocker=False)
        # Disable ms-enforce (not present in temp repo)
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        result = _run_tool(repo, ["wave/S-99-topic"], monkeypatch=monkeypatch)
        assert result == 0


class TestConflictHandling:
    """Merge conflict → abort cleanly, denies restored, audit entry says ABORTED."""

    def _make_conflicting_branch(self, repo: Path, branch: str) -> None:
        """Create a branch that will conflict with a later main commit."""
        # Add a conflicting change on main first
        (repo / "conflict.txt").write_text("main version\n")
        _git(repo, "add", "conflict.txt")
        _git(repo, "commit", "-m", "main: add conflict.txt")

        # Create branch from the commit BEFORE conflict.txt was added
        parent_sha = _git(repo, "rev-parse", "HEAD~1").stdout.strip()
        _git(repo, "checkout", "-b", branch, parent_sha)
        (repo / "conflict.txt").write_text("branch version\n")
        _git(repo, "add", "conflict.txt")
        _git(repo, "commit", "-m", f"branch: add conflicting conflict.txt on {branch}")
        _git(repo, "checkout", "main")

    def test_conflict_aborts_non_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        settings = _make_settings(repo)
        merge_log = _make_merge_log(repo)
        self._make_conflicting_branch(repo, "wave/S-99-conflict")
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        result = _run_tool(repo, ["wave/S-99-conflict"], monkeypatch=monkeypatch)
        assert result != 0

    def test_conflict_restores_denies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        settings = _make_settings(repo)
        merge_log = _make_merge_log(repo)
        self._make_conflicting_branch(repo, "wave/S-99-conflict")
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        _run_tool(repo, ["wave/S-99-conflict"], monkeypatch=monkeypatch)

        data = json.loads(settings.read_text())
        deny = data["permissions"]["deny"]
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in deny, f"Deny rule not restored after conflict: {rule}"
        allow = data["permissions"].get("allow", [])
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule not in allow, f"Deny rule still in allow after conflict: {rule}"

    def test_conflict_writes_aborted_audit_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        merge_log = _make_merge_log(repo)
        self._make_conflicting_branch(repo, "wave/S-99-conflict")
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        _run_tool(repo, ["wave/S-99-conflict"], monkeypatch=monkeypatch)

        log_text = merge_log.read_text()
        assert "ABORTED" in log_text.upper() or "aborted" in log_text.lower(), (
            "Expected ABORTED marker in audit log after conflict"
        )

    def test_conflict_repo_still_on_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After conflict abort, repo should be back on main (merge aborted)."""
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        self._make_conflicting_branch(repo, "wave/S-99-conflict")
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        import os
        os.chdir(repo)
        _run_tool(repo, ["wave/S-99-conflict"], monkeypatch=monkeypatch)

        current = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        assert current == "main", f"Expected main after conflict abort, got {current}"


class TestHappyPath:
    """Successful merge → merge commit landed, audit entry written, denies restored."""

    def test_happy_path_returns_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-happy", {"new_feature.py": "# new\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        result = _run_tool(repo, ["wave/S-99-happy"], monkeypatch=monkeypatch)
        assert result == 0

    def test_happy_path_merge_commit_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-happy", {"new_feature.py": "# new\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        import os
        os.chdir(repo)
        _run_tool(repo, ["wave/S-99-happy"], monkeypatch=monkeypatch)

        # main should now contain new_feature.py
        assert (repo / "new_feature.py").exists(), "Merged file not found on main"

    def test_happy_path_audit_entry_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        merge_log = _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-happy", {"new_feature.py": "# new\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        _run_tool(repo, ["wave/S-99-happy"], monkeypatch=monkeypatch)

        log_text = merge_log.read_text()
        assert "wave/S-99-happy" in log_text
        assert "tools/merge_wave_to_main.py" in log_text

    def test_happy_path_denies_restored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        settings = _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-happy", {"new_feature.py": "# new\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        _run_tool(repo, ["wave/S-99-happy"], monkeypatch=monkeypatch)

        data = json.loads(settings.read_text())
        deny = data["permissions"]["deny"]
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in deny, f"Deny rule not restored after success: {rule}"
        allow = data["permissions"].get("allow", [])
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule not in allow, f"Deny rule still in allow after success: {rule}"

    def test_happy_path_no_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Audit entry must record 'no' for pushed-to-origin."""
        repo = _make_repo(tmp_path)
        _make_settings(repo)
        merge_log = _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-happy", {"new_feature.py": "# new\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        _run_tool(repo, ["wave/S-99-happy"], monkeypatch=monkeypatch)

        log_text = merge_log.read_text()
        assert "push" in log_text.lower() and "no" in log_text.lower()


class TestDeniesRestoredOnException:
    """Denies must be restored even when an unexpected exception is raised mid-merge."""

    def test_exception_mid_merge_restores_denies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_repo(tmp_path)
        settings = _make_settings(repo)
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-exc", {"exc_feature.py": "# exc\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        # Patch _do_merge to raise an unexpected exception AFTER denies have been lifted
        call_count = [0]

        original_lift = merge_wave_to_main.lift_denies
        lifted = [False]

        def patched_lift(path: Path) -> None:
            original_lift(path)
            lifted[0] = True

        def patched_do_merge(branch: str):
            raise RuntimeError("Simulated mid-merge failure")

        monkeypatch.setattr(merge_wave_to_main, "lift_denies", patched_lift)
        monkeypatch.setattr(merge_wave_to_main, "_do_merge", patched_do_merge)

        import os
        os.chdir(repo)

        with pytest.raises((RuntimeError, SystemExit)):
            _run_tool(repo, ["wave/S-99-exc"], monkeypatch=monkeypatch)

        # Regardless of whether lift happened, denies must be back
        data = json.loads(settings.read_text())
        deny = data["permissions"]["deny"]
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in deny, (
                f"Deny rule NOT restored after mid-merge exception: {rule}\n"
                f"Current deny list: {deny}"
            )

    def test_exception_no_settings_file_does_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If settings file doesn't exist, the tool should not crash on restore."""
        repo = _make_repo(tmp_path)
        # No settings file created
        _make_merge_log(repo)
        _make_wave_branch(repo, "wave/S-99-exc", {"exc_feature.py": "# exc\n"})
        monkeypatch.setattr(merge_wave_to_main, "_find_ms_enforce", lambda _: None)

        def patched_do_merge(branch: str):
            raise RuntimeError("Simulated mid-merge failure")

        monkeypatch.setattr(merge_wave_to_main, "_do_merge", patched_do_merge)

        import os
        os.chdir(repo)

        # Should raise but not crash with FileNotFoundError from restore_denies
        with pytest.raises((RuntimeError, SystemExit)):
            _run_tool(repo, ["wave/S-99-exc"], monkeypatch=monkeypatch)
        # If we get here without an unexpected error, the test passes


class TestLiftRestoreSymmetry:
    """Unit tests for lift_denies / restore_denies symmetry."""

    def test_lift_removes_deny_rules(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        data = {
            "permissions": {
                "allow": ["Bash(ls *)"],
                "deny": list(merge_wave_to_main.DENY_RULES) + ["Bash(sudo *)"],
            }
        }
        settings.write_text(json.dumps(data, indent=2))
        merge_wave_to_main.lift_denies(settings)
        result = json.loads(settings.read_text())
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule not in result["permissions"]["deny"]
        assert "Bash(sudo *)" in result["permissions"]["deny"]

    def test_lift_adds_to_allow(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        data = {
            "permissions": {
                "allow": [],
                "deny": list(merge_wave_to_main.DENY_RULES),
            }
        }
        settings.write_text(json.dumps(data, indent=2))
        merge_wave_to_main.lift_denies(settings)
        result = json.loads(settings.read_text())
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in result["permissions"]["allow"]

    def test_restore_puts_rules_back_in_deny(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        data = {
            "permissions": {
                "allow": list(merge_wave_to_main.DENY_RULES),
                "deny": ["Bash(sudo *)"],
            }
        }
        settings.write_text(json.dumps(data, indent=2))
        merge_wave_to_main.restore_denies(settings)
        result = json.loads(settings.read_text())
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in result["permissions"]["deny"]

    def test_restore_removes_from_allow(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.local.json"
        data = {
            "permissions": {
                "allow": list(merge_wave_to_main.DENY_RULES) + ["Bash(ls *)"],
                "deny": ["Bash(sudo *)"],
            }
        }
        settings.write_text(json.dumps(data, indent=2))
        merge_wave_to_main.restore_denies(settings)
        result = json.loads(settings.read_text())
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule not in result["permissions"]["allow"]
        assert "Bash(ls *)" in result["permissions"]["allow"]

    def test_lift_restore_is_idempotent(self, tmp_path: Path) -> None:
        """lift_denies followed by restore_denies returns settings to original state."""
        settings = tmp_path / "settings.local.json"
        original_deny = list(merge_wave_to_main.DENY_RULES) + ["Bash(sudo *)"]
        data = {
            "permissions": {
                "allow": ["Bash(ls *)"],
                "deny": original_deny,
            }
        }
        settings.write_text(json.dumps(data, indent=2))
        original_text = settings.read_text()

        merge_wave_to_main.lift_denies(settings)
        merge_wave_to_main.restore_denies(settings)

        result = json.loads(settings.read_text())
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule in result["permissions"]["deny"]
        for rule in merge_wave_to_main.DENY_RULES:
            assert rule not in result["permissions"].get("allow", [])
        assert "Bash(sudo *)" in result["permissions"]["deny"]
        assert "Bash(ls *)" in result["permissions"]["allow"]


class TestAuditLogAppend:
    """Unit tests for the audit log append function."""

    def test_appends_new_entry_at_top(self, tmp_path: Path) -> None:
        merge_log = tmp_path / "MERGE-LOG.md"
        merge_log.write_text(
            "# Wave Merge Log\n\n---\n\n## 2026-01-01 — old entry\n\nold content\n",
            encoding="utf-8",
        )
        merge_wave_to_main._append_audit_entry(
            merge_log,
            branches=["wave/S-99-test"],
            pre_sha="abc1234",
            post_sha="def5678",
            preflight_results={"working-tree": "CLEAN"},
            notes="test merge",
            caller="tester",
            timestamp="2026-05-29T12:00:00Z",
        )
        text = merge_log.read_text()
        new_pos = text.find("2026-05-29")
        old_pos = text.find("2026-01-01")
        assert new_pos < old_pos, "New entry should appear before old entry"

    def test_creates_file_if_not_exists(self, tmp_path: Path) -> None:
        merge_log = tmp_path / "MERGE-LOG.md"
        assert not merge_log.exists()
        merge_wave_to_main._append_audit_entry(
            merge_log,
            branches=["wave/S-99-test"],
            pre_sha="abc1234",
            post_sha="def5678",
            preflight_results={"working-tree": "CLEAN"},
            notes="test",
            caller="tester",
            timestamp="2026-05-29T12:00:00Z",
        )
        assert merge_log.exists()
        assert "wave/S-99-test" in merge_log.read_text()

    def test_includes_method_field(self, tmp_path: Path) -> None:
        merge_log = tmp_path / "MERGE-LOG.md"
        merge_log.write_text("# Log\n\n---\n\n")
        merge_wave_to_main._append_audit_entry(
            merge_log,
            branches=["wave/S-99-test"],
            pre_sha="abc1234",
            post_sha="def5678",
            preflight_results={},
            notes="test",
            caller="tester",
            timestamp="2026-05-29T12:00:00Z",
        )
        assert "tools/merge_wave_to_main.py" in merge_log.read_text()


class TestWaveKeyExtraction:
    """Unit tests for _extract_wave_key."""

    def test_standard_wave_branch(self) -> None:
        assert merge_wave_to_main._extract_wave_key("wave/S-59-access-requests") == "S-59"

    def test_multi_digit_wave(self) -> None:
        assert merge_wave_to_main._extract_wave_key("wave/S-123-long-topic") == "S-123"

    def test_no_wave_prefix(self) -> None:
        result = merge_wave_to_main._extract_wave_key("S-59-topic")
        assert result == "S-59"
