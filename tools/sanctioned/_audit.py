"""
tools/sanctioned/_audit.py — Sanctioned-ops audit writer (S-68 Stream B).

Public contract (PINNED — downstream C/D/E import exactly these symbols):

    SANCTIONED_OPS_LOG: Path
        Path to docs/SANCTIONED-OPS-LOG.md, relative to the repo root.

    write_entry(
        *,
        tool: str,
        op: str,
        pre_sha: str | None,
        post_sha: str | None,
        result: str,
        notes: str,
        caller: str | None = None,
        timestamp: str | None = None,
        log_path: Path = SANCTIONED_OPS_LOG,
    ) -> None
        Prepend a structured Markdown audit entry (newest at top).
        Creates the file with a header block if absent.
        caller defaults to $USER (or $USERNAME on Windows).
        timestamp defaults to UTC now (ISO-8601 with Z suffix).

All stdlib — no external dependencies.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

# ── public constants ──────────────────────────────────────────────────────────

SANCTIONED_OPS_LOG: Path = Path("docs/SANCTIONED-OPS-LOG.md")

# ── header written when the file is created for the first time ────────────────

_FILE_HEADER = """\
# Sanctioned-Ops Log

Audit trail for every sanctioned tool operation that is NOT a wave merge
(merge ops continue to write to `docs/MERGE-LOG.md`).  Each entry records
the tool, the operation performed, the pre/post state SHA (if applicable),
the result, the caller, and any explanatory notes.

**Why this log exists:** the sanctioned-channel toolkit (`tools/sanctioned/`)
gives every recurring deny-list workaround a single blessed code path with a
mandatory `try/finally` lift-restore.  This file is the tamper-evident receipt
for every such operation — so any lift that occurred during a session can be
audited after the fact.

**Entry format:**

```
## YYYY-MM-DDTHH:MM:SSZ — <tool>: <op>

- **Tool:** <tool>
- **Op:** <op>
- **Pre-SHA:** <sha | n/a>
- **Post-SHA:** <sha | n/a>
- **Result:** <result>
- **Caller:** <caller>
- **Notes:** <notes>
```

**Convention:** newest entries at the TOP (below the `---` divider).
"""

_DIVIDER = "---"


# ── internal helpers ──────────────────────────────────────────────────────────

def _utc_now() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_caller() -> str:
    """Return the current OS user, falling back to 'unknown'."""
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def _build_entry(
    *,
    tool: str,
    op: str,
    pre_sha: str | None,
    post_sha: str | None,
    result: str,
    notes: str,
    caller: str,
    timestamp: str,
) -> str:
    """Render a single audit entry as a Markdown block (trailing newline included)."""
    pre_sha_str = pre_sha if pre_sha is not None else "n/a"
    post_sha_str = post_sha if post_sha is not None else "n/a"
    return (
        f"## {timestamp} — {tool}: {op}\n"
        f"\n"
        f"- **Tool:** {tool}\n"
        f"- **Op:** {op}\n"
        f"- **Pre-SHA:** {pre_sha_str}\n"
        f"- **Post-SHA:** {post_sha_str}\n"
        f"- **Result:** {result}\n"
        f"- **Caller:** {caller}\n"
        f"- **Notes:** {notes}\n"
        f"\n"
    )


def _ensure_header(log_path: Path) -> None:
    """Create the log file with a header + divider if it does not yet exist."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        _FILE_HEADER + "\n" + _DIVIDER + "\n",
        encoding="utf-8",
    )


# ── public API ────────────────────────────────────────────────────────────────

def write_entry(
    *,
    tool: str,
    op: str,
    pre_sha: str | None,
    post_sha: str | None,
    result: str,
    notes: str,
    caller: str | None = None,
    timestamp: str | None = None,
    log_path: Path = SANCTIONED_OPS_LOG,
) -> None:
    """Prepend a structured Markdown audit entry to *log_path*.

    Parameters
    ----------
    tool:
        Short identifier for the sanctioned tool (e.g. ``robot_settings``).
    op:
        Operation label (e.g. ``lift push``, ``filter-branch``, ``rm-recursive``).
    pre_sha:
        Git SHA (or other state identifier) before the operation, or ``None``.
    post_sha:
        Git SHA (or other state identifier) after the operation, or ``None``.
    result:
        Outcome string — e.g. ``OK``, ``ABORTED``, ``FAILED: <reason>``.
    notes:
        Free-form explanation; required (pass empty string if nothing to add).
    caller:
        Identity of the invoking agent/user.  Defaults to ``$USER``.
    timestamp:
        ISO-8601 UTC timestamp string.  Defaults to UTC now.
    log_path:
        Path to the Markdown log file.  Defaults to ``SANCTIONED_OPS_LOG``.
    """
    resolved_caller = caller if caller is not None else _default_caller()
    resolved_ts = timestamp if timestamp is not None else _utc_now()

    entry = _build_entry(
        tool=tool,
        op=op,
        pre_sha=pre_sha,
        post_sha=post_sha,
        result=result,
        notes=notes,
        caller=resolved_caller,
        timestamp=resolved_ts,
    )

    if not log_path.exists():
        _ensure_header(log_path)

    existing = log_path.read_text(encoding="utf-8")
    divider_pos = existing.find("\n" + _DIVIDER + "\n")
    if divider_pos != -1:
        insert_at = divider_pos + len("\n" + _DIVIDER + "\n")
        new_content = existing[:insert_at] + "\n" + entry + existing[insert_at:]
    else:
        # No divider found — prepend entry at the very top
        new_content = entry + existing

    log_path.write_text(new_content, encoding="utf-8")
