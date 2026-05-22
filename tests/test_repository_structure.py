"""Repository structure invariant tests.

Step 1.1.c: gitignore data/ pattern enforcement
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _tracked_data_subdirs():
    """Return top-level subdirectory names under data/ that have tracked files."""
    result = subprocess.run(
        ["git", "ls-files", "data/"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    dirs = set()
    for line in result.stdout.splitlines():
        parts = line.split("/")
        if len(parts) >= 2:
            dirs.add(parts[1])
    return dirs


def _gitignore_data_exceptions():
    """Return subdirectory names with explicit !data/<x>/ exceptions in .gitignore."""
    gitignore = REPO / ".gitignore"
    exceptions = set()
    for line in gitignore.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("!data/") and stripped.endswith("/"):
            name = stripped[len("!data/"):-1]
            exceptions.add(name)
    return exceptions


class TestGitignoreDataPattern:
    def test_tracked_data_subdirs_have_exceptions(self):
        """Every tracked data/ subdirectory must have a !data/<x>/ exception in .gitignore."""
        tracked = _tracked_data_subdirs()
        exceptions = _gitignore_data_exceptions()
        missing = tracked - exceptions
        assert not missing, (
            "Tracked files under data/ but no !data/<x>/ exception in .gitignore: "
            + ", ".join(sorted("data/" + d + "/" for d in missing))
            + " -- add the exception before tracking files in this directory"
        )

class TestCanonicalDocumentPaths:
    """Step 1.3.a: canonical document locations must not have stray copies."""

    def test_core_rules_not_at_repo_root(self):
        """CORE_RULES.md must exist only at docs/CORE_RULES.md, not at repo root."""
        stray = list(REPO.glob("CORE_RULES.md"))
        assert not stray, (
            "CORE_RULES.md found at repo root -- "
            "canonical location is docs/CORE_RULES.md; remove the stray copy"
        )

    def test_adr_files_only_under_docs_adr(self):
        """ADR files (NNNN-*.md) must live under docs/adr/, not loose in docs/."""
        import re
        adr_pattern = re.compile(r"^\d{4}-.*\.md$")
        stray = [
            p for p in (REPO / "docs").glob("*.md")
            if adr_pattern.match(p.name)
        ]
        assert not stray, (
            "ADR files found loose in docs/ (should be in docs/adr/): "
            + ", ".join(str(p.relative_to(REPO)) for p in sorted(stray))
        )

    def test_project_cleanup_not_at_repo_root(self):
        """PROJECT_CLEANUP.md must exist only at docs/cleanup/PROJECT_CLEANUP.md."""
        stray = list(REPO.glob("PROJECT_CLEANUP.md"))
        assert not stray, (
            "PROJECT_CLEANUP.md found at repo root -- "
            "canonical location is docs/cleanup/PROJECT_CLEANUP.md; remove the stray copy"
        )
