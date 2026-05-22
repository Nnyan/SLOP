"""tests/test_cli_snapshots.py

Step 2.8 — CLI snapshot targets follow-up.

Step 2.1's seed implementation locked in two API-shape snapshots and
deferred three CLI banner/summary snapshots because each needs a
subprocess-runner fixture with path/timestamp/SHA redaction. This
module is the follow-up — the three tools surfaced in
`docs/cleanup/STEP_2_1_SNAPSHOT_STRATEGY.md` get their stable
output forms locked in.

Targets:

    1. `ms-update --help` banner — argparse-equivalent help block
    2. `ms-test.py --help`     — argparse-generated help block
    3. `ms-enforce --list`     — active Core Rules listing

Each tool's --help / --list output is intentionally low-volatility
content (no timestamps, no SHAs, no environment-dependent paths).
We still scrub aggressively because:

  - some tools include a Python interpreter path ("python3.13") in
    argparse usage lines depending on PATH ordering;
  - terminal-width detection alters argparse line-wrap;
  - ANSI colour escapes get emitted when stdout is a TTY but not a
    pipe — the runner forces NO_COLOR=1 to keep this deterministic.

When a CLI's output legitimately changes (new flag, new rule, etc.),
regenerate snapshots with:

    pytest tests/test_cli_snapshots.py --snapshot-update

then commit the source change AND the snapshot diff together.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── Subprocess runner fixture (step 2.8.a) ────────────────────────────────


_REDACTIONS: tuple[tuple[str, str], ...] = (
    # Absolute /tmp paths (vary per test run)
    (r"/tmp/[A-Za-z0-9_\-/.]+", "<TMP-PATH>"),
    # Absolute repo paths anchored at any prefix
    (r"/srv/mediastack(?=[^A-Za-z0-9_])", "<REPO>"),
    (r"/home/[A-Za-z0-9_\-]+/code/mediastack(?=[^A-Za-z0-9_])", "<REPO>"),
    # ISO-8601 timestamps (date-only or full)
    (r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:?\d{2})?",
     "<ISO-TIMESTAMP>"),
    (r"\b\d{4}-\d{2}-\d{2}\b", "<ISO-DATE>"),
    # 24-hour clock
    (r"\b\d{2}:\d{2}(?::\d{2})?\b", "<HH:MM>"),
    # 7+ char hex blobs (git SHAs)
    (r"\b[a-f0-9]{7,40}\b", "<SHA>"),
    # Specific Python interpreter path that argparse may embed
    (r"/[^\s]+/python3(?:\.\d+)?\b", "<PYTHON>"),
    (r"\bpython3\.\d+\b", "<PYTHON>"),
    # ANSI escape sequences (defence-in-depth even with NO_COLOR=1)
    (r"\x1b\[[0-9;]*[A-Za-z]", ""),
)


def _redact(text: str) -> str:
    for pat, repl in _REDACTIONS:
        text = re.sub(pat, repl, text)
    return text


@pytest.fixture
def cli_runner():
    """Return a callable that runs `ms-<tool>` with controlled env +
    redaction. Default args: ('--help',). Custom args via the second
    positional argument.

    The callable returns the redacted stdout (string). Stderr + return
    code are ignored — these tests assert on the formatted banner /
    listing only, not on exit semantics.
    """

    def _run(tool: str, args: tuple[str, ...] = ("--help",)) -> str:
        # Bash scripts launch via bash; Python via the same interpreter
        # the test runs in. NO_COLOR=1 + COLUMNS=80 stabilises layout.
        path = REPO / tool
        is_python = path.read_bytes()[:2] == b"#!" and b"python" in path.read_bytes()[:64]
        cmd = [sys.executable, str(path), *args] if is_python else ["bash", str(path), *args]
        env = {
            "NO_COLOR": "1",
            "COLUMNS": "80",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp/cli-snapshot-home",
            "TERM": "dumb",
        }
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, env=env, cwd=str(REPO),
        )
        return _redact(result.stdout + result.stderr)

    return _run


# ── 2.8.b: ms-update banner snapshot ──────────────────────────────────────


def test_ms_update_help_banner(cli_runner, snapshot) -> None:
    """The `ms-update --help` banner is a four-line user-facing summary
    that operators see when they forget a flag. The exact wording is
    part of the operator UX contract — changes need a snapshot update."""
    output = cli_runner("ms-update")
    assert output == snapshot


# ── 2.8.c: ms-test summary block snapshot ─────────────────────────────────


def test_ms_test_help_block(cli_runner, snapshot) -> None:
    """`python3 ms-test.py --help` is argparse-generated; its shape pins
    the public CLI surface (flag names, defaults, help text). Volatile
    bits redacted: Python interpreter path, terminal width."""
    output = cli_runner("ms-test.py")
    assert output == snapshot


# ── 2.8.d: ms-enforce --list snapshot (machine-readable rules) ────────────


def test_ms_enforce_list_rules(cli_runner, snapshot) -> None:
    """`python3 ms-enforce --list` enumerates active Core Rules. The list
    grows as Tier 4 lands; each addition needs a paired snapshot update,
    which doubles as a sanity check that the new rule reached the
    coverage map (`data/coverage_map.json`).

    If `data/coverage_map.json` is missing in the test environment,
    --list emits a "Coverage map not found" message — that's also a
    stable shape we want to lock so CI vs local-dev parity is enforced.
    """
    output = cli_runner("ms-enforce", ("--list",))
    assert output == snapshot
