#!/usr/bin/env python3
"""stale.py — report ADRs whose Review-by date has passed.

Scans every ``docs/adr/0*.md`` file for a ``**Review by:** YYYY-MM-DD`` line
(or the list-style ``- **Review by:** YYYY-MM-DD`` variant).  Any ADR whose
date is today or earlier is reported as a WARNING to stdout.

Exit status: always 0 (warn-only; does not block CI).

Usage:
    python3 tools/ms-docs/stale.py
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
ADR_DIR = REPO / "docs" / "adr"

# Matches both:
#   **Review by:** 2027-05-08
#   - **Review by:** 2027-05-08
_REVIEW_BY_RE = re.compile(
    r"(?:^-\s+)?\*\*Review by:\*\*\s+(\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)


def check_stale_adrs() -> list[str]:
    today = datetime.date.today()
    warnings: list[str] = []

    if not ADR_DIR.exists():
        print(f"WARNING: ADR directory not found: {ADR_DIR}", file=sys.stderr)
        return warnings

    for path in sorted(ADR_DIR.glob("0*.md")):
        content = path.read_text(encoding="utf-8")
        m = _REVIEW_BY_RE.search(content)
        if not m:
            continue
        try:
            review_date = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            warnings.append(f"WARNING: {path.name}: unparseable Review-by date: {m.group(1)!r}")
            continue
        if review_date <= today:
            warnings.append(
                f"WARNING: {path.name}: Review-by date {review_date} is in the past "
                f"(today is {today}) — this ADR is due for review"
            )

    return warnings


def main() -> None:
    warnings = check_stale_adrs()
    if warnings:
        for w in warnings:
            print(w)
    else:
        print("OK: no stale ADRs")
    sys.exit(0)


if __name__ == "__main__":
    main()
