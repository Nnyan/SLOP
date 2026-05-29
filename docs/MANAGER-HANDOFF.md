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

## Current state (as of 2026-05-29, late)

- **origin/main at `bff804d`** ("waves: batch-6 pre-flight corrections"). Confirm with `git rev-parse origin/main`.
- **Batch-5 fully landed** (S-59 + S-63 + S-64 + adapter fix + doctrine recovery). All cleanly merged + audit-logged.
- **S-68/S-69 drafts + A↔B contract doctrine + batch-5 close-outs are MERGED** (the `docs/wave-drafts-s68-s69-doctrine` branch was merged via `tools/merge_wave_to_main.py` — first real use of the sanctioned channel — commit `ab716cd`, then deleted). Recent main history: `ab716cd` (sanctioned merge) → `cdbf1dd` (audit log + S-68-C tool follow-ups) → `069d798` (S-67-C descope) → `bff804d` (batch-6 pre-flight corrections).
- **Batch-6 is planned, pre-flighted, and ready to fire** (see Wave queue + the orchestrator prompt below). Not yet launched — that's a fresh-Opus-orchestrator action the user triggers.
- **No drafting/orchestrator session is currently running.** Safe to do main-side operations.

## Wave queue (current)

**Batch-6 — all four drafted, on main, pre-flighted (2026-05-29), ready to fire under ONE orchestrator (~21 active streams):**
- **S-66-POST-S58-UNMASK-CLEANUP** (4 streams: A first, B/C/D parallel) — 12 unmasked-by-S-58 failures + A-bucket pre-existing failures + scrub.py items. NOTE: failure counts are stale (Stream A re-inventories; current main ~59, not the old "43"); env-dependent (Docker/network) failures are out of scope.
- **S-67-DOC-AND-TOOLING-HYGIENE** (4 active streams: A→B sequential, D/E parallel; **C deferred to S-68**) — ~90 broken doc-link warnings + phantom RELEASE_NOTES/CHANGELOG TODOs + orchestrator-dispatch gate + validate-wave-file fix.
- **S-68-SANCTIONED-CHANNEL-TOOLKIT** (5 streams: A+B foundation, C/D/E after) — "every deny has a sanctioned tool or is no-exceptions-period"; refactors `merge_wave_to_main.py` onto shared `_lift_restore`/`_audit` modules; **sole owner of `robot_settings.py` + `.claude/settings-wave-mode-profile.json`** (absorbed S-67-C).
- **S-69-DOCTRINE-MECHANICAL-ENFORCEMENT** (8 streams: A–G parallel, H after) — 7 human-enforced rules → ms-enforce TIER_1 warn-only gates; Stream G+H fold in the batch-5 merge-worktree pattern.

Batch-6 firing prerequisite resolved: S-67↔S-68 file collision (both created `robot-settings.py` + wave-mode profile) — descoped S-67-C into S-68 (commit `069d798`). All four are now file-disjoint except the additive `ms-enforce` TIER_1 registration list (keep-both default applies). No hard cross-wave merge-order dependency → one orchestrator.

**Known S-68-C tool follow-ups** (logged in BACKLOG, found during the first sanctioned merge): `merge_wave_to_main.py` has (1) a `_append_audit_entry` dedent bug that mangles MERGE-LOG indentation, and (2) it skips ms-enforce when invoked from `main`. S-68 Stream C refactors this tool and should fix both.

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

## Immediate next actions (batch-6)

The drafting-session merge + descope + pre-flight are DONE (see Current state). What remains:

1. **If the user wants batch-6 fired:** hand them the orchestrator prompt below (a fresh Opus session — you do NOT run it; you're the Manager, not the orchestrator). Confirm `git rev-parse origin/main` matches the SHA in the prompt first; if main has advanced, regenerate the prompt's SHA.
2. **While the orchestrator runs:** do NOT do main-side operations in `/home/stack/code/slop/` (cross-session HEAD collision risk — batch-5 hit two). Use a separate worktree if you must.
3. **When the orchestrator reports wave branches COMPLETE:** merge each via `python3 tools/merge_wave_to_main.py wave/S-66-... wave/S-67-... wave/S-68-... wave/S-69-...` (it accepts multiple branches), then push via `/tmp/lift-push-restore.py all`.
4. **After merge:** verify the MERGE-LOG audit entries (watch for the known dedent-formatting bug until S-68-C fixes it), run a BACKLOG re-annotation pass (realize the `[→ S-66-*]`/`[→ S-67-*]`/`[→ S-68-*]`/`[→ S-69-*]` entries to `[x]`), and do a batch-6 retro.

**Batch-6 orchestrator prompt (fresh Opus session; verify the SHA is still origin/main first):**

```
in Robot mode: you are the orchestrator for the SLOP batch-6 — 4 independent waves to fire concurrently under ONE orchestrator. main is at origin/main commit bff804d. Waves to handle: .claude/waves/S-66-POST-S58-UNMASK-CLEANUP.md, .claude/waves/S-67-DOC-AND-TOOLING-HYGIENE.md, .claude/waves/S-68-SANCTIONED-CHANNEL-TOOLKIT.md, .claude/waves/S-69-DOCTRINE-MECHANICAL-ENFORCEMENT.md. Note: S-67 Stream C is DEFERRED to S-68 — do not dispatch it. Follow the standard orchestrator startup sequence in .claude/ROBOT.md (read ROBOT.md + AUTONOMOUS-DEFAULTS.md, pre-flight fact-check each wave file, dispatch streams per each wave's Parallelization section with the subagent preamble, merge each stream to its wave branch, never to main).
```

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
