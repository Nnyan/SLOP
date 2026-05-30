#!/usr/bin/env python3
"""
tools/sanctioned/robot_settings.py — Sanctioned operator-handoff settings tool (S-68 Stream C).

Subcommands:
  lift push            Lift Bash(git push*) deny (allows git push for one operation).
  lift checkout-main   Lift Bash(git checkout main*) + Bash(git switch main*) denies.
  lift filter-branch   Lift Bash(git filter-branch*) deny.
  restore              Restore canonical wave-mode profile (no-op if already matches).
  push-then-restore    Convenience: lift push -> git push -> restore in finally.
                       Accepts [--repo PATH] [--branch NAME] (default: SLOP main) so a
                       single sanctioned path pushes any Nnyan/* repo (e.g. v5).

Built on tools.sanctioned._lift_restore.lifted() / restore() for mandatory try/finally
lift-restore discipline.  Audits every operation via tools.sanctioned._audit.write_entry
to docs/SANCTIONED-OPS-LOG.md.

All stdlib — no external dependencies.

Usage:
  python3 tools/sanctioned/robot_settings.py <subcommand> [args...]
  python3 tools/sanctioned/robot_settings.py --help

Environment:
  Runs from the repository root (the directory containing .claude/).
  The wave-mode profile must exist at .claude/settings-wave-mode-profile.json
  before using the lift or restore subcommands.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ── resolve repo root and import shared modules ───────────────────────────────

# Support running from any cwd by resolving relative to this file's location
_TOOLS_SANCTIONED = Path(__file__).resolve().parent
_TOOLS = _TOOLS_SANCTIONED.parent
_REPO_ROOT = _TOOLS.parent

# Make repo root importable so `from tools.sanctioned._lift_restore import …` works
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.sanctioned._lift_restore import lifted, restore, SETTINGS_LOCAL, WAVE_MODE_PROFILE  # noqa: E402
from tools.sanctioned._audit import write_entry  # noqa: E402

# ── deny-rule sets per subcommand ─────────────────────────────────────────────

_PUSH_RULES = [
    "Bash(git push*)",
    "Bash(git push -f*)",
    "Bash(git push -u*)",
    "Bash(git push --no-verify*)",
    "Bash(git push --force*)",
]

_CHECKOUT_MAIN_RULES = [
    "Bash(git checkout main*)",
    "Bash(git switch main*)",
]

_FILTER_BRANCH_RULES = [
    "Bash(git filter-branch*)",
]

# Map subcommand name -> deny rules to lift
_LIFT_SUBCOMMANDS: dict[str, list[str]] = {
    "push": _PUSH_RULES,
    "checkout-main": _CHECKOUT_MAIN_RULES,
    "filter-branch": _FILTER_BRANCH_RULES,
}

# ── helpers ───────────────────────────────────────────────────────────────────

def _git_sha(ref: str = "HEAD", repo: Path | str = _REPO_ROOT) -> str | None:
    """Return the short SHA of ref in *repo*, or None on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", ref],
            capture_output=True, text=True, check=True,
            cwd=repo,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _settings_matches_profile(settings_path: Path, profile_path: Path) -> bool:
    """Return True if the settings permissions block matches the profile verbatim."""
    import json
    try:
        with settings_path.open(encoding="utf-8") as f:
            settings = json.load(f)
        with profile_path.open(encoding="utf-8") as f:
            profile = json.load(f)
        return settings.get("permissions") == profile.get("permissions")
    except Exception:
        return False


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ── subcommand handlers ───────────────────────────────────────────────────────

def _cmd_lift(args: list[str]) -> int:
    """lift <subcommand> — lift one set of deny rules, perform no operation."""
    if not args:
        _die(
            "lift requires a subcommand: " + ", ".join(_LIFT_SUBCOMMANDS)
        )
    sub = args[0]
    if sub not in _LIFT_SUBCOMMANDS:
        _die(f"Unknown lift subcommand {sub!r}. Valid: {', '.join(_LIFT_SUBCOMMANDS)}")

    patterns = _LIFT_SUBCOMMANDS[sub]
    settings_path = _REPO_ROOT / SETTINGS_LOCAL

    if not settings_path.exists():
        _die(f"Settings file not found: {settings_path}")

    pre_sha = _git_sha()
    result = "OK"
    notes = f"lifted {sub!r} deny rules: {patterns}; no operation performed (operator must act then call restore)"

    try:
        with lifted(patterns, settings_path=settings_path):
            write_entry(
                tool="robot_settings",
                op=f"lift {sub}",
                pre_sha=pre_sha,
                post_sha=None,
                result="LIFTED — awaiting operator action",
                notes=notes,
            )
            print(f"  [robot_settings] lifted: {sub}")
            print(f"  Rules lifted: {patterns}")
            print("  Denies will be restored when this process exits (try/finally).")
            # The lift subcommand just lifts and immediately restores via the context manager.
            # For persistent lift (operator needs to act), use push-then-restore instead.
            print()
            print("NOTE: lift <sub> lifts and immediately restores within this invocation.")
            print("      For a persistent lift during an interactive operation, use the")
            print("      push-then-restore subcommand, or call this from a wrapping script.")
    except Exception as exc:
        result = f"FAILED: {exc}"
        write_entry(
            tool="robot_settings",
            op=f"lift {sub}",
            pre_sha=pre_sha,
            post_sha=None,
            result=result,
            notes=f"exception during lift: {exc}",
        )
        _die(str(exc))

    return 0


