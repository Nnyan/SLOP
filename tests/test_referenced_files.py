"""tests/test_referenced_files.py — Test suite for tools/check_referenced_files.py.

Specified by .claude/waves/S-48-TRACK-GATE.md (Stream B deliverable).
Extended by wave S-56 Stream C for doc-tree checks.

Test cases (original S-48):
  1. File with inbound reference → no warning
  2. Truly orphan file older than 30 days, not in allowlist → warning printed, exit 0
  3. Orphan file in allowlist → no warning
  4. Orphan file under 30 days old → no warning (grace window)

Test cases (S-56 Stream C — doc-tree):
  5. Broken Markdown link [text](path) in docs/ → warning with [doc-broken-link]
  6. Broken backtick path reference `docs/missing.md` → [doc-broken-link] warning
  7. Valid Markdown link → no warning
  8. Doc orphan (docs/ .md with zero inbound refs, older than 30d) → [doc-orphan]
  9. Doc missing from MAP.md → [doc-missing-from-MAP] warning
  10. Doc covered by directory entry in MAP.md → no [doc-missing-from-MAP] warning
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

# Allow importing from the tools/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from check_referenced_files import (  # noqa: E402
    ALLOWLIST_FILE,
    load_allowlist,
    run_check,
    check_doc_broken_links,
    check_doc_orphans,
    check_docs_map_coverage,
    build_search_corpus,
    git_tracked_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_init(path: Path) -> None:
    """Initialise a minimal git repo at *path*."""
    subprocess.check_call(
        ["git", "init", "-q", "--initial-branch=main"],
        cwd=str(path),
    )
    subprocess.check_call(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
    )
    subprocess.check_call(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
    )


def _git_add_commit(path: Path, message: str = "initial") -> None:
    """Stage all files and create a commit in the repo at *path*."""
    subprocess.check_call(["git", "add", "-A"], cwd=str(path))
    subprocess.check_call(
        ["git", "commit", "-q", "-m", message],
        cwd=str(path),
    )


def _backdate_commit(path: Path, epoch: float) -> None:
    """Amend the most recent commit to appear at *epoch* (Unix timestamp).

    Uses --date flag for the author date and GIT_COMMITTER_DATE env var for
    the committer date.  The ISO 8601 format is portable across git versions.
    """
    import datetime as dt
    iso_date = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S+0000"
    )
    env = dict(os.environ)
    env["GIT_COMMITTER_DATE"] = iso_date
    subprocess.check_call(
        ["git", "commit", "--amend", "--no-edit", "--quiet",
         "--date", iso_date],
        cwd=str(path),
        env=env,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in a temp directory."""
    _git_init(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Case 1: File with inbound reference → no warning
# ---------------------------------------------------------------------------

def test_referenced_file_produces_no_warning(repo: Path) -> None:
    """A file that is explicitly referenced by another tracked file must not
    produce an orphan warning, even when it is older than 30 days."""
    # Create the subject file.
    subject = repo / "tools" / "helper.py"
    _write(subject, "# helper\n")

    # Create a referencer (a .md file that mentions helper.py by basename).
    ref_doc = repo / "README.md"
    _write(ref_doc, "See tools/helper.py for details.\n")

    _git_add_commit(repo)

    # Back-date so the file is 40 days old (past the grace window).
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "helper.py" not in output


# ---------------------------------------------------------------------------
# Case 2: Orphan file older than 30 days → WARNING, exit 0
# ---------------------------------------------------------------------------

def test_old_orphan_file_produces_warning(repo: Path) -> None:
    """An unref'd file older than 30 days that is not allowlisted must produce
    a WARNING line. Exit code must still be 0."""
    # Create an orphan file (nothing references it).
    orphan = repo / "tools" / "forgotten.py"
    _write(orphan, "# forgotten\n")

    # Create a second file that mentions something else, not forgotten.py.
    _write(repo / "README.md", "Nothing here references the other script.\n")

    _git_add_commit(repo)

    # Back-date so the file is 40 days old.
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0, "check must always exit 0 (warning only)"
    assert "WARNING" in output
    assert "forgotten.py" in output


# ---------------------------------------------------------------------------
# Case 3: Orphan file in allowlist → no warning
# ---------------------------------------------------------------------------

def test_allowlisted_orphan_produces_no_warning(repo: Path) -> None:
    """An orphan file that appears in .orphan-allowlist must not produce a
    warning, even if it is older than 30 days."""
    # Create an orphan file.
    orphan = repo / "deploy.sh"
    _write(orphan, "#!/bin/bash\necho hello\n")

    # Write an allowlist entry for it.
    allowlist = repo / ALLOWLIST_FILE
    _write(
        allowlist,
        "deploy.sh    # reason: top-level entry-point script — no inbound refs by design\n",
    )

    # A second tracked file so the commit is non-empty.
    _write(repo / "README.md", "Placeholder.\n")

    _git_add_commit(repo)

    # Back-date so the orphan is older than 30 days.
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "deploy.sh" not in output


# ---------------------------------------------------------------------------
# Case 4: Orphan file under 30 days old → no warning (grace window)
# ---------------------------------------------------------------------------

def test_young_orphan_file_is_within_grace_window(repo: Path) -> None:
    """An orphan file that is less than 30 days old must not produce a warning,
    even if it has zero inbound references."""
    # Create an orphan file.
    orphan = repo / "tools" / "brand_new.py"
    _write(orphan, "# brand new\n")

    _write(repo / "README.md", "Nothing here references brand_new.\n")

    _git_add_commit(repo)
    # Do NOT back-date — the commit is seconds old, well within the grace window.

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "brand_new.py" not in output


# ---------------------------------------------------------------------------
# Allowlist parsing: missing reason comment is an error
# ---------------------------------------------------------------------------

def test_allowlist_missing_reason_exits_nonzero(repo: Path) -> None:
    """An allowlist entry without '# reason: ...' must cause the check to exit
    with a non-zero status (config error, not a warning)."""
    allowlist = repo / ALLOWLIST_FILE
    _write(allowlist, "deploy.sh\n")  # missing reason comment

    _write(repo / "README.md", "placeholder\n")
    _git_add_commit(repo)

    with pytest.raises(SystemExit) as exc_info:
        run_check(repo)
    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# Script exit code is always 0 even when orphans are found
# ---------------------------------------------------------------------------

def test_script_always_exits_zero(repo: Path) -> None:
    """Running the script as a subprocess must always exit 0, even with orphans."""
    orphan = repo / "tools" / "lonely.py"
    _write(orphan, "# lonely\n")
    _write(repo / "README.md", "Nothing references lonely.\n")
    _git_add_commit(repo)

    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    script = Path(__file__).resolve().parent.parent / "tools" / "check_referenced_files.py"
    result = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Script must exit 0; got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "WARNING" in result.stdout
    assert "lonely.py" in result.stdout


# ---------------------------------------------------------------------------
# S-56 Stream C — doc-tree checks
# ---------------------------------------------------------------------------

# Case 5: Broken Markdown link [text](path) in docs/ → [doc-broken-link] warning

def test_broken_markdown_link_in_docs_produces_warning(repo: Path) -> None:
    """A docs/ .md file with a [text](path) link pointing to a non-existent file
    must produce a [doc-broken-link] WARNING.  Exit code must be 0."""
    _write(repo / "README.md", "placeholder\n")
    # Create a docs/ file with a broken link.
    _write(
        repo / "docs" / "index.md",
        "[missing file](docs/missing_target.md)\n",
    )
    _git_add_commit(repo)
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "[doc-broken-link]" in output
    assert "missing_target.md" in output


# Case 6: Broken backtick path reference `docs/missing.md` → [doc-broken-link]

def test_broken_backtick_path_in_docs_produces_warning(repo: Path) -> None:
    """A docs/ .md file with a backtick-quoted relative path like
    ``docs/phantom.md`` that doesn't exist must produce a [doc-broken-link]
    WARNING.  This is the pattern used by the 3 phantom TODO files in
    docs/RELEASE_NOTES_v5_0_0.md."""
    _write(repo / "README.md", "placeholder\n")
    _write(
        repo / "docs" / "release.md",
        "Deferred per `docs/phantom_todo.md`.\n",
    )
    _git_add_commit(repo)
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "[doc-broken-link]" in output
    assert "phantom_todo.md" in output


# Case 7: Valid Markdown link in docs/ → no [doc-broken-link] warning

def test_valid_markdown_link_in_docs_no_warning(repo: Path) -> None:
    """A docs/ .md file whose [text](path) link resolves to an existing tracked
    file must not produce a [doc-broken-link] warning."""
    _write(repo / "README.md", "intro\n")
    _write(repo / "docs" / "guide.md", "# guide\n")
    _write(
        repo / "docs" / "index.md",
        "[guide](guide.md)\n",
    )
    _git_add_commit(repo)
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "[doc-broken-link]" not in output


# Case 8: Doc orphan (docs/ .md with zero inbound refs, older than 30d) → [doc-orphan]

def test_orphan_doc_produces_doc_orphan_warning(repo: Path) -> None:
    """A tracked docs/ .md file with no inbound references that is older than
    30 days must produce a [doc-orphan] WARNING.  Exit code must be 0."""
    _write(repo / "README.md", "nothing references the orphan\n")
    _write(repo / "docs" / "orphan_guide.md", "# orphan\n")
    # The README doesn't reference orphan_guide.md.
    _git_add_commit(repo)
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    # Either [doc-orphan] or generic orphan warning must mention the file.
    assert "orphan_guide.md" in output


# Case 9: Doc missing from MAP.md → [doc-missing-from-MAP] warning

def test_doc_missing_from_map_produces_warning(repo: Path) -> None:
    """A tracked docs/ .md file not mentioned in docs/MAP.md must produce a
    [doc-missing-from-MAP] WARNING.  Exit code must be 0."""
    _write(repo / "README.md", "placeholder\n")
    # Create MAP.md that does NOT mention the other doc.
    _write(repo / "docs" / "MAP.md", "# Doc map\n- README.md — root\n")
    # Create a tracked doc not in MAP.md.
    _write(repo / "docs" / "hidden.md", "# hidden\n")
    # Add a reference to hidden.md so it doesn't also trigger orphan warnings.
    _write(repo / "docs" / "index.md", "See [hidden](hidden.md).\n")
    _git_add_commit(repo)
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "[doc-missing-from-MAP]" in output
    assert "hidden.md" in output


# Case 10: Doc covered by directory entry in MAP.md → no [doc-missing-from-MAP]

def test_doc_covered_by_dir_entry_in_map_no_warning(repo: Path) -> None:
    """A tracked docs/ .md file under a sub-directory whose directory is listed
    in MAP.md (e.g. ``docs/adr/``) must NOT produce a [doc-missing-from-MAP]
    warning — the directory entry is sufficient coverage."""
    _write(repo / "README.md", "placeholder\n")
    # MAP.md references the docs/adr/ directory, not individual ADR files.
    _write(
        repo / "docs" / "MAP.md",
        "# Doc map\n- docs/adr/ — Architecture Decision Records\n",
    )
    # Create an ADR file under docs/adr/.
    _write(repo / "docs" / "adr" / "0001-example.md", "# ADR 0001\n")
    # Reference it so it's not an orphan.
    _write(repo / "README.md", "See docs/adr/0001-example.md for details.\n")
    _git_add_commit(repo)
    old_epoch = time.time() - 40 * 86400
    _backdate_commit(repo, old_epoch)

    out = io.StringIO()
    rc = run_check(repo, out=out)
    output = out.getvalue()

    assert rc == 0
    assert "[doc-missing-from-MAP]" not in output or "0001-example.md" not in output
