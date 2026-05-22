# Structural Anti-Pattern Rules

Registry for `tools/check_structural_antipatterns.py`. Each rule encodes a
drift pattern observed during the v4.x audit cycle. New patterns discovered
during release audits or routine work are appended here and added to the
rule registry — the cost of adding rule N+1 is minimal (one tuple, one doc
entry, one test). See Core Rule 5.24.

## Adding a New Rule

1. Append a `_check_<name>(repo, mode)` function to `tools/check_structural_antipatterns.py`
2. Add the tuple to the `RULES` list: `("rule-NNN", description, _check_<name>, remedy)`
3. Add a test in `tests/test_structural_antipatterns.py`: positive case (violation detected)
   and negative case (legitimate file does not trigger)
4. Append an entry to this document
5. Commit all four changes together

---

## rule-001 — Loose ADR File

**Pattern:** ADR file (`NNNN-*.md`) placed in `docs/` instead of `docs/adr/`

**Past drift it would have caught:** During v4.1.0 cleanup execution,
temporary ADR drafts were occasionally staged in `docs/` before being moved
to `docs/adr/`. The rule enforces the canonical path at commit time.

**How to fix when triggered:**
```
git mv docs/NNNN-name.md docs/adr/NNNN-name.md
```

---

## rule-002 — Unexcepted Tracked Data Subdirectory

**Pattern:** A file tracked under `data/<x>/` but no `!data/<x>/` exception
in `.gitignore`

**Past drift it would have caught:** Drift 6 and Drift 7 from the v4.1.0
audit — runtime data directories (`data/compose/`, `data/models/`,
`data/dockhand/`) accumulated in git history without explicit exception
discipline. The `data/*/` gitignore pattern blocks new additions silently;
this rule makes the intent visible for anything that bypasses it.

**How to fix when triggered:**
```
# Either add the exception (for tracked content):
echo '!data/<x>/' >> .gitignore

# Or stop tracking the directory (for runtime data):
git rm -r --cached data/<x>/
```

---

## rule-003 — Canonical Document at Repo Root

**Pattern:** `CORE_RULES.md` or `PROJECT_CLEANUP.md` found at repo root
instead of their canonical locations

**Past drift it would have caught:** Drift 9 from the v4.1.0 audit — stray
copies of `CORE_RULES.md` and `PROJECT_CLEANUP.md` were found at repo root
alongside their canonical copies in `docs/` and `docs/cleanup/`. The stray
copies diverged silently.

**Canonical paths:**
- `docs/CORE_RULES.md`
- `docs/cleanup/PROJECT_CLEANUP.md`

**How to fix when triggered:**
```
git rm CORE_RULES.md          # or PROJECT_CLEANUP.md
```

---

## rule-004 — Root-Owned Pytest Scratch Files

**Pattern:** Files or directories under `/tmp/pytest-base/` owned by
`root` (uid=0), indicating a test invoked Docker without the `fake_docker`
fixture.

**Past drift it would have caught:** Tests that run real Docker operations
during the test suite leave root-owned files that cannot be cleaned up by
the non-root test runner, causing spurious failures on subsequent runs.

**How to fix when triggered:**
```
sudo rm -rf /tmp/pytest-base/<entry>
```
Then fix the test to use the `fake_docker` fixture instead of real Docker.

---

## rule-005 — Installer Hardcoded Paths

**Pattern:** A file under `installer/` (excluding `installer/tests/`)
contains the literal string `/opt/mediastack` or `/var/lib/mediastack`
outside the canonical default-value module.

**Past drift it would have caught:** Added pre-emptively for v5.0. Without
this check, a Tier 2/3/4 Sonnet session writing installer code could
hardcode the default path instead of reading it from CLI args, env vars, or
the state file. This would silently break `--install-dir` / `--data-dir`
customization for operators running non-default install locations. Violates
ADR 0013 INV-1 (Installer Layout Contract).

**Allowlist:** `installer/tests/` is always excluded — test fixtures may
reference the literal paths as expected values. When a single canonical
default-value module (e.g. `installer/config.py`) is added in Tier 2, add
its relative path to `_INSTALLER_PATH_ALLOWLIST` in
`tools/check_structural_antipatterns.py`.

**How to fix when triggered:**
Replace the literal string with a named constant imported from the canonical
default-value module, or read the path from CLI args, env vars, or the
state file. Do NOT add new canonical locations to the allowlist; the point
is that there is exactly one.

---

## Audit Mode

Running `--audit` scans the full repo state (not just staged changes):

```
python3 tools/check_structural_antipatterns.py --audit
```

This is wired into `ms-update`'s post-deploy health banner and into the
release-tag-gate checklist (see `docs/RELEASE_PROCESS.md` when created in
Step 3.2). Output: `Structural audit: clean` or a count of findings.
