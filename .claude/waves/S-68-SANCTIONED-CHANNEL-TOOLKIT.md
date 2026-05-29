# S-68-SANCTIONED-CHANNEL-TOOLKIT — Every deny has a sanctioned tool or an explicit no-exceptions rationale

## Goal
Generalize the pattern prototyped by `tools/merge_wave_to_main.py` (S-59 Stream D)
into a coherent **sanctioned-channel toolkit**: a small family of audited,
lift-restore-disciplined helpers under `tools/sanctioned/` that give every
recurring deny-list workaround a single blessed code path — OR an explicit
"no-exceptions-period" rationale recorded in a tracked file. The end state:
no agent ever hand-edits `.claude/settings.local.json` to work around a deny,
because for each deny that legitimately needs a one-time lift there is a tool
that does the lift, the operation, the audit entry, and the restore in one
`try/finally`; and for each deny that must NEVER be lifted, a tracked rationale
says so and a gate enforces the dichotomy.

## Context
- `tools/merge_wave_to_main.py` (shipped S-59 Stream D, on main) is the canonical
  prototype: pre-flight checks → lift `Bash(git checkout main*)` + `Bash(git switch main*)`
  → operate → audit to `docs/MERGE-LOG.md` → restore denies in `finally`. It is
  ALREADY the sanctioned merge channel; this wave does NOT replace it. The wave
  factors the lift-restore + audit primitives it inlines into shared modules other
  sanctioned tools reuse, and `merge_wave_to_main.py` is refactored to consume them
  (behavior-preserving — same denies, same MERGE-LOG format, same exit codes).
- Recurring deny-list workarounds documented across batches 3–5 that currently
  rely on ad-hoc `python3 -c "import json..."` lift snippets or temp helpers:
  - merge-to-main (covered by `merge_wave_to_main.py`)
  - settings lift/restore for post-wave operator handoff (the `/tmp/lift-push-restore.py`
    temp helper, slipped from S-56-B → tracked in BACKLOG `[→ S-67-C]` as
    `tools/robot-settings.py`)
  - force-push of a rewritten tag/ref after history scrub (Tailscale key-leak
    rewrite, 2026-05-28 — done by hand under a one-time lift)
  - `git filter-branch` secret-scrub (same incident)
  - recursive project-tree deletion (`rm -rf` workarounds that the deny list blocks)
- `ms-enforce` has TWO warn-only TIER_1 gates already in the mechanical-enforcement
  pattern (`check_walkback_log`, `check_access_requests_stale`). This wave adds ONE
  more (`check_sanctioned_channels_complete`); S-69 adds the rest of the audit-tool
  family. The two waves are file-disjoint (see Cross-wave dependencies).

## Rules to follow
- **Behavior-preserving refactor of `merge_wave_to_main.py`.** Streams A/B extract
  the lift-restore and audit primitives; the merge tool is rewired to import them.
  Its CLI, pre-flight checks, MERGE-LOG format, and exit codes MUST NOT change. A
  golden test asserts the MERGE-LOG entry shape is byte-identical to pre-refactor.
- **`try/finally` is mandatory** in every tool that lifts a deny. Denies are
  restored on success AND on every error path. This is the single most important
  invariant — a tool that lifts and crashes before restore is a security hole.
- **Canonical profile is the source of truth for restore.** `restore` re-applies
  `.claude/settings-wave-mode-profile.json`, never in-memory diff state. No flag-chasing.
- **Every sanctioned op writes an audit entry.** Merge ops keep writing to
  `docs/MERGE-LOG.md` (unchanged); all OTHER sanctioned tools write to a new
  `docs/SANCTIONED-OPS-LOG.md` via the shared audit module.
- **No new business logic in tools beyond the sanctioned operation itself.** These
  are thin, audited wrappers, not feature surfaces. Pure stdlib, no external deps
  (match `merge_wave_to_main.py`).
