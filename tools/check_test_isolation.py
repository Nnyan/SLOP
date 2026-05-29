#!/usr/bin/env python3
"""check_test_isolation — warn-only test-data-isolation scanner (S-71 Stream C).

Flags test files that appear to WRITE outside ``tmp_path`` or mutate real,
committed repository files. Backs the warn-only ms-enforce gate
``check_test_isolation`` (mirrors ``check_referenced_files``: collects
``WARNING``-prefixed lines, never blocks CI). The canonical policy this gate
mechanically backstops is ``docs/adr/0019-test-data-isolation.md`` (Stream A).

Output format (one per finding)::

    WARNING [test-isolation] <file>:<line> <reason>

Exit code is ALWAYS 0 — this scanner is warning-only, never blocking.

Heuristic (deliberately CONSERVATIVE — AST-based, not regex)
============================================================
A finding fires only on a *write* whose target is a **string literal** that is
NOT rooted under ``tmp_path`` / ``tmp_path_factory`` / a system temp dir, OR on
a write to a path the policy names as a real shared artifact (``docs/``,
``.claude/settings.local.json``, ``requirements*``). Specifically it flags:

  1. ``open(<str-literal>, "w"|"a"|"x"|"wb"|...)`` — a write-mode open of a
     hard-coded path string.
  2. ``Path(<str-literal>).write_text(...)`` / ``.write_bytes(...)`` — a write
     to a hard-coded path string.
  3. A write (open-for-write, write_text/bytes, mkdir, unlink, rmtree, copy,
     remove) whose literal-string target contains a real-tree shared marker:
     ``docs/``, ``.claude/settings.local.json``, or ``requirements`` with a
     ``.txt`` suffix.

The unit of judgment is "is the destination a *literal* that names the real
tree?" — because in this suite essentially every legitimate write targets a
*variable* (``tmp_path / "x"``, a fixture like ``cfg_dir`` / ``docs`` / ``path``
that is itself rooted under ``tmp_path``). Restricting to literals is what keeps
the gate from flooding on day one (the aging problem: a gate that warns on every
legitimate fixture write gets muted and stops catching real offenders).

False-positive classes DELIBERATELY EXCLUDED (and why)
======================================================
- **Reading a fixture / real file is fine.** ``open(p)`` / ``open(p, "r")`` /
  ``Path(...).read_text()`` / ``.exists()`` are never flagged. Many meta-tests
  legitimately *read or assert existence of* real repo files (e.g.
  ``assert Path("docs/ARCHITECTURE.md").exists()`` in test_recommendations.py,
  ``Path("requirements.txt").read_text()`` in test_deploy_tooling.py). Those do
  not pollute state; flagging them would drown the signal. Only WRITE modes
  (``w/a/x/+`` and the mutating ``Path``/``os``/``shutil`` calls) fire.
- **Building a path STRING that is later joined under tmp_path is fine.** A bare
  string like ``"docs/MERGE-LOG.md"`` passed as a *commit-message argument* or
  joined onto a ``tmp_path``-rooted repo (``repo / "docs/MERGE-LOG.md"``) is not
  a write target literal — the receiver of the write call is a *variable*, so it
  is not flagged. We only look at the literal that is the *direct* argument to a
  write call (``open("literal","w")`` / ``Path("literal").write_text(...)``).
- **Variable / fixture-rooted writes are fine.** ``cfg_dir.write_text(...)``,
  ``(tmp_path / "x").write_text(...)``, ``(docs / "BACKLOG.md").write_text(...)``
  where ``docs = tmp_path / "docs"`` — the write receiver is a Name/BinOp, not a
  string literal, so it is not flagged.
- **monkeypatch / env-redirect cases are fine.** A test that sets
  ``SLOP_AUDIT_LOG_PATH`` (Stream B's redirect convention) and then lets a tool
  write the audit log is writing to the redirected tmp path, not the real
  ``docs/SANCTIONED-OPS-LOG.md`` — there is no literal real-tree write call in
  the test body, so nothing fires. (We additionally suppress any finding in a
  file that sets ``SLOP_AUDIT_LOG_PATH`` for the SANCTIONED-OPS-LOG marker
  specifically, to stay conservative about the redirect convention.)
- **String literals inside the scanner's own docstrings/comments** never fire —
  this is AST-based, so only real call expressions are inspected.

Usage
-----
  python3 tools/check_test_isolation.py            # scan tests/ under repo root
  python3 tools/check_test_isolation.py --repo /path/to/repo
  python3 tools/check_test_isolation.py --tests-dir /path/to/tests
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# open() modes that mutate the target. Any mode containing one of these chars
# (other than a lone "r"/"rb") writes.
_WRITE_MODE_CHARS = frozenset("wax+")

# Path methods on a literal-Path(...) receiver that mutate the filesystem.
_PATH_WRITE_METHODS = frozenset(
    {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir"}
)

# os / shutil functions that mutate, when called with a literal path arg.
_MODULE_WRITE_FUNCS = {
    "shutil": frozenset({"copy", "copy2", "copyfile", "move", "rmtree"}),
    "os": frozenset({"remove", "unlink", "mkdir", "makedirs", "rmdir"}),
}

# Substrings in a literal path that mark the real, committed tree. A write to a
# literal containing one of these is flagged even if it wouldn't otherwise be
# (belt-and-suspenders for the policy's named artifacts).
_REAL_TREE_MARKERS = (
    "docs/",
    ".claude/settings.local.json",
)

# Tmp-rooted prefixes that make a literal safe (rare, but explicit).
_TMP_SAFE_PREFIXES = ("/tmp/", "/var/tmp/")

# The env redirect convention owned by Stream B. A file that opts into it is
# trusted for the SANCTIONED-OPS-LOG marker specifically.
_AUDIT_REDIRECT_ENV = "SLOP_AUDIT_LOG_PATH"


def _str_literal(node: ast.AST) -> str | None:
    """Return the value if *node* is a plain string constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_real_tree_literal(value: str) -> bool:
    if value.startswith(_TMP_SAFE_PREFIXES):
        return False
    if any(marker in value for marker in _REAL_TREE_MARKERS):
        return True
    # requirements*.txt at a non-tmp location
    base = value.rsplit("/", 1)[-1]
    if base.startswith("requirements") and base.endswith(".txt"):
        return True
    return False


