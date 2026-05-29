# Robot mode — autonomous overnight wave execution

## What this is

A discipline + tooling pattern for running wave coordinators (and their subagent
streams) overnight with **zero user prompts**. The user goes to sleep; coordinators
self-execute against documented defaults; any forks are logged for morning review;
nothing dangerous can happen because the settings deny it.

Robot mode is OPT-IN per session. A user launches a wave "in Robot mode" by
prefixing the prompt. Regular interactive sessions are unaffected.

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

2. **NEVER enter plan mode** (`ExitPlanMode`). The wave file is the plan.

3. **NEVER use interactive Bash.** No `sudo`, no `-i` flags (`rebase -i`,
   `add -i`, `commit -i`), no anything that waits on a TTY. The settings
   deny list backs this up; if you somehow construct a command that would
   prompt, settings will halt the call.

3a. **NEVER use the Write tool to create a new file in Robot mode.** Use Bash
    heredocs instead (`cat > file <<'EOF' ... EOF`). The Write tool requires
    a prior Read of the file via the Read tool, even for files that don't
    exist yet; Bash `touch` does NOT satisfy this. See "File creation pattern"
    in "Launching a Robot run" below. For editing EXISTING files, the
    standard Read-then-Edit/Write pattern is fine.

4. **On hard blocker** (genuinely cannot proceed — failed install, unrecoverable
   merge conflict, missing file you can't synthesize):
   - Write `.claude/run/blockers/<wave>-<stream>.md` with what blocked, what
     you tried, and what the morning user / Opus reviewer needs to decide.
   - **Halt ONLY that stream.** Other streams in the wave keep going.
   - The coordinator continues to merge whatever streams succeeded.

5. **Maintain status continuously.** Each coordinator writes
   `.claude/run/status/<wave>.md` and updates it:
   - At wave start (timestamp, intent, stream list)
   - After each subagent dispatch (worktree path, stream name)
   - After each subagent return (status: merged / blocked / failed)
   - At wave completion (final branch name, what merged, what didn't)

6. **Merge to a wave branch, NEVER to `main`.** Each wave creates and merges
   stream worktree branches into `wave/<S-NN>-<short-topic>`. The wave branch
   stays local. Morning review merges to `main` after verification.

7. **NEVER `git push`.** Settings deny all push variants. If a command
   somehow constructs a push, it will be blocked.

8. **NEVER modify `.claude/settings.local.json` or `~/.claude/**`** during a
   Robot run. Settings are immutable for the duration. If you think you need
   a new permission, write a decision file.

9. **One try on test failures.** Do not aggressively retry. If a stream's tests
   fail, write a blocker file with the failing output, halt the stream.

10. **No scope creep.** Stick to the wave's deliverables. If you spot adjacent
    issues, write `.claude/run/observations/<wave>-<n>.md` for morning review.
    Do not fix them. The "fix all pre-existing failures" rule was tried and
    walked back; respect that boundary.

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

### Architecture (revised 2026-05-29: ONE orchestrator per batch)

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

For a single-wave batch, the same form works with one wave file listed.

**Future-session compliance:** any agent generating Robot-mode prompts (this
project's Claude sessions included) MUST follow the batch architecture above
and SHOULD NOT produce one-orchestrator-per-wave prompts unless the
"multiple orchestrators warranted" exception applies. CLAUDE.md mirrors this
rule at project level so it loads into every session by default.

### Orchestrator startup sequence

1. Read ROBOT.md (this file) — confirm operating under the rules.
2. Read `.claude/AUTONOMOUS-DEFAULTS.md` — load the decision register.
3. Read the wave file end-to-end — confirm streams, models, deliverables.
4. **Pre-flight fact-check:** spot-check the wave file's factual claims
   against the actual repo. At minimum: every named file path exists with the
   content the wave claims; every named inbound-reference count is current.
   This catches wave-design errors before they propagate (S-47 lesson: the
   wave had docker-compose labels inverted).
5. Create `.claude/run/status/<wave>.md` with start-time. **Use a Bash heredoc,
   not the Write tool, for any new file** (see "File creation pattern" below).
6. Dispatch the streams concurrently as Agent subagent calls (single message,
   multiple Agent tool uses). Each subagent gets `model:` per the wave's
   Parallelization section, plus the **subagent preamble** (see below) injected
   at the top of the task prompt. The preamble carries the "in Robot mode"
   signal AND the venv-symlink + file-creation rules — subagents won't read
   ROBOT.md on their own.
7. Watch for blocker/decision file events as streams return.
8. Merge streams to `wave/<S-NN>-<topic>` (NOT main). Use Bash heredocs for
   commit messages too (avoids any new-file prompts even though commits
   themselves don't create files).
9. Update status to COMPLETE.
10. Exit.

### Subagent preamble (REQUIRED in every Agent dispatch)

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

Do not call AskUserQuestion. Do not git push. Do not git checkout main. On
hard blocker, write .claude/run/blockers/<wave>-<stream>.md and halt only
your stream.
```

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

When the user wakes up:

1. `ls .claude/run/blockers/` — anything here needs immediate attention.
2. `ls .claude/run/decisions/` — scan; most are informational, a few may need a call.
3. `cat .claude/run/status/*.md` — high-level "did each wave land?"
4. `git branch | grep ^wave/` — list of wave branches ready for review.
5. For each wave branch: `git diff main..wave/S-NN-topic`, run the wave's
   verification section, decide merge / rollback / fix.
6. Once a wave is merged to main, archive its run files: `mv .claude/run
   .claude/run-archive/<date>` (or delete).
7. Launch any Round-2 waves that were waiting on Round 1.

## Wave file conventions

### "Authorized deletions" section

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

### Post-wave operator handoff

The Robot deny list blocks `git checkout main`, `git switch main`, and `git push*`.
This is intentional during a wave (prevents accidental main checkout / push by
an agent in the middle of work) but it also blocks the orchestrator from doing
the final merge-to-main and push when the wave is done.

Two operating patterns; pick whichever fits the moment:

- **Handoff pattern (default):** the user does `git checkout main` before
  merge work and `git push origin main` after. The orchestrator does everything
  in between (merges, doctrine updates, cleanup).
- **Lift pattern (faster, one-time):** the user lifts the relevant denies in
  `.claude/settings.local.json` (and adds matching allows) before the
  orchestrator starts the post-wave batch. The orchestrator does everything
  end-to-end, then restores the denies as the final step. Useful when there
  are multiple waves to merge in one sitting.

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

## Out of scope (deliberate)

- No live supervisor session. Defaults + decision files + morning review
  cover ~95% of value at ~5% of the cost of a 30-min-poll Opus loop.
- No multi-day Robot runs. Each run is "one night" and reviewed in the morning.
  Compounding runs without review compounds risk.
- No automated push to remote. Origin only changes from a user-initiated push
  after morning review.
- No auto-merge to main. Wave branches stay isolated; merging is a user act.
