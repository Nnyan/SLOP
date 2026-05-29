"""tools.access_request_appliers — Category appliers for the access-requests queue.

Each applier handles one category from docs/ACCESS-REQUESTS.md:
  - apply_install  : invoke `uv pip install <pkg>`; track in requirements*.txt
  - apply_upgrade  : file an --upgrade-package request for the S-49 refresh-train
  - apply_allow    : add an allow entry to settings.local.json (lift-restore pattern)
  - apply_deny     : add a deny entry to settings.local.json (requires explicit flag)

Design constraints (Robot rule 8 — settings immutable during run):
  - All appliers take TARGET PATHS as parameters so tests can pass temp files.
  - No applier mutates live settings/requirements during the wave itself.
  - dry_run=True is a no-op for every applier (returns what WOULD change).

Wave: S-59-B (access-request category appliers)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Marker file name written by apply_upgrade inside the repo root.
UPGRADE_REQUESTS_FILE = "upgrade-requests.txt"

#: Field name in the marker file recognised by the S-49 refresh-train.
UPGRADE_PACKAGE_FLAG = "--upgrade-package"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    """Read and return JSON from *path*; return {} if file is absent/empty."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text)  # type: ignore[return-value]


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write *data* to *path* as pretty-printed JSON (no trailing newline)."""
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _lift_deny(settings: dict[str, Any], pattern: str) -> bool:
    """Remove *pattern* from the deny list.  Returns True if it was present."""
    deny: list[str] = settings.get("permissions", {}).get("deny", [])
    if pattern in deny:
        deny.remove(pattern)
        settings.setdefault("permissions", {})["deny"] = deny
        return True
    return False


def _restore_deny(settings: dict[str, Any], pattern: str) -> None:
    """Re-add *pattern* to the deny list if absent."""
    deny: list[str] = settings.setdefault("permissions", {}).setdefault("deny", [])
    if pattern not in deny:
        deny.append(pattern)


def _parse_pkg_name(requirement: str) -> str:
    """Extract the bare package name from a requirement specifier like 'foo>=1.2'."""
    return re.split(r"[>=<!;@\s]", requirement.strip())[0].strip()


def _requirements_contain(pkg_name: str, req_path: Path) -> bool:
    """Return True if *pkg_name* (case-insensitive) already appears in the file."""
    if not req_path.exists():
        return False
    norm = pkg_name.lower().replace("-", "_")
    for line in req_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        existing = _parse_pkg_name(stripped).lower().replace("-", "_")
        if existing == norm:
            return True
    return False


def _constraint_satisfied(pkg_name: str, req_paths: list[Path]) -> bool:
    """Return True if *pkg_name* appears in any of the given requirements files."""
    return any(_requirements_contain(pkg_name, p) for p in req_paths)


# ---------------------------------------------------------------------------
# apply_install
# ---------------------------------------------------------------------------


def apply_install(
    package: str,
    *,
    venv_bin: Path | str | None = None,
    requirements_path: Path | None = None,
    extra_req_paths: list[Path] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Install *package* into the project venv via `uv pip install`.

    Parameters
    ----------
    package:
        Package specifier, e.g. ``"pip-audit>=2.7.0"`` or ``"pip-audit"``.
    venv_bin:
        Path to the venv ``bin/`` directory or the ``uv`` executable.
        Defaults to ``Path(".venv/bin")``.
    requirements_path:
        The requirements file to append the package to when it is not already
        constrained.  Defaults to ``requirements-dev.txt`` in the current
        directory.  Pass a temp-file path in tests.
    extra_req_paths:
        Additional requirements files to search for existing constraints
        (e.g. ``requirements.txt``).  Not written to.
    dry_run:
        If True, return what WOULD happen without running pip or editing files.

    Returns
    -------
    dict with keys:
        ``already_constrained`` (bool),
        ``appended`` (bool),
        ``installed`` (bool),
        ``dry_run`` (bool),
        ``package`` (str).
    """
    if venv_bin is None:
        venv_bin = Path(".venv/bin")
    venv_bin = Path(venv_bin)

    if requirements_path is None:
        requirements_path = Path("requirements-dev.txt")
    requirements_path = Path(requirements_path)

    search_paths: list[Path] = [requirements_path]
    if extra_req_paths:
        search_paths.extend(extra_req_paths)

    pkg_name = _parse_pkg_name(package)
    already = _constraint_satisfied(pkg_name, search_paths)

    result: dict[str, Any] = {
        "package": package,
        "already_constrained": already,
        "appended": False,
        "installed": False,
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    # Append to requirements file when not already constrained.
    if not already:
        with requirements_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{package}\n")
        result["appended"] = True

    # Invoke uv pip install.
    uv_exec = shutil.which("uv") if not (venv_bin / "uv").exists() else str(venv_bin / "uv")  # noqa: E501
    # Prefer uv from PATH; fall back to python -m pip.
    cmd: list[str]
    if uv_exec:
        cmd = [uv_exec, "pip", "install", package]
    else:
        cmd = [sys.executable, "-m", "pip", "install", package]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"uv pip install failed (exit {proc.returncode}):\n{proc.stderr}"
        )
    result["installed"] = True
    return result


