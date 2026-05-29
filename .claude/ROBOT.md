# Robot mode — autonomous overnight wave execution

## What this is

A discipline + tooling pattern for running wave coordinators (and their subagent
streams) overnight with **zero user prompts**. The user goes to sleep; coordinators
self-execute against documented defaults; any forks are logged for morning review;
nothing dangerous can happen because the settings deny it.

Robot mode is OPT-IN per session. A user launches a wave "in Robot mode" by
prefixing the prompt. Regular interactive sessions are unaffected.

## BACKLOG triage discipline (added 2026-05-29)

`docs/BACKLOG.md` is **not a forever-parking lot**. Every entry MUST be in one of four
explicit states — pure `[ ]` open without an assigned target is not a valid end state:

- `[→ S-NN-stream]` scheduled into a specific wave + stream
- `[park]` deferred WITH a documented re-eval trigger (when/why we'll revisit)
- `[x]` done (kept for provenance; prune after 60 days)
- `[—]` won't fix / superseded with reason

**Before any new batch fires:** review BACKLOG's open items. Each one must be
(a) folded into a wave going out in this batch, (b) explicitly parked with a trigger,
or (c) explicitly denied. Items that have been bare `[ ]` for >14 days are a
process failure — they indicate the triage discipline lapsed.

**Cleanup waves are how pre-existing failures get fixed.** The "fix all pre-existing
failures inside any wave" rule was rightly walked back — focused waves don't expand
scope. The inverse is enshrined here: **dedicated cleanup waves are how accumulated
pre-existing issues get drained.** S-57 (TIER_2 cleanup), S-58 (TestClient sweep),
S-66 (post-S-58 unmask cleanup), S-67 (doc + tooling hygiene) are all instances of
this pattern. Whenever BACKLOG accumulates ≥10 open items in a single category, draft
a cleanup wave; don't let the category grow unbounded.

**Mechanical enforcement:** `tools/audit_backlog_stale.py` (shipped in S-69 alongside
the orchestrator-dispatch gate) flags entries that have been bare `[ ]` for >14
days. → enforced by `check_backlog_stale` (warn-only TIER_1 in ms-enforce, S-69-A).

## When to use it

- Overnight or away-from-keyboard runs of mechanical waves.
- Bulk wave processing where decisions are mostly mechanical and the user wants
  to review in a batch the next morning.
- Any wave whose streams are well-scoped and whose decision points are largely
  enumerated in `AUTONOMOUS-DEFAULTS.md`.

**Do NOT use Robot mode for:**
- First-of-its-kind work where you don't know the decision space yet.
- Anything touching production deployment, secrets, external APIs that mutate state.
- Waves that require human design judgment at runtime (e.g., "decide the new auth model").

## The binding rules (apply to coordinator AND every subagent)

1. **NEVER call `AskUserQuestion`.** No exceptions. If you reach for it:
   - Check `.claude/AUTONOMOUS-DEFAULTS.md` for the scenario.
   - If covered: apply the default. Write a one-line entry to
     `.claude/run/decisions/<wave>-<stream>-<n>.md` describing what you decided
     and citing the default. (Informational log, not a question.)
   - If NOT covered: write a full decision file with `question`, `best-guess`,
     `alternatives`, `applied`. Apply your best guess and continue.
   _not-mechanically-enforced (harness-level block; no post-hoc audit tool exists for this)_

2. **NEVER enter plan mode** (`ExitPlanMode`). The wave file is the plan.
   _not-mechanically-enforced (harness mode is session-scoped; no artifact to audit)_

3. **NEVER use interactive Bash.** No `sudo`, no `-i` flags (`rebase -i`,
   `add -i`, `commit -i`), no anything that waits on a TTY. The settings
   deny list backs this up; if you somehow construct a command that would
   prompt, settings will halt the call.
   _not-mechanically-enforced (deny-list enforcement in settings.local.json is the gate)_

3a. **NEVER use the Write tool to create a new file in Robot mode.** Use Bash
    heredocs instead (`cat > file <<'EOF' ... EOF`). The Write tool requires
    a prior Read of the file via the Read tool, even for files that don't
    exist yet; Bash `touch` does NOT satisfy this. See "File creation pattern"
    in "Launching a Robot run" below. For editing EXISTING files, the
    standard Read-then-Edit/Write pattern is fine.
    _not-mechanically-enforced (harness-level; no post-hoc artifact to audit)_

4. **On hard blocker** (genuinely cannot proceed — failed install, unrecoverable
   merge conflict, missing file you can't synthesize):
   - Write `.claude/run/blockers/<wave>-<stream>.md` with what blocked, what
     you tried, and what the morning user / Opus reviewer needs to decide.
   - **Halt ONLY that stream.** Other streams in the wave keep going.
   - The coordinator continues to merge whatever streams succeeded.
   _not-mechanically-enforced (presence of blocker files signals compliance; completeness not auditable)_

5. **Maintain status continuously.** Each coordinator writes
   `.claude/run/status/<wave>.md` and updates it:
   - At wave start (timestamp, intent, stream list)
   - After each subagent dispatch (worktree path, stream name)
   - After each subagent return (status: merged / blocked / failed)
   - At wave completion (final branch name, what merged, what didn't)
   → enforced by `check_status_file_freshness` (warn-only TIER_1 in ms-enforce, S-69-E)

6. **Merge to a wave branch, NEVER to `main`.** Each wave creates and merges
   stream worktree branches into `wave/<S-NN>-<short-topic>`. The wave branch
   stays local. Morning review merges to `main` after verification.
   _not-mechanically-enforced (deny rules in settings block raw main checkout; sanctioned tool enforces the path)_

7. **NEVER `git push`.** Settings deny all push variants. If a command
   somehow constructs a push, it will be blocked.
   _not-mechanically-enforced (deny-list enforcement in settings.local.json is the gate)_

8. **NEVER modify `.claude/settings.local.json` or `~/.claude/**`** during a
   Robot run. Settings are immutable for the duration. If you think you need
   a new permission, append an entry to `docs/ACCESS-REQUESTS.md` per the
   convention in that file (categories: `[install]`, `[upgrade]`, `[allow]`,
   `[deny]`). The processor (manual today, automated via S-59) handles the
   actual settings change later. Do NOT write a decision file for this — the
   access-requests queue is the canonical path for needs you can't satisfy
   directly.
   _not-mechanically-enforced (file-write deny in settings is the gate; queue staleness covered by check_access_requests_stale)_

9. **One try on test failures.** Do not aggressively retry. If a stream's tests
   fail, write a blocker file with the failing output, halt the stream.
   _not-mechanically-enforced (behavioral rule; no artifact trail to audit retry attempts)_

10. **No scope creep.** Stick to the wave's deliverables. If you spot adjacent
    issues, write `.claude/run/observations/<wave>-<n>.md` for morning review.
    Do not fix them. The "fix all pre-existing failures" rule was tried and
    walked back; respect that boundary.
    _not-mechanically-enforced (scope is defined per wave; no cross-wave diff tool exists)_

## File and directory layout (per run)

```
.claude/
  ROBOT.md                          # this file (doctrine, tracked)
  AUTONOMOUS-DEFAULTS.md            # default decision register (tracked, evolves)
  waves/<S-NN-TOPIC>.md             # wave prompts (tracked)
  run/                              # PER-RUN OUTPUT — gitignored
    status/
      S-46.md                       # coordinator's live status for that wave
      S-47.md
      ...
    decisions/
      S-46-A-1.md                   # decisions written by coordinator/streams
      S-46-A-2.md
      S-47-B-1.md
      ...
    blockers/
      S-47-C.md                     # hard halts — review needed
      ...
    observations/                   # adjacent-but-out-of-scope findings
      S-46-1.md
      ...
    log/                            # optional free-form per-wave log
      S-46-coordinator.log
      ...
```

The `.claude/run/` directory is gitignored. Morning review archives or deletes
its contents after merging the wave branches.

## Decision file format

```markdown
---
wave: S-46-PIN-RELAX
stream: A
sequence: 1
type: informational | decision | blocker
default-applied: <name of default from AUTONOMOUS-DEFAULTS.md, or "none">
timestamp: 2026-05-27T22:14:03Z
---

## Question / scenario
<what was the fork in the road?>

## Best guess applied
<what I did, in one paragraph>

## Alternatives considered
- <alternative 1, why rejected>
- <alternative 2, why rejected>

## Morning review action
<one of: "confirm and merge", "review diff at <path>", "rollback if X",
"requires human judgment — do not merge wave branch until decided">
```

## Status file format

```markdown
# S-46-PIN-RELAX status
**Started:** 2026-05-27T22:01:12Z  **Last updated:** 2026-05-27T23:47:55Z
**Wave branch:** wave/S-46-pin-relax
**Coordinator model:** opus | **Subagent model:** sonnet

## Streams
- A (deps policy) — DISPATCHED 22:03 → MERGED 22:41 (commit a1b2c3d)
- B (TrustedHostMiddleware) — DISPATCHED 22:03 → MERGED 22:52 (commit e4f5g6h)
- C (gitignore hygiene) — DISPATCHED 22:03 → MERGED 22:18 (commit i7j8k9l)

## Decisions logged
- S-46-A-1.md (informational, default applied)

## Blockers
- (none)

## Verification status
- pip install -r requirements.txt: PASS
- pytest tests/test_trusted_host.py: PASS
- ms-enforce: PASS
- grep -c '^name = ' uv.lock: 38 (was 15 — production deps locked)

## Final state
COMPLETE. wave/S-46-pin-relax ready for morning review + merge to main.
```

## Blocker file format

```markdown
---
wave: S-46-PIN-RELAX
stream: A
type: blocker
timestamp: 2026-05-27T22:33:14Z
---

## What blocked
<one paragraph>

## What I tried
<bullet list of attempts>

## Why I stopped
<rule-citation: "Robot rule 9 — one try on test failures">

## State on disk
- Worktree branch: wave/S-46-pin-relax-A
- Last commit: <sha>
- Files modified: <list>

## Morning action needed
<concrete steps for the human/reviewer>
```

## Launching a Robot run

### Two phases: wave execution vs post-wave merge (added 2026-05-29 post-batch-4; tool shipped S-59-D)

Robot mode has TWO operationally distinct phases that look similar but have
opposite `main` access requirements:

**Phase 1 — Wave execution:** Orchestrator + subagents in worktrees actively
producing wave-branch commits. `main` MUST stay untouched — runaway agents
or unverified merges to main are exactly what the deny rules
(`Bash(git checkout main*)`, `Bash(git switch main*)`) protect against.

**Phase 2 — Post-wave merge:** Waves are COMPLETE with verification recorded;
their branches need to land on main. The deny rules from Phase 1 would catch
legitimate post-wave merges too. The sanctioned channel is
`tools/merge_wave_to_main.py` (shipped in S-59 Stream D):

```
python3 tools/merge_wave_to_main.py wave/S-NN-topic [wave/S-MM-topic ...]
```

The tool does internal lift-restore of the `Bash(git checkout main*)` and
`Bash(git switch main*)` denies via a `try/finally` block — denies are always
restored regardless of success or failure. It runs five pre-flight checks per
branch (branch exists; status file COMPLETE; non-empty diff vs main; ms-enforce
passes; working tree clean), merges with `--no-ff`, aborts cleanly on any
conflict, and appends an audit entry to `docs/MERGE-LOG.md`. Raw deny rules
stay in place permanently; the tool is the only sanctioned exception.

**Pre-S-59 operator handoff** (historical; preserved for context): orchestrator
finished wave run → reported branches ready → operator ran `git checkout main`
from their own terminal. Updated `docs/MERGE-LOG.md` manually. That path is
superseded by the tool but still works for operators who prefer a manual flow.

**Sanctioned path (current):** any agent or session needing to merge to main
invokes `python3 tools/merge_wave_to_main.py <branch> [<branch>...]`. Refuses
if pre-flight checks fail. Writes audit log. Restores denies on exit via
`try/finally`. Does NOT push (push stays operator-only).

**Never:** raw `git checkout main` or `git switch main` from inside any agent
session, even an operator-assist session — those denies are absolute. The
ONE exception is the sanctioned tool described above.

**Tool behavior summary** (`tools/merge_wave_to_main.py`):
1. Pre-flight checks (branch exists; status COMPLETE if file present; non-empty
   diff; ms-enforce TIER_1 passes; working tree clean).
2. Lift `Bash(git checkout main*)` + `Bash(git switch main*)` from deny list.
3. `git checkout main` + `git merge --no-ff <branch>`.
4. On conflict: `git merge --abort`, restore denies, write "ABORTED" audit
   entry, exit non-zero. Never auto-resolve.
5. Append audit entry to `docs/MERGE-LOG.md` (newest at top, method field =
   `tools/merge_wave_to_main.py`).
   → completeness of MERGE-LOG entries enforced by `check_merge_log_completeness` (warn-only TIER_1, S-69-D)
6. Restore denies unconditionally in `finally` block.
7. Does NOT push. Does NOT delete merged branches.

### Architecture (revised 2026-05-29: ONE orchestrator per batch)
_not-mechanically-enforced (prompt-generation behavior; no post-hoc audit of session count)_

**Core rule:** **ONE orchestrator session handles ALL waves in a batch**, not
one orchestrator per wave. The orchestrator session IS the coordinator. Instead
of the user launching a separate Claude Code session per wave, the user fires
ONE Opus orchestrator session that reads all wave files in the batch,
dispatches all streams together (Agent tool, isolation:worktree, model per
each wave's Parallelization section), and merges each stream into the
appropriate wave branch.

**Why one-per-batch instead of one-per-wave:**
- Cross-wave conflict resolution is easier when one orchestrator sees all
  streams' commits (e.g., if S-55-B and S-56-E both touch the same
  ms-enforce file, one orchestrator can merge both correctly).
- User manages one session/terminal instead of N.
- Matches Round 2's empirically-validated pattern (one orchestrator handled
  S-48 + S-49 with 5 concurrent streams; zero issues attributable to the
  unified coordinator).
- Stream-level parallelism is unchanged — 11 streams across 3 waves run as
  concurrently from one orchestrator as they would from three orchestrators.

**The only time multiple orchestrators are warranted:** when a later wave has a
hard dependency on an earlier wave being on `main` first (rare). In that case,
state the dependency explicitly in the wave file's Context section, and the
operator runs the merge handoff between the two orchestrator sessions.

Invocation pattern (from the user, in the orchestrator session):

```
in Robot mode: you are the orchestrator for the SLOP next batch — [N] independent waves to fire concurrently. main is at origin/main commit <SHA>. Waves to handle: .claude/waves/S-NN-A.md, .claude/waves/S-NN-B.md, ... [follow the standard orchestrator startup sequence below]
```
→ prompt must include explicit `git rev-parse origin/main` base, per-stream models, and subagent preamble reference; enforced by `check_orchestrator_prompt_format` (warn-only TIER_1 in ms-enforce, S-69-C)

For a single-wave batch, the same form works with one wave file listed.

**Future-session compliance:** any agent generating Robot-mode prompts (this
project's Claude sessions included) MUST follow the batch architecture above
and SHOULD NOT produce one-orchestrator-per-wave prompts unless the
"multiple orchestrators warranted" exception applies. CLAUDE.md mirrors this
rule at project level so it loads into every session by default.

### Dedicated merge-worktree pattern (added 2026-05-29; batch-5 retro)

Every wave-branch merge operation MUST happen in a **dedicated
`.claude/worktrees/merge-<wave>/` worktree with a detached HEAD**, never in
the shared main working tree. This is the canonical two-phase merge procedure:

**Why dedicated merge worktrees:**
Batch-5 (2026-05-29) produced two HEAD collisions where the orchestrator and a
parallel stream shared the same working tree during the merge phase. The
collisions required manual untangling and delayed morning review. Dedicated
merge worktrees eliminate this class of issue entirely: each wave-branch merge
is fully isolated; the shared tree never changes state during Robot runs; and
the orchestrator can operate in its own named worktree while all streams operate
in their own.

**Canonical procedure for a single wave merge:**
```bash
# Create a named merge worktree for this wave
git worktree add .claude/worktrees/merge-S-NN --detach origin/main

# In that worktree: merge the stream branches
cd .claude/worktrees/merge-S-NN
git merge --no-ff wave/S-NN-stream-A -m "merge: stream A into wave/S-NN"
git merge --no-ff wave/S-NN-stream-B -m "merge: stream B into wave/S-NN"
# ... etc.

# When complete, remove the worktree (do not leave stale merge worktrees)
cd /home/stack/code/slop
git worktree remove .claude/worktrees/merge-S-NN
```

**Rules:**
1. Never run `git merge` in the shared main working tree during a Robot wave.
2. The merge worktree MUST be named `merge-<wave-short-name>` (prefix `merge-`)
   so it is distinguishable from stream worktrees (prefix `agent-`).
3. The merge worktree uses detached HEAD (`--detach origin/main`), NOT a checked-
   out branch. This prevents accidental commits to main from the merge context.
4. Remove the merge worktree after the wave-branch merge is confirmed. Stale
   `merge-*` worktrees are logged as warnings by `check_merge_worktree_pattern`.
5. The post-wave merge-to-main still goes through `tools/merge_wave_to_main.py`
   as documented in the "Two phases" section above — the dedicated-merge-worktree
   pattern governs the intra-wave stream→wave-branch merge step only.

→ enforced by `check_merge_worktree_pattern` (warn-only TIER_1 in ms-enforce, S-69-G)

### Orchestrator startup sequence

1. Read ROBOT.md (this file) — confirm operating under the rules.
   _not-mechanically-enforced (self-referential; no audit artifact produced)_
2. Read `.claude/AUTONOMOUS-DEFAULTS.md` — load the decision register.
   _not-mechanically-enforced (self-referential; no audit artifact produced)_
3. Read the wave file end-to-end — confirm streams, models, deliverables.
   _not-mechanically-enforced (pre-run intent; auditable only via presence of status file)_
4. **Pre-flight fact-check:** spot-check the wave file's factual claims
   against the actual repo. At minimum: every named file path exists with the
   content the wave claims; every named inbound-reference count is current.
   This catches wave-design errors before they propagate (S-47 lesson: the
   wave had docker-compose labels inverted).
   _not-mechanically-enforced (judgment step; outcome visible in decision files)_
5. Create `.claude/run/status/<wave>.md` with start-time. **Use a Bash heredoc,
   not the Write tool, for any new file** (see "File creation pattern" below).
   → enforced by `check_status_file_freshness` (warn-only TIER_1 in ms-enforce, S-69-E)
6. Dispatch the streams concurrently as Agent subagent calls (single message,
   multiple Agent tool uses). Each subagent gets `model:` per the wave's
   Parallelization section, plus the **subagent preamble** (see below) injected
   at the top of the task prompt. The preamble carries the "in Robot mode"
   signal AND the venv-symlink + file-creation rules — subagents won't read
   ROBOT.md on their own.
   → enforced by `check_wave_subagent_preamble` (warn-only TIER_1 in ms-enforce, S-69-B)
7. Watch for blocker/decision file events as streams return.
   _not-mechanically-enforced (coordinator behavior; no artifact audit path)_
8. Merge streams to `wave/<S-NN>-<topic>` (NOT main). Use Bash heredocs for
   commit messages too (avoids any new-file prompts even though commits
   themselves don't create files).
   → enforced by `check_merge_log_completeness` (warn-only TIER_1 in ms-enforce, S-69-D);
   → merge operations in dedicated worktrees enforced by `check_merge_worktree_pattern` (warn-only TIER_1, S-69-G)
9. Update status to COMPLETE.
   → enforced by `check_status_file_freshness` (warn-only TIER_1 in ms-enforce, S-69-E)
10. Exit.
    _not-mechanically-enforced (session termination; not auditable post-hoc)_

### Subagent preamble (REQUIRED in every Agent dispatch)
→ enforced by `check_wave_subagent_preamble` (warn-only TIER_1 in ms-enforce, S-69-B)

The orchestrator includes this verbatim as the first paragraph of every
subagent's task prompt:

```
You are operating in Robot mode (see /home/stack/code/slop/.claude/ROBOT.md).
Before any other action, run these two Bash commands in your worktree cwd:
  ln -sf /home/stack/code/slop/.venv .venv
  ls -la .venv | head -2
The symlink gives you access to the project venv (pytest, ms-enforce,
structlog, etc.). Verify it resolves before proceeding. Without this, any
pytest/ms-enforce invocation will fail with ModuleNotFoundError.

For new file creation, use Bash heredocs (cat > file <<'EOF' ... EOF), NOT
the Write tool — the Write tool requires a prior Read of the file (even for
new files) and Bash touch does NOT satisfy that requirement. For existing
files, Read then Edit is fine.

Do not call AskUserQuestion. Do not git push. Do not git checkout main. Commit
ONLY to your own worktree branch — never merge into or move the wave/* branch
ref; the orchestrator owns all wave-branch merges. On hard blocker, write
.claude/run/blockers/<wave>-<stream>.md and halt only your stream.
```

(The "never move the wave/* ref" rule was added 2026-05-29 after a batch-6 S-67-B
subagent self-merged its commits into the wave branch — harmless that time, but a
subagent advancing a wave branch that is checked out in the orchestrator's merge
worktree can corrupt the worktree state. The orchestrator owns wave-branch merges.)

### File creation pattern (empirically verified 2026-05-28)

The Claude Code Write tool requires the file to have been Read via the Read
tool first — even for new files that don't exist yet. Bash `touch` does NOT
satisfy this; the harness tracks Read-tool calls, not filesystem state.

**Use Bash heredocs for new file creation:**
```bash
cat > .claude/run/status/S-NN.md <<'EOF'
# Wave status content goes here
...
EOF
```

This avoids the Write tool's Read-first requirement entirely, runs under
`Bash(cat *)` allow, and is silent under `defaultMode: "bypassPermissions"`.

For SHORT content, `echo`/`printf` redirect also works:
```bash
echo "single-line content" > path/to/new-file.md
```

For EXISTING file edits, the standard pattern still applies: Read first via
the Read tool, then Edit (or Write).

### Worktree behavior (empirically verified 2026-05-28)

Subagents launched with `isolation: "worktree"` create their worktree under
`/home/stack/code/slop/.claude/worktrees/agent-<id>/` regardless of the
orchestrator's cwd. The Agent tool anchors to the project's git root, not the
parent agent's working directory. This is the desired behavior for SLOP
Robot mode — wave work always lands in the SLOP repo — but worth knowing if
ever sandbox-testing from outside SLOP.

### Verified zero-prompt configuration (2026-05-28; two batteries)

`.claude/settings.local.json` with `defaultMode: "bypassPermissions"` + the
77-rule deny list produces ZERO permission/safety prompts in a **fresh
session**. Verified empirically against 30 tests across two batteries:

**Battery 1** (20 tests, 2026-05-28 daytime):
- Bash with brace expansion, heredocs (quoted `<<'EOF'`), command
  substitution `$(...)`, cd-prefix git, pipes, glob, symlinks
- Read tool including sensitive paths (`/etc/passwd`)
- Edit tool on existing files
- Agent tool with and without worktree isolation
- WebFetch on allowed domains
- Deny-list enforcement (sudo, rm-rf-root rejected as designed)

**Battery 2** (10 tests, 2026-05-29 early morning) — added after older
`acceptEdits`-mode sessions leaked prompts on patterns missed by Battery 1:
- Nested `for`-loop with `$var` interpolation in body
- Multi-line `if/then/else`
- Variable interpolation in conditional body (`$PID` in `[ ... ]`)
- Cross-boundary `mv` (`/tmp/x` → outside test root)
- Subshells `(...)` and brace groups `{...;}`
- Process substitution `<(cmd)`
- Background command `cmd &; wait`
- Heredoc with UNQUOTED EOF (variable interpolation enabled, `<<EOF`)
- 4-stage pipe with redirection (`find | sort | head | tee`)
- Glob in destructive context (`find ... -name 'X*' -delete`)

**Result: 30/30 silent in fresh sessions under bypassPermissions.** The two
categories that leaked in older sessions (`simple_expansion` and "shell
syntax that cannot be statically analyzed") are silenced too — they fire
only when a session is running under `acceptEdits` (the older default)
because `defaultMode` does not live-reload mid-session.

**Practical doctrine:** for autonomous Robot runs, always launch a FRESH
session in a directory whose `.claude/settings.local.json` (or
`.claude/settings.json` for shared) has `defaultMode: "bypassPermissions"`.
Mid-session mode switches do not work. The "command-style discipline"
section in AUTONOMOUS-DEFAULTS.md remains useful as defense-in-depth for
contexts running under the older `acceptEdits` mode, but is not required
for fresh `bypassPermissions` sessions.

**Known caveats — categories that LEAK under acceptEdits but Battery 2
confirmed silenced under fresh bypassPermissions** (empirically observed
in long-running sessions stuck on the older mode):

- Writes to `.claude/waves/` and `.claude/run/` trigger the "sensitive file"
  prompt. The `.claude/` protected-path exemption list is narrow: only
  `.claude/commands`, `.claude/agents`, `.claude/skills`, `.claude/worktrees`
  are exempted. Other `.claude/` subpaths fire the safety check. Workaround:
  use Bash heredoc redirect (`cat > file <<EOF`) instead of the Write tool —
  but even Bash writes to these paths can prompt under acceptEdits.
- `find -delete`: Claude Code's static analyzer refuses to associate
  destructive `find -delete` with a generic `Bash(find *)` allow. Message:
  "cannot be auto-allowed by a Bash(find:*) prefix rule". Under
  bypassPermissions this is silenced like other safety checks; under
  acceptEdits a more specific allow entry (`Bash(find * -delete)`) is
  needed.
- Process substitution `<(cmd)`: fires the syntax-analyzer category in
  acceptEdits. Use intermediate files instead.

These are documented for completeness; they do NOT invalidate the
"fresh bypassPermissions = zero prompts" guarantee from doctrine v4.

**How to extend the test battery for future Robot iterations:** when any
future run hits an unexpected prompt, add a test for that exact pattern to
the permanent battery at [`.claude/robot-test-battery/`](.claude/robot-test-battery/).
See `test-instructions.md` for the numbered tests, `runner.sh` to generate
the operator prompt, and `RESULTS-TEMPLATE.md` for the results format.
A warn-only CI static-analysis job runs monthly via
`.github/workflows/robot-battery-validation.yml`.
The battery should grow over time; ideal end state is that no pattern
verified in a fresh `bypassPermissions` session ever prompts silently.

## Morning review workflow
_not-mechanically-enforced (manual review ritual; individual steps have targeted gates below)_

When the user wakes up:

1. `ls .claude/run/blockers/` — anything here needs immediate attention.
   _not-mechanically-enforced (presence check; completeness not auditable)_
2. `ls .claude/run/decisions/` — scan; most are informational, a few may need a call.
   _not-mechanically-enforced (decision file audit; no completeness gate)_
3. `cat .claude/run/status/*.md` — high-level "did each wave land?"
   → enforced by `check_status_file_freshness` (warn-only TIER_1, S-69-E): stale status files surface here
4. `git branch | grep ^wave/` — list of wave branches ready for review.
   _not-mechanically-enforced (manual step)_
5. For each wave branch: `git diff main..wave/S-NN-topic`, run the wave's
   verification section, decide merge / rollback / fix.
   _not-mechanically-enforced (judgment step)_
6. Once a wave is merged to main, archive its run files: `mv .claude/run
   .claude/run-archive/<date>` (or delete).
   → MERGE-LOG completeness enforced by `check_merge_log_completeness` (warn-only TIER_1, S-69-D)
7. Launch any Round-2 waves that were waiting on Round 1.
   _not-mechanically-enforced (manual orchestration step)_
8. Run `python3 ms-enforce` — check for stale memory entries or BACKLOG issues surfaced overnight.
   → memory staleness enforced by `check_memory_staleness` (warn-only TIER_1, S-69-F)
   → BACKLOG staleness enforced by `check_backlog_stale` (warn-only TIER_1, S-69-A)

## Wave file conventions

### "Authorized deletions" section
_not-mechanically-enforced (wave-file content; checked by author + coordinator at wave-design time)_

If a wave's deliverables include deleting any file, the wave file MUST include
an **"Authorized deletions"** section listing each path with a one-line
rationale and a pre-validated inbound-reference scan result. Without this
section, the AUTONOMOUS-DEFAULTS "no deletions in Robot mode" rule applies and
the agent will defer the deletion to morning review.

Example section in a wave file:

```markdown
## Authorized deletions

The following files may be deleted by this wave's streams:

- `backend/requirements.txt` — stale fossil pinning fastapi==0.115.6; not
  referenced by installer (`installer/backend.py:109` reads the root file).
  `grep -rn "backend/requirements" .` returns 0 inbound refs as of YYYY-MM-DD.
- `<other-path>` — <one-line rationale + inbound-ref status>
```

This makes deletions visible at wave-design time (when errors can be caught)
and lets the agent proceed autonomously when the wave designer has
deliberately authorized them.

### Sanctioned channels (S-68)

Every entry in the Robot deny list is intentional. Over time, recurring
wave-level operations (merge-to-main, post-wave push, recursive delete of
generated files) require lifting specific denies — but doing so by hand-editing
`.claude/settings.local.json` is error-prone and unaudited.

**The sanctioned-channel toolkit** (`tools/sanctioned/`) solves this:

```
tools/sanctioned/
  _lift_restore.py        # lift(), restore(), lifted() context manager
  _audit.py               # write_entry() → docs/SANCTIONED-OPS-LOG.md
  rm_recursive_safe.py    # recursive delete, project tree only
  robot_settings.py       # lift/restore for push + operator handoff
  force_push_tag.py       # force-push a single rewritten tag/ref
  filter_branch_secret_scrub.py  # secret-scrub via git filter-branch
tools/merge_wave_to_main.py      # merge wave branch to main (S-59-D)
```

**Invariant — every tool that lifts a deny MUST:**
1. Call `lifted()` (or `lift()` / `restore()` in an explicit `try/finally`).
2. Write an audit entry via `write_entry()` to `docs/SANCTIONED-OPS-LOG.md`
   (merge ops continue to write to `docs/MERGE-LOG.md`).
3. Restore the canonical wave-mode profile on SUCCESS AND on every ERROR path.
   A tool that lifts and crashes before restore is a security hole.

**Rule: every deny maps to a sanctioned tool OR a no-exceptions-period rationale.**

- Denies in the registry section of `docs/SANCTIONED-CHANNELS.md` have a
  dedicated sanctioned tool that is the ONLY authorized code path for the operation.
- Denies in the no-exceptions section of `docs/SANCTIONED-CHANNELS.md` are
  NEVER lifted by any tool, for any reason — the rationale is documented there.
- Any deny not present in either section is a gap flagged by the
  `check_sanctioned_channels_complete` TIER_1 gate in `ms-enforce` (warn-only).

**Never hand-edit `.claude/settings.local.json` to work around a deny.**
If a deny needs a legitimate one-time lift, the correct path is:
```
# Use the appropriate tool, e.g.:
python3 tools/merge_wave_to_main.py wave/S-NN-topic
python3 tools/sanctioned/robot_settings.py push-then-restore
python3 tools/sanctioned/rm_recursive_safe.py <path-inside-repo>
```

### Post-wave operator handoff
_not-mechanically-enforced (operator choice between handoff/lift patterns; no audit tool applicable)_

The Robot deny list blocks `git checkout main`, `git switch main`, and `git push*`.
This is intentional during a wave (prevents accidental main checkout / push by
an agent in the middle of work) but it also blocks the orchestrator from doing
the final merge-to-main and push when the wave is done.

Two operating patterns; pick whichever fits the moment:

- **Handoff pattern (default):** the user does `git checkout main` before
  merge work and `git push origin main` after. The orchestrator does everything
  in between (merges, doctrine updates, cleanup).
- **Lift pattern (faster, one-time):** use the sanctioned tool
  `tools/sanctioned/robot_settings.py` instead of ad-hoc `python3 -c "import json..."` snippets.

  ```bash
  # Lift push deny, push origin main, restore in finally (audited):
  python3 tools/sanctioned/robot_settings.py push-then-restore

  # Or restore the canonical profile explicitly:
  python3 tools/sanctioned/robot_settings.py restore

  # Restore is a no-op if settings already match the wave-mode profile.
  ```

  `robot_settings.py` wraps every deny-lifting path in `try/finally` (restore
  runs on success AND error), and writes an audit entry to
  `docs/SANCTIONED-OPS-LOG.md` for each operation.  Available subcommands:
  `lift push`, `lift checkout-main`, `lift filter-branch`, `restore`,
  `push-then-restore`.  See `python3 tools/sanctioned/robot_settings.py --help`.

  **Never** hand-edit `.claude/settings.local.json` to lift a deny — always use
  a sanctioned tool so the lift-restore discipline and audit trail are enforced.

## How Robot mode improves over time

After each Robot run, the morning reviewer (user + Opus session) does a short retrospective:

1. **What decisions were unforeseen?** Any decision file marked "not covered by
   defaults" — add a new entry to `AUTONOMOUS-DEFAULTS.md` so next run handles it.
2. **What blockers were avoidable?** Any blocker that should have been caught
   by stricter wave-prompt rules — update the wave-file template.
3. **What settings prompted?** If the morning user sees a halted session
   because a tool prompt fired, the missing allow/deny entry goes into the
   settings update commit for next run.
4. **What was over-allowed?** If anything happened that shouldn't have, tighten
   the deny list.

The retrospective is itself ≤ 10 minutes of work. The file changes that result
get committed under the message `robot: lessons from <date> run`.

## Retrospective ritual

The retro tool (`tools/robot-retro.py`) automates aggregation of a run's
artifacts into a single markdown report. Run it as the first step of every
morning review.

### Step-by-step post-run loop

```bash
# 1. Generate the retro report (output to stdout; optionally save)
python3 tools/robot-retro.py .claude/run-archive/<date>/ \
    --output .claude/run-archive/<date>/RETRO-<date>.md

# 2. Read the report
#    Sections to focus on:
#      "Needs-Judgment" decisions  → require a confirm/rollback call
#      "Blockers"                  → require action before merging
#      "Candidate AUTONOMOUS-DEFAULTS Updates" → proposals to add to the defaults file

# 3. For each "Candidate AUTONOMOUS-DEFAULTS Updates" entry:
#    - Open .claude/AUTONOMOUS-DEFAULTS.md
#    - Add a new entry under the matching category (or a new category)
#    - Cite the date and the decision file that surfaced it

# 4. Commit doctrine updates:
git add .claude/AUTONOMOUS-DEFAULTS.md
git commit -m "robot: lessons from <date> run"

# 5. For each blocker: resolve manually, amend or squash the wave branch,
#    then proceed with the normal morning review merge.
```

### What the report contains

| Section | What to do |
|---|---|
| Summary counts | Quick sanity check — are all streams accounted for? |
| Per-Stream Status | Any stream not COMPLETE needs investigation |
| Decisions — Informational | No action needed; read for awareness |
| Decisions — Needs-Judgment | Confirm or roll back before merging the wave branch |
| Blockers | Requires human resolution; wave branch should NOT merge until fixed |
| Observations | Adjacent findings noted by streams; decide if any need a follow-up wave |
| Proposed Deletions | Review and apply manually if still relevant |
| Candidate AUTONOMOUS-DEFAULTS Updates | Prime material for the lessons commit |

### Keeping the retro lightweight

The retro ritual is not a full code review — it is ≤ 10 minutes of triage.
Deep diffs happen in the normal morning review (`git diff main..wave/S-NN-topic`).
The retro's job is to surface the *meta-level* signals: what the agents decided
autonomously, what they couldn't resolve, and what the defaults register is
missing for next time.

## Out of scope (deliberate)

- No live supervisor session. Defaults + decision files + morning review
  cover ~95% of value at ~5% of the cost of a 30-min-poll Opus loop.
- No multi-day Robot runs. Each run is "one night" and reviewed in the morning.
  Compounding runs without review compounds risk.
- No automated push to remote. Origin only changes from a user-initiated push
  after morning review.
- No auto-merge to main. Wave branches stay isolated; merging is a user act.
