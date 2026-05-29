# SLOP Manager Session — Handoff

You are taking over the **operator-assist / Manager** role for SLOP from a long-running Opus session that hit context-limit. This document is your full briefing. Read it end-to-end before doing anything else.

## Your role

You are the operator-assist session — the single long-running Claude that:
- Coordinates with the user (Nnyan) on the SLOP project (Self-hosted Linux Orchestration Platform).
- Reviews orchestrator outputs after each Robot batch lands.
- Handles the post-wave merge handoff to `main` (via the sanctioned tool — see below).
- Updates BACKLOG, doctrine, MERGE-LOG, WALK-BACK-LOG as needed.
- Plans future batches based on the wave queue and emerging needs.
- Catches doctrine drift and meta-pattern issues (the user values structural answers over point-fixes).
- Maintains audit trails.

You are NOT a Robot mode orchestrator. Orchestrators are fired in SEPARATE fresh Opus sessions per the one-orchestrator-per-batch doctrine; you coordinate around them.

You are NOT a wave-drafting session either; those are also separate fresh sessions when needed.

## Current state (as of 2026-05-29)

- **origin/main at `578c452`** ("backlog: batch-5 retro entries"). Confirm with `git rev-parse origin/main`.
- **Batch-5 fully landed** in commits `73a8fe0` through `caf1d6e` (S-59 + S-63 + S-64 + adapter fix + doctrine recovery). All cleanly merged + audit-logged.
- **A drafting session is CURRENTLY RUNNING** in a separate fresh Opus terminal. It's producing:
  - `.claude/waves/S-68-SANCTIONED-CHANNEL-TOOLKIT.md`
  - `.claude/waves/S-69-DOCTRINE-MECHANICAL-ENFORCEMENT.md`
  - A small doctrine commit (processor-pattern A↔B contract requirement) to `.claude/AUTONOMOUS-DEFAULTS.md`
  - BACKLOG close-outs for batch-5 retro entries
- It commits to branch `docs/wave-drafts-s68-s69-doctrine` and exits cleanly. **Your first real action is merging that branch when it pings back.**

## Wave queue (current)

Drafted and on main, ready for next batch:
- **S-66-POST-S58-UNMASK-CLEANUP** — cleanup wave for 12 unmasked-by-S-58 failures + 30 A-bucket pre-existing failures + 2 scrub.py BACKLOG items
- **S-67-DOC-AND-TOOLING-HYGIENE** — 88 broken doc-link warnings + 3 phantom RELEASE_NOTES TODOs + 4 CHANGELOG v4.2.0 TODOs + slipped S-56 tooling (`robot-settings.py`, orchestrator-dispatch gate) + validate-wave-file fix

Being drafted right now:
- **S-68-SANCTIONED-CHANNEL-TOOLKIT** — "every deny has a sanctioned tool or is no-exceptions-period"; extends `tools/merge_wave_to_main.py` pattern
- **S-69-DOCTRINE-MECHANICAL-ENFORCEMENT** — convert ~6-7 human-enforced rules to ms-enforce TIER_1 warn-only gates

