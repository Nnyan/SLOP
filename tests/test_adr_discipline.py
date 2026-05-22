"""tests/test_adr_discipline.py — ADR convention tests (step 2.5.d).

Per Core Rule 4.15, architectural decisions live in `docs/adr/` as
numbered Markdown files. These tests verify the convention is followed:

  - The template exists and has the expected sections.
  - Existing ADRs are numbered sequentially with no gaps.
  - Each ADR has the four required sections (Context / Decision /
    Consequences / Status).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADR_DIR = REPO / "docs" / "adr"


def test_adr_template_exists() -> None:
    """The template that documents the ADR shape is in the directory."""
    template = ADR_DIR / "template.md"
    assert template.exists(), \
        f"docs/adr/template.md must exist (Core Rule 4.15)"
    content = template.read_text()
    # The template's own sections — readers copy these
    for header in ("## Context", "## Decision", "## Consequences", "## Status"):
        assert header in content, f"template missing section: {header}"


def test_adr_numbering_is_sequential() -> None:
    """Numbered ADRs (`NNNN-*.md`) are sequential with no gaps."""
    pattern = re.compile(r"^(\d{4})-.*\.md$")
    numbers = []
    for path in ADR_DIR.glob("*.md"):
        if path.name == "template.md":
            continue
        m = pattern.match(path.name)
        assert m, f"ADR filename must match NNNN-slug.md: {path.name}"
        numbers.append(int(m.group(1)))

    if not numbers:
        return  # no ADRs yet — vacuously OK
    numbers.sort()
    expected = list(range(1, len(numbers) + 1))
    assert numbers == expected, \
        f"ADR numbers must be sequential 0001..N with no gaps; got {numbers}"


def test_each_adr_has_required_sections() -> None:
    """Every numbered ADR has the 4 required sections from the template."""
    required = ("## Context", "## Decision", "## Consequences", "## Status")
    pattern = re.compile(r"^\d{4}-.*\.md$")
    for path in ADR_DIR.glob("*.md"):
        if not pattern.match(path.name):
            continue
        content = path.read_text()
        missing = [s for s in required if s not in content]
        assert not missing, \
            f"{path.name} missing sections: {missing} (Core Rule 4.15)"


def test_each_adr_declares_status_value() -> None:
    """Each ADR has a `Status:` field with a known value at the top."""
    valid = {"Proposed", "Accepted", "Superseded", "Deprecated"}
    pattern = re.compile(r"^\d{4}-.*\.md$")
    status_re = re.compile(
        r"\*\*Status:\*\*\s*(Proposed|Accepted|Superseded|Deprecated)"
    )
    for path in ADR_DIR.glob("*.md"):
        if not pattern.match(path.name):
            continue
        content = path.read_text()
        m = status_re.search(content)
        assert m, f"{path.name} missing **Status:** Proposed|Accepted|..."
        assert m.group(1) in valid, \
            f"{path.name} has invalid status: {m.group(1)}"
