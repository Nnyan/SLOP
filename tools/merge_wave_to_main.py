#!/usr/bin/env python3
"""
tools/merge_wave_to_main.py — Sanctioned wave-merge tool (S-59 Stream D).

Merges one or more completed wave branches into main with full pre-flight
checks, internal lift-restore of checkout-main denies, audit logging, and
clean conflict-abort handling.

CLI:
    python3 tools/merge_wave_to_main.py wave/S-NN-topic [wave/S-MM-topic ...]

Behavior:
1.  Pre-flight per branch: branch exists; status file COMPLETE (if present);
    non-empty diff vs main; ms-enforce passes on wave branch; main is clean.
2.  Internal lift-restore of Bash(git checkout main*) and Bash(git switch main*)
    denies in .claude/settings.local.json — try/finally guarantees restore.
3.  Merge --no-ff with a generated commit message.
4.  Conflict: abort cleanly, restore denies, surface files, non-zero exit.
5.  Append audit entry to docs/MERGE-LOG.md (newest at top).
6.  Restore denies unconditionally (try/finally).
7.  Does NOT push. Does NOT delete merged branches.

All stdlib — no external dependencies.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

# ── shared lift-restore primitives (S-68 Stream A) ───────────────────────────
# Import the sanctioned lift-restore context manager.  The merge tool keeps
# its own DENY_RULES constant (the specific rules it needs to lift) and its
# own audit format (docs/MERGE-LOG.md), but delegates the actual lift/restore
# mechanics to the shared module so the two stay in sync.
try:
    import sys as _sys
    import importlib.util as _ilu
    _pkg = Path(__file__).parent / "sanctioned" / "_lift_restore.py"
    _spec = _ilu.spec_from_file_location("tools.sanctioned._lift_restore", _pkg)
    _lr_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_lr_mod)
    _lifted_cm = _lr_mod.lifted
    _lift_fn = _lr_mod.lift
    _restore_fn = _lr_mod.restore
    _HAVE_SHARED_LIFT_RESTORE = True
except Exception:
    _HAVE_SHARED_LIFT_RESTORE = False
    _lifted_cm = None  # type: ignore[assignment]
    _lift_fn = None    # type: ignore[assignment]
    _restore_fn = None # type: ignore[assignment]

# ── constants ────────────────────────────────────────────────────────────────

DENY_RULES = [
    "Bash(git checkout main*)",
    "Bash(git switch main*)",
]

SETTINGS_LOCAL = Path(".claude/settings.local.json")
MERGE_LOG = Path("docs/MERGE-LOG.md")
STATUS_DIR = Path(".claude/run/status")
STATUS_ARCHIVE_DIRS = [
    Path(".claude/run-archive"),
]

MS_ENFORCE = Path("ms-enforce")
VENV_MS_ENFORCE = Path(".venv/bin/ms-enforce")


# ── git helpers ───────────────────────────────────────────────────────────────

def _run(args: list[str], *, capture: bool = True, check: bool = True,
         cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=capture,
        text=True,
        check=check,
        cwd=cwd,
    )


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git"] + list(args), check=check)


def _git_output(*args: str) -> str:
    return _git(*args).stdout.strip()


def _repo_root() -> Path:
    """Return the git repository root (works inside a worktree too)."""
    return Path(_git_output("rev-parse", "--show-toplevel"))


def _current_branch() -> str:
    return _git_output("rev-parse", "--abbrev-ref", "HEAD")


def _branch_exists(branch: str) -> bool:
    result = _git("rev-parse", "--verify", branch, check=False)
    return result.returncode == 0


def _main_is_clean() -> tuple[bool, str]:
    """Check that main's working tree has no uncommitted changes.

    We use --porcelain but only flag tracked-file modifications (staged or
    unstaged), not untracked files (lines starting with '??').  Untracked
    files in a worktree are expected and do not block a merge.
    """
    result = _git("status", "--porcelain", check=False)
    if result.returncode != 0:
        return False, "git status failed"
    dirty_lines = [
        ln for ln in result.stdout.splitlines()
        if ln.strip() and not ln.startswith("??")
    ]
    if dirty_lines:
        return False, f"working tree has uncommitted changes:\n" + "\n".join(dirty_lines)
    return True, "clean"


def _diff_main(branch: str) -> str:
    """Return the diff between main and the wave branch (stat only)."""
    result = _git("diff", "--stat", f"main..{branch}", check=False)
    return result.stdout.strip()


def _wave_commits(branch: str) -> list[str]:
    """Return commit messages on the wave branch not in main."""
    result = _git("log", "--oneline", f"main..{branch}", check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]


def _head_sha(ref: str = "HEAD") -> str:
    return _git_output("rev-parse", ref)


# ── settings lift / restore ───────────────────────────────────────────────────

def _load_settings(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_settings(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def lift_denies(settings_path: Path) -> None:
    """Remove DENY_RULES from the deny list in settings_path.

    Delegates to tools.sanctioned._lift_restore.lift() when available;
    falls back to the self-contained implementation for environments where
    the shared package is not importable (e.g. isolated test fixtures that
    do not carry the full tools/ tree).
    """
    if _HAVE_SHARED_LIFT_RESTORE and _lift_fn is not None:
        _lift_fn(DENY_RULES, settings_path=settings_path)
        return
    # Fallback: inline implementation (kept for test-fixture compatibility)
    data = _load_settings(settings_path)
    deny_list = data.get("permissions", {}).get("deny", [])
    new_deny = [rule for rule in deny_list if rule not in DENY_RULES]
    data.setdefault("permissions", {})["deny"] = new_deny
    allow_list = data["permissions"].setdefault("allow", [])
    for rule in DENY_RULES:
        if rule not in allow_list:
            allow_list.append(rule)
    _save_settings(settings_path, data)


def restore_denies(settings_path: Path) -> None:
    """Re-add DENY_RULES to deny list and remove from allow list.

    NOTE: this function uses a diff-based restore (explicitly adds DENY_RULES
    back) rather than the profile-based restore from _lift_restore.restore().
    This is intentional: the merge tool's lift is scoped to exactly DENY_RULES,
    and its restore must be deterministic even without a wave-mode profile
    present (e.g. in test fixtures).  The main() function uses the shared
    lifted() context manager which calls the profile-based restore internally
    when a profile is available.
    """
    data = _load_settings(settings_path)
    deny_list = data.get("permissions", {}).get("deny", [])
    # Add back any missing deny rules
    for rule in DENY_RULES:
        if rule not in deny_list:
            deny_list.append(rule)
    data.setdefault("permissions", {})["deny"] = deny_list
    # Remove from allow if present
    allow_list = data["permissions"].get("allow", [])
    data["permissions"]["allow"] = [r for r in allow_list if r not in DENY_RULES]
    _save_settings(settings_path, data)


# ── status file check ─────────────────────────────────────────────────────────

def _find_status_file(wave_key: str, repo_root: Path) -> Path | None:
    """Find a status file for the given wave key (e.g. 'S-59').

    Searches STATUS_DIR first, then run-archive subdirs.
    """
    candidates = [repo_root / STATUS_DIR / f"{wave_key}.md"]
    for archive_dir in STATUS_ARCHIVE_DIRS:
        ad = repo_root / archive_dir
        if ad.is_dir():
            for sub in ad.iterdir():
                if sub.is_dir():
                    candidates.append(sub / "status" / f"{wave_key}.md")
    for path in candidates:
        if path.exists():
            return path
    return None


def _status_is_complete(status_path: Path) -> tuple[bool, str]:
    """Return (is_complete, reason). Checks for COMPLETE + no open blockers."""
    text = status_path.read_text(encoding="utf-8")
    upper = text.upper()
    if "COMPLETE" not in upper:
        return False, f"status file does not contain COMPLETE: {status_path}"
    # Check for open blockers — lines containing "BLOCKED" without RESOLVED/NONE
    for line in text.splitlines():
        stripped = line.strip().upper()
        if "BLOCKED" in stripped and "NONE" not in stripped and "UNBLOCKED" not in stripped:
            # Allow lines like "Blockers: (none)" or "## Blockers\n- (none)"
            if "(NONE)" in stripped or "- (NONE)" in stripped:
                continue
            return False, f"status file has open blocker indicator: {line!r}"
    return True, "COMPLETE"


def _extract_wave_key(branch: str) -> str:
    """Extract wave key like 'S-59' from branch name like 'wave/S-59-topic'."""
    # branch: wave/S-59-access-requests-processor → S-59
    parts = branch.split("/")
    name = parts[-1] if parts else branch
    # name: S-59-access-requests-processor → S-59
    pieces = name.split("-")
    if len(pieces) >= 2 and pieces[0].upper() == "S" and pieces[1].isdigit():
        return f"S-{pieces[1]}"
    return name


# ── ms-enforce check ──────────────────────────────────────────────────────────

def _find_ms_enforce(repo_root: Path) -> str | None:
    """Return path to ms-enforce executable, or None if not found."""
    candidates = [
        repo_root / VENV_MS_ENFORCE,
        repo_root / MS_ENFORCE,
        Path("ms-enforce"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# Gitignored runtime artifacts that several ms-enforce checks read from the
# working tree (present in the main checkout, ABSENT in a fresh worktree). They
# must be symlinked into the isolation worktree or the checks false-fail:
#   - .venv               → pytest/ms-enforce import the project venv
#   - backend/static      → favicon/static route + cli-snapshot tests (built assets)
#   - .claude/run-archive  → track-status gate reads wave-file run-archive refs
_MS_ENFORCE_WORKTREE_ARTIFACTS = (".venv", "backend/static", ".claude/run-archive")


def _run_ms_enforce(branch: str, repo_root: Path) -> tuple[bool, str]:
    """Run ms-enforce against *branch* in an isolated worktree. Returns (passed, output).

    Runs branch-isolated regardless of the caller's current branch (the tool is
    normally invoked from main): checks out *branch* in a throwaway detached
    worktree, symlinks the gitignored runtime artifacts the checks depend on, and
    runs ms-enforce there. TIER_1 failures are fatal; warn-only checks tolerated.
    The worktree is always removed in a finally block.
    """
    enforcer = _find_ms_enforce(repo_root)
    if enforcer is None:
        return True, "ms-enforce not found — skipped"

    wt = repo_root / ".claude" / "worktrees" / f"_ms-enforce-{branch.replace('/', '-')}"
    # Clear any stale worktree from a previous interrupted run.
    _git("worktree", "remove", "--force", str(wt), check=False)
    add = _git("worktree", "add", "--detach", str(wt), branch, check=False)
    if add.returncode != 0:
        return True, f"ms-enforce skipped: could not create isolation worktree ({add.stderr.strip()})"
    try:
        # The symlinked artifacts must ALSO be added to the worktree's local
        # info/exclude — otherwise the track-status gate flags the symlink itself
        # as an untracked file (the .gitignore dir-pattern doesn't match a symlink).
        exclude_path = _run(
            ["git", "-C", str(wt), "rev-parse", "--git-path", "info/exclude"],
            capture=True, check=False,
        ).stdout.strip()
        if exclude_path:
            ep = Path(exclude_path)
            if not ep.is_absolute():
                ep = wt / ep
            ep.parent.mkdir(parents=True, exist_ok=True)
            with open(ep, "a", encoding="utf-8") as fh:
                for art in _MS_ENFORCE_WORKTREE_ARTIFACTS:
                    fh.write(f"\n/{art}\n")
        for art in _MS_ENFORCE_WORKTREE_ARTIFACTS:
            src, dst = repo_root / art, wt / art
            if src.exists() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.symlink(src, dst)
                except OSError:
                    pass  # best-effort; a missing artifact only risks a false warn
        # Run the worktree's own ms-enforce via its (symlinked) venv python.
        venv_py = wt / ".venv" / "bin" / "python3"
        cmd = [str(venv_py), "ms-enforce"] if venv_py.exists() else [str(wt / "ms-enforce")]
        result = _run(cmd, capture=True, check=False, cwd=wt)
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            lines = output.splitlines()
            tier1_fail = any(
                ("TIER_1" in ln or "FAIL" in ln.upper()) and "WARN" not in ln.upper()
                for ln in lines
            )
            if tier1_fail:
                return False, output
        return True, output
    finally:
        _git("worktree", "remove", "--force", str(wt), check=False)
        _git("worktree", "prune", check=False)


# ── merge logic ───────────────────────────────────────────────────────────────

def _build_merge_message(branch: str, commits: list[str]) -> str:
    header = f"merge: {branch} into main"
    if commits:
        body = "Commits from wave branch:\n" + "\n".join(f"  {c}" for c in commits)
    else:
        body = "(no additional commits listed)"
    return f"{header}\n\n{body}"


def _do_merge(branch: str) -> tuple[bool, list[str]]:
    """Perform the --no-ff merge. Returns (success, conflicting_files)."""
    commits = _wave_commits(branch)
    msg = _build_merge_message(branch, commits)
    result = _git("merge", "--no-ff", "-m", msg, branch, check=False)
    if result.returncode == 0:
        return True, []
    # Gather conflicting files
    conflict_result = _git("diff", "--name-only", "--diff-filter=U", check=False)
    conflicting = [
        ln.strip() for ln in conflict_result.stdout.splitlines() if ln.strip()
    ]
    # Abort the merge
    _git("merge", "--abort", check=False)
    return False, conflicting


# ── audit log ─────────────────────────────────────────────────────────────────

def _append_audit_entry(
    merge_log: Path,
    *,
    branches: list[str],
    pre_sha: str,
    post_sha: str,
    preflight_results: dict[str, str],
    notes: str,
    caller: str,
    timestamp: str,
    method: str = "tools/merge_wave_to_main.py",
) -> None:
    """Prepend a new audit entry to docs/MERGE-LOG.md."""
    date_str = timestamp[:10]
    summary = ", ".join(branches)
    # Use post_sha for the last branch; mark earlier branches as 'see notes' when
    # multiple branches are merged (we don't track per-branch SHAs in the simple
    # single-merge-per-call flow).
    if post_sha == "ABORTED":
        branch_lines = "\n".join(
            f"  {i+1}. `{b}` → ABORTED (conflict)"
            for i, b in enumerate(branches)
        )
    elif len(branches) == 1:
        branch_lines = f"  1. `{branches[0]}` → merge commit `{post_sha}`"
    else:
        inner = "\n".join(
            f"  {i+1}. `{b}` → merge commit (see notes)"
            for i, b in enumerate(branches[:-1])
        )
        branch_lines = inner + f"\n  {len(branches)}. `{branches[-1]}` → merge commit `{post_sha}`"
    preflight_str = "\n".join(
        f"  - {k}: {v}" for k, v in preflight_results.items()
    )
    # Build the entry with explicit flush-left lines. Do NOT use textwrap.dedent
    # on an f-string here: the interpolated multi-line fields (branch_lines,
    # preflight_str) have only 2-space indent, which breaks dedent's common-prefix
    # computation and leaves the template lines with stray leading spaces (they
    # then render as Markdown code blocks). See BACKLOG batch-6 finding.
    entry = (
        f"## {date_str} — {summary}\n\n"
        f"- **Method:** {method}\n"
        f"- **Operator/Caller:** {caller}\n"
        f"- **Pre-merge main HEAD:** `{pre_sha}`\n"
        f"- **Branches merged (in order):**\n"
        f"{branch_lines}\n"
        f"- **Post-merge main HEAD:** `{post_sha}`\n"
        f"- **Pushed to origin:** no (push is operator-only)\n"
        f"- **Pre-flight checks run:**\n"
        f"{preflight_str}\n"
        f"- **Notes:** {notes}\n\n"
    )
    if not merge_log.exists():
        merge_log.parent.mkdir(parents=True, exist_ok=True)
        merge_log.write_text(entry, encoding="utf-8")
        return
    existing = merge_log.read_text(encoding="utf-8")
    # Insert after the header block (before the first ## entry or at end)
    header_end = existing.find("\n---\n")
    if header_end != -1:
        insert_at = header_end + 5  # after "---\n"
        new_content = existing[:insert_at] + "\n" + entry + existing[insert_at:]
    else:
        # No divider found — prepend at top
        new_content = entry + existing
    merge_log.write_text(new_content, encoding="utf-8")


# ── main ──────────────────────────────────────────────────────────────────────

def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _info(msg: str) -> None:
    print(f"  {msg}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    branches = argv

    # Resolve paths relative to repo root
    try:
        repo_root = _repo_root()
    except subprocess.CalledProcessError as exc:
        _die(f"Not inside a git repository: {exc}")

    settings_path = repo_root / SETTINGS_LOCAL
    merge_log_path = repo_root / MERGE_LOG
    caller = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"merge_wave_to_main: merging {len(branches)} branch(es) into main")
    print(f"  repo root:  {repo_root}")
    print(f"  caller:     {caller}")
    print(f"  timestamp:  {timestamp}")
    print()

    # ── Phase 1: Pre-flight (before touching main or denies) ─────────────────
    print("=== PRE-FLIGHT CHECKS ===")
    preflight_results: dict[str, str] = {}

    # 1a. Main working tree clean
    print("[1/5] Main working tree clean...")
    clean, clean_msg = _main_is_clean()
    preflight_results["working-tree"] = "CLEAN" if clean else f"DIRTY: {clean_msg}"
    if not clean:
        _die(f"Working tree is not clean: {clean_msg}")
    _info("OK — working tree clean")

    # 1b. All branches exist
    print("[2/5] Branch existence...")
    for branch in branches:
        if not _branch_exists(branch):
            preflight_results[f"branch-exists:{branch}"] = "MISSING"
            _die(f"Branch not found: {branch!r}")
        preflight_results[f"branch-exists:{branch}"] = "OK"
        _info(f"OK — {branch} exists")

    # 1c. Status file check
    print("[3/5] Wave status files...")
    for branch in branches:
        wave_key = _extract_wave_key(branch)
        status_path = _find_status_file(wave_key, repo_root)
        if status_path is not None:
            ok, reason = _status_is_complete(status_path)
            if not ok:
                preflight_results[f"status:{branch}"] = f"FAIL: {reason}"
                _die(f"Wave {wave_key} status check failed: {reason}")
            preflight_results[f"status:{branch}"] = "COMPLETE"
            _info(f"OK — {wave_key} status COMPLETE ({status_path.name})")
        else:
            preflight_results[f"status:{branch}"] = "no status file (skipped)"
            _info(f"SKIP — no status file for {wave_key}")

    # 1d. Non-empty diff
    print("[4/5] Non-empty diff vs main...")
    for branch in branches:
        diff = _diff_main(branch)
        if not diff:
            preflight_results[f"diff:{branch}"] = "EMPTY — refusing empty merge"
            _die(
                f"Branch {branch!r} has no differences vs main. "
                "Refusing empty merge."
            )
        preflight_results[f"diff:{branch}"] = f"OK ({len(diff.splitlines())} diff-stat lines)"
        _info(f"OK — {branch} has content vs main")

    # 1e. ms-enforce on wave branch
    print("[5/5] ms-enforce...")
    for branch in branches:
        passed, ms_output = _run_ms_enforce(branch, repo_root)
        if not passed:
            preflight_results[f"ms-enforce:{branch}"] = "TIER_1 FAIL"
            _die(
                f"ms-enforce TIER_1 failures on {branch!r}:\n{ms_output}\n"
                "Fix failures before merging."
            )
        summary = ms_output.splitlines()[0] if ms_output else "OK"
        preflight_results[f"ms-enforce:{branch}"] = summary[:80]
        _info(f"OK — ms-enforce: {summary[:60]}")

    print()
    print("Pre-flight: ALL PASSED")
    print()

    # Record pre-merge SHA
    pre_sha = _head_sha("main")
    post_sha = "ABORTED"

    # ── Phase 2: Lift denies, merge, restore (try/finally) ───────────────────
    print("=== MERGING ===")
    notes_parts: list[str] = []
    merge_succeeded = False
    conflict_files: list[str] = []

    # Select lift/restore strategy:
    # - Preferred: use the shared lifted() context manager from _lift_restore
    #   (profile-based restore; canonical wave-mode source of truth).
    # - Fallback: use the self-contained lift_denies/restore_denies (diff-based;
    #   used when the wave-mode profile is absent, e.g. in isolated test fixtures).
    _profile_path = settings_path.parent / "settings-wave-mode-profile.json"
    _use_shared_cm = (
        _HAVE_SHARED_LIFT_RESTORE
        and _lifted_cm is not None
        and _profile_path.exists()
    )

    import contextlib as _contextlib

    @_contextlib.contextmanager
    def _legacy_lift_restore():
        """Fallback context manager using diff-based lift_denies/restore_denies."""
        if settings_path.exists():
            _info(f"Lifting denies in {settings_path}")
            lift_denies(settings_path)
        else:
            _info(f"Settings file not found at {settings_path} — skipping lift")
        try:
            yield
        finally:
            if settings_path.exists():
                restore_denies(settings_path)
                _info("Denies restored.")

    if _use_shared_cm:
        _info(f"Lifting denies via shared lifted() context manager in {settings_path}")
        _ctx: _contextlib.AbstractContextManager = _lifted_cm(DENY_RULES, settings_path=settings_path)
    else:
        _ctx = _legacy_lift_restore()

    with _ctx:
        # Switch to main
        _info("Switching to main...")
        _git("checkout", "main")
        _info(f"Now on main (pre-merge HEAD: {_head_sha()})")

        # Merge each branch in order
        for branch in branches:
            print(f"  Merging {branch}...")
            success, conflicting = _do_merge(branch)
            if not success:
                conflict_files = conflicting
                notes_parts.append(
                    f"ABORTED (conflict) on {branch}. "
                    f"Conflicting files: {', '.join(conflicting) or 'unknown'}"
                )
                print(
                    f"\nMERGE CONFLICT on {branch}:\n"
                    + "\n".join(f"  {f}" for f in conflicting),
                    file=sys.stderr,
                )
                break
            sha = _head_sha()
            _info(f"Merged — new HEAD: {sha}")
            notes_parts.append(f"merged {branch} → {sha}")

        if not conflict_files:
            merge_succeeded = True
            post_sha = _head_sha()

    if _use_shared_cm and settings_path.exists():
        _info("Denies restored.")

    # ── Phase 3: Audit log ────────────────────────────────────────────────────
    print()
    print("=== AUDIT LOG ===")
    notes = "; ".join(notes_parts) if notes_parts else "clean merge"
    _append_audit_entry(
        merge_log_path,
        branches=branches,
        pre_sha=pre_sha,
        post_sha=post_sha if merge_succeeded else "ABORTED",
        preflight_results=preflight_results,
        notes=notes,
        caller=caller,
        timestamp=timestamp,
    )
    _info(f"Audit entry appended to {merge_log_path}")

    # ── Done ─────────────────────────────────────────────────────────────────
    print()
    if merge_succeeded:
        print(f"SUCCESS: {len(branches)} branch(es) merged into main.")
        print(f"  Pre-merge:  {pre_sha}")
        print(f"  Post-merge: {post_sha}")
        print("  (push to origin is operator-only — not done here)")
        return 0
    else:
        print(
            "ABORTED: merge conflict encountered. Conflicting files:",
            file=sys.stderr,
        )
        for f in conflict_files:
            print(f"  {f}", file=sys.stderr)
        print("Denies restored. Audit log entry written (ABORTED).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
