#!/usr/bin/env python3
"""check_xfail_age.py — flag stale pytest.mark.xfail marks without an issue link.

Scans ``tests/`` recursively for every ``pytest.mark.xfail(...)`` call (used as
a decorator OR inside ``pytest.param(..., marks=...)``) and asks ``git blame``
when the line was introduced. A mark is flagged when:

  * age > 30 days, AND
  * the ``reason`` kwarg does not contain a ``github.com/<owner>/<repo>/issues/<n>`` URL.

Exit status: 0 = clean, 1 = at least one violation.

Output format:
  <file>:<line> -- xfail age <N>d, no issue link: "<reason>"

Background: see AUDIT-S-29. An xfail(strict=True) sat in test_api_smoke.py for
weeks silencing a known NameError instead of surfacing it.
"""

from __future__ import annotations

import ast
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

MAX_AGE_DAYS = 30
ISSUE_LINK_RE = re.compile(r"github\.com/[^/\s]+/[^/\s]+/issues/\d+")


def repo_root(start: Path) -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=start, check=True,
    )
    return Path(out.stdout.strip())


def is_xfail_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "xfail"):
        return False
    mark = func.value
    if not (isinstance(mark, ast.Attribute) and mark.attr == "mark"):
        return False
    pytest_name = mark.value
    return isinstance(pytest_name, ast.Name) and pytest_name.id == "pytest"


def extract_reason(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return ""


def find_xfail_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if is_xfail_call(node):
            yield node.lineno, node


def git_blame_time(file: Path, lineno: int, root: Path) -> int | None:
    rel = file.relative_to(root)
    res = subprocess.run(
        ["git", "blame", "--porcelain", "-L", f"{lineno},{lineno}", str(rel)],
        capture_output=True, text=True, cwd=root,
    )
    if res.returncode != 0:
        return None
    for line in res.stdout.splitlines():
        if line.startswith("author-time "):
            return int(line.split()[1])
    return None


def main() -> int:
    root = repo_root(Path.cwd())
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        print(f"check_xfail_age: no tests/ dir at {tests_dir}", file=sys.stderr)
        return 0

    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    violations = 0

    for path in sorted(tests_dir.rglob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for lineno, call in find_xfail_calls(tree):
            reason = extract_reason(call)
            if ISSUE_LINK_RE.search(reason):
                continue
            ts = git_blame_time(path, lineno, root)
            if ts is None:
                continue
            age_days = (now - ts) // 86400
            if age_days <= MAX_AGE_DAYS:
                continue
            rel = path.relative_to(root)
            print(f'{rel}:{lineno} -- xfail age {age_days}d, no issue link: "{reason}"')
            violations += 1

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
