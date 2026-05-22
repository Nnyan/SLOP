#!/usr/bin/env python3
"""Structural anti-pattern checker — Mediastack repository.

Each rule in RULES is a tuple of:
  (rule_id, description, check_fn, remedy)

check_fn(repo, mode) -> list[str]
  mode "staged"  — checks git-staged changes only (pre-commit)
  mode "audit"   — scans full repo state (post-deploy / release gate)
  Returns a list of finding strings; empty list means clean.

Usage:
  tools/check_structural_antipatterns.py --staged   # pre-commit
  tools/check_structural_antipatterns.py --audit    # post-deploy / release gate

Exit 0 if clean, 1 if findings.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

ADR_PATTERN = re.compile(r"^\d{4}-.*\.md$")

CANONICAL_DOCS = [
    "CORE_RULES.md",
    "PROJECT_CLEANUP.md",
]


def _staged_files():
    """Return list of (status, filepath) tuples for staged changes."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    pairs = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            pairs.append((parts[0].strip(), parts[1].strip()))
    return pairs


def _is_git_ignored(path_str):
    """Return True if path is ignored by .gitignore."""
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path_str],
        capture_output=True, cwd=str(REPO),
    )
    return result.returncode == 0


def _check_loose_adr(repo, mode):
    """rule-001: ADR file staged or present at docs/*.md instead of docs/adr/."""
    findings = []
    if mode == "staged":
        for status, path in _staged_files():
            if not status.startswith("A"):
                continue
            p = Path(path)
            if p.parent == Path("docs") and ADR_PATTERN.match(p.name):
                findings.append(
                    "rule-001: ADR file staged at " + path
                    + " -- must be under docs/adr/; "
                    + "remedy: git mv " + path + " docs/adr/" + p.name
                )
    else:
        for p in (repo / "docs").glob("*.md"):
            if ADR_PATTERN.match(p.name):
                rel = str(p.relative_to(repo))
                findings.append(
                    "rule-001: ADR file at " + rel
                    + " -- must be under docs/adr/; "
                    + "remedy: git mv " + rel + " docs/adr/" + p.name
                )
    return findings


def _check_unignored_data_dir(repo, mode):
    """rule-002: tracked file under data/<x>/ with no !data/<x>/ gitignore exception."""
    findings = []
    gitignore = repo / ".gitignore"
    exceptions = set()
    if gitignore.exists():
        for line in gitignore.read_text().splitlines():
            s = line.strip()
            if s.startswith("!data/") and s.endswith("/"):
                exceptions.add(s[len("!data/"):-1])

    if mode == "staged":
        seen = set()
        for status, path in _staged_files():
            if not status.startswith("A"):
                continue
            parts = path.split("/")
            if len(parts) >= 2 and parts[0] == "data":
                subdir = parts[1]
                if subdir in seen or subdir in exceptions:
                    continue
                seen.add(subdir)
                findings.append(
                    "rule-002: new tracked file under data/" + subdir + "/"
                    + " with no !data/" + subdir + "/ exception in .gitignore"
                    + " -- remedy: add '!data/" + subdir + "/' to .gitignore exceptions"
                )
    else:
        result = subprocess.run(
            ["git", "ls-files", "data/"],
            capture_output=True, text=True, cwd=str(repo),
        )
        tracked_subdirs = set()
        for line in result.stdout.splitlines():
            parts = line.split("/")
            if len(parts) >= 2:
                tracked_subdirs.add(parts[1])
        for subdir in sorted(tracked_subdirs):
            if subdir not in exceptions:
                findings.append(
                    "rule-002: tracked files under data/" + subdir + "/"
                    + " but no !data/" + subdir + "/ exception in .gitignore"
                    + " -- remedy: add '!data/" + subdir + "/' to .gitignore exceptions"
                )
    return findings


def _check_canonical_doc_at_root(repo, mode):
    """rule-003: canonical doc (CORE_RULES.md, PROJECT_CLEANUP.md) found at repo root."""
    findings = []
    if mode == "staged":
        for status, path in _staged_files():
            if status.startswith("A") and path in CANONICAL_DOCS:
                findings.append(
                    "rule-003: canonical doc " + path + " added at repo root"
                    + " -- remedy: git rm --cached " + path
                    + " and place at canonical path"
                )
    else:
        for doc in CANONICAL_DOCS:
            if (repo / doc).exists():
                findings.append(
                    "rule-003: canonical doc " + doc + " exists at repo root"
                    + " -- remedy: git rm " + doc + " (canonical: docs/ or docs/cleanup/)"
                )
    return findings