- **Processor-pattern contract (S-59 retro):** Streams A and B share the
  `_lift_restore` / `_audit` module symbols. The exact public symbols each stream
  ships are PINNED in the Deliverables section below so the two parallel streams
  cannot drift the way S-59 A/B did. See `.claude/AUTONOMOUS-DEFAULTS.md`
  § "agent / subagent coordination" → "Processor-pattern contract".

## Authorized deletions
None. This wave is purely additive (new `tools/sanctioned/` package + new
`docs/SANCTIONED-OPS-LOG.md` + doctrine edits + one ms-enforce gate). The
`merge_wave_to_main.py` refactor MOVES code into shared modules but does not
delete the file; the temp `/tmp/lift-push-restore.py` helper is not tracked and
is out of scope to remove here.

## Parallelization

**Models:** coordinator = **opus** (cross-stream contract enforcement +
behavior-preserving refactor review), subagents = **sonnet**. Five streams:
A and B are the shared-module foundation and must merge before C/D/E rebase onto
them; C/D/E are parallel with each other.

| Stream | Order | Subagent type | Scope |
|---|---|---|---|
| A — `tools/sanctioned/_lift_restore.py` | foundation (first) | `general-purpose` in worktree | Settings lift-restore primitives + canonical wave-mode profile reader |
| B — `tools/sanctioned/_audit.py` | foundation (first, parallel with A — file-disjoint) | `general-purpose` in worktree | Per-tool audit-entry writer to `docs/SANCTIONED-OPS-LOG.md` |
| C — `tools/sanctioned/robot_settings.py` + refactor `merge_wave_to_main.py` | after A+B | `general-purpose` in worktree | Operator-handoff settings tool; rewire merge tool onto shared modules |
| D — force-push + filter-branch tools | after A+B | `general-purpose` in worktree | `tools/sanctioned/force_push_tag.py`, `tools/sanctioned/filter_branch_secret_scrub.py` |
| E — rm-recursive + doctrine + gate | after A+B | `general-purpose` in worktree | `tools/sanctioned/rm_recursive_safe.py`; ROBOT.md updates; `check_sanctioned_channels_complete` ms-enforce gate |

Streams A and B are file-disjoint and run in parallel from the start (they are the
"foundation"). C, D, E each depend on A+B's public symbols and rebase onto the
merged A+B foundation; among themselves C/D/E are file-disjoint and parallel.

## Deliverables per stream

### Stream A — `tools/sanctioned/_lift_restore.py` (PINNED public contract)
Pure-stdlib module. **Public symbols (PINNED — C/D/E import exactly these):**
- `SETTINGS_LOCAL: Path` — `.claude/settings.local.json`
- `WAVE_MODE_PROFILE: Path` — `.claude/settings-wave-mode-profile.json`
- `lift(patterns: list[str], settings_path: Path = SETTINGS_LOCAL) -> None`
  — remove each pattern from `permissions.deny`, add to `permissions.allow`.
- `restore(settings_path: Path = SETTINGS_LOCAL) -> None`
  — re-apply the canonical wave-mode profile verbatim (source of truth; not a diff).
- `lifted(patterns, settings_path=SETTINGS_LOCAL)` — context manager wrapping
  `lift`/`restore` in `try/finally` (the preferred entry point for all callers).
Plus:
- Create `.claude/settings-wave-mode-profile.json` (tracked) capturing the current
  canonical deny list as the restore source of truth. Coordinate with S-67-C if
  that stream also creates this file (see Cross-wave dependencies — one creator).
- Tests: lift/restore idempotency; multi-pattern lift; `lifted()` restores on
  exception; `restore()` recovers from arbitrary mangled state to match the profile.

