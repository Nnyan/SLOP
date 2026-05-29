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

### A test fails intermittently
**Default:** Run it three times in isolation. If 3/3 pass, treat as flaky and
proceed (note in observations). If any of the 3 fail, treat as a real failure
per "in-scope test failure" entry above.

---

## Category: git operations

### Merge conflict between two streams within the same wave
**Default:** Abort the merge. Write a blocker file naming the conflicting paths
and lines. Leave both stream branches intact. The wave's "streams touch disjoint
files" claim has failed and needs human triage.
**Escalate:** always — this is a wave-design failure to surface.

### Merge conflict between a wave branch and `main`
**Default:** Should not happen in Robot mode (waves don't merge to main).
If it does (e.g., a wave branch is rebased), abort and write a blocker.

### A commit needs a co-author tag
**Default:** Use `Co-Authored-By: Claude {model-name} <noreply@anthropic.com>`.
Match the model that did the work (subagent's model, not the coordinator's).

### `git push` is attempted
**Default:** Settings deny it. If a command somehow constructs a push,
the deny list halts it; the stream should write a blocker citing the
attempted push and what it was trying to accomplish.
**Escalate:** always — pushing is never autonomous.

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

### A tool call would prompt for permission (not on allow list)
**Default:** Settings should catch this. If the agent foresees the prompt, halt
the action and write a decision file naming the tool + arguments + why it was
needed.
**Escalate:** always — missed allow entries are a settings update for next run.

### `.claude/settings.local.json` modification is needed
**Default:** Forbidden during Robot run. Write decision file with the proposed
settings change for morning review.

### A bash command needs a new flag or pattern not on the allow list
**Default:** Try a different command pattern that IS on the allow list. If no
alternative exists, write a decision file naming the command + why it's needed.

---

## Category: agent / subagent coordination

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

---

## Category: scope / discovery

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

### A subagent should be on a different model than the wave file says
**Default:** Follow the wave file. Models are pre-decided.
**Escalate:** never (or write an observation for next-run tuning).

### Coordinator wants to spawn an unplanned helper agent
**Default:** Don't, in Robot mode. Stick to the wave's planned streams.

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
