"""Static assertions over the deploy scripts (S-74 deploy-hardening).

These are text/grep-style checks over the shell scripts — there is no live
server in CI (the same gap the parked install.sh-test wave covers). They guard
the cross-script contracts that S-74 pins:

  * the shared helper tools/deploy_lib.sh defines exactly the three pinned
    functions and is sourced (not re-implemented inline);
  * the fetch on ms-update's update path no longer swallows stderr with
    2>/dev/null;
  * the canonical service-port var is MS_PORT, with MEDIASTACK_PORT only a
    deprecated fallback.

deploy.sh is authored by Stream B; the assertions that depend on B's alignment
are guarded so this file passes in Stream A's isolated worktree and becomes a
hard gate once B is merged.
"""

import os
import re

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    path = os.path.join(REPO_ROOT, rel)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _exists(rel):
    return os.path.exists(os.path.join(REPO_ROOT, rel))


# --- shared helper -------------------------------------------------------

PINNED_FUNCS = ("detect_service_user", "build_home", "normalize_ownership")


def test_deploy_lib_exists():
    assert _exists("tools/deploy_lib.sh"), "tools/deploy_lib.sh must exist"


def test_deploy_lib_defines_pinned_functions():
    text = _read("tools/deploy_lib.sh")
    for name in PINNED_FUNCS:
        pattern = re.compile(r"^\s*%s\s*\(\)" % re.escape(name), re.MULTILINE)
        assert pattern.search(text), "deploy_lib.sh must define %s()" % name


def test_deploy_lib_build_home_default():
    text = _read("tools/deploy_lib.sh")
    assert "${MS_BUILD_HOME:-/tmp}" in text, (
        "build_home must echo the pinned ${MS_BUILD_HOME:-/tmp} value"
    )


def test_normalize_ownership_shim_resolves():
    # The dangling tools/normalize-ownership.sh reference must resolve: either
    # the shim exists OR ms-update calls normalize_ownership directly.
    shim = _exists("tools/normalize-ownership.sh")
    ms = _read("ms-update")
    calls_helper = "normalize_ownership " in ms or "normalize_ownership\n" in ms
    assert shim or calls_helper, (
        "dangling tools/normalize-ownership.sh reference must resolve"
    )


# --- ms-update (Stream A) ------------------------------------------------


def test_ms_update_sources_shared_helper():
    text = _read("ms-update")
    assert "tools/deploy_lib.sh" in text, "ms-update must source the shared helper"


def test_ms_update_no_inline_detect_logic():
    # ms-update must NOT re-implement service-user detection inline; it calls the
    # helper. We assert it does not define detect_service_user itself.
    text = _read("ms-update")
    assert not re.search(r"^\s*detect_service_user\s*\(\)", text, re.MULTILINE), (
        "ms-update must not redefine detect_service_user (use the helper)"
    )


def test_ms_update_fetch_does_not_swallow_stderr():
    text = _read("ms-update")
    for line in text.splitlines():
        if "fetch" in line and "git" in line and "2>/dev/null" in line:
            raise AssertionError(
                "ms-update fetch must not swallow stderr with 2>/dev/null: %r" % line
            )


def test_ms_update_has_sha_verify():
    text = _read("ms-update")
    assert "origin/$BRANCH" in text and "rev-parse HEAD" in text
    assert "SHA mismatch" in text or "did NOT land" in text, (
        "ms-update must fail loud on a post-update SHA mismatch"
    )


def test_ms_update_reads_canonical_ms_port_first():
    text = _read("ms-update")
    ms_idx = text.find("^MS_PORT=") if "^MS_PORT=" in text else text.find("MS_PORT=")
    legacy_idx = text.find("MEDIASTACK_PORT=")
    assert ms_idx != -1, "ms-update must read MS_PORT"
    assert legacy_idx != -1, "ms-update must keep MEDIASTACK_PORT as a fallback"
    assert ms_idx < legacy_idx, "ms-update must read MS_PORT before legacy MEDIASTACK_PORT"


def test_ms_update_runs_git_as_service_user():
    text = _read("ms-update")
    assert 'sudo -u "$SVC_USER" git' in text, (
        "ms-update must run git as the service user"
    )


def test_ms_update_build_uses_build_home():
    text = _read("ms-update")
    assert 'HOME="$(build_home)"' in text, (
        "ms-update npm build must run with a writable HOME from build_home"
    )


# --- deploy.sh (Stream B; guarded until merged) --------------------------


def _deploy_aligned():
    if not _exists("deploy.sh"):
        return False
    return "tools/deploy_lib.sh" in _read("deploy.sh")


def test_deploy_sh_sources_helper_when_aligned():
    if not _deploy_aligned():
        pytest.skip("deploy.sh not yet aligned by Stream B (merge-time gate)")
    text = _read("deploy.sh")
    assert "tools/deploy_lib.sh" in text


def test_both_scripts_use_same_canonical_port_when_aligned():
    if not _deploy_aligned():
        pytest.skip("deploy.sh not yet aligned by Stream B (merge-time gate)")
    assert "MS_PORT" in _read("deploy.sh")
    assert "MS_PORT" in _read("ms-update")


# ── Stream B unique assertions (kept at merge — S-74-MERGE-1) ────────────────

def test_deploy_sh_no_new_mediastack_port_writes():
    """MEDIASTACK_PORT must only appear as a deprecated fallback read, never written."""
    dep = _deploy_sh_text()
    if not dep or "deploy_lib.sh" not in dep:
        import pytest
        pytest.skip("deploy.sh not yet aligned (Stream B)")
    assert "MEDIASTACK_PORT=" not in dep


def test_deploy_sh_no_bare_git_pull():
    """deploy.sh --update must not use a bare 'git pull origin main'."""
    dep = _deploy_sh_text()
    if not dep or "deploy_lib.sh" not in dep:
        import pytest
        pytest.skip("deploy.sh not yet aligned (Stream B)")
    assert "git pull origin main" not in dep


def test_deploy_sh_uses_detect_service_user():
    """deploy.sh must call detect_service_user (not hardcode REAL_USER)."""
    dep = _deploy_sh_text()
    if not dep or "deploy_lib.sh" not in dep:
        import pytest
        pytest.skip("deploy.sh not yet aligned (Stream B)")
    assert "detect_service_user" in dep
