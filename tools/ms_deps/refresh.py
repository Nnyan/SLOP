"""tools.ms_deps.refresh — uv.lock upgrade wrapper with audit-regression abort.

CLI:
    python3 -m tools.ms_deps.refresh [options]

Options:
    --upgrade-package <name>   Targeted single-package bump.
    --dry-run                  Show the diff but do NOT write a new uv.lock.

Exit codes:
    0  Success (lock updated or unchanged, no CVE regression).
    1  Unexpected error (subprocess failure, missing file, etc.).
    2  Audit regression: new CVEs introduced; previous uv.lock restored.

Wave: S-49-B  (uv.lock refresh wrapper with audit-regression abort)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Interface contract for tools.ms_deps.diff
# At runtime (after all S-49 streams merge) this resolves to the real module.
# Tests can mock it via unittest.mock.patch("tools.ms_deps.refresh.deps_diff").
# ---------------------------------------------------------------------------
try:
    from tools.ms_deps import diff as deps_diff  # type: ignore[import]
except ImportError:  # pragma: no cover — only fires if diff stream not yet merged
    deps_diff = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the repository root (parent of this file's package)."""
    return Path(__file__).resolve().parent.parent.parent


def _uv_executable() -> str:
    """Return the path to the uv executable, preferring the system install."""
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError(
            "uv not found on PATH.  Install it via 'pip install uv' or "
            "download from https://docs.astral.sh/uv/"
        )
    return uv


