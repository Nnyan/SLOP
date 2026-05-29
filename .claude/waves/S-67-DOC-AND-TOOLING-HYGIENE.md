# S-67-DOC-AND-TOOLING-HYGIENE — Doc cleanup + slipped S-56 tooling + validate-wave-file fix

> **Batch-6 descope (2026-05-29):** Stream C (`tools/robot-settings.py` +
> `.claude/settings-wave-mode-profile.json`) is **deferred to S-68**, which owns
> the sanctioned-channel toolkit and creates exactly these artifacts under
> `tools/sanctioned/`. Two waves in the same batch must not both create the same
> files. S-67 keeps Streams A, B, D, E. See Stream C below and Cross-wave
> dependencies.

## Goal
Drain accumulated doc-hygiene debt (~90 broken links — run `python3 tools/check_referenced_files.py` for the live count; 93 at pre-flight 2026-05-29 — 3 phantom TODO refs in
RELEASE_NOTES, 4 CHANGELOG v4.2.0 fix-later items) AND complete the tooling
items that slipped from S-56 — the `audit_orchestrator_dispatch.py` mechanical
gate (the `robot-settings.py` helper is now owned by S-68; see descope note above).
Plus the `validate-wave-file.py` false-positive fix (the single residual S-58
failure).

## Context
- S-56 shipped on main but two BACKLOG-flagged additions slipped: the
  `tools/robot-settings.py` promotion and the `audit_orchestrator_dispatch.py`
  gate. The `robot-settings.py` half is now owned by S-68 (see descope note at
  top); this wave completes the `audit_orchestrator_dispatch.py` gate (Stream D).
  Tracked in BACKLOG with `[→ S-67-D]` / `[→ S-68]` markers.
- `tools/validate-wave-file.py` (S-55-C) has known false positives surfaced
  three times now (OPTIONAL-FILE-SIZE-REMEDIATION.md, S-46-PIN-RELAX.md,
  S-59-ACCESS-REQUESTS-PROCESSOR.md). Same root cause each time: heuristic
  doesn't skip illustrative path fragments / authorized-deletion paths.
- Doc audit (S-56-C) detected ~90 broken-link warnings in docs/ (93 at
  pre-flight 2026-05-29; count drifts as docs change — `python3 tools/check_referenced_files.py` is the live source). Most are
  refs to `docs/cleanup/*` (deleted post-v5.0.0); some are missing files
  referenced from GLOSSARY/ADRs; some are template placeholders. Triage
  needed.
- `docs/RELEASE_NOTES_v5_0_0.md` references three `docs/TODO_2026_05_*.md`
  files that don't exist — either the work was done (refs stale) or
  never tracked.
- `CHANGELOG.md` mentions 4 "fix-later TODOs" from v4.2.0 audit
  (F1/F4/F7/F8: ledger coverage gap, structural antipatterns CI wiring,
  STRUCTURAL_RULES.md rule-004 entry, HARDENING_V4_2_AUDIT_RESULTS.md
  staleness). Status of each is unknown.

## Rules to follow
- For broken doc refs: investigate before deleting. Each ref may be (a) a
  reference to work that was done and refs are now stale, (b) a reference
  to work that was never tracked elsewhere — recover it to BACKLOG, or
  (c) an illustrative placeholder that should be marked as such.
- For CHANGELOG F1/F4/F7/F8: same. Investigate current state (grep for
  the named issues; check git log); either mark `[x]` done with provenance
  in BACKLOG or `[ ]` open + fold into a future wave.
- For tooling: build with proper tests + ms-enforce integration. Don't ship
  a half-baked tool.