# ---------------------------------------------------------------------------
# apply_upgrade
# ---------------------------------------------------------------------------


def apply_upgrade(
    package: str,
    *,
    upgrade_requests_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """File an ``--upgrade-package <name>`` request for the S-49 refresh-train.

    The request is written/appended to *upgrade_requests_path* (default:
    ``upgrade-requests.txt`` at the repo root).  The refresh-train reads
    this file and passes each ``--upgrade-package <name>`` flag to
    ``tools.ms_deps.refresh``.

    The applier does NOT execute an upgrade; the train handles that with its
    full test gate.

    Parameters
    ----------
    package:
        Bare package name, e.g. ``"starlette"``.
    upgrade_requests_path:
        Path to the upgrade-requests file.  Pass a temp file in tests.
    dry_run:
        If True, return what WOULD happen without writing any file.

    Returns
    -------
    dict with keys:
        ``package`` (str),
        ``already_requested`` (bool),
        ``appended`` (bool),
        ``dry_run`` (bool),
        ``upgrade_requests_path`` (str).
    """
    if upgrade_requests_path is None:
        upgrade_requests_path = Path(UPGRADE_REQUESTS_FILE)
    upgrade_requests_path = Path(upgrade_requests_path)

    pkg_name = _parse_pkg_name(package)

    # Check if already present to stay idempotent.
    already = False
    if upgrade_requests_path.exists():
        lines = upgrade_requests_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            stripped = line.strip()
            # Line format: "--upgrade-package <name>"
            if stripped == f"{UPGRADE_PACKAGE_FLAG} {pkg_name}":
                already = True
                break

    result: dict[str, Any] = {
        "package": pkg_name,
        "already_requested": already,
        "appended": False,
        "dry_run": dry_run,
        "upgrade_requests_path": str(upgrade_requests_path),
    }

    if dry_run or already:
        return result

    # Append the request marker.
    with upgrade_requests_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{UPGRADE_PACKAGE_FLAG} {pkg_name}\n")
    result["appended"] = True
    return result


# ---------------------------------------------------------------------------
# apply_allow
# ---------------------------------------------------------------------------


def apply_allow(
    entry: str,
    *,
    settings_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add *entry* to the allow list in a settings.local.json file.

    Uses the lift-restore pattern:
      1. Temporarily lift the self-edit deny for the settings file.
      2. Add *entry* to ``permissions.allow`` (idempotent — no duplicates).
      3. Restore the deny.

    Parameters
    ----------
    entry:
        The permission string to allow, e.g. ``"WebFetch(domain:example.com)"``.
    settings_path:
        Path to the settings.local.json file.  Defaults to
        ``.claude/settings.local.json``.  Pass a temp file in tests.
    dry_run:
        If True, return what WOULD happen without writing any file.

    Returns
    -------
    dict with keys:
        ``entry`` (str),
        ``already_present`` (bool),
        ``added`` (bool),
        ``dry_run`` (bool).
    """
    if settings_path is None:
        settings_path = Path(".claude/settings.local.json")
    settings_path = Path(settings_path)

    settings = _read_json(settings_path)
    allow: list[str] = settings.setdefault("permissions", {}).setdefault("allow", [])

    already_present = entry in allow

    result: dict[str, Any] = {
        "entry": entry,
        "already_present": already_present,
        "added": False,
        "dry_run": dry_run,
    }

    if dry_run or already_present:
        return result

    # Lift self-edit deny for this specific settings file path, edit, restore.
    self_edit_deny_pattern = f"Edit({settings_path})"
    lifted = _lift_deny(settings, self_edit_deny_pattern)

    try:
        allow.append(entry)
        _write_json(settings_path, settings)
        result["added"] = True
    finally:
        if lifted:
            _restore_deny(settings, self_edit_deny_pattern)
            _write_json(settings_path, settings)

    return result


# ---------------------------------------------------------------------------
# apply_deny
# ---------------------------------------------------------------------------


def apply_deny(
    entry: str,
    *,
    settings_path: Path | None = None,
    allow_deny_additions: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Add *entry* to the deny list in a settings.local.json file.

    Same lift-restore pattern as apply_allow but for the deny list.
    Requires ``allow_deny_additions=True`` — deny additions are rare and
    tighten restrictions, so they must be explicitly authorised by the caller.

    Parameters
    ----------
    entry:
        The permission string to deny, e.g. ``"Bash(rm -rf /)"`.
    settings_path:
        Path to the settings.local.json file.  Defaults to
        ``.claude/settings.local.json``.  Pass a temp file in tests.
    allow_deny_additions:
        Must be True or the applier raises ValueError.
    dry_run:
        If True, return what WOULD happen without writing any file.

    Returns
    -------
    dict with keys:
        ``entry`` (str),
        ``already_present`` (bool),
        ``added`` (bool),
        ``dry_run`` (bool).

    Raises
    ------
    ValueError
        When ``allow_deny_additions`` is False.
    """
    if not allow_deny_additions:
        raise ValueError(
            "apply_deny requires allow_deny_additions=True. "
            "Deny additions tighten restrictions and must be explicitly authorised."
        )

    if settings_path is None:
        settings_path = Path(".claude/settings.local.json")
    settings_path = Path(settings_path)

    settings = _read_json(settings_path)
    deny: list[str] = settings.setdefault("permissions", {}).setdefault("deny", [])

    already_present = entry in deny

    result: dict[str, Any] = {
        "entry": entry,
        "already_present": already_present,
        "added": False,
        "dry_run": dry_run,
    }

    if dry_run or already_present:
        return result

    # Lift self-edit deny for this specific settings file path, edit, restore.
    self_edit_deny_pattern = f"Edit({settings_path})"
    lifted = _lift_deny(settings, self_edit_deny_pattern)

    try:
        deny.append(entry)
        _write_json(settings_path, settings)
        result["added"] = True
    finally:
        if lifted:
            _restore_deny(settings, self_edit_deny_pattern)
            _write_json(settings_path, settings)

    return result



# ── A<->B reconciliation adapter (added by operator at merge time per
#    .claude/run-archive/2026-05-29-batch5/decisions/S-59-AB-interface-gap.md) ──
def _pkg_from_subject(subject: str) -> str:
    """Extract first backtick-quoted token (the package name) from an entry subject."""
    import re
    m = re.search(r"`([^`]+)`", subject or "")
    return m.group(1).strip() if m else (subject or "").strip()


def _install_adapter(entry, *, dry_run, target_paths):
    pkg = _pkg_from_subject(entry.get("subject", ""))
    try:
        r = apply_install(pkg, requirements_path=target_paths["requirements"], dry_run=dry_run)
        return {"ok": True, "action": r.get("action", ""), "error": ""}
    except Exception as exc:
        return {"ok": False, "action": "", "error": str(exc)[:200]}


def _upgrade_adapter(entry, *, dry_run, target_paths):
    pkg = _pkg_from_subject(entry.get("subject", ""))
    try:
        r = apply_upgrade(pkg, dry_run=dry_run)
        return {"ok": True, "action": r.get("action", ""), "error": ""}
    except Exception as exc:
        return {"ok": False, "action": "", "error": str(exc)[:200]}


def _allow_adapter(entry, *, dry_run, target_paths):
    try:
        r = apply_allow(entry, dry_run=dry_run)
        return {"ok": True, "action": r.get("action", ""), "error": ""}
    except Exception as exc:
        return {"ok": False, "action": "", "error": str(exc)[:200]}


def _deny_adapter(entry, *, dry_run, target_paths):
    try:
        r = apply_deny(entry, dry_run=dry_run, allow_deny_additions=True)
        return {"ok": True, "action": r.get("action", ""), "error": ""}
    except Exception as exc:
        return {"ok": False, "action": "", "error": str(exc)[:200]}


APPLIERS = {
    "install": _install_adapter,
    "upgrade": _upgrade_adapter,
    "allow": _allow_adapter,
    "deny": _deny_adapter,
}