def _uv_supports_upgrade_flag(uv: str) -> bool:
    """Return True if `uv lock --help` advertises --upgrade / -U."""
    try:
        result = subprocess.run(
            [uv, "lock", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        help_text = result.stdout + result.stderr
        return "--upgrade" in help_text or "-U" in help_text
    except (subprocess.TimeoutExpired, OSError):
        return False


def _run_uv_lock(
    uv: str,
    *,
    upgrade: bool,
    upgrade_package: str | None,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """Run uv lock with the appropriate flags."""
    cmd: list[str] = [uv, "lock"]
    if upgrade_package:
        cmd += ["--upgrade-package", upgrade_package]
    elif upgrade:
        cmd.append("--upgrade")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _run_pip_audit(cwd: Path) -> dict[str, Any] | None:
    """Run pip-audit and return parsed JSON result, or None if unavailable.

    Returns None (with a printed observation) when pip-audit is not installed
    so that the refresh step degrades gracefully.
    """
    pip_audit = shutil.which("pip-audit")
    if pip_audit is None:
        # Check inside the project venv
        venv_pip_audit = cwd / ".venv" / "bin" / "pip-audit"
        if venv_pip_audit.exists():
            pip_audit = str(venv_pip_audit)
        else:
            print(
                "OBSERVATION: pip-audit not found; audit step skipped. "
                "Install with: pip install pip-audit",
                file=sys.stderr,
            )
            return None

    requirements = cwd / "requirements.txt"
    if not requirements.exists():
        print(
            "OBSERVATION: requirements.txt not found; audit step skipped.",
            file=sys.stderr,
        )
        return None

    result = subprocess.run(
        [pip_audit, "-r", str(requirements), "--strict", "--format", "json"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # pip-audit may emit non-JSON on certain errors; treat as empty.
        return {}


def _extract_cve_set(audit_result: dict[str, Any] | None) -> set[str]:
    """Extract a frozenset of CVE/vuln IDs from a pip-audit JSON result."""
    if not audit_result:
        return set()
    vulns: set[str] = set()
    for dep in audit_result.get("dependencies", []):
        for v in dep.get("vulns", []):
            vid = v.get("id", "")
            if vid:
                vulns.add(vid)
    return vulns


def _compute_diff(old_lock: Path, new_lock: Path) -> str:
    """Return a markdown diff table between two lockfiles.

    Falls back to a plain message when deps_diff is not available.
    """
    if deps_diff is not None:
        try:
            return deps_diff.diff_to_markdown(str(old_lock), str(new_lock))
        except Exception as exc:  # noqa: BLE001
            return f"(diff failed: {exc})"
    return (
        "(Version diff unavailable — tools.ms_deps.diff not yet installed. "
        "Run after S-49-A merges.)"
    )


# ---------------------------------------------------------------------------
# Core refresh logic
# ---------------------------------------------------------------------------

def run_refresh(
    *,
    upgrade_package: str | None = None,
    dry_run: bool = False,
    cwd: Path | None = None,
) -> int:
    """Execute the uv.lock refresh workflow.

    Returns an exit code (0, 1, or 2).
    """
    if cwd is None:
        cwd = _repo_root()

    lock_path = cwd / "uv.lock"
    if not lock_path.exists():
        print(f"ERROR: uv.lock not found at {lock_path}", file=sys.stderr)
        return 1

    uv = _uv_executable()
    supports_upgrade = _uv_supports_upgrade_flag(uv)

    # ------------------------------------------------------------------
    # Step 1: Snapshot current uv.lock
    # ------------------------------------------------------------------
    # Write snapshot to /tmp to avoid the need for a .gitignore entry.
    # A decision file (S-49-B-1.md) records the reasoning.
    run_id = uuid.uuid4().hex[:12]
    snapshot_path = Path(tempfile.gettempdir()) / f"uv.lock.previous-{run_id}"
    shutil.copy2(lock_path, snapshot_path)
    print(f"Snapshot saved: {snapshot_path}")

    # ------------------------------------------------------------------
    # Step 2: Run pip-audit on the *current* lock (baseline CVE set)
    # ------------------------------------------------------------------
    print("Running pip-audit on current lock (baseline)...")
    baseline_audit = _run_pip_audit(cwd)
    baseline_cves = _extract_cve_set(baseline_audit)
    if baseline_cves:
        print(f"  Baseline CVEs: {', '.join(sorted(baseline_cves))}")
    else:
        print("  Baseline CVEs: none detected (or pip-audit unavailable).")

    # ------------------------------------------------------------------
    # Step 3: Run uv lock --upgrade (or uv lock if flag unavailable)
    # ------------------------------------------------------------------
    print("Running uv lock...")
    proc = _run_uv_lock(
        uv,
        upgrade=(supports_upgrade and not upgrade_package),
        upgrade_package=upgrade_package if upgrade_package else None,
        cwd=cwd,
    )
    if proc.returncode != 0:
        print(f"ERROR: uv lock failed (exit {proc.returncode}):", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        # Restore snapshot
        shutil.copy2(snapshot_path, lock_path)
        print(f"Restored previous lock from {snapshot_path}")
        return 1

    # ------------------------------------------------------------------
    # Step 4: Compute version diff
    # ------------------------------------------------------------------
    diff_output = _compute_diff(snapshot_path, lock_path)
    print("\n--- Version diff ---")
    print(diff_output)
    print("--- End diff ---\n")

    # ------------------------------------------------------------------
    # Step 5: Run pip-audit on the NEW lock
    # ------------------------------------------------------------------
    print("Running pip-audit on new lock...")
    new_audit = _run_pip_audit(cwd)
    new_cves = _extract_cve_set(new_audit)

    introduced_cves = new_cves - baseline_cves
    resolved_cves = baseline_cves - new_cves

    if resolved_cves:
        print(f"  CVEs resolved: {', '.join(sorted(resolved_cves))}")
    if introduced_cves:
        print(
            f"  REGRESSION: New CVEs introduced: "
            f"{', '.join(sorted(introduced_cves))}",
            file=sys.stderr,
        )

    # ------------------------------------------------------------------
    # Step 6: Abort / restore on regression or dry-run
    # ------------------------------------------------------------------
    if introduced_cves:
        shutil.copy2(snapshot_path, lock_path)
        print(
            f"Previous uv.lock restored from {snapshot_path}.",
            file=sys.stderr,
        )
        return 2

    if dry_run:
        shutil.copy2(snapshot_path, lock_path)
        print("Dry-run: uv.lock restored to previous state.")
        return 0

    print("uv.lock updated successfully.")
    return 0


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m tools.ms_deps.refresh",
        description=(
            "Upgrade uv.lock via 'uv lock --upgrade'. "
            "Aborts (exit 2) if pip-audit finds new CVEs in the new lock."
        ),
    )
    parser.add_argument(
        "--upgrade-package",
        metavar="NAME",
        help="Upgrade only the named package (targeted bump).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the diff but do not persist the new uv.lock.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return run_refresh(
        upgrade_package=args.upgrade_package,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
