#!/usr/bin/env python3
"""gen_open_items.py -- generate Open items block from TODO.md.

Reads TODO.md, extracts all unchecked (- [ ]) items, and renders them as a
compact Open items list.  When --update is passed, replaces content between
BEGIN/END marker comments in the target file without touching surrounding text.

Usage:
    python3 tools/gen_open_items.py                           # print to stdout
    python3 tools/gen_open_items.py --update docs/STATE.md   # replace in-place
    python3 tools/gen_open_items.py --todo /path/TODO.md \\
                                    --update /path/STATE.md   # custom paths
    python3 tools/gen_open_items.py --self-test              # run self-tests
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BEGIN_MARKER = "<!-- BEGIN GENERATED -->"
END_MARKER = "<!-- END GENERATED -->"

# Default TODO path: /home/stack/v5/docs/TODO.md (SLOP process docs live outside the
# code repo, in a non-versioned v5/ tree on the Tardis WSL host). Override with --todo
# when running against a different location.
DEFAULT_TODO = Path("/home/stack/v5/docs/TODO.md")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_open_items(text: str) -> list:
    """Return list of dicts for every unchecked (- [ ]) item in TODO text."""
    lines = text.splitlines()
    items = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^- \[ \] (.+)", line)
        if m:
            rest = m.group(1)

            # ---- title (prefer bold **...**) --------------------------------
            title_m = re.search(r"\*\*(.+?)\*\*", rest)
            if title_m:
                title = title_m.group(1)
                after_title = rest[title_m.end():]
            else:
                # No bold: strip bracket tags, take remaining text as title
                title = re.sub(r"\[.*?\]", "", rest).strip()
                after_title = rest

            # ---- strip backtick-wrapped routing tags: `[E->C]` `[C]` -------
            after_clean = re.sub(r"`\[[^\]]+\]`", "", after_title)

            # ---- [BR: class name] tag --------------------------------------
            br_tag = None
            br_m = re.search(r"\[BR: ([^\]]+)\]", after_clean)
            if br_m:
                br_tag = br_m.group(1)

            # ---- effort tag: first [XYZ] that is not a BR tag --------------
            after_no_br = re.sub(r"\[BR: [^\]]+\]", "", after_clean)
            effort = "?"
            ef_m = re.search(r"\[([^\[\]]+)\]", after_no_br)
            if ef_m:
                val = ef_m.group(1).strip()
                if val:
                    effort = val

            # ---- description: first non-empty indented line after bullet ---
            desc = ""
            j = i + 1
            while j < len(lines):
                l = lines[j]
                if l.startswith("- ") or l.startswith("#"):
                    break
                stripped = l.strip()
                if stripped:
                    desc = stripped
                    break
                j += 1

            if len(desc) > 80:
                desc = desc[:77] + "..."

            items.append(
                {"title": title, "effort": effort, "br_tag": br_tag, "description": desc}
            )
        i += 1
    return items


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render_items(items: list) -> list:
    """Render item dicts to markdown lines."""
    out = []
    for item in items:
        parts = []
        if item["br_tag"]:
            parts.append("[BR: " + item["br_tag"] + "]")
        parts.append("[" + item["effort"] + "]")
        parts.append("**" + item["title"] + "**")
        line = " ".join(parts)
        if item["description"]:
            line += " — " + item["description"]   # em dash
        out.append("- " + line)
    return out


# ---------------------------------------------------------------------------
# Updater
# ---------------------------------------------------------------------------

def update_file(target: Path, generated: list) -> None:
    """Replace content between BEGIN/END markers in target file."""
    text = target.read_text(encoding="utf-8")
    bi = text.find(BEGIN_MARKER)
    ei = text.find(END_MARKER)
    if bi == -1 or ei == -1:
        print("no markers in target; insert manually", file=sys.stderr)
        sys.exit(1)
    if ei < bi:
        print("END marker appears before BEGIN marker", file=sys.stderr)
        sys.exit(1)
    before = text[: bi + len(BEGIN_MARKER)]
    after = text[ei:]
    new_text = before + "\n" + "\n".join(generated) + "\n" + after
    target.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

_SELF_TEST_TODO = """\
# Test TODO

