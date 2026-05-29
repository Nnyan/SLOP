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

## Current state (as of 2026-05-29, batch-7 in-flight)

- **origin/main at `4989d87`** (+ a docs/handoff commit on top of that from this
  session — confirm the live value with `git rev-parse origin/main`).
- **⚠️ BATCH-7 (S-73) IS RUNNING RIGHT NOW** in a separate orchestrator session.
  **Do NOT do main-side git operations** (merge/commit that moves main's HEAD, or
  `merge_wave_to_main.py` which checks out main) until it's COMPLETE — cross-session
  HEAD-collision risk (batch-5 lesson). Docs-only commits to files disjoint from
  S-73's scope are lower-risk if needed, but prefer to wait or use a separate worktree.
  - Liveness: the orchestrator is leaking an untracked `.claude/waves/_TEMPLATE.md`
    into the MAIN working tree (S-73 Stream D output → repo-root pollution, the exact
    class Test-Data-Hygiene fixes). Leave it; canonical copy is on the wave branch;
    clean it during the merge (like the batch-6 stray files).
- **YOUR FIRST ACTION:** when the orchestrator reports `wave/S-73-wave-authoring-rigor`
  COMPLETE, review it (per-stream Model dogfood; the 3 pinned contracts held; ROBOT.md
  additive merges resolved keep-both not union), then merge via
  `python3 tools/merge_wave_to_main.py wave/S-73-wave-authoring-rigor` and push.
- **Batch-6 FULLY LANDED** (`ebaf67c`) + all follow-ups done (both merge-tool bugs
  FIXED `cea63cb`; scrub.py egress leak FIXED `cb58f70`; SANCTIONED-OPS-LOG cleaned).
- **S-73 was drafted by a fresh session, reviewed, and merged to main** (`86cd5a1`) —
  that's why its wave file is on main; it is now EXECUTING as batch-7. The merge was
  the first on the fixed tool (validated: clean MERGE-LOG entry + branch-isolated ms-enforce ran).
- **Consolidation done:** the 5 remaining candidates condensed → 3 waves + 1 direct
  fix. The full spec is `docs/POST-BATCH6-WAVE-MAP.md` (READ IT — it's your roadmap).

## Wave queue (current)

The remaining roadmap is the consolidated 3-wave plan in `docs/POST-BATCH6-WAVE-MAP.md`
(5 raw candidates → 3 waves + 1 direct fix; condensed 2026-05-29). Sequenced:

- **Batch-7 = S-73-WAVE-AUTHORING-RIGOR** — RUNNING NOW. Per-stream Model column +
  rubric, complexity-gated automated pre-flight (`tools/wave_complexity.py` +
  extended `validate-wave-file.py` + orchestrator pre-flight step), first
  `.claude/waves/_TEMPLATE.md`. 5 streams. Your job: review + merge its branch.
- **Batch-8 = TEST-DATA-HYGIENE** (merge of S-71 + the batch-6 pollution root-cause) —
  NOT yet drafted; **draft it AFTER S-73 lands, using S-73's new `_TEMPLATE.md` + Model
  column.** Core: test-data lifecycle policy, finish the `write_entry`/scanner
  repo-relative-path fix, `check_test_isolation` gate, sweep offenders (narrow the
  S-66-B autouse fixture). See the brief in POST-BATCH6-WAVE-MAP.md.
- **Batch-9 = ENFORCEMENT-LIFECYCLE** (merge of S-70 + S-72) — draft/fire LATER, once
  the ~11 warn-only gates + doctrine have accumulated run-history (aging policy needs
  signal). Core: gate-aging policy + `audit_gate_age.py`, doctrine-relevance audit.
  **Two low-effort parked items woven in as bundled adjacents** (2026-05-29): the
  pre-commit file-size-ratchet hook + provenance-headers `check_provenance` gate.

Parked (reviewed 2026-05-29 — do NOT fit batch-8/9 themes; forcing them would dilute
coherence, the same reason we kept the batches separate): CLAUDE.md split, refresh-train
auto-bisect, prometheus-instrumentator tracking, installer/state.py root-chown,
`apps.py:964` register-endpoint TODO, scrub.py bare-"stack" over-redaction (cosmetic;
direct-fix candidate), `.bak` cleanup (→ a small `robot_settings.py --prune-backups`
direct follow-up), OPTIONAL-FILE-SIZE-REMEDIATION (re-eval 2026-08-27).

**Already direct-fixed this session (not waves):** scrub.py `is_external` egress leak (`cb58f70`).

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
10. **`docs/POST-BATCH6-WAVE-MAP.md`** — THE ROADMAP. The consolidated 3-wave plan
    (S-73 batch-7 / Test-Data-Hygiene batch-8 / Enforcement-Lifecycle batch-9) with
    per-wave briefs, processor-contract pins, sequencing, and the woven parked items.
11. **memory `project-s73-wave-authoring-rigor`** — the S-73 design rationale.
(The batch-6 wave files `.claude/waves/S-66..S-69` are landed/spent; S-73 is executing — no longer queue items.)

## Immediate next actions (picking up with batch-7 in-flight)

Batch-7 (S-73) is RUNNING when this handoff was written. In order:

1. **WAIT for batch-7 to report COMPLETE.** While it runs, no main-side git ops
   (HEAD-collision discipline). If you must touch main, use a separate worktree off
   origin/main. (If it has already completed by the time you read this, proceed.)
2. **Review + merge S-73.** When `wave/S-73-wave-authoring-rigor` is COMPLETE:
   verify the per-stream Model dogfood, the 3 pinned contracts held (tier-string,
   Model-column format, ROBOT.md subsection ownership), and that the ROBOT.md
   additive merges across streams A/C/D/E were keep-both (NEVER `merge=union`; look
   for an `S-73-MERGE-N.md` decision). Then:
   `python3 tools/merge_wave_to_main.py wave/S-73-wave-authoring-rigor`
   (the tool is FIXED: runs ms-enforce branch-isolated + writes a clean MERGE-LOG
   entry). Push via `/tmp/lift-push-restore.py all`. Clean up the stray
   `.claude/waves/_TEMPLATE.md` in the main tree (canonical version arrives via the merge).
   Prune the batch-7 worktrees/branches once that orchestrator session is closed.
3. **Draft batch-8 = TEST-DATA-HYGIENE** using S-73's freshly-landed `_TEMPLATE.md` +
   Model column. Brief in `docs/POST-BATCH6-WAVE-MAP.md`. A fresh bypassPermissions
   session drafts it (you supply the one-line pointer to the brief); you review + merge.
4. **Batch-9 = ENFORCEMENT-LIFECYCLE later** (after the gates age). Same draft→review→merge.
5. **Post-batch-7 BACKLOG sweep:** flip the `[→ S-73]` / batch-7 entries to `[x]`; retro.

**Merge mechanics reminder:** for multi-branch batches with additive conflicts, use
the merge-worktree integration pattern (build off main in a scratch worktree, resolve
keep-both / difflib-reconstruct, verify ms-enforce green + suite, then ONE clean
sanctioned merge of the integration branch) — the batch-6 MERGE-LOG entry is the worked example.

**Note:** the standalone batch-6 wave files (`.claude/waves/S-66..S-69`) and S-73 are
spent/executing — don't re-fire them. New waves (batch-8/9) get drafted fresh.

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
