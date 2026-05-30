# Robot-mode default decision register

This file is the static "supervisor brain" for Robot mode (see `.claude/ROBOT.md`).
Wave coordinators and subagents consult it whenever they would otherwise call
`AskUserQuestion`. Each entry covers one anticipated decision category, gives the
**default action**, and names the **escalation condition** under which the agent
should write a full decision file instead of silently applying the default.

This document EVOLVES. After each Robot run, lessons-learned entries get added
under the `robot: lessons from <date> run` commit pattern.

---

## Category: documentation consolidation
_not-mechanically-enforced (all entries in this category are judgment calls; no audit tool applicable)_

### Two docs with the same purpose, one substantive + one stub
**Default:** Keep the substantive file at its current location. Replace the stub
with a single line `> See [{canonical}](path) for {purpose}.` Update inbound
references.
**Escalate when:** the stub has unique sentences not present in the substantive
file (then it's actually a fork, see next entry).

### Two docs with the same purpose, both substantive (forked content)
**Default:** Prefer `docs/<name>.md` over root `<name>.md` (project convention
is to consolidate under `docs/`). MERGE unique content from the loser into the
canonical. Do not silently drop sentences — if two sentences disagree on the same
topic, log both in the decision file and keep the one that matches current code.
**Escalate when:** the two files describe genuinely different procedures (not
just different phrasings) — write a decision file naming both and apply the
docs/-located version pending review.

### Inbound references to renamed/deleted docs
**Default:** Update every inbound reference to point to the new canonical
location. Use `grep -rn` to find them.
**Escalate when:** a reference is in a place the agent doesn't have write
access to (e.g., an external URL, a published release note).

---

## Category: dependency / lockfile
_not-mechanically-enforced (all entries in this category require runtime judgment; no static audit tool applicable)_

### `uv lock` resolves a major version bump (e.g., pydantic 2.x → 3.x)
**Default:** ABORT the lock update. Restore the previous `uv.lock`. Write a
decision file naming the package, the major-version transition, and the cap
that should be added to `requirements.txt` to block it.
**Escalate:** always — major bumps are never silently accepted.

### `pip-audit` flags a new CVE against the proposed lockfile
**Default:** Compare the new CVE set against the previous lockfile's CVE set.
If the new lockfile introduces a CVE not present before, ABORT and restore
previous. If the new lockfile only resolves existing CVEs, accept.
**Escalate:** always for new CVEs introduced; never for CVEs resolved.

### Wheel install fails on `pip install`
**Default:** Halt the stream. Write blocker citing the package + the install
error output.
**Escalate:** always.

### Transitive dependency floor changes (e.g., starlette 0.52 → 1.0)
**Default:** Accept the change if `requirements.txt` does not name the
transitive dep. The intent file constrains direct deps only; transitives flow
through.
**Escalate when:** the transitive change crosses a known compatibility boundary
documented in `installer/DEPENDENCIES.md`.

---

## Category: test failures
_not-mechanically-enforced (runtime behavior; ms-enforce runs tests but does not audit decision files)_

### A test fails after a code change in scope
**Default:** First, attempt to understand the failure (read the test, read what
changed). If the failure is in scope and the fix is < 10 lines, apply the fix.
Otherwise halt that stream and write a blocker with the failing output.
**Escalate when:** the fix would require touching files outside the stream's
scope.

### A test was already failing before the wave started (pre-existing breakage)
**Default:** Do NOT fix it. Note it in observations. Continue with the wave's
in-scope work. The "fix all pre-existing failures" rule was added then walked
back; respect that boundary.
**Escalate:** never — this is settled doctrine.
**Inverse:** the no-fix-all rule applies to FOCUSED waves doing other work. It does
NOT mean we never fix pre-existing failures. Dedicated cleanup waves are the
authorized scope: S-57 (TIER_2), S-58 (TestClient), S-66 (post-S-58 unmask),
S-67 (doc+tooling hygiene). When BACKLOG accumulates ≥10 open items in one
category, draft a cleanup wave for the next batch.

### BACKLOG entry sits bare `[ ]` for >14 days
**Default:** This is a process failure, not a normal state. The pre-batch BACKLOG
triage step (see ROBOT.md) should have either (a) folded the entry into a wave,
(b) explicitly parked it with a re-eval trigger, or (c) marked it won't-fix with
a reason. Surface stale `[ ]` entries during the next batch-planning conversation
and assign a target. Pure `[ ]` is not an acceptable end state.
**Escalate:** when an entry has bumped its date forward without progressing
status, flag it as triage-failure rather than normal pending.
→ enforced by `check_backlog_stale` (warn-only TIER_1 in ms-enforce, S-69-A)

### A test fails intermittently
**Default:** Run it three times in isolation. If 3/3 pass, treat as flaky and
proceed (note in observations). If any of the 3 fail, treat as a real failure
per "in-scope test failure" entry above.

### A snapshot/coverage test "fix" makes the test pass in the worktree but the change is suspicious
**Default:** If a snapshot or coverage-dependent test changes UNEXPECTEDLY in a
worktree (e.g., a snapshot shrinks dramatically, a coverage assertion drops to
zero, a JSON contract loses fields), STOP and verify in a real checkout before
committing the change. Worktree subagents lack gitignored runtime artifacts
(`data/coverage_map.json` in particular — generated by `ms-coverage` only in
the main repo, gitignored at line 77). A worktree without that file produces
an "empty coverage" output that snapshots will rewrite to match — that's NOT
a fix, it's masking a bug.

**Escalate:** always when the change deletes >50% of a snapshot's content or
zeros out a coverage assertion. Write a decision file; do NOT commit the
change in the worktree. Run the test in the main repo (where the gitignored
artifacts exist) and either accept the original snapshot or surface a real
fix.

**Lesson:** S-58 Stream C (2026-05-29) attempted to "fix" a snapshot by
shrinking a 118-line snapshot to 40 lines because the worktree was missing
`data/coverage_map.json`. The coordinator caught it at verification and
reverted. Captured in `S-58-MERGE-2-stream-c-snapshot-regression.md`.

The broader pattern: **any worktree-only "fix" to a test that depends on
gitignored runtime artifacts is a worktree-artifact trap.** Verify in the
real checkout before merging the worktree's commit.

**Known gitignored artifacts that false-fail in a worktree** (present in the main
checkout, ABSENT in any `git worktree`): `data/coverage_map.json` (coverage
snapshots), `backend/static` (built frontend assets → favicon/static-route +
`test_cli_snapshots` tests), `.claude/run-archive/**` (the track-status gate reads
wave-file run-archive references), and `.venv` (imports). When you MUST run
ms-enforce or the suite in a worktree, symlink these from the main checkout AND add
them to the worktree's `.git/info/exclude` (else the track-status gate flags the
symlinks themselves as untracked). `tools/merge_wave_to_main.py::_run_ms_enforce`
now bakes this in for its branch-isolated pre-flight (batch-6). **Lesson:** batch-6
morning-merge verification false-failed on `backend/static` (favicon) and
`.claude/run-archive` (track-status) in the integration worktree; both pass on
`main`. Don't treat them as wave regressions.