## Section A

- [x] **Done item** [5m]
  This is completed work.

- [ ] **Open with effort** [30m]
  First sentence of description. More text here.

- [ ] **Open with BR tag** [BR: stale config dispatch path] [5m]
  Description of BR item.

- [ ] **Open no description**

## Section B

- [ ] **Another open item**
  Some description text here.

- [x] **Another done** (fixed 2026-01-01)
  Should not appear.

- [ ] **Item with backtick tag** [~20m] `[E->C]`
  Description with details.
"""


def run_self_test() -> None:
    items = parse_open_items(_SELF_TEST_TODO)
    failures = []

    # 1 — only unchecked items extracted
    titles = [i["title"] for i in items]
    if "Done item" in titles or "Another done" in titles:
        failures.append("FAIL 1: checked items included in output")
    else:
        print("PASS 1: only unchecked items extracted (no [x] items present)")

    # 2 — [BR:] tag preserved
    br_items = [i for i in items if i["br_tag"]]
    expected_br = "stale config dispatch path"
    if not br_items or br_items[0]["br_tag"] != expected_br:
        got = [i["br_tag"] for i in items]
        failures.append("FAIL 2: BR tag not preserved -- got " + str(got))
    else:
        print("PASS 2: BR tag preserved: " + repr(br_items[0]["br_tag"]))

    # 3 — item with no description still rendered
    no_desc = [i for i in items if i["title"] == "Open no description"]
    if not no_desc:
        failures.append("FAIL 3: no-description item missing from output")
    elif no_desc[0]["description"]:
        failures.append("FAIL 3: expected empty description, got: " + repr(no_desc[0]["description"]))
    else:
        print("PASS 3: no-description item rendered (description='')")

    # 4 — indented continuation line picked up as description
    ef_item = [i for i in items if i["title"] == "Open with effort"]
    if not ef_item or not ef_item[0]["description"]:
        failures.append("FAIL 4: description not picked up from indented line")
    else:
        print("PASS 4: indented description captured: " + repr(ef_item[0]["description"]))

    # 5 — section headers ignored
    if len(items) != 5:
        failures.append("FAIL 5: expected 5 open items, got " + str(len(items)))
    else:
        print("PASS 5: section headers ignored (5 open items found)")

    # 6 — backtick-wrapped routing tag not treated as effort tag
    bt_item = [i for i in items if i["title"] == "Item with backtick tag"]
    if not bt_item:
        failures.append("FAIL 6: backtick-tag item missing from output")
    elif bt_item[0]["effort"] != "~20m":
        failures.append("FAIL 6: effort should be '~20m', got " + repr(bt_item[0]["effort"]))
    else:
        print("PASS 6: backtick routing tag stripped; effort=~20m")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("All self-tests passed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ## Open items block from TODO.md"
    )
    parser.add_argument(
        "--todo", type=Path, default=DEFAULT_TODO,
        help="Path to TODO.md (default: docs/TODO.md relative to repo root)",
    )
    parser.add_argument(
        "--update", type=Path, metavar="TARGET",
        help="Replace content between BEGIN/END markers in this file in-place",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run self-test with embedded synthetic TODO content and exit",
    )
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    text = args.todo.read_text(encoding="utf-8")
    items = parse_open_items(text)
    skipped = len(re.findall(r"^- \[x\]", text, re.MULTILINE))
    generated = render_items(items)

    if args.update:
        update_file(args.update, generated)
        print(
            "Generated " + str(len(items)) + " items from TODO.md "
            "(" + str(len(items)) + " unchecked, " + str(skipped) + " skipped checked)."
        )
    else:
        print("\n".join(generated))


if __name__ == "__main__":
    main()