### Stream B — `tools/sanctioned/_audit.py` (PINNED public contract)
Pure-stdlib module. **Public symbols (PINNED — C/D/E import exactly these):**
- `SANCTIONED_OPS_LOG: Path` — `docs/SANCTIONED-OPS-LOG.md`
- `write_entry(*, tool: str, op: str, pre_sha: str | None, post_sha: str | None, result: str, notes: str, caller: str | None = None, timestamp: str | None = None, log_path: Path = SANCTIONED_OPS_LOG) -> None`
  — prepend a structured Markdown entry (newest at top), creating the file with a
  header if absent. `caller` defaults to `$USER`; `timestamp` defaults to UTC now.
- Create `docs/SANCTIONED-OPS-LOG.md` with a header block + `---` divider matching
  `docs/MERGE-LOG.md` layout so the insert-after-divider logic is shared-shaped.
- Tests: first-write creates file with header; subsequent writes prepend below
  divider; ABORTED/result fields render; missing optional fields tolerated.
- **Note:** merge ops continue using `docs/MERGE-LOG.md` (Stream C does NOT redirect
  `merge_wave_to_main.py`'s audit to the new log — only its lift-restore primitives
  are shared).

### Stream C — `tools/sanctioned/robot_settings.py` + merge-tool refactor
- `tools/sanctioned/robot_settings.py` — subcommands `lift push`,
  `lift checkout-main`, `lift filter-branch`, `restore`, `push-then-restore`
  (convenience: lift push → `git push origin main` → restore in `finally`).
  Built on Stream A's `lifted()` / `restore()`; audits via Stream B `write_entry`.
- Refactor `tools/merge_wave_to_main.py`: replace its inlined `lift_denies` /
  `restore_denies` with Stream A's `lifted()`; keep `docs/MERGE-LOG.md` audit
  (NOT redirected to SANCTIONED-OPS-LOG). CLI/pre-flight/exit codes UNCHANGED.
- Golden test: pre/post-refactor MERGE-LOG entry byte-identical for a fixture merge.
- ROBOT.md "Post-wave operator handoff" updated to point at `robot_settings.py`
  (replaces the ad-hoc `python3 -c "import json..."` pattern).
- Settings-write permission requested via the access-requests queue
  (`docs/ACCESS-REQUESTS.md` `[allow]` entry referencing this stream).
- **Coordinate with S-67-C:** if S-67-C's `tools/robot-settings.py` merges first,
  this stream's tool becomes a thin re-export/alias under `tools/sanctioned/`
  delegating to the shared modules; if this wave merges first, S-67-C folds into
  it. State the resolution in a decision file at merge time.

### Stream D — force-push + filter-branch sanctioned tools
- `tools/sanctioned/force_push_tag.py` — sanctioned force-push of a single
  rewritten tag/ref after an authorized history rewrite. Lifts the relevant
  `Bash(git push*)` deny via `lifted()`, requires an explicit `--reason` and a
  confirmation token argument, audits via `write_entry`, restores in `finally`.
  Refuses force-push of branch refs other than an explicitly named tag/ref.
- `tools/sanctioned/filter_branch_secret_scrub.py` — wraps the secret-scrub
  filter-branch flow used in the Tailscale-key incident: takes a path/pattern to
  scrub, runs the rewrite, audits. Does NOT push (push is a separate sanctioned op).
- Tests for each (dry-run mode; audit entry written; deny restored after error).

### Stream E — rm-recursive-safe + doctrine + completeness gate
- `tools/sanctioned/rm_recursive_safe.py` — sanctioned recursive delete restricted
  to the **project tree only**: refuses any target that resolves outside the repo
  root (realpath containment check), refuses `/`, `$HOME`, and symlink-escape
  targets. Audits each deletion via `write_entry`.
- ROBOT.md: new "Sanctioned channels" subsection under "Launching a Robot run"
  documenting the toolkit, the lift-restore-`try/finally`-audit invariant, and the
  rule "every deny maps to a sanctioned tool OR a no-exceptions-period rationale."