def _cmd_restore(args: list[str]) -> int:  # noqa: ARG001
    """restore — re-apply canonical wave-mode profile (no-op if already matches)."""
    settings_path = _REPO_ROOT / SETTINGS_LOCAL
    profile_path = _REPO_ROOT / WAVE_MODE_PROFILE

    if not profile_path.exists():
        _die(f"Wave-mode profile not found: {profile_path}")
    if not settings_path.exists():
        _die(f"Settings file not found: {settings_path}")

    pre_sha = _git_sha()

    if _settings_matches_profile(settings_path, profile_path):
        print("  [robot_settings] restore: settings already match the canonical profile — no-op.")
        write_entry(
            tool="robot_settings",
            op="restore",
            pre_sha=pre_sha,
            post_sha=None,
            result="NO-OP (already canonical)",
            notes="settings.local.json permissions block matches wave-mode profile verbatim",
        )
        return 0

    try:
        restore(settings_path=settings_path)
        print(f"  [robot_settings] restore: canonical profile applied from {profile_path}")
        write_entry(
            tool="robot_settings",
            op="restore",
            pre_sha=pre_sha,
            post_sha=None,
            result="OK",
            notes=f"applied canonical wave-mode profile from {profile_path}",
        )
    except Exception as exc:
        write_entry(
            tool="robot_settings",
            op="restore",
            pre_sha=pre_sha,
            post_sha=None,
            result=f"FAILED: {exc}",
            notes=f"exception during restore: {exc}",
        )
        _die(str(exc))

    return 0


def _cmd_push_then_restore(args: list[str]) -> int:
    """push-then-restore [--repo PATH] [--branch NAME] — lift push deny, push, restore.

    The SETTINGS lifted are always this session's SLOP settings (the deny governs the
    session, not the target repo). --repo only changes the git push TARGET, so a single
    sanctioned path pushes any Nnyan/* repo (e.g. v5/slop-process) — see CLAUDE.md
    § "No phantom owners". Defaults to SLOP main.
    """
    repo = Path(_REPO_ROOT)
    branch = "main"
    rest = list(args)
    while rest:
        tok = rest.pop(0)
        if tok == "--repo":
            repo = Path(rest.pop(0)) if rest else _die("--repo requires a path")
        elif tok == "--branch":
            branch = rest.pop(0) if rest else _die("--branch requires a name")
        else:
            _die(f"Unknown push-then-restore arg {tok!r}. Use [--repo PATH] [--branch NAME].")

    settings_path = _REPO_ROOT / SETTINGS_LOCAL

    if not settings_path.exists():
        _die(f"Settings file not found: {settings_path}")

    pre_sha = _git_sha(repo=repo)
    post_sha = None
    op_result = "ABORTED"
    target = f"{repo} {branch}"

    try:
        with lifted(_PUSH_RULES, settings_path=settings_path):
            write_entry(
                tool="robot_settings",
                op="push-then-restore (start)",
                pre_sha=pre_sha,
                post_sha=None,
                result="LIFTED",
                notes=f"push deny lifted; executing git -C {repo} push origin {branch}",
            )
            print(f"  [robot_settings] push-then-restore: push deny lifted; running git -C {repo} push origin {branch}...")
            push_result = subprocess.run(
                ["git", "-C", str(repo), "push", "origin", branch],
                capture_output=False,
                text=True,
            )
            post_sha = _git_sha(repo=repo)
            if push_result.returncode == 0:
                op_result = "OK"
                print("  [robot_settings] push-then-restore: push succeeded.")
            else:
                op_result = f"FAILED: git push exited {push_result.returncode}"
                print(f"  [robot_settings] push-then-restore: push FAILED (exit {push_result.returncode}).", file=sys.stderr)
    except Exception as exc:
        op_result = f"FAILED: {exc}"
        _die(str(exc))
    finally:
        write_entry(
            tool="robot_settings",
            op="push-then-restore (complete)",
            pre_sha=pre_sha,
            post_sha=post_sha,
            result=op_result,
            notes=f"target {target}; push deny restored unconditionally in finally block",
        )

    return 0 if op_result == "OK" else 1


# ── dispatch ──────────────────────────────────────────────────────────────────

_USAGE = """\
Usage: python3 tools/sanctioned/robot_settings.py <subcommand> [args]

Subcommands:
  lift push            Lift Bash(git push*) deny temporarily.
  lift checkout-main   Lift Bash(git checkout main*) + Bash(git switch main*) denies temporarily.
  lift filter-branch   Lift Bash(git filter-branch*) deny temporarily.
  restore              Re-apply canonical wave-mode profile (no-op if already matches).
  push-then-restore [--repo PATH] [--branch NAME]
                       Lift push deny, run git push (default SLOP main; --repo pushes
                       any Nnyan/* repo, e.g. /home/stack/v5), restore in finally.

All operations are audited to docs/SANCTIONED-OPS-LOG.md.
Every deny-lifting path is wrapped in try/finally — restore runs on success AND error.
"""


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE)
        return 0

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "lift":
        return _cmd_lift(rest)
    elif cmd == "restore":
        return _cmd_restore(rest)
    elif cmd == "push-then-restore":
        return _cmd_push_then_restore(rest)
    else:
        _die(f"Unknown subcommand {cmd!r}. Run with --help for usage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