- For `validate-wave-file.py` fix: don't over-engineer. Add the obvious
  heuristics (skip paths without top-level dir prefix; treat "delete"/"Authorized
  deletions"/"example"/"illustrative" as classification markers). Tests
  verify each of the 3 previously-false-positive wave files passes after fix.

## Authorized deletions
- Broken-link references that point to files confirmed to have been deleted
  with no recoverable provenance — delete the references with rationale in
  commit message. Stream A's triage classifies each before Stream B acts.

## Parallelization

**Models:** coordinator = **opus**, subagents = **sonnet**. Four active streams
(A, B, D, E). Stream C is deferred to S-68 — do NOT dispatch it.

| Stream | Subagent type | Scope |
|---|---|---|
| A — doc-ref triage | `general-purpose` in worktree | Investigate every broken-link warning + 3 RELEASE_NOTES TODO refs + 4 CHANGELOG TODOs; classify each (stale/recoverable-work/template); output `.claude/run/observations/S-67-A-triage.md` |
| B — doc-ref fix | `general-purpose` in worktree (after A merges) | Apply Stream A's classifications: update refs to current canonical locations, delete stale refs, recover lost work to BACKLOG, mark template placeholders explicitly |
| ~~C — tools/robot-settings.py~~ | **DEFERRED to S-68** | Moved to S-68 (sanctioned-channel toolkit owns `tools/sanctioned/robot_settings.py` + `.claude/settings-wave-mode-profile.json`). Not dispatched by this wave. |
| D — tools/audit_orchestrator_dispatch.py | `general-purpose` in worktree | New file: scan `.claude/run-archive/*/status/*.md` for multiple orchestrator status files within same hour referencing different waves (the one-orchestrator-per-batch anti-pattern); warn-only ms-enforce TIER_1 check; tests |
| E — validate-wave-file.py fix | `general-purpose` in worktree | Heuristic improvements: skip path fragments without top-level dir prefix; treat "delete"/"Authorized deletions"/"example"/"illustrative" as classification markers; tests verifying the 3 previously-false-positive waves now pass |

Stream B is sequential after Stream A delivers its triage classifications.
Streams D, E are parallel from start (file-disjoint). Stream C is deferred (see above).

## Deliverables

### Stream A — doc-ref triage
For each broken-link warning (live count via `python3 tools/check_referenced_files.py`; ~93 at pre-flight) + 3 RELEASE_NOTES TODO refs + 4 CHANGELOG TODOs:
1. Classify: `stale-ref-target-deleted` / `recoverable-work-needs-backlog-entry` /
   `template-placeholder-mark-as-such` / `ref-target-renamed-update-link`.
2. For `recoverable-work` items: write the recovered context (what the work
   was about, who/why) — Stream B will move these into BACKLOG.
3. Output structured classification in `.claude/run/observations/S-67-A-triage.md`.

### Stream B — doc-ref fix (after A)
- For `ref-target-renamed`: update the ref to current canonical path.
- For `stale-ref-target-deleted`: delete the ref with one-line rationale.
- For `recoverable-work`: append a new BACKLOG entry with the recovered context
  per A's notes, plus delete the orphaned ref.
- For `template-placeholder`: mark the placeholder explicitly (e.g.,
  ``` `<TEMPLATE>` ``` or HTML comment) so audit tooling skips it.
- Commit per category cluster with message `docs: <category> cleanup (S-67-B)`.

### Stream C — DEFERRED to S-68 (do not dispatch)
The `tools/robot-settings.py` permanent helper and the canonical
`.claude/settings-wave-mode-profile.json` deny profile are now owned by
**S-68-SANCTIONED-CHANNEL-TOOLKIT** (Stream A creates the profile; Stream C
ships `tools/sanctioned/robot_settings.py` with the `lift push` /
`lift checkout-main` / `lift filter-branch` / `restore` / `push-then-restore`
subcommands, built on the shared `_lift_restore` / `_audit` modules). Building
the same artifacts in two waves of one batch would collide, so this stream is
descoped here. The ROBOT.md "Post-wave operator handoff" update and the
settings-write access-requests entry move to S-68 with it. No deliverable for
this stream in S-67.

### Stream D — `tools/audit_orchestrator_dispatch.py` mechanical gate
- Scan `.claude/run-archive/*/status/*.md` for the anti-pattern: multiple
  orchestrator status files written within the same hour for different waves
  (suggests one-orchestrator-per-wave rather than the doctrine ONE-per-batch).
- Warn-only ms-enforce TIER_1 check `check_orchestrator_dispatch_pattern`.
- Tests with fixture run dirs.

### Stream E — `validate-wave-file.py` false-positive fix
- Skip paths that don't begin with a known top-level dir (`backend/`, `tools/`,
  `frontend/`, `tests/`, `docs/`, `installer/`, `catalog/`, `migrations/`, etc.).
- Treat "delete", "Authorized deletions", "example", "illustrative" as
  classification markers — paths under these sections are excluded from
  existence checks.
- Tests: re-run validator against `OPTIONAL-FILE-SIZE-REMEDIATION.md`,
  `S-46-PIN-RELAX.md`, `S-59-ACCESS-REQUESTS-PROCESSOR.md` — all three now
  exit 0 (or warn-only without flagging the previously-false-positive paths).

## Verification
1. `python3 -m pytest tests/test_audit_orchestrator_dispatch.py tests/test_validate_wave_file.py -v` — all pass. (Stream C / `test_robot_settings.py` moved to S-68.)
2. `python3 ms-enforce` exits 0 (warn-only checks may emit warnings; failures abort).
3. `python3 tools/validate-wave-file.py .claude/waves/S-59-ACCESS-REQUESTS-PROCESSOR.md` exits 0.
4. BACKLOG entries from Stream A's `recoverable-work` classifications are present.
   (The `robot-settings.py` restore-idempotency check and the ROBOT.md
   post-wave-handoff reference are now verified by S-68.)

## Out of scope
- The 12 unmasked + 30 A-bucket pre-existing test failures — owned by S-66.
- New features in any tool. Build the helper functions and audit gates; don't expand scope.
- A frontend surface for any of this (CLI + doc updates only).
- Replacing `validate-wave-file.py` with a different framework — heuristic improvements only.

## Cross-wave dependencies (EXPLICIT)
- Depends only on current main (batch-5 + the S-68/S-69 drafts are already merged).
- **Stream C deferred to S-68** (sanctioned-channel toolkit). With C removed, this
  wave is file-disjoint from S-68: S-67 touches `docs/**`, `tools/audit_orchestrator_dispatch.py`,
  `tools/validate-wave-file.py`; S-68 owns `tools/sanctioned/**` + `robot_settings.py` +
  the wave-mode profile. The only shared touch-point with S-68/S-69 is the
  `ms-enforce` TIER_1 registration list (Stream D adds one line) — additive append,
  resolve via the intra-wave additive-conflict default (keep-both).
- File-disjoint and parallel-safe with S-66. May merge to main in any order with S-66.
- Stream B sequential after Stream A inside this wave; D/E parallel.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Stream A sequential first; B
after A; D/E parallel from start (Stream C deferred to S-68 — not dispatched).
Coordinator merges all to `wave/S-67-doc-and-tooling-hygiene`, never main.
Post-wave merge through `python3 tools/merge_wave_to_main.py wave/S-67-doc-and-tooling-hygiene`.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-67-DOC-AND-TOOLING-HYGIENE.md as orchestrator.`
