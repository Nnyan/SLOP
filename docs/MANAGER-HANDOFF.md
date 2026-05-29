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

## Current state (as of 2026-05-29, end of batch-6)

- **origin/main at `6bc5c82`** ("robot: lessons from batch-6"). Confirm with `git rev-parse origin/main`.
- **Batch-6 FULLY LANDED** (S-66 + S-67 + S-68 + S-69). Merged via the merge-worktree pattern (additive conflicts resolved keep-both; S-69 ms-enforce difflib-reconstructed) → integration branch → one clean sanctioned merge `ebaf67c`. ms-enforce green on main; suite failures = known-17 residual subset only. MERGE-LOG has the comprehensive entry.
- **Post-batch-6 follow-ups all done this session:** adapter `target_paths` settings-path fix (`77fb678`); SANCTIONED-OPS-LOG pollution stripped + `test_running_twice_is_noop` un-flaked (`1435529`); **both merge-tool bugs fixed** (dedent + from-main ms-enforce-skip, now branch-isolated, `cea63cb`); doctrine lessons + BACKLOG re-annotation (`6bc5c82`). All 21 batch-6 worktrees + branches pruned (orchestrator session was closed).
- **BACKLOG re-annotated:** zero bare `[→ S-6x]` entries remain; S-73 logged.
- **Next batch = batch-7 = S-73-WAVE-AUTHORING-RIGOR** (per-stream model column + complexity-gated automated pre-flight + first real `_TEMPLATE.md`). NOT yet drafted — the Manager drafts it (see memory `project-s73-wave-authoring-rigor`).
- **No orchestrator/drafting session running.** Safe to do main-side operations.

## Wave queue (current)

**Batch-6 (S-66+S-67+S-68+S-69) — LANDED on main (`ebaf67c`).** Done. The sanctioned
toolkit (`tools/sanctioned/`), the 7 mechanical gates, the doc/tooling hygiene, and
the post-S58 test fixes are all on main.

**Next batch = batch-7 = S-73-WAVE-AUTHORING-RIGOR (NOT yet drafted — Manager drafts it):**
- Per-stream `Model` column + selection rubric (Opus=judgment / Sonnet=default / Haiku=mechanical).
- Complexity-gated automated pre-flight: `tools/wave_complexity.py` scores a wave, the
  orchestrator runs the matching fact-check rigor (extend `validate-wave-file.py`) and
  BLOCKS dispatch on FALSE claims; first real `.claude/waves/_TEMPLATE.md`.
- Build on the merged `validate-wave-file.py` / `ROBOT.md` / `AUTONOMOUS-DEFAULTS.md`.
- Memory: `project-s73-wave-authoring-rigor`. BACKLOG: `[→ S-73]` entry under "From batch-6 retro".

Future candidates (from the Tier-1-7 meta-analysis, not drafted):
- **S-70-AGING-POLICY-FOR-WARN-ONLY** — temporal escalation of warn-only checks (now ~9 warn-only gates live; aging policy is increasingly relevant)
- **S-71-TEST-DATA-POLICY** — formal lifecycle policy (would have prevented the settings.local.json + SANCTIONED-OPS-LOG test-pollution class)
- **S-72-DOCTRINE-SELF-AUDIT** — periodic relevance check on accumulated doctrine
- Agent-code-quality cleanup wave — the 2 parked `scrub.py` items + apps.py TODO

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
9. **`tools/merge_wave_to_main.py`** + **`tools/sanctioned/`** — the sanctioned merge channel + toolkit (shipped/fixed in batch-6); your primary tools for handoffs. Use instead of inline lift-restore scripts.
10. **memory `project-s73-wave-authoring-rigor`** — the approved next-wave (batch-7) plan you draft.
(The batch-6 wave files `.claude/waves/S-66..S-69` are landed/spent — no longer queue items.)

## Immediate next actions (batch-7)

Batch-6 is fully landed + swept (merge, fixes, prune, doctrine, BACKLOG re-annotation
all done — see Current state). What remains:

1. **Draft S-73-WAVE-AUTHORING-RIGOR** (the Manager drafts wave files for this batch per
   the user's approval). Build on the merged `validate-wave-file.py` / `ROBOT.md` /
   `AUTONOMOUS-DEFAULTS.md`. Two bundled features + a `_TEMPLATE.md` (see Wave queue +
   memory `project-s73-wave-authoring-rigor`). Apply the new per-stream model convention
   to the draft itself.
2. **Then fire batch-7** (S-73 + optionally a co-batched cleanup wave): ONE fresh Opus
   orchestrator. Hand the user the orchestrator prompt; confirm `git rev-parse origin/main`
   for the base SHA at prompt-writing time. You coordinate, you don't run it.
3. **Post-wave merge:** use `python3 tools/merge_wave_to_main.py wave/S-73-...` — the tool
   now runs ms-enforce branch-isolated (bug fixed) and writes a correctly-formatted
   MERGE-LOG entry (dedent bug fixed). Push via `/tmp/lift-push-restore.py all`.
4. **If multiple branches with additive conflicts:** the merge-worktree integration pattern
   (build off main in a scratch worktree, resolve keep-both / difflib-reconstruct, verify,
   then one clean sanctioned merge) is the proven path — see the batch-6 MERGE-LOG entry.

**Note:** the standalone batch-6 wave files (`.claude/waves/S-66..S-69`) are spent (landed).
Don't re-fire them.

## Working patterns / discipline

### Sanctioned channel hierarchy
- Merges to main → `tools/merge_wave_to_main.py` (S-59-D; both batch-6 bugs now fixed — runs ms-enforce branch-isolated, clean MERGE-LOG formatting)
- Settings lift/restore + force-push + filter-branch + rm-recursive → `tools/sanctioned/` (SHIPPED in S-68: `robot_settings.py`, `force_push_tag.py`, `filter_branch_secret_scrub.py`, `rm_recursive_safe.py`, on shared `_lift_restore.py`/`_audit.py`)
- Push to origin → still operator-manual OR `/tmp/lift-push-restore.py` (S-68 did not add a push wrapper; `robot_settings.py push-then-restore` exists but you've been using the /tmp helper)
- Canonical wave-mode deny profile → `.claude/settings-wave-mode-profile.json` (S-68; `robot_settings.py restore` re-applies it)

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

## What this session's prior Manager (me) did, and where you pick up

Done this session:
1. Merged the `docs/wave-drafts-s68-s69-doctrine` branch via `tools/merge_wave_to_main.py` (first real use; found + logged two tool bugs for S-68-C).
2. Resolved the S-67↔S-68 file collision (descoped S-67-C into S-68).
3. Pre-flighted all four batch-6 wave files with parallel verification agents; corrected stale counts/SHAs/attribution. No FALSE claims, no blockers.
4. Refreshed this handoff.

You pick up at: **batch-6 is ready to fire.** Either the user fires the orchestrator (prompt above) and you handle the post-wave merge, or they direct something else. After batch-6 lands: BACKLOG re-annotation + retro + audit log.

**New user-preference memory this session:** `feedback-prompt-and-menu-formatting` — (1) set copy-paste prompts off with blank lines before/after, (2) ask "what next" as a menu list not a paragraph, (3) decision asks get a concise recommendation with no whys, and recommend multiple options when more than one is right.

## Final notes

- The user explicitly fired the drafting session before requesting this handoff. So as you read this, that session is producing wave files on `docs/wave-drafts-s68-s69-doctrine`. They will ping you (in your fresh session terminal) when done.
- Trust the audit trails. `docs/MERGE-LOG.md`, `docs/BACKLOG.md`, `.claude/run-archive/`, memory entries — these are the institutional memory.
- When in doubt, ask the user. They prefer one clarification question over silent wrong action.

Good luck. The infrastructure is solid; you're picking up at a clean state with a clear queue.