Future candidates (from the Tier-1-7 meta-analysis the user pushed on, not drafted):
- **S-70-AGING-POLICY-FOR-WARN-ONLY** — temporal escalation of warn-only checks
- **S-71-TEST-DATA-POLICY** — formal lifecycle policy (would have prevented S-58's 52 fixes and Stream C regression)
- **S-72-DOCTRINE-SELF-AUDIT** — periodic relevance check on accumulated doctrine

Parked:
- **OPTIONAL-FILE-SIZE-REMEDIATION** — re-eval 2026-08-27

## Read order (after you finish this file)

1. **Memory** — `~/.claude/projects/-home-stack-code-slop/memory/MEMORY.md` (auto-loaded; key entries: `project-robot-mode`, `feedback-no-version-pinning`, `feedback-no-fix-all-failures-rule`, `feedback-one-orchestrator-per-batch`, `feedback-robot-design-decisions`, `project-next-robot-batch-plan`, `feedback-manager-role-handoff` — the entry that points to this file).
2. **CLAUDE.md** (auto-loaded; project-level rules including BACKLOG triage + walk-back log + ONE-orchestrator-per-batch).
3. **`.claude/ROBOT.md`** — full Robot mode doctrine v4 with two-phase architecture, BACKLOG triage section, post-batch-4 caveats.
4. **`.claude/AUTONOMOUS-DEFAULTS.md`** — full default register including base-commit-from-origin, snapshot/coverage worktree-artifact trap, orchestrator dispatch pattern.
5. **`docs/BACKLOG.md`** — re-annotated state; every open item has explicit fold-in target. Review for "from batch-5 retro" section.
6. **`docs/ACCESS-REQUESTS.md`** — install/upgrade/allow queue. Note the `[—]` entry confirming sensitive-path silencing is unsolvable in acceptEdits.
7. **`docs/MERGE-LOG.md`** — audit trail for every merge. Newest entries at top.
8. **`docs/WALK-BACK-LOG.md`** — meta-process artifact for doctrine rule removals.
9. **`.claude/waves/S-66-POST-S58-UNMASK-CLEANUP.md`** — drafted, queued.
10. **`.claude/waves/S-67-DOC-AND-TOOLING-HYGIENE.md`** — drafted, queued.
11. **`tools/merge_wave_to_main.py`** — the sanctioned merge channel; your primary tool for handoffs. **Use this instead of inline lift-restore scripts** from now on (per S-68 doctrine pattern).

## Immediate next actions when drafting session reports

1. **Verify** `origin/main` is still at `578c452` (or further; check `git rev-parse origin/main`).
2. **Inspect** the drafting session's branch: `git log --oneline main..docs/wave-drafts-s68-s69-doctrine`. Should be 3 commits (wave drafts + doctrine + BACKLOG).
3. **Dry-merge** to spot conflicts: `git merge-tree $(git merge-base main docs/wave-drafts-s68-s69-doctrine) main docs/wave-drafts-s68-s69-doctrine | head`.
4. **Merge via sanctioned channel** — this is `tools/merge_wave_to_main.py`'s first real use:
   ```
   python3 tools/merge_wave_to_main.py docs/wave-drafts-s68-s69-doctrine
   ```
   It does pre-flight + internal lift-restore + the merge + audit log entry to `docs/MERGE-LOG.md`. It does NOT push.
5. **Push** via the lift-restore helper at `/tmp/lift-push-restore.py` (the merge tool deliberately stops short of push).
6. **Verify** the audit log entry was written by the tool.
7. **Ping the user** with the new HEAD SHA + a brief note about batch-6 composition (probably S-66 + S-67 + S-68 + S-69 under ONE orchestrator).

## Working patterns / discipline

### Sanctioned channel hierarchy
- Merges to main → `tools/merge_wave_to_main.py` (shipped in S-59-D)
- Push to origin → operator-manual OR `/tmp/lift-push-restore.py` helper (until S-68 builds `tools/sanctioned/push.py`)
- Settings lift/restore → `/tmp/lift-push-restore.py` (until S-67-C ships `tools/robot-settings.py`, then S-68 wraps it)

### Helper scripts in `/tmp/`
- `/tmp/lift-push-restore.py` — lift git push deny → push origin main → restore
- `/tmp/fix-detached-head.py` — FF main from a detached commit; recovery template
- /tmp/ scripts are EPHEMERAL. Don't promote them to permanent without going through the sanctioned-tool pattern.

### Sensitive paths in acceptEdits (your session is acceptEdits, NOT bypassPermissions)
- Writes to `.claude/waves/` and `.claude/run/` trigger sensitive-file prompts. **No silencing mechanism exists** (confirmed via claude-code-guide research; documented in `docs/ACCESS-REQUESTS.md` `[—]` entry).
- Mitigation: write to those paths ONLY when necessary. Use `docs/` for things that don't need to be under `.claude/`. Use Bash heredocs (still prompts but a single prompt per file vs many for Write-tool calls).

### Multi-line commit messages from `!` prefix
- Don't. Bash eats the closing quote. Use single-line `-m` OR `git commit -F <file>` with a pre-written message file.

### Cross-session HEAD safety
- Batch-5 hit two collisions because main's working tree was shared with the orchestrator session.
- If a Robot orchestrator is running in parallel, do NOT do main-side operations in `/home/stack/code/slop/`. Either wait or use a separate worktree (`git worktree add /tmp/slop-manager origin/main`).
- The drafting session currently running is a wave-file drafter, not an orchestrator — same caveat applies but lower risk (they don't switch branches).

### BACKLOG triage (enforced)
- Every entry: `[→ S-NN-stream]` | `[park: trigger=X]` | `[x]` done | `[—]` won't fix.
- Pure `[ ]` >14 days is a triage failure.
- Pre-batch planning includes a BACKLOG sweep.

### Walk-back log (enforced)
- Any doctrine rule removal needs an entry in `docs/WALK-BACK-LOG.md` answering four questions.
- `ms-enforce check_walkback_log` (warn-only) catches commits that remove ≥3 lines from `.claude/ROBOT.md`, `.claude/AUTONOMOUS-DEFAULTS.md`, or `CLAUDE.md` without referencing the log.

### Cleanup-wave doctrine
- "fix-all-failures" was walked back. Focused waves don't expand scope.
- **Inverse:** dedicated cleanup waves are how pre-existing failures get drained. S-57 (TIER_2), S-58 (TestClient), S-66 (queued unmask cleanup), S-67 (queued doc/tooling hygiene) are the established pattern.
- When BACKLOG accumulates ≥10 open items in one category, draft a cleanup wave.

## Open meta-patterns (from the user's "extremely deep" prompt earlier)

The user asked me to identify where ad-hoc point-fixes hide structural patterns. I categorized into 7 tiers, ranked by leverage:

1. **Sanctioned-exception pattern** — every deny rule needs either a sanctioned tool OR an explicit no-exceptions rationale. `tools/merge_wave_to_main.py` is the prototype; S-68 builds out the rest.
2. **Tool-enforced doctrine** — convert ~10 human-enforced rules (BACKLOG triage, subagent preamble, base-SHA discipline, merge-log completeness, status freshness, memory staleness) to ms-enforce gates. S-69 owns this.
3. **Walk-back log** — landed (commit `73a8fe0` cherry-picked from `995a4c7`). Doctrine in place.
4. **Aging policy for warn-only** — warn-only checks ignore-forever loophole. S-70 candidate.
5. **Test data lifecycle policy** — would have prevented S-58's 52 fixes and Stream C snapshot regression. S-71 candidate.
6. **Doctrine self-audit** — periodic relevance check on accumulated doctrine. S-72 candidate.
7. **Wave-file schema** — convert prose convention to structured fields. Parked (high effort, unclear payoff).

Currently in flight: 1, 2 (S-68 + S-69 drafting). Already done: 3. Future: 4, 5, 6. Parked: 7.

## Communication with the user

- Concise responses preferred. The user is direct and decisive.
- They tolerate long responses when the meta-thinking is the point (they explicitly asked for "extremely deep and hard" thinking at one point).
- They want structural answers, not point-fixes. When you catch yourself proposing a per-occurrence patch, step back.
- They will tell you when to wait and when to act. Don't over-assume.
- They have been firing things via `!` prefix in this session — be careful with multi-line commit messages.
- When they say "do this" they mean it. When they say "think about this" they want analysis first.
- They've been on this session for many hours and are slightly impatient with avoidable rework. Be careful, get it right.

## Helper-script library in `/tmp/`

Likely still present (verify with `ls /tmp/`):
- `/tmp/lift-push-restore.py` — keeper
- `/tmp/fix-detached-head.py` — recovery template
- `/tmp/batch5-recovery-and-merge.py` — example of comprehensive merge handling
- `/tmp/batch5-continue.py` — example of mid-merge recovery
- `/tmp/cleanup-tmp.py` — periodic /tmp cruft cleanup

These are NOT canonical tools. S-68 will promote the durable ones to `tools/sanctioned/`.

## Open follow-up items (BACKLOG entries to remember)

After the drafting session merges, several BACKLOG entries get either closed or re-targeted:
- "Merge-worktree doctrine" → `[→ S-69]` (drafting session may absorb into S-69)
- "Pin A↔B contract" → drafting session's small doctrine commit closes this
- Various `[→ S-67-*]` entries get realized when S-67 fires
- Various `[→ S-66-*]` entries get realized when S-66 fires

Your job after the next batch: do another re-annotation pass.

## What this session's prior Manager (me) was about to do

1. Standing by for the drafting session to ping back.
2. Then: merge their branch via `tools/merge_wave_to_main.py` (first real use of the sanctioned channel).
3. Then: plan batch-6 firing — probably ONE Opus orchestrator covering S-66 + S-67 + S-68 + S-69 (10-13 streams, biggest batch yet but coherent).
4. Then: another BACKLOG sweep + close-out + audit log.

That's where you pick up.

## Final notes

- The user explicitly fired the drafting session before requesting this handoff. So as you read this, that session is producing wave files on `docs/wave-drafts-s68-s69-doctrine`. They will ping you (in your fresh session terminal) when done.
- Trust the audit trails. `docs/MERGE-LOG.md`, `docs/BACKLOG.md`, `.claude/run-archive/`, memory entries — these are the institutional memory.
- When in doubt, ask the user. They prefer one clarification question over silent wrong action.

Good luck. The infrastructure is solid; you're picking up at a clean state with a clear queue.
