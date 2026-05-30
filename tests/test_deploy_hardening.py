"""tests/test_deploy_hardening.py

S-74 Stream B — static assertions over deploy.sh and ms-update shell scripts.
No live server required. All checks are grep/text-analysis over the script files.

Assertions:
  1. Both scripts reference the canonical port var MS_PORT (not only MEDIASTACK_PORT).
  2. Neither script has a bare `git pull origin main` on its update path.
  3. Neither script has `git fetch` with 2>/dev/null on its update path (fetch errors must surface).
  4. Both scripts source tools/deploy_lib.sh rather than containing inline copies of the
     detect_service_user / build_home / normalize_ownership functions.
  5. MEDIASTACK_PORT appears ONLY as a deprecated read fallback (never written).
  6. deploy.sh --help exits 0 (guarded dry-run gate).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DEPLOY_SH = REPO_ROOT / "deploy.sh"
MS_UPDATE = REPO_ROOT / "ms-update"
DEPLOY_LIB = REPO_ROOT / "tools" / "deploy_lib.sh"

SHARED_FUNCTIONS = ("detect_service_user", "build_home", "normalize_ownership")

# Stream A (ms-update rewrite) produces the ms-update changes. In Stream B's
# standalone worktree ms-update has NOT yet been updated. These assertions are
# correct and will pass post-merge; pre-merge they are xfail.
def _ms_update_updated() -> bool:
    """Return True if ms-update has already been updated by Stream A."""
    if not MS_UPDATE.exists():
        return False
    content = MS_UPDATE.read_text(encoding="utf-8")
    return "tools/deploy_lib.sh" in content


_MS_UPDATE_PENDING = pytest.mark.xfail(
    not _ms_update_updated(),
    reason="ms-update not yet updated by Stream A — expected xfail pre-merge",
    strict=False,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _update_block(text: str) -> str:
    """Extract lines in or near the update path (best-effort for grep assertions)."""
    return text


# ── 1. Canonical port var ──────────────────────────────────────────────────

class TestCanonicalPortVar:
    def test_deploy_sh_reads_ms_port(self):
        content = _read(DEPLOY_SH)
        assert "MS_PORT" in content, "deploy.sh must reference MS_PORT"

    @_MS_UPDATE_PENDING
    def test_ms_update_reads_ms_port(self):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        assert "MS_PORT" in content, "ms-update must reference canonical MS_PORT"

    def test_deploy_sh_no_mediastack_port_write(self):
        """MEDIASTACK_PORT must NOT be written anywhere — only read as deprecated fallback."""
        content = _read(DEPLOY_SH)
        # Allowed: read as fallback (assignment from it, e.g. MS_PORT="$MEDIASTACK_PORT").
        # Not allowed: writing MEDIASTACK_PORT= (assigning into it).
        write_pattern = re.compile(r'^\s*MEDIASTACK_PORT\s*=(?!=)', re.MULTILINE)
        bad_lines = write_pattern.findall(content)
        assert not bad_lines, (
            f"deploy.sh must not write MEDIASTACK_PORT — found: {bad_lines}"
        )

    @_MS_UPDATE_PENDING
    def test_ms_update_no_mediastack_port_write(self):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        write_pattern = re.compile(r'^\s*MEDIASTACK_PORT\s*=(?!=)', re.MULTILINE)
        bad_lines = write_pattern.findall(content)
        assert not bad_lines, (
            f"ms-update must not write MEDIASTACK_PORT — found: {bad_lines}"
        )


# ── 2. No bare `git pull origin main` on the update path ──────────────────

class TestNoBareGitPull:
    def test_deploy_sh_no_bare_git_pull(self):
        content = _read(DEPLOY_SH)
        # Bare git pull: "git pull origin main" not preceded by "sudo -u ..." on same line
        # Simple check: no `git pull origin main` at all (fetch+reset is the replacement)
        assert "git pull origin main" not in content, (
            "deploy.sh must not use bare 'git pull origin main' — "
            "use fetch + fast-forward + reset --hard fallback instead"
        )

    @_MS_UPDATE_PENDING
    def test_ms_update_no_bare_git_pull(self):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        assert "git pull origin main" not in content, (
            "ms-update must not use bare 'git pull origin main'"
        )

    def test_deploy_sh_has_reset_hard_fallback(self):
        content = _read(DEPLOY_SH)
        assert "reset --hard origin/main" in content, (
            "deploy.sh must have a 'reset --hard origin/main' fallback for diverged clones"
        )

    @_MS_UPDATE_PENDING
    def test_ms_update_has_reset_hard_fallback(self):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        assert "reset --hard origin/main" in content, (
            "ms-update must have a 'reset --hard origin/main' fallback for diverged clones"
        )


# ── 3. No git fetch with 2>/dev/null on the update path ───────────────────

class TestFetchErrorsNotSuppressed:
    def test_deploy_sh_fetch_not_silenced(self):
        content = _read(DEPLOY_SH)
        # Pattern: git fetch ... 2>/dev/null on the same logical line
        silenced = re.search(r'git\b.*fetch\b.*2>/dev/null', content)
        assert not silenced, (
            "deploy.sh must not suppress git fetch stderr — fetch errors must surface"
        )

    @_MS_UPDATE_PENDING
    def test_ms_update_fetch_not_silenced(self):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        silenced = re.search(r'git\b.*fetch\b.*2>/dev/null', content)
        assert not silenced, (
            "ms-update must not suppress git fetch stderr — fetch errors must surface"
        )


# ── 4. Both scripts source deploy_lib.sh; no inline reimplementation ───────

class TestDeployLibSourced:
    def test_deploy_sh_sources_deploy_lib(self):
        content = _read(DEPLOY_SH)
        assert "tools/deploy_lib.sh" in content, (
            "deploy.sh must source tools/deploy_lib.sh"
        )

    @_MS_UPDATE_PENDING
    def test_ms_update_sources_deploy_lib(self):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        assert "tools/deploy_lib.sh" in content, (
            "ms-update must source tools/deploy_lib.sh"
        )

    @pytest.mark.parametrize("fn", SHARED_FUNCTIONS)
    def test_deploy_sh_no_inline_function(self, fn: str):
        content = _read(DEPLOY_SH)
        # Inline definition looks like: `detect_service_user() {` or `function detect_service_user`
        inline_def = re.search(
            r'\b' + re.escape(fn) + r'\s*\(\s*\)\s*\{|function\s+' + re.escape(fn) + r'\b',
            content,
        )
        assert not inline_def, (
            f"deploy.sh must not define {fn} inline — source it from tools/deploy_lib.sh"
        )

    @_MS_UPDATE_PENDING
    @pytest.mark.parametrize("fn", SHARED_FUNCTIONS)
    def test_ms_update_no_inline_function(self, fn: str):
        if not MS_UPDATE.exists():
            pytest.skip("ms-update not present in this worktree")
        content = _read(MS_UPDATE)
        inline_def = re.search(
            r'\b' + re.escape(fn) + r'\s*\(\s*\)\s*\{|function\s+' + re.escape(fn) + r'\b',
            content,
        )
        assert not inline_def, (
            f"ms-update must not define {fn} inline — source it from tools/deploy_lib.sh"
        )


# ── 5. deploy_lib.sh (when present) defines exactly the three contracts ────

class TestDeployLibContracts:
    def test_deploy_lib_defines_all_three_functions(self):
        if not DEPLOY_LIB.exists():
            pytest.skip("tools/deploy_lib.sh not yet present (Stream A produces it)")
        content = _read(DEPLOY_LIB)
        for fn in SHARED_FUNCTIONS:
            assert re.search(
                r'\b' + re.escape(fn) + r'\s*\(\s*\)\s*\{|function\s+' + re.escape(fn) + r'\b',
                content,
            ), f"tools/deploy_lib.sh must define {fn}"


# ── 6. deploy.sh --help exits 0 ───────────────────────────────────────────

class TestHelpFlag:
    def test_deploy_sh_help_exits_zero(self):
        """--help must exit 0 and touch nothing (guarded dry-run gate)."""
        result = subprocess.run(
            ["bash", str(DEPLOY_SH), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"deploy.sh --help exited {result.returncode}; stderr: {result.stderr}"
        )
        assert result.stdout.strip(), "deploy.sh --help must print usage text"