- `check_sanctioned_channels_complete` ms-enforce gate (warn-only TIER_1, ~50–70
  lines): parse `permissions.deny` from `.claude/settings.local.json`; for each
  deny rule, verify it is EITHER (a) handled by a tool under `tools/sanctioned/`
  (or `merge_wave_to_main.py`) — detected via a declared registry mapping deny→tool —
  OR (b) listed in a tracked `docs/SANCTIONED-CHANNELS.md` (or a clearly-marked
  section) with a "no-exceptions-period" rationale. Warn on any deny that is neither.
- Tests with fixture settings files (deny mapped → pass; deny unmapped → warn).
- Register the gate in `ms-enforce` TIER_1 list (additive — coordinate the
  registration line with any other wave touching the TIER_1 list; both adds kept).

## Verification per stream
1. `python3 -m pytest tests/test_sanctioned_lift_restore.py tests/test_sanctioned_audit.py tests/test_robot_settings.py tests/test_sanctioned_force_push.py tests/test_sanctioned_rm_safe.py tests/test_sanctioned_channels_gate.py -v` — all pass.
2. `python3 -m pytest tests/test_merge_wave_to_main.py -v` — existing merge-tool tests STILL pass (behavior-preserving refactor); golden MERGE-LOG entry byte-identical.
3. `python3 ms-enforce` exits 0 (warn-only checks may emit warnings; TIER_1 failures abort).
4. `python3 tools/merge_wave_to_main.py --help` prints unchanged usage; a fixture merge produces a MERGE-LOG entry matching the pre-refactor golden.
5. `python3 tools/sanctioned/robot_settings.py restore` is a no-op when settings already match the canonical profile.
6. `python3 tools/sanctioned/rm_recursive_safe.py /etc` (or any path outside repo root) refuses with non-zero exit and writes no audit entry.
7. ROBOT.md references `tools/sanctioned/` and the "Sanctioned channels" subsection.

## Out of scope
- Replacing or changing `merge_wave_to_main.py`'s external behavior — refactor is
  internal only.
- The S-69 mechanical audit-gate family (`audit_*` tools) — owned by S-69.
- Auto-pushing anything. `force_push_tag.py` and `robot_settings.py push-then-restore`
  lift the push deny but the operator still invokes them deliberately; no autonomous push.
- A frontend surface for any sanctioned op (CLI + doctrine only).
- Generalizing the toolkit to non-deny operations.

## Cross-wave dependencies (EXPLICIT)
- Depends ONLY on current main (`578c452`). Builds on `tools/merge_wave_to_main.py`
  (already on main) as the prototype it refactors.
- File-disjoint with S-69 (this wave: `tools/sanctioned/**`, `merge_wave_to_main.py`
  refactor, `docs/SANCTIONED-OPS-LOG.md`, one new ms-enforce gate; S-69: `tools/audit_*.py`
  + doctrine cross-references). May merge to main in any order with S-69.
- **Overlap risk with S-67-C** (`tools/robot-settings.py`) and S-67-A
  (`.claude/settings-wave-mode-profile.json`): if S-67 has NOT merged when this wave
  fires, this wave creates both. If S-67 merged first, Stream A consumes the existing
  profile file (does not recreate it) and Stream C delegates to / aliases the existing
  `robot-settings.py`. Coordinate scope at merge time; log the resolution in a
  decision file. Both tools sharing the `tools/sanctioned/` modules is the target end state.
- Both this wave's TIER_1 gate registration and any S-69 gate registration touch the
  `ms-enforce` TIER_1 list — additive append, keep-both per the intra-wave additive-conflict default.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Streams A+B foundation first
(parallel, file-disjoint); C/D/E parallel after A+B merge. Coordinator merges all
to `wave/S-68-sanctioned-channel-toolkit`, never main. Post-wave merge to main goes
through `python3 tools/merge_wave_to_main.py wave/S-68-sanctioned-channel-toolkit`
(the canonical sanctioned channel).

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-68-SANCTIONED-CHANNEL-TOOLKIT.md as orchestrator.`
