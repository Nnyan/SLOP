"""
tools/sanctioned/_lift_restore.py — Settings lift-restore primitives (S-68 Stream A).

Pure stdlib. Provides a try/finally-safe mechanism for temporarily lifting
deny-list entries in .claude/settings.local.json and restoring the canonical
wave-mode profile when done.

PUBLIC SYMBOLS (PINNED — streams C/D/E import exactly these):
  SETTINGS_LOCAL: Path       — .claude/settings.local.json
  WAVE_MODE_PROFILE: Path    — .claude/settings-wave-mode-profile.json
  lift(patterns, settings_path=SETTINGS_LOCAL) -> None
  restore(settings_path=SETTINGS_LOCAL) -> None
  lifted(patterns, settings_path=SETTINGS_LOCAL)  — context manager

Design:
- restore() re-applies the canonical wave-mode profile VERBATIM. It is NOT
  a diff-based undo. The profile is the single source of truth.
- lift() removes each pattern from permissions.deny AND adds it to
  permissions.allow so that bypassPermissions sessions still honour the
  explicit allow.
- lifted() wraps lift/restore in a try/finally. This is the preferred entry
  point for all callers — a tool that lifts and crashes before restore is a
  security hole.
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path

# ── pinned path constants ─────────────────────────────────────────────────────

SETTINGS_LOCAL: Path = Path(".claude/settings.local.json")
WAVE_MODE_PROFILE: Path = Path(".claude/settings-wave-mode-profile.json")


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ── public API ────────────────────────────────────────────────────────────────

def lift(patterns: list[str], settings_path: Path = SETTINGS_LOCAL) -> None:
    """Remove each pattern from permissions.deny, add to permissions.allow.

    Idempotent: calling lift() twice with the same patterns is safe.

    Args:
        patterns: List of deny-rule strings to lift (e.g. ["Bash(git push*)"]).
        settings_path: Path to the settings JSON file (default: SETTINGS_LOCAL).
    """
    data = _load_json(settings_path)
    perms = data.setdefault("permissions", {})

    deny_list: list[str] = perms.setdefault("deny", [])
    allow_list: list[str] = perms.setdefault("allow", [])

    # Remove from deny
    new_deny = [rule for rule in deny_list if rule not in patterns]
    perms["deny"] = new_deny

    # Add to allow (no duplicates)
    for pattern in patterns:
        if pattern not in allow_list:
            allow_list.append(pattern)

    _save_json(settings_path, data)


def restore(settings_path: Path = SETTINGS_LOCAL) -> None:
    """Re-apply the canonical wave-mode profile VERBATIM.

    Reads WAVE_MODE_PROFILE and writes its permissions block (allow + deny)
    into settings_path, completely replacing whatever is there. This is NOT
    a diff-based undo — it is a full canonical restore.

    The profile is located relative to settings_path's parent directory.
    Specifically: settings_path.parent / WAVE_MODE_PROFILE (using the same
    .claude/ root).

    Args:
        settings_path: Path to the settings JSON file to restore.
    """
    # Resolve profile path relative to the same base directory as settings_path
    # Both live under .claude/ so we compute: settings_path.parent / profile_filename
    profile_path = settings_path.parent / WAVE_MODE_PROFILE.name
    profile = _load_json(profile_path)

    data = _load_json(settings_path)
    # Replace the permissions block wholesale
    data["permissions"] = profile["permissions"]
    _save_json(settings_path, data)


@contextlib.contextmanager
def lifted(patterns: list[str], settings_path: Path = SETTINGS_LOCAL):
    """Context manager: lift patterns, yield, restore in try/finally.

    This is the PREFERRED entry point for all callers. The try/finally
    guarantees restore runs on success AND on every error path.

    Usage:
        with lifted(["Bash(git push*)", "Bash(git push -f*)"]):
            subprocess.run(["git", "push", "origin", "main"])

    Args:
        patterns: List of deny-rule strings to lift temporarily.
        settings_path: Path to the settings JSON file (default: SETTINGS_LOCAL).
    """
    lift(patterns, settings_path=settings_path)
    try:
        yield
    finally:
        restore(settings_path=settings_path)
