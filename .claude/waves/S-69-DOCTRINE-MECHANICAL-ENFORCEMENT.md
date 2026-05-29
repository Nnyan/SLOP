# S-69-DOCTRINE-MECHANICAL-ENFORCEMENT — Convert human-enforced rules into warn-only mechanical gates

## Goal
Take ~6–7 rules that are currently enforced by human discipline ("the operator
checks this by hand before each batch") and give each one a mechanical gate, using
`check_walkback_log` and `check_access_requests_stale` as the established pattern:
warn-only TIER_1, ~50 lines each, pure stdlib, never blocking. The end state: every
human-enforced doctrine rule either has a mechanical gate that surfaces violations,
OR is explicitly marked "not-mechanically-enforced" in the doctrine docs — no rule
silently relies on the operator remembering to check it.

## Context
- `ms-enforce` already has two gates in exactly this shape:
  - `check_walkback_log` (warn-only TIER_1) — flags doctrine-removing commits that
    don't reference a WALK-BACK-LOG entry.
  - `check_access_requests_stale` (warn-only TIER_1) — flags stale/overflowing
    access-request queue entries.
  Both are ~50–70 lines, return `(True, summary)` always, and are registered in the
  `TIER_1` list near the bottom of `ms-enforce`. New gates copy this shape exactly.
- `check_backlog_coverage` (S-56-E) already shells out to a `tools/audit_*.py` family
  (`audit_todos.py`, `audit_archived_observations.py`, `audit_wave_out_of_scope.py`).
  New gates follow that split: a standalone `tools/audit_*.py` scanner that an
  ms-enforce check invokes (so the scanner is independently runnable + testable).
- `tools/audit_backlog_stale.py` does NOT yet exist (CLAUDE.md / ROBOT.md reference it
  as "planned"; `check_backlog_coverage` covers floating-work tracking but NOT the
  ">14-day bare `[ ]`" staleness rule). Stream A builds it.
- The batch-5 retro surfaced the **dedicated-merge-worktree** pattern (BACKLOG
  `[→ S-69]`): every wave-branch operation should happen in a dedicated
  `.claude/worktrees/merge-*` worktree with detached HEAD, never in the shared main
  working tree (batch-5 hit two cross-session HEAD collisions). This wave folds that
  entry in directly: Stream G builds the mechanical gate that verifies it, and the
  doctrine-update Stream H writes the canonical pattern into ROBOT.md +
  AUTONOMOUS-DEFAULTS. (See "Structural note" at the end.)

## Rules to follow
- **Warn-only, always.** Every gate returns `(True, summary)`. None of them block CI.
  Graduation to TIER_2/fail is a SEPARATE future decision (mirrors `check_walkback_log`'s
  "graduates after S-70" note); do not pre-graduate any gate here.
- **Standalone scanner + thin ms-enforce check.** Each `tools/audit_*.py` is runnable
  on its own (`python3 tools/audit_X.py --repo .`) and has its own tests. The
  ms-enforce check is a ~10-line wrapper that shells out and summarizes, mirroring
  `check_backlog_coverage`.
- **Pure stdlib.** No external deps. Match the existing audit tools.
- **No false-positive-prone heuristics that would nag.** Warn-only means low cost to a
  false positive, but each gate should be conservative; document known-FP classes in
  the tool docstring.
- **Doctrine cross-reference is mandatory (Stream H).** Each new gate gets a one-line
  cross-reference in ROBOT.md or AUTONOMOUS-DEFAULTS, and each human-enforced rule in
  those docs gets either a "→ enforced by `check_X`" pointer or an explicit
  "not-mechanically-enforced (reason)" marker.

## Authorized deletions
None. This wave is purely additive: seven new `tools/audit_*.py` scanners + seven new
ms-enforce TIER_1 registrations + doctrine cross-reference edits. No files removed.

## Parallelization

**Models:** coordinator = **opus** (doctrine cross-reference synthesis in Stream H +
gate-registration conflict resolution), subagents = **sonnet**. Eight streams: A–G
are one-gate-each and fully parallel (file-disjoint — each owns one new tool file +
one test file + one TIER_1 registration line); H is the doctrine-update stream and
runs after A–G land so it can cite the actual gate names/behaviors.

| Stream | Order | Subagent type | Scope |
|---|---|---|---|
| A — `tools/audit_backlog_stale.py` | parallel | `general-purpose` in worktree | Flag bare `[ ]` BACKLOG entries >14 days old |
| B — `tools/audit_wave_subagent_preamble.py` | parallel | `general-purpose` in worktree | Verify wave files' orchestrator sections include the subagent preamble template |
| C — `tools/audit_orchestrator_prompt_format.py` | parallel | `general-purpose` in worktree | Lint archived orchestrator prompts for required elements |
| D — `tools/audit_merge_log_completeness.py` | parallel | `general-purpose` in worktree | Every merge commit on main has a MERGE-LOG entry within 3 commits or references it |
| E — `tools/audit_status_file_freshness.py` | parallel | `general-purpose` in worktree | Status file updates within N minutes of stream-merge events during a run |
| F — `tools/audit_memory_staleness.py` | parallel | `general-purpose` in worktree | Flag memory entries with dated language >60 days |
| G — `tools/audit_merge_worktree_pattern.py` | parallel | `general-purpose` in worktree | Verify merges happened in dedicated `.claude/worktrees/merge-*` worktrees |
| H — doctrine cross-references | after A–G | `general-purpose` in worktree | ROBOT.md + AUTONOMOUS-DEFAULTS gate↔rule cross-reference pass + merge-worktree doctrine text |

## Deliverables per stream

Each of A–G ships: (1) `tools/audit_<name>.py` standalone scanner (pure stdlib,
`--repo` arg, prints `WARNING`/`CANDIDATE`/`UNTRACKED`-prefixed lines like the
existing audit family, exits 0 always); (2) `check_<name>` in `ms-enforce` (warn-only
TIER_1, returns `(True, summary)`, shells out to the scanner mirroring
`check_backlog_coverage`); (3) `tests/test_audit_<name>.py` with fixture inputs
covering clean-pass and warn cases; (4) one registration line appended to the
`ms-enforce` TIER_1 list.

### Stream A — `audit_backlog_stale.py` → `check_backlog_stale`
Parse `docs/BACKLOG.md`; find entries whose status token is bare `[ ]` (NOT
`[→ S-NN]`, `[park]`, `[parked]`, `[x]`, `[—]`); parse the `Date added: YYYY-MM-DD`
provenance; warn on any bare `[ ]` older than 14 days. This is the mechanical backing
for the BACKLOG-triage doctrine (ROBOT.md § "BACKLOG triage discipline", which already
names this tool as "planned"). **Note (pre-flight 2026-05-29):** that ROBOT.md note
(line ~36) currently mis-attributes the tool to **S-67** ("planned in S-67 alongside
the orchestrator-dispatch gate"); it is actually owned by **S-69 Stream A**. Stream H
must fix BOTH the status word ("planned" → "shipped") AND the attribution
("S-67" → "S-69") when it updates that note.

### Stream B — `audit_wave_subagent_preamble.py` → `check_wave_subagent_preamble`
Parse `.claude/waves/*.md`; for each, confirm the "Robot mode" / orchestrator section
references the subagent preamble (venv-symlink + file-creation + no-AskUserQuestion
rules). Warn on wave files whose orchestrator footer omits the preamble pointer.

### Stream C — `audit_orchestrator_prompt_format.py` → `check_orchestrator_prompt_format`
Lint archived orchestrator prompts (under `.claude/run-archive/*/` where present, and
any tracked prompt files) for: explicit `git rev-parse origin/main` base (not bare
HEAD), per-stream model assignments, and the subagent preamble. Warn on missing
elements. (Distinct from S-67-D's `audit_orchestrator_dispatch.py`, which detects the
one-orchestrator-per-wave anti-pattern; this one lints prompt CONTENT.)

### Stream D — `audit_merge_log_completeness.py` → `check_merge_log_completeness`
Walk `git log` on main for merge commits; assert each has a corresponding
`docs/MERGE-LOG.md` entry within 3 commits OR references the log in its message.
Warn on merges with no audit trail.

### Stream E — `audit_status_file_freshness.py` → `check_status_file_freshness`
Given a run dir (`.claude/run/status/*.md` or an archived run), check that status-file
"Last updated" timestamps advance within N minutes (default configurable) of recorded
stream-merge events. Warn on stale status files during a run. (Operates on a supplied
or discovered run dir; clean-pass when no active run.)

### Stream F — `audit_memory_staleness.py` → `check_memory_staleness`
Scan the auto-memory dir (path supplied via `--memory-dir`; default the project memory
path) for entries containing dated language (`2026-05-..`, "today", "this session")
older than 60 days. Warn → operator-driven prune. Conservative: only flags entries with
an explicit parseable date >60 days; never auto-deletes.

### Stream G — `audit_merge_worktree_pattern.py` → `check_merge_worktree_pattern`
Verify (from archived run status/log artifacts) that wave-branch merge operations were
performed in dedicated `.claude/worktrees/merge-*` worktrees with detached HEAD, not in
the shared main working tree. Warn when status/log evidence shows a merge done directly
on the shared HEAD. **This is the mechanical half of the batch-5 retro
`[→ S-69]` merge-worktree entry; Stream H writes the doctrine half.**

### Stream H — doctrine cross-references + merge-worktree doctrine text (after A–G)
- For each gate A–G: add a one-line "→ enforced by `check_<name>`" cross-reference next
  to the corresponding human-enforced rule in ROBOT.md / AUTONOMOUS-DEFAULTS.
- For each remaining human-enforced rule in ROBOT.md / AUTONOMOUS-DEFAULTS that has NO
  mechanical gate: add an explicit `not-mechanically-enforced (<reason>)` marker so the
  enforcement status of every rule is visible.
- **Write the merge-worktree doctrine TEXT** (the doctrine half of the batch-5 retro
  entry): extend ROBOT.md § "Architecture" / the two-phase doctrine and add an
  AUTONOMOUS-DEFAULTS § "git operations" entry making the dedicated-merge-worktree +
  detached-HEAD pattern the canonical merge procedure, cross-referencing Stream G's gate.
- If this stream removes ≥3 lines from any doctrine file, add a WALK-BACK-LOG entry
  (per `check_walkback_log`) — though this stream is expected to be purely additive.

## Verification per stream
1. `python3 -m pytest tests/test_audit_backlog_stale.py tests/test_audit_wave_subagent_preamble.py tests/test_audit_orchestrator_prompt_format.py tests/test_audit_merge_log_completeness.py tests/test_audit_status_file_freshness.py tests/test_audit_memory_staleness.py tests/test_audit_merge_worktree_pattern.py -v` — all pass.
2. Each scanner runs standalone: `python3 tools/audit_<name>.py --repo .` exits 0 and prints warnings (or clean) without traceback.
3. `python3 ms-enforce` exits 0; the seven new checks appear in the TIER_1 section as warn-only.
4. ROBOT.md / AUTONOMOUS-DEFAULTS: every human-enforced rule either cross-references a `check_<name>` gate or carries a `not-mechanically-enforced` marker (Stream H).
5. ROBOT.md § "BACKLOG triage discipline" updated: `audit_backlog_stale.py` note changed from "planned" to "shipped" AND re-attributed from S-67 to S-69 (pre-flight finding).
6. The merge-worktree doctrine text is present in ROBOT.md + AUTONOMOUS-DEFAULTS and cross-references `check_merge_worktree_pattern`.

## Out of scope
- Graduating any gate from warn-only to blocking — separate future decision (post-S-70,
  mirroring `check_walkback_log`).
- The sanctioned-channel toolkit (`tools/sanctioned/**`) — owned by S-68.
- S-67-D's `audit_orchestrator_dispatch.py` (dispatch anti-pattern detector) — different
  tool; Stream C lints prompt CONTENT, not dispatch shape.
- Building a unified "audit dashboard" — each gate stands alone, surfaced through ms-enforce.
- Auto-pruning memory or auto-editing BACKLOG — gates surface, humans act.

## Cross-wave dependencies (EXPLICIT)
- Depends ONLY on current main (`069d798` as of 2026-05-29; orchestrator re-confirms
  `git rev-parse origin/main` at startup). Builds on the `check_walkback_log` /
  `check_access_requests_stale` warn-only TIER_1 pattern and the
  `check_backlog_coverage` scanner-plus-wrapper split.
- File-disjoint with S-68 (this wave: `tools/audit_*.py` + doctrine cross-refs; S-68:
  `tools/sanctioned/**` + `merge_wave_to_main.py` refactor). May merge to main in any
  order with S-68.
- File-disjoint with S-66/S-67. The one shared touch-point with S-68 and any other wave
  is the `ms-enforce` TIER_1 registration list — additive append, resolve via the
  intra-wave additive-conflict default (keep-both, log a `<wave>-MERGE-N.md` decision).
- Streams A–G parallel; H sequential after A–G (cites their actual gate names).

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. Streams A–G parallel from start
(file-disjoint, one gate each); H after A–G merge. Coordinator merges all to
`wave/S-69-doctrine-mechanical-enforcement`, never main. Post-wave merge to main goes
through `python3 tools/merge_wave_to_main.py wave/S-69-doctrine-mechanical-enforcement`.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-69-DOCTRINE-MECHANICAL-ENFORCEMENT.md as orchestrator.`
