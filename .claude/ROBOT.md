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

The user (or orchestrator) starts each wave coordinator in its own session with:

```
in Robot mode: execute the wave defined in .claude/waves/S-NN-TOPIC.md as coordinator.
```

The "in Robot mode" prefix is the signal. The coordinator:

1. Reads ROBOT.md (this file) — confirms it's about to operate under the rules.
2. Reads `.claude/AUTONOMOUS-DEFAULTS.md` — loads the decision register.
3. Reads its wave file — confirms streams, models, deliverables.
4. Creates `.claude/run/status/<wave>.md` with start-time.
5. Dispatches its subagent streams (concurrent, as the wave's Parallelization
   section dictates). Each subagent gets a one-line "in Robot mode" preamble
   to its task prompt.
6. Watches for blocker/decision file events as streams return.
7. Merges streams to `wave/<S-NN>-<topic>` (NOT main).
8. Updates status to COMPLETE.
9. Exits.

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