def _open_is_write(call: ast.Call) -> bool:
    """True if an open()/Path.open() call uses a write mode."""
    mode = None
    # positional mode is arg index 1 for builtin open, index 0 for Path.open
    # Be permissive: scan all positional string args + the `mode=` kw.
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = _str_literal(kw.value)
    if mode is None:
        for arg in call.args:
            s = _str_literal(arg)
            if s is not None and (set(s) & _WRITE_MODE_CHARS):
                # Looks like a mode string (short, mode-char only-ish).
                if len(s) <= 4 and set(s) <= set("rwaxb+t"):
                    mode = s
                    break
    if mode is None:
        return False
    return bool(set(mode) & _WRITE_MODE_CHARS)


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, redirect_optin: bool) -> None:
        self.rel_path = rel_path
        self.redirect_optin = redirect_optin
        self.findings: list[tuple[int, str]] = []

    def _flag(self, lineno: int, reason: str, literal: str) -> None:
        # Conservative redirect suppression: if the file opts into the audit
        # redirect convention, do not flag the SANCTIONED-OPS-LOG literal.
        if self.redirect_optin and "SANCTIONED-OPS-LOG" in literal:
            return
        self.findings.append((lineno, reason))

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self._check_open(node)
        self._check_path_method(node)
        self._check_module_func(node)
        self.generic_visit(node)

    # --- open("literal", "w") -------------------------------------------
    def _check_open(self, node: ast.Call) -> None:
        is_open = (isinstance(node.func, ast.Name) and node.func.id == "open")
        is_path_open = (
            isinstance(node.func, ast.Attribute) and node.func.attr == "open"
        )
        if not (is_open or is_path_open):
            return
        if not node.args:
            return
        target = _str_literal(node.args[0]) if is_open else None
        # Path(...).open(...) literal target handled by _check_path_method via
        # receiver inspection; here we only handle builtin open() with a literal.
        if target is None:
            return
        if not _open_is_write(node):
            return
        if not _real_or_nontmp(target):
            return
        self._flag(
            node.lineno,
            f"open() write-mode on literal path '{target}' "
            "(not derived from tmp_path)",
            target,
        )

    # --- Path("literal").write_text(...) / .mkdir() / ... ----------------
    def _check_path_method(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        if node.func.attr not in _PATH_WRITE_METHODS:
            return
        recv = node.func.value
        literal = _literal_path_of_receiver(recv)
        if literal is None:
            return
        if not _real_or_nontmp(literal):
            return
        self._flag(
            node.lineno,
            f"Path('{literal}').{node.func.attr}(...) writes a literal path "
            "(not derived from tmp_path)",
            literal,
        )

    # --- shutil.copy("literal", ...) / os.remove("literal") --------------
    def _check_module_func(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Attribute):
            return
        recv = node.func.value
        if not isinstance(recv, ast.Name):
            return
        funcs = _MODULE_WRITE_FUNCS.get(recv.id)
        if not funcs or node.func.attr not in funcs:
            return
        for arg in node.args:
            literal = _str_literal(arg)
            if literal is not None and _real_or_nontmp(literal):
                self._flag(
                    node.lineno,
                    f"{recv.id}.{node.func.attr}('{literal}') mutates a literal "
                    "real-tree path (not derived from tmp_path)",
                    literal,
                )
                return


def _literal_path_of_receiver(node: ast.AST) -> str | None:
    """If *node* is ``Path("literal")`` (or ``pathlib.Path("literal")``),
    return the literal; else None. A receiver that is a Name/BinOp/etc. (i.e.
    a variable or tmp_path-joined expression) returns None — and is NOT flagged.
    """
    if isinstance(node, ast.Call):
        f = node.func
        is_path_ctor = (
            (isinstance(f, ast.Name) and f.id == "Path")
            or (isinstance(f, ast.Attribute) and f.attr == "Path")
        )
        if is_path_ctor and node.args:
            return _str_literal(node.args[0])
    return None


def _real_or_nontmp(value: str) -> bool:
    """A literal is flag-worthy if it names the real tree OR is a relative
    repo-ish path that is plainly not a tmp path. We stay conservative: only
    real-tree markers (docs/, settings.local.json, requirements*.txt) qualify.
    Absolute non-tmp paths are NOT flagged (could be intentional system fixtures
    the author owns); the policy's concern is the *committed repo* tree.
    """
    return _is_real_tree_literal(value)


def _scan_file(path: Path, rel: str) -> list[tuple[int, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    redirect_optin = _AUDIT_REDIRECT_ENV in src
    v = _Visitor(rel, redirect_optin)
    v.visit(tree)
    return sorted(set(v.findings))


def scan(tests_dir: Path, repo: Path) -> list[str]:
    warnings: list[str] = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        try:
            rel = str(path.relative_to(repo))
        except ValueError:
            rel = str(path)
        for lineno, reason in _scan_file(path, rel):
            warnings.append(f"WARNING [test-isolation] {rel}:{lineno} {reason}")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="repo root (default: tool's parent)")
    parser.add_argument("--tests-dir", default=None, help="tests dir (default: <repo>/tests)")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parent.parent
    tests_dir = Path(args.tests_dir).resolve() if args.tests_dir else repo / "tests"

    if not tests_dir.is_dir():
        # Nothing to scan — warn-only, exit clean.
        return 0

    for line in scan(tests_dir, repo):
        print(line)
    return 0  # always 0 — warn-only.


if __name__ == "__main__":
    sys.exit(main())