---

## Category: git operations

### Merge conflict between two streams within the same wave
**Default:** Abort the merge. Write a blocker file naming the conflicting paths
and lines. Leave both stream branches intact. The wave's "streams touch disjoint
files" claim has failed and needs human triage.
**Escalate:** always — this is a wave-design failure to surface.
_not-mechanically-enforced (conflict is detected by git at merge time; no separate audit tool)_

### Merge conflict between a wave branch and `main`
**Default:** Should not happen in Robot mode (waves don't merge to main).
If it does (e.g., a wave branch is rebased), abort and write a blocker.
_not-mechanically-enforced (deny list prevents the direct path; sanctioned tool handles the exception)_

### A commit needs a co-author tag
**Default:** Use `Co-Authored-By: Claude {model-name} <noreply@anthropic.com>`.
Match the model that did the work (subagent's model, not the coordinator's).
_not-mechanically-enforced (formatting convention; no post-hoc audit tool exists)_

### `git push` is attempted
**Default:** Settings deny it. If a command somehow constructs a push,
the deny list halts it; the stream should write a blocker citing the
attempted push and what it was trying to accomplish.
**Escalate:** always — pushing is never autonomous.
_not-mechanically-enforced (deny-list enforcement in settings.local.json is the gate)_

### Wave-branch merge operations use dedicated merge worktrees
**Default:** All intra-wave merges (stream branch → wave branch) MUST happen in
a dedicated `.claude/worktrees/merge-<wave>/` worktree with detached HEAD, never
in the shared main working tree. See ROBOT.md § "Dedicated merge-worktree pattern"
for the canonical procedure.
**Escalate:** never — use the standard pattern. If you cannot create a new
worktree (e.g., disk full), write a blocker rather than proceeding in the shared tree.
→ enforced by `check_merge_worktree_pattern` (warn-only TIER_1 in ms-enforce, S-69-G)

### Every merge to main gets a MERGE-LOG entry
**Default:** When merging via `tools/merge_wave_to_main.py`, the tool auto-appends
the audit entry. For manual flows (operator does `git checkout main` + merge),
manually append to `docs/MERGE-LOG.md` before pushing.
**Escalate:** never — this is a mechanical follow-through step, not a decision.
→ enforced by `check_merge_log_completeness` (warn-only TIER_1 in ms-enforce, S-69-D)

### Status file must be updated when streams complete
**Default:** After each stream returns (merged/blocked/failed), the coordinator
updates `.claude/run/status/<wave>.md` with the stream's outcome and timestamp.
At wave completion the status is set to COMPLETE.
**Escalate:** never — mechanical follow-through.
→ enforced by `check_status_file_freshness` (warn-only TIER_1 in ms-enforce, S-69-E)

---

## Category: file deletion / rename / move

### Delete a file flagged as orphan
**Default:** In Robot mode, NEVER delete a file. Move it to `.claude/run/proposed-deletions/<path>.txt` (a manifest line) for morning review.
**Escalate:** always — deletions are reviewed.

### Wave file explicitly directs a deletion
**Default:** Check the wave file for an **"Authorized deletions"** section. If
the path being deleted appears in that section *with a one-line rationale*,
the wave's authorization overrides the default — proceed with the deletion.
If no Authorized deletions section exists, or the path is not listed in it,
apply the orphan-deletion default above (queue to proposed-deletions, do NOT
delete).
**Escalate when:** the path is listed but the rationale is missing or ambiguous —
queue to proposed-deletions and log a decision file.
**Lesson:** S-46 wave instructed deletion of `backend/requirements.txt` without
an Authorized deletions section. Stream A correctly deferred. The wave file
convention added 2026-05-28 closes this gap: future waves authorize deletions
explicitly or have them deferred.

### Rename or move a tracked file
**Default:** Allowed if the wave explicitly calls for it. Update all inbound
references in the same commit.
**Escalate when:** inbound reference scan finds matches in files the agent
hasn't been granted write access to.

### Untracked file appears that the agent didn't create
**Default:** Leave it alone. Note in observations. Don't delete or modify.

### Creating a new file
**Default:** Use Bash heredoc (`cat > path/to/file <<'EOF' ... EOF`), NOT the
Write tool. The Write tool requires a prior Read of the file via the Read
tool — even for files that don't exist yet — and Bash `touch` does NOT
satisfy this requirement (the harness tracks Read-tool calls, not filesystem
state). Heredoc bypasses this constraint and runs silent under
`bypassPermissions`. Short single-line content can use `echo "..." > file` or
`printf "..." > file` instead.
**Escalate:** never — this is a mechanical pattern, no judgment needed.
**Lesson:** Empirically verified 2026-05-28 in the 20-test battery. The
proposed touch-then-Write workaround failed because the harness checks Read
history, not file existence.

### Editing an existing file
**Default:** Read the file via the Read tool first, then use Edit or Write.
Bash `cat` does NOT satisfy the Read-tracking; only the Read tool does.
**Escalate:** never.

---

## Category: web / network
_not-mechanically-enforced (runtime network behavior; no audit tool applicable)_

### WebFetch returns a 301/302 redirect to a different host
**Default:** Re-fetch using the redirect URL the response provided. No
decision file needed — this is a routine network behavior. The Read of the
redirect URL is automatically allowed by the WebFetch domain-allow rules
provided the redirect target's domain is also on the allow list.
**Escalate when:** the redirect target domain is NOT on the allow list — log
a decision file and skip the fetch (or use a different source).

---


### Intra-wave merge conflict in a file the wave assigns to multiple streams
**Default:** If the conflict is purely ADDITIVE (both sides add disjoint blocks
to a file the wave knowingly assigns to multiple streams — e.g., ms-enforce check
registrations, package __init__.py docstrings, allowlist/denylist additions),
resolve by KEEPING BOTH and log a decision file (`<wave>-MERGE-N.md`)
documenting the resolution. Do not abort.
**Escalate when:** the conflict involves semantic overlap, contradictory edits to
the same lines, or risk of content loss — then apply the strict abort default
above.
**Lesson:** Round 2 (S-48 + S-49, 2026-05-28) produced 3 such conflicts (ms-enforce
check_track_status + check_referenced_files; tools/ms_deps/__init__.py docstring x2).
The strict abort default's "disjoint files" premise didn't apply because the wave
explicitly assigned multiple streams to the same registration file. Aborting would
have wasted the parallel work for no safety gain.
**NEVER use `git merge=union` to auto-resolve these.** Union is LINE-level: for
source files whose additive blocks share boilerplate (function bodies with
identical `_rc, out = _run(...)` / `return True, ...` lines, near-identical
registration lines), it INTERLEAVES the blocks — weaving one function's body into
another, producing a function that returns None and crashes the runner. Resolve
"keep both" at the WHOLE-BLOCK level instead: for N=2 streams, strip markers
keeping each side's complete blocks; for N>2 streams touching one file, reconstruct
deterministically (difflib each side's inserts vs the merge-base, concatenate
block-wise) and verify the rebuilt file parses + runs. **Lesson:** S-69 (batch-6,
2026-05-29) — `merge=union` interleaved 7 `check_*` gate functions in `ms-enforce`;
`check_backlog_stale` lost its return path → `run_tier` crashed on a None unpack.
Reconstructed via difflib (`S-69-MERGE-1` decision). Batch-6's merge-to-main hit
the same file again across S-67/S-68/S-69 and used the difflib reconstruction.

### Known additive-registration files (auto-pin in every wave's Cross-wave dependencies)
**Default:** Treat the following as a STANDING list of known multi-stream
additive-registration files. Whenever a wave has ≥2 streams that each touch one of
them, the wave file's "Cross-wave dependencies" section MUST pin it keep-both-whole-block
(per the intra-wave-conflict default above) WITHOUT waiting to discover the overlap at
merge-time — these are known plural touchpoints, not surprises:
- **`ms-enforce` TIER_1 registration** — each stream APPENDS its own `check_*` function +
  its TIER_1 registration tuple; never reformat a neighbour's block. (Recurring since
  S-68/S-69/S-75; S-75's disjointness claim missed this 3-way touch — BACKLOG `:166`.)
- **Lint baselines** `.linecount-baseline.json`, `.factprobe-baseline.json`,
  `.probe-health-baseline.json` — additive rows (shrink-only ratchets); keep-both on
  conflict, never drop a row.
**Why a standing list:** before this, the additive-file set was referenced only ad hoc in
MERGE-LOG history, so each wave re-discovered it at merge-time. The list (mirrored in the
wave `_TEMPLATE.md` Robot-mode comment) lets pre-flight auto-pin them. The list itself can
rot — when a NEW recurring additive-registration file appears, add it here in the same
stroke that introduces it. **Escalate when:** a "registration" turns out to carry semantic
overlap (contradictory edits to the same logical entry) — then it is NOT a clean additive
keep-both; apply the strict abort default.

### Command-style discipline (avoid hardcoded safety-check prompts)

**Default:** Write Bash commands that the harness static analyzer can
pre-resolve. This avoids hardcoded safety-check prompts that fire even when
the operation itself is on the allow list.

Patterns to AVOID:
- `for X in ...; do ... done` with variable interpolation in the body — use
  `xargs` or explicit per-item commands instead.
- Multi-line `if/then/else` — use single-line tests with `&&`/`||` chains.
- Variable interpolation inside loop bodies (`$pid`, `${name}`) — when the
  analyzer can't see the value statically, it fires "simple_expansion".
- Brace expansion `path/{a,b,c}` — fires "Brace expansion" even with
  `Bash(mkdir *)` on allow.
- Complex command substitution in conditional bodies.

Patterns that work cleanly:
- Single-line commands with explicit arguments.
- Repeated explicit `git worktree remove --force <path>` calls instead of a
  `for` loop. (Or `git worktree list --porcelain | ... | xargs` if needed.)
- Heredocs (`cat > file <<'EOF'`) for new file content — these are clean
  EXCEPT for writes to `.claude/waves/` and `.claude/run/` (see below).
- Pipes (`cmd1 | cmd2`) — clean.
- Command substitution at top level (`mkdir x-$(date +%s)`) — clean.
- Process substitution `<(cmd)` — clean under bypassPermissions; LEAKS
  under acceptEdits (fires "process_substitution" safety check). Use
  intermediate files in acceptEdits sessions.
- `find ... -delete` — clean under bypassPermissions; LEAKS under
  acceptEdits ("cannot be auto-allowed by a Bash(find:*) prefix rule").
  Workaround in acceptEdits: add `Bash(find * -delete)` to allow list
  explicitly, or use a helper-script pattern (Python subprocess to invoke
  the delete via os.unlink / shutil.rmtree).

Sensitive-path writes (`.claude/waves/`, `.claude/run/`):
- The `.claude/` protected-path exemption list is narrow: only
  `commands/`, `agents/`, `skills/`, `worktrees/` are exempted. Writes to
  `.claude/waves/` and `.claude/run/` fire the sensitive-file safety
  prompt. Silenced under bypassPermissions; LEAKS under acceptEdits.
  No clean workaround — accept the occasional prompt or use the
  "always allow access to waves/" option (#2 in the prompt).

**Escalate:** never — this is operator-style discipline, not a decision.
**Why:** `bypassPermissions` silences these in fresh sessions (Round 2
verified), but older `acceptEdits` sessions still fire them. Writing simpler
commands keeps any session class silent.

### Prior orchestrator session interrupted mid-wave (locked worktrees, unmerged commits)
**Default:** Inspect each locked worktree to verify the stream's work is intact
(commit reachable, tests passing in worktree). If yes, RESUME from the merge
step rather than re-dispatching — write a `ROUND-N-RESUME.md` decision file
documenting which prior session's work is being adopted, with the worktree
SHAs. Do not unlock the worktrees until after the merge step succeeds (the
locks are stale but provide a safety boundary against accidental tampering).
**Escalate when:** the prior session's commits don't pass their stream's
verification, or the worktree state is ambiguous (uncommitted changes, dirty
tree). Then re-dispatch fresh and log the discarded work in observations.
**Lesson:** Round 2 (2026-05-28) — opus-4.8 orchestrator found five locked
worktrees from a prior opus-4.7 session that had been interrupted before merge.
Resuming saved ~30 min of redundant agent work with no quality loss.

---

## Category: tool / settings / permission
_not-mechanically-enforced (runtime permission behavior; queue-staleness covered by check_access_requests_stale)_

### A tool call would prompt for permission (not on allow list)
**Default:** Append an entry to `docs/ACCESS-REQUESTS.md` under the `[allow]`
category describing the missing permission, why it's needed, and the
exact tool-pattern string. Then either: (a) take an alternate path that
IS on the allow list (preferred when possible), or (b) halt the stream
with a blocker referencing the queue entry.
**Escalate:** never — the queue file is the canonical path. The processor
(manual today, automated via S-59) applies the change. Do NOT call
AskUserQuestion; do NOT modify settings.local.json directly.

### A package needs to be installed (pip / uv / system)
**Default:** Append an entry to `docs/ACCESS-REQUESTS.md` under the
`[install]` category. Then either: (a) take an alternate path that doesn't
need the package (preferred when possible), or (b) halt the stream with a
blocker referencing the queue entry. The S-49 refresh-train integration
(planned in S-59) will pick up `[install]` entries and add them to
`requirements*.txt` automatically.
**Escalate:** never — same as the allow-list case.

### A package needs to be upgraded beyond what S-49 refresh-train auto-resolves
**Default:** Append an entry to `docs/ACCESS-REQUESTS.md` under the
`[upgrade]` category, naming the package, the current version, the desired
version, and what's blocking the auto-resolution (e.g., a transitive cap
from another dep). The S-49 train handles routine upgrades; the
access-requests queue handles the exceptional cases.
**Escalate:** never.

### `.claude/settings.local.json` modification is needed
**Default:** Forbidden during Robot run. Append an entry to
`docs/ACCESS-REQUESTS.md` under the appropriate category (`[allow]` or
`[deny]`). The queue is the canonical path; do not write a settings-change
decision file or hand-edit settings.local.json.

### A bash command needs a new flag or pattern not on the allow list
**Default:** Try a different command pattern that IS on the allow list. If no
alternative exists, write a decision file naming the command + why it's needed.

---

## Category: orchestrator dispatch pattern

### How to structure a Robot batch of multiple waves
_not-mechanically-enforced (prompt-generation behavior; enforced by convention and CLAUDE.md); orchestrator prompt CONTENT is checked by `check_orchestrator_prompt_format` (warn-only TIER_1, S-69-C)_
**Default:** **ONE Opus orchestrator session handles ALL waves in the batch.**
The orchestrator reads all wave files, dispatches all parallel streams in one
big message (or as few messages as the sequential dependencies allow), and
merges each stream to its appropriate wave branch. The user manages ONE
session/terminal.
**Escalate when:** a wave in the batch has a hard dependency on another wave
being on `main` first (the dependency must be stated explicitly in the wave
file's Context section). Then the operator runs an orchestrator for the
prerequisite, does the merge handoff, and runs a second orchestrator for the
dependent wave.
**Lesson:** Round 2 (2026-05-28) validated one orchestrator handling
S-48 + S-49 concurrently with 5 streams. The next-batch planning briefly
drifted to one-prompt-per-wave (2026-05-29) and was corrected. Doctrine
mirrored to CLAUDE.md so future sessions don't deviate.

### Computing the base commit ("main HEAD") for a batch
**Default:** Resolve the batch base with `git rev-parse origin/main`, NOT
`git rev-parse HEAD`. Label it as `origin/main` in the orchestrator prompt. The
orchestrator re-confirms `origin/main` at startup and rebases the wave branches
on it if it has advanced since the prompt was written.
**Escalate when:** local HEAD and `origin/main` disagree and `origin` is
unreachable — surface a blocker rather than guess a base.
**Lesson:** Batch 4 (2026-05-29) — the prompt stated main HEAD `d34cb2a`, which
was actually the unmerged `wave/S-58` tip; real `origin/main` was `ed7e130`. The
local working-copy HEAD can be ahead/behind/diverged from origin (e.g. the
operator-assist session pushes commits after the orchestrator spawns). The
orchestrator self-corrected and rebased, but the error was avoidable — generate
the base SHA from `git rev-parse origin/main` at prompt-writing time.
→ enforced by `check_orchestrator_prompt_format` (warn-only TIER_1 in ms-enforce, S-69-C)

### Subagent preamble inclusion in Agent dispatch
**Default:** Every Agent tool dispatch MUST include the standard subagent preamble
(venv-symlink + file-creation-heredoc + no-AskUserQuestion + no-push + no-checkout-main
rules) as the first paragraph of the task prompt. See ROBOT.md § "Subagent preamble".
**Escalate:** never — include verbatim.
→ enforced by `check_wave_subagent_preamble` (warn-only TIER_1 in ms-enforce, S-69-B)

### A wave's verification step requires running another wave's verification first
**Default:** Treat as cross-wave dependency. Don't try to chain inside the
orchestrator — surface as an observation and run the second wave's
verification post-merge in morning review.

---

## Category: agent / subagent coordination
_not-mechanically-enforced (runtime coordination behavior; no audit tool applicable)_

### A subagent returns with status "failed" but no blocker file
**Default:** Coordinator writes the blocker file on the subagent's behalf,
citing what info is available from the agent's return message. Marks stream
as blocked. Continues with other streams.

### A subagent takes longer than expected (no return after 30 min)
**Default:** Wait. The harness handles long-running subagents. Do not retry,
do not cancel.
**Escalate when:** a subagent has been running > 2 hours with no return.

### Coordinator can't dispatch a subagent (Agent tool error)
**Default:** Retry once. If still failing, halt the wave and write a wave-level
blocker.

### Processor-pattern contract (parallel streams sharing a symbol)
**Default:** Any wave whose parallel streams share a symbol — one stream
*produces* it (a dict, a class, a module-level constant, a function signature)
and another *consumes* it — MUST pin the exact symbol name AND shape in the wave
file's Deliverables section before dispatch. "Pin" means: the producing stream's
deliverable lists the public symbol(s) it ships verbatim (name, type, and for
callables the signature), and the consuming stream's deliverable imports exactly
those. Neither stream is then free to drift the interface. When you draft or
review such a wave, treat an unpinned shared symbol as a wave-design defect:
surface it as a blocker (wave instructions are wrong/impossible) rather than
guessing a shape at runtime.

**A shared symbol INCLUDES the filename / path of any tool, harness, or module a
stream ships that another stream references in code or doctrine.** If Stream X
ships `tools/foo.py` and Stream Y's doctrine/import names that path, pin the path
in X's Deliverables — not just the functions inside it. The filename is part of
the interface.
**Escalate when:** a shared symbol is discovered at merge time that the wave file
never pinned — write a decision file, commit a minimal adapter to bridge the two
shapes (do NOT rewrite either stream's work), and flag the wave file for a
pinning amendment.
**Lesson:** S-59 (2026-05-29) dispatched Streams A and B in parallel against an
under-specified interface — Stream A imported an `APPLIERS` dict; Stream B shipped
standalone `apply_*` functions. The wave file's "Helper modules for the four
category appliers" never pinned the symbol/shape, so neither stream was "wrong."
An adapter (`tools/access_request_appliers.py` `APPLIERS` mapping +
`_*_adapter` shims, consumed by `tools/process_access_requests.py`) was committed
at merge time (`1b192d5`). S-68 and S-69 (the sanctioned-channel toolkit and
audit-tool family) apply this rule prospectively — S-68 pins the
`tools/sanctioned/_lift_restore.py` and `_audit.py` public symbols in its
Deliverables section.
**Lesson (filename-as-symbol):** S-73 (batch-7, 2026-05-29) — Stream C's doctrine
referenced the pre-flight harness as `tools/preflight_harness.py`; Stream E
actually shipped `tools/preflight_wave.py`. The harness FILENAME was never pinned
in Deliverables (only the `score_wave()` interface and tier-string were), so C
guessed it from an absent-in-its-worktree file. Reconciled at merge (`S-73-MERGE-2`:
fixed the two doc refs to the shipped name). Fix: pin tool/harness paths, not just
their contents.

---

## Category: scope / discovery
_not-mechanically-enforced (runtime judgment; no audit tool applicable)_

### Agent discovers an issue adjacent to the wave's scope
**Default:** Write `.claude/run/observations/<wave>-<n>.md` with the finding.
Do NOT fix it. The wave's deliverables stay the boundary.
**Escalate:** never (just log).

### Agent discovers the wave's instructions are wrong or impossible
**Default:** Halt the affected stream. Write a blocker file naming what's
impossible and what the wave file claimed.
**Escalate:** always — the wave file needs revision before another run.

### A wave's verification step fails
**Default:** Halt at verification. Write a blocker with the verification
output. Do not attempt to fix the verification target (that's morning review).

---

## Category: model / cost
_not-mechanically-enforced (pre-decided in wave files; no runtime audit tool)_

### A subagent should be on a different model than the wave file says
**Default:** Follow the wave file. Models are pre-decided.
**Escalate:** never (or write an observation for next-run tuning).

### Coordinator wants to spawn an unplanned helper agent
**Default:** Don't, in Robot mode. Stick to the wave's planned streams.

---

## Category: project continuity / memory hygiene

### Auto-memory entries contain dated language older than 60 days
**Default:** Do not auto-delete or auto-edit memory entries. Surface the stale
entries as a warning during morning review. The operator prunes or updates them
in a focused commit. Memory entries that reference "today", "this session", or
explicit dates older than 60 days are the target; conservative—only flag entries
with parseable dates, never entries with vague recency language.
**Escalate:** never — flag only, human prunes.
→ enforced by `check_memory_staleness` (warn-only TIER_1 in ms-enforce, S-69-F)

---

## Category: knowledge-lifecycle / gap-discovery ritual

See CLAUDE.md § "Knowledge-Lifecycle & reconciliation" and ADR 0020
(`docs/adr/0020-knowledge-lifecycle.md`) for the pinned vocabulary
(GROUND / XREF / INDETERMINATE / UNPROBED) and the discipline: *a green light is only
trustworthy if it can go red against physics.*

### Gap-discovery ritual cadence (session-relative, NOT a silent wall-clock cron)
**Default:** The doc-vs-reality reconciler runs **session-relative**, piggybacked on
the **SessionStart** boundary hook — NOT a silent wall-clock cron. At session start,
the dev-time reconciler (`tools/audit_doc_reality.py` → `ms-enforce check_doc_reality`,
warn-only) reconciles the SLOP AI Agent's runtime reality view + a host-side probe
(reached via the operator's **ambient SSH** at `ssh <host> slop-reality-probe` — no
tool stores a credential) against the documented claims. GROUND-confirmed,
load-bearing `DRIFT` is filed to `docs/BACKLOG.md` as a `[gap-discovery]` entry;
everything else (`INCONSISTENT`/XREF/low-confidence) goes to a lower-tier queue that
does NOT count against BACKLOG triage discipline. Findings dedup — update an existing
entry, never re-file. Host unreachable ⇒ the probe emits `INDETERMINATE` (loud), never
`OK`. The operator is in the **decision (triage)** path only — never the **detection**
path; the human provides SSH auth, not detection.
**Escalate when:** the host probe emits `DRIFT` on a claim that is load-bearing for a
deploy/runbook step (surface it for the current session, don't just queue it), OR the
`[gap-discovery]` queue floods (the flood→ignore-forever loophole that
`check_backlog_stale` exists to fight) — then surface the queue volume during the next
batch-planning conversation rather than letting it silently grow.

### A `[gap-discovery]` BACKLOG entry needs triage
**Default:** Treat `[gap-discovery]` entries under the same BACKLOG triage discipline
as any other open item — they must resolve to `[→ S-NN-stream]`, `[park: re-eval
<DATE>]` (with a measurable trigger + backstop date + owner), `[x]`, or `[—]`. They are
drained by a dedicated **cleanup wave** (the S-57/S-58/S-66/S-67 pattern), NOT
one-at-a-time, and NOT by a focused wave (the no-fix-all-failures rule applies to
focused waves only). A `[gap-discovery]` entry carries its own GROUND evidence line
(e.g. "probed 10.0.1.51:8080 → 200") — trust that evidence; if the evidence line is
absent or the verdict is `INCONSISTENT`/`INDETERMINATE` (not GROUND `DRIFT`), it does
NOT belong in BACKLOG and should be moved to the lower-tier queue.
**Escalate when:** a `[gap-discovery]` entry sits bare `[ ]` past the 14-day staleness
window (it becomes a triage failure, same as any stale `[ ]` — see the BACKLOG entry
above), OR a single entry's GROUND `DRIFT` contradicts a fact that other docs/runbooks
still assert (a stored-fact rot that needs a coordinated fix, not a point patch).
→ governed by ADR 0020 (warn-only `check_doc_reality`, S-75); shares BACKLOG triage
enforcement with `check_backlog_stale` (S-69-A)

---

## Category: no phantom owners / operator-owned reclassification

See CLAUDE.md § "No phantom owners; no silently-trusted manual step" for the rule.

### A cross-repo touchpoint surfaces mid-session (e.g. a `v5` hook edit)
**Default:** COMMIT it in the session that made it — do NOT defer it to "the operator's
docs work" or any unscheduled future session (that is a phantom owner; the change rots
uncommitted, as the S-75 `v5` hook one-liner did). The committing session owns it; push
via `tools/sanctioned/lift_push_restore.py --repo <path>` (the repo-agnostic **routine**
push; the same SSH identity pushes all `Nnyan/*` remotes; `robot_settings.py
push-then-restore` is the **audited** one-off variant). The only thing that is genuinely
operator-gated is a *decision* (what/when), never the mechanical commit/push.
**Escalate when:** the touchpoint is itself a *decision* (e.g. should this hook run at
all), not a mechanical edit — surface that decision to the operator; the edit's *landing*
is still the session's job once the decision is made.

### An item is about to be marked operator-owned / deferred
**Default:** Before filing anything as "operator does later," apply the three-way test:
(a) can it be done now? do it. (b) is there a real owner + real trigger? name both.
(c) else attach a freshness signal that goes red when stale. A manual step with none of
the three is not "deferred," it is orphaned — reject that state, same as a bare `[ ]`.
→ governed by CLAUDE.md § "No phantom owners"; shares enforcement intent with the
coverage-completeness audit (every operator-owned item reclassified or red-signal-gated).

---

## Category: reuse-and-blast-radius checkpoint

See CLAUDE.md § "Reuse-and-blast-radius checkpoint" for the rule.

### Authoring a tool/gate in a sibling family or over a known plural set
**Default:** Before authoring a tool/gate/fix whose home directory has a sibling family
(`tools/`, `tools/sanctioned/`, `frontend/src/composables/`) or whose operand is a member of a
known plural set (the 3 repo rings, file-size ratchet categories, the sanctioned-channel
hierarchy, the BACKLOG-triage queues), SEARCH the sibling family first. If adapting an existing
one: regression (run its suite) + a red-path test (feed a known-bad input, assert DRIFT/non-zero
exit) + a caller/side-effect map (blast radius). Parameterize the INTERFACE over the set (a
`--repo`/registry param), ship the one entity in scope, and file a BACKLOG `[→]`/`[park]`
(trigger + backstop date + owner) for the uncovered members.
**Escalate when:** the entity set is open/unknowable at write-time — then build a registry (NOT a
hardcode) and put a freshness signal on the registry itself, so an unregistered member surfaces
loudly rather than going silently unwatched.

---

## Category: independent review for significant changes

See CLAUDE.md § "Independent review for significant changes" for the rule.

### A change trips the mechanical floor
**Default:** When a change trips the mechanical floor (touches a doctrine file —
`CLAUDE.md` / `.claude/ROBOT.md` / `.claude/AUTONOMOUS-DEFAULTS.md`; adds a `tools/sanctioned/`
file; adds a `def check_`; or invokes an irreversible-git sanctioned tool), obtain the
tier-appropriate review BEFORE landing: a **four-question self-rationale** for a doctrine
edit/addition (what need, why this mechanism, its failure mode, its red-signal); a **fresh Opus
adversarial subagent** for a new gate/tool; a **fixed-charge separate session** for irreversible
git. Record it in `docs/REVIEW-LOG.md` with the per-finding reconciliation (accept/reject + why),
citing a durable, committed review record.
**Escalate when:** the change is genuinely urgent — proceed-and-owe, but file the owed review as a
BACKLOG entry (so `check_backlog_stale` ages it red), never as a free log line.

---

## How to add an entry

When a Robot run produces a decision file marked "not covered by defaults",
the morning review adds an entry here. Format:

```markdown
### <Scenario name>
**Default:** <action to take>
**Escalate when:** <condition for writing a decision file instead>
```

Commit message: `robot: defaults — add <scenario> from <date> run`.