_PYTEST_BASE = Path("/tmp/pytest-base")


def _get_entry_uid(entry):
    """Return the uid of a filesystem entry, or -1 on stat error."""
    try:
        return entry.stat(follow_symlinks=False).st_uid
    except OSError:
        return -1


def _check_root_owned_pytest_scratch(repo, mode):
    """rule-004: root-owned files/dirs under /tmp/pytest-base/."""
    base = _PYTEST_BASE
    if not base.exists():
        return []
    findings = []
    try:
        for entry in base.iterdir():
            if _get_entry_uid(entry) == 0:
                findings.append(
                    "rule-004: root-owned entry in pytest scratch: " + str(entry)
                    + " -- caused by a test that invokes real Docker without fake_docker;"
                    + " remedy: sudo rm -rf " + str(entry)
                    + " and see docs/TODO_2026_05_10_root_owned_test_files.md"
                )
    except PermissionError:
        pass
    return findings

_INSTALLER_HARDCODED_PATHS = ["/opt/mediastack", "/var/lib/mediastack"]

# Files within installer/ that are permitted to contain the default path strings
# (e.g., the single canonical default-value definition module per ADR 0013 §1).
# Expand here when installer/config.py or equivalent is added in Tier 2.
_INSTALLER_PATH_ALLOWLIST: set = {
    "installer/_defaults.py",  # canonical default-value definitions (ADR 0013 INV-1)
}


def _check_installer_hardcoded_paths(repo, mode):
    """rule-005: installer/ file hardcodes /opt/mediastack or /var/lib/mediastack.

    Enforces ADR 0013 INV-1 (Core Rule 5.26): paths must be read from CLI args,
    env vars, or the state file. installer/tests/ is automatically excluded (test
    fixtures may reference the literal strings as expected values).
    """
    findings = []
    installer_dir = repo / "installer"
    tests_dir = installer_dir / "tests"

    if mode == "staged":
        for status, path in _staged_files():
            if not path.startswith("installer/"):
                continue
            try:
                Path(path).relative_to(Path("installer/tests"))
                continue
            except ValueError:
                pass
            if path in _INSTALLER_PATH_ALLOWLIST:
                continue
            full_path = repo / path
            if not full_path.exists() or not full_path.is_file():
                continue
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for hp in _INSTALLER_HARDCODED_PATHS:
                if hp in content:
                    findings.append(
                        "rule-005: " + path + " hardcodes '" + hp + "'"
                        + " -- paths must come from CLI args, env vars, or the state file"
                        + " (Core Rule 5.26 / ADR 0013 INV-1)"
                        + "; remedy: replace with a named constant from the canonical"
                        + " default-value module and remove the literal string"
                    )
                    break
    else:
        if not installer_dir.exists():
            return findings
        for py_file in sorted(installer_dir.rglob("*.py")):
            try:
                py_file.relative_to(tests_dir)
                continue
            except ValueError:
                pass
            rel = str(py_file.relative_to(repo))
            if rel in _INSTALLER_PATH_ALLOWLIST:
                continue
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for hp in _INSTALLER_HARDCODED_PATHS:
                if hp in content:
                    findings.append(
                        "rule-005: " + rel + " hardcodes '" + hp + "'"
                        + " -- paths must come from CLI args, env vars, or the state file"
                        + " (Core Rule 5.26 / ADR 0013 INV-1)"
                        + "; remedy: replace with a named constant from the canonical"
                        + " default-value module and remove the literal string"
                    )
                    break
    return findings


def _check_bare_subprocess_run_in_installer(repo, mode):
    """rule-006: installer/ file calls subprocess.run() directly outside _run.py and tests/.

    Enforces Core Rule 5.27 (two-track test coverage): all subprocess calls in
    installer/ must go through installer._run.run_required() so that
    FileNotFoundError -> MissingBinaryError translation is guaranteed.
    installer/_run.py and installer/tests/ are automatically excluded.
    """
    findings = []
    installer_dir = repo / "installer"
    tests_dir = installer_dir / "tests"
    run_py = installer_dir / "_run.py"
    bare_pattern = "subprocess.run("

    if mode == "staged":
        for status, path in _staged_files():
            if not path.startswith("installer/"):
                continue
            try:
                Path(path).relative_to(Path("installer/tests"))
                continue
            except ValueError:
                pass
            if path == "installer/_run.py":
                continue
            full_path = repo / path
            if not full_path.exists() or not full_path.is_file():
                continue
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if bare_pattern in content:
                findings.append(
                    "rule-006: " + path + " calls subprocess.run() directly"
                    + " -- use installer._run.run_required() instead"
                    + " (Core Rule 5.27 / CLASS_A_AUDIT_2026_05_15 C1)"
                    + "; remedy: replace subprocess.run(...) with run_required(...)"
                    + " and remove 'import subprocess'"
                )
    else:
        if not installer_dir.exists():
            return findings
        for py_file in sorted(installer_dir.rglob("*.py")):
            if py_file == run_py:
                continue
            try:
                py_file.relative_to(tests_dir)
                continue
            except ValueError:
                pass
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if bare_pattern in content:
                rel = str(py_file.relative_to(repo))
                findings.append(
                    "rule-006: " + rel + " calls subprocess.run() directly"
                    + " -- use installer._run.run_required() instead"
                    + " (Core Rule 5.27 / CLASS_A_AUDIT_2026_05_15 C1)"
                    + "; remedy: replace subprocess.run(...) with run_required(...)"
                    + " and remove 'import subprocess'"
                )
    return findings


RULES = [
    (
        "rule-001",
        "Loose ADR file at docs/NNNN-*.md (should be under docs/adr/)",
        _check_loose_adr,
        "git mv docs/NNNN-name.md docs/adr/NNNN-name.md",
    ),
    (
        "rule-002",
        "Tracked file under data/<x>/ without !data/<x>/ gitignore exception",
        _check_unignored_data_dir,
        "Add '!data/<x>/' to .gitignore before tracking files in that subdirectory",
    ),
    (
        "rule-003",
        "Canonical doc (CORE_RULES.md, PROJECT_CLEANUP.md) exists at repo root",
        _check_canonical_doc_at_root,
        "Remove repo-root copy; canonical paths are docs/ or docs/cleanup/",
    ),
    (
        "rule-004",
        "Root-owned files/dirs in /tmp/pytest-base/ (test escaped fake_docker)",
        _check_root_owned_pytest_scratch,
        "sudo rm -rf the entry; fix the test to use fake_docker fixture",
    ),
    (
        "rule-005",
        "Installer file hardcodes /opt/mediastack or /var/lib/mediastack outside canonical default-value module",
        _check_installer_hardcoded_paths,
        "Replace literal path with named constant; read from CLI args, env vars, or state file (ADR 0013 INV-1)",
    ),
    (
        "rule-006",
        "Installer file calls subprocess.run() directly outside installer/_run.py and installer/tests/",
        _check_bare_subprocess_run_in_installer,
        "Replace subprocess.run(...) with run_required(...) from installer._run (Core Rule 5.27)",
    ),
]


def run_checks(mode, exclude=None):
    all_findings = []
    for rule_id, desc, check_fn, remedy in RULES:
        if exclude and rule_id in exclude:
            continue
        findings = check_fn(REPO, mode)
        all_findings.extend(findings)
    return all_findings


def main():
    args = sys.argv[1:]
    if not args or "--help" in args:
        print("Usage: tools/check_structural_antipatterns.py [--staged] [--audit]")
        print("  --staged  check staged changes only (pre-commit hook)")
        print("  --audit   scan full repo state (post-deploy / release gate)")
        sys.exit(0)

    mode = "audit" if "--audit" in args else "staged"
    findings = run_checks(mode)

    if not findings:
        if mode == "audit":
            print("Structural audit: clean")
        sys.exit(0)

    print("Structural anti-pattern findings (" + mode + " mode):")
    for f in findings:
        print("  " + f)
    sys.exit(1)


if __name__ == "__main__":
    main()
