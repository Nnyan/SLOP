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

You are NOT a wave-drafting or audit session either; those are also separate fresh sessions.

## Current state (as of 2026-05-30 — S-74 EXECUTED + orchestrator CLOSED; output PENDING your review/merge)

- **origin/main at `e3a0eef`** — CONFIRM LIVE (`git rev-parse origin/main`); do NOT trust this
  number, it goes stale. Tree clean except a stray untracked `.claude/scheduled_tasks.lock`
  (harmless; gitignore candidate). **As of this writing no orchestrator/drafting/audit session
  is running — but VERIFY before any main-side git op** (`git worktree list`, `git branch
  --list '*S-74*'`, `.claude/run/status/`, `.claude/run/blockers/`). Do not assume liveness.
- **✅ Batches 7 & 8 LANDED.** Batch-7 = S-73-WAVE-AUTHORING-RIGOR (`ff27adb`): the
  `_TEMPLATE.md` + per-stream Model column + `wave_complexity.py`/`preflight_wave.py`
  pre-flight tooling. Batch-8 = S-71-TEST-DATA-HYGIENE (`96fd6a2`): ADR-0019, the
  `SLOP_AUDIT_LOG_PATH` redirect, the warn-only `check_test_isolation` gate, narrowed the
  S-66-B autouse fixture, renamed the preflight test. Both swept + archived.
- **🟠 Batch-9 = S-74-DEPLOY-HARDENING — EXECUTED; orchestrator CLOSED; PENDING your review+merge.**
  **Closing output: `.claude/run/status/S-74.md` — READ IT FIRST; it is the handoff payload.**
  Result: COMPLETE, **no blockers**, all 4 streams merged to `wave/S-74-deploy-hardening` (final
  HEAD **d6b93b1** — verify the branch points there). Pre-flight DISPATCH-OK, fact-check ALL-TRUE.
  Coordinator verified all PINNED contracts + the SHA-verify rider (deploy_lib.sh shared-symbol;
  MS_PORT canonical port-var; C's `.env`-authoritative operator-env model; no `2>/dev/null` on
  fetch; no bare `git pull`; 16+6 tests pass; ms-enforce EXIT 0). **NOT merged/pushed — your call.**
  Per-stream branches A–D still exist (prune in sweep). Merge: `python3 tools/merge_wave_to_main.py
  wave/S-74-deploy-hardening`. Post-merge: flip the 6 `[→ S-74]` BACKLOG entries to `[x]` +
  cross-ref `docs/DEPLOY.md` from the "From Rocinante deploy session" entries. No real-server CI —
  consider a Rocinante confirmation run (memory `project-rocinante-deploy`).
- **🟡 Batch-10 = S-75-KNOWLEDGE-LIFECYCLE — DRAFTED, on main, fire-ready but GATED.** Wave
  + launch prompt + `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`, dogfooded DISPATCH-OK.
  Builds the two-owner reality-reconciliation layer (the SLOP AI Agent emits a
  runtime-only RealityView; a SEPARATE dev-time `check_doc_reality` reconciler owns docs)
  + the GROUND-vs-XREF discipline + the gap-discovery ritual. **HARD-sequenced: do NOT fire
  until S-74 has executed and landed on main** (shared `CLAUDE.md` deploy section; the
  host-probe needs S-74's fixed update path). Its launch prompt gates on this.
- **🆕 Combined Coverage+Handoff AUDIT — SCHEDULED; draft launch prompt ready.** Fresh Opus Robot
  orchestrator, max-parallel read-only subagents, TWO tracks: A = coverage-completeness (meta-pattern
  #9 — every KNOWN tiered invariant has every tier reconciled/gated, e.g. the 3 repo rings), B =
  handoff integrity (meta-pattern #10 — longitudinal review of handoff history → a Handoff Protocol +
  prompt/automation doctrine). Keystone "covered only if it can go RED vs physics." Output = ONE
  report + ONE blast-radius target list → batch-11. **Fire AFTER S-74 AND S-75 land.** Full design +
  draft prompt: memories `project-coverage-completeness-audit` + `project-handoff-integrity-audit`;
  commit the charter+prompt to `.claude/waves/` during the S-74 sweep.
- **⏸ Batch-11 = ENFORCEMENT-LIFECYCLE (S-70+S-72) — ACCELERATED.** Was deferred to 2026-07-15; now
  to be drafted from the combined-audit findings + TWO blast-radius streams: the audit's targets AND
  the `check_backlog_stale` blast-radius expansion (memory `project-backlog-stale-gate-blast-radius`).
  Draft after the audit reports.
- **Session arc (2026-05-29→30):** Rocinante deploy → real `ms-update` bugs → S-74 (now executed +
  closed, pending review). Knowledge-Lifecycle audit → S-75 + park-rule strengthening. Then a
  coordination thread surfaced 4 structural items: Ring-0 working-tree detection (LANDED in the
  slop-process session-start hook, `e5c0da5`), the check_backlog_stale blast-radius expansion, the
  combined coverage+handoff audit, and a new handoff doctrine (state durable facts + the verification
  to run, NEVER volatile state). See `docs/KNOWLEDGE-LIFECYCLE-AUDIT.md` + the 4 new memories.

## Wave queue (current)

Roadmap: `docs/POST-BATCH6-WAVE-MAP.md` (READ IT). Live sequence:

- **Batch-7 = S-73** ✅ LANDED. **Batch-8 = S-71** ✅ LANDED. Not queue items.
- **Batch-9 = S-74-DEPLOY-HARDENING** — 🟢 fire-ready. Paste
  `.claude/waves/S-74-LAUNCH-PROMPT.md` into a fresh Opus orchestrator. 4 streams.
- **Batch-10 = S-75-KNOWLEDGE-LIFECYCLE** — 🟡 fire-ready, GATED on S-74 landing first.
  Paste `.claude/waves/S-75-LAUNCH-PROMPT.md` AFTER S-74 is on main. 5 streams. After it
  merges, apply the one-line cross-repo touchpoint (S-75 Stream B's addition to the v5
  SessionStart hook `/home/stack/v5/docs/tools/check_push_status.sh` — v5 isn't worktree-able).
- **Batch-11 = ENFORCEMENT-LIFECYCLE (S-70+S-72)** — ⏸ deferred/undrafted. **Readiness is
  OWNED now** (was an un-owned vague trigger; fixed 2026-05-30): trigger = ≥30d since the
  newest warn-only gate was added (clock NOT started — gate set still growing) + gates
  exercised ≥2 batches + a stable fired/never-fired classification across 2 reviews;
  **hard re-eval checkpoint 2026-07-15**; owner = Manager retro (interim) / S-75 ritual
  (permanent). Absorbs S-75's aging-engine design + adds the 4th aging leg (probes age).
  Two woven adjacents ride along (pre-commit ratchet hook + `check_provenance`). Spec:
  POST-BATCH6-WAVE-MAP §"Wave 3 — Readiness".

Parked items all now carry a **2026-07-15 backstop re-eval** (strengthened park rule).
The "Split CLAUDE.md" park's trigger has FIRED (S-55-B landed) → needs a decision at the
checkpoint. See BACKLOG "Park backstop".

## Read order (after you finish this file)

1. **Memory** — `~/.claude/projects/-home-stack-code-slop/memory/MEMORY.md` (auto-loaded). Key NEW entries (2026-05-30): `feedback-handoff-no-volatile-state`, `project-coverage-completeness-audit`, `project-handoff-integrity-audit`, `project-backlog-stale-gate-blast-radius`; plus `project-knowledge-lifecycle-audit`, `project-rocinante-deploy`, `feedback-one-orchestrator-per-batch`, `feedback-orchestrator-cwd-verification`, `feedback-prompt-and-menu-formatting`, `feedback-manager-role-handoff` (points here).
2. **CLAUDE.md** (auto-loaded; BACKLOG triage — park rule strengthened; deploy fact corrected; one-orchestrator-per-batch).
3. **`.claude/ROBOT.md`** — Robot mode doctrine; BACKLOG triage discipline (strengthened park rule + the known enforcement gap); subagent preamble (`git -C <worktree>` pin).
4. **`.claude/AUTONOMOUS-DEFAULTS.md`** — default register (processor-pattern contract incl. filename-as-shared-symbol; worktree-artifact trap; dispatch pattern).
5. **`docs/BACKLOG.md`** — every item triaged; the "Park backstop" note + the `[→ S-74]`/`[→ batch-11]`/`[→ S-75]` entries.
6. **`docs/POST-BATCH6-WAVE-MAP.md`** — THE ROADMAP: batch-9 S-74 / batch-10 S-75 (Wave 4) / batch-11 Enforcement-Lifecycle (Wave 3, with the owned Readiness spec).
7. **`docs/KNOWLEDGE-LIFECYCLE-AUDIT.md`** (charter) + **`docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`** (the audit's findings — the reconciliation methodology, the 8-class taxonomy, why prior audits missed these).
8. **`.claude/waves/S-74-*` and `S-75-*`** — the two fire-ready waves + their launch prompts.
9. **`docs/MERGE-LOG.md`** — audit trail; newest at top.
10. **`tools/merge_wave_to_main.py`** + **`tools/sanctioned/`** — sanctioned merge channel + toolkit; your primary handoff tools.
11. **`docs/WALK-BACK-LOG.md`** + **`docs/ACCESS-REQUESTS.md`** — doctrine-removal log; install/allow queue.
(Batch-6/7/8 wave files are landed/spent — don't re-fire.)

## Immediate next actions (S-74 executed; your first job is to review+merge it)

0. **VERIFY before acting — do not trust the SHA/liveness above.** `git switch main`;
   `git rev-parse origin/main`; confirm no orchestrator owns the checkout (`git worktree list`,
   `git branch --list '*S-74*'`, `.claude/run/status/`, `.claude/run/blockers/`). **READ the S-74
   closing output `.claude/run/status/S-74.md` before touching S-74** — it is the handoff payload.
1. **Review + merge S-74.** Spot-check the merge-tree is conflict-free vs current main and
   re-confirm the PINNED contracts + SHA-verify rider on `wave/S-74-deploy-hardening` (HEAD
   d6b93b1) — the coordinator already verified them (status file), so this is confirmation not
   re-derivation. `python3 tools/merge_wave_to_main.py wave/S-74-deploy-hardening`; push via
   `/tmp/lift-push-restore.py all`.
2. **Sweep S-74.** Prune `wave/S-74-deploy-hardening` + A–D branches + any worktrees; archive
   run-state to `.claude/run-archive/`; correct the appended MERGE-LOG entry; flip the 6
   `[→ S-74]` BACKLOG entries to `[x]` + cross-ref `docs/DEPLOY.md` from the Rocinante entries.
   **ALSO in this sweep (owed):** (a) land the `check_backlog_stale` blast-radius BACKLOG item
   (memory `project-backlog-stale-gate-blast-radius`), routed to batch-11; (b) commit the combined-
   audit charter + launch prompt to `.claude/waves/` (design in the two audit memories).
3. **Fire batch-10 (S-75) — ONLY after S-74 is on main.** Paste `.claude/waves/S-75-LAUNCH-PROMPT.md`
   into a fresh Opus orchestrator. Review + merge as above. AFTER merge, apply the one-line v5-hook
   touchpoint (Stream B; v5 isn't worktree-able — edit directly).
4. **Fire the combined Coverage+Handoff audit — ONLY after S-74 AND S-75 are on main.** Paste the
   launch prompt committed in step 2. Read-only; it commits a report to a branch for your review,
   does NOT merge. Then **draft batch-11 (accelerated)** from its blast-radius targets + the
   check_backlog_stale item + the Handoff Protocol/automation doctrine.
5. **Each batch landing:** BACKLOG re-annotation + retro + MERGE-LOG audit; at the 2026-07-15
   backstop, re-triage all parked items per the strengthened rule.

**Merge mechanics:** single-wave batches merge clean via the sanctioned tool. For
multi-branch batches with additive conflicts, use the merge-worktree integration pattern
(build off main in a scratch worktree, resolve keep-both, verify ms-enforce + suite, then
ONE clean sanctioned merge) — the batch-6 MERGE-LOG entry is the worked example.

## Working patterns / discipline

### Sanctioned channel hierarchy
- Merges to main → `tools/merge_wave_to_main.py` (runs ms-enforce branch-isolated, appends a MERGE-LOG entry to the working tree which YOU then commit/correct — push status + notes).
- Settings lift/restore + force-push + filter-branch + rm-recursive → `tools/sanctioned/` (`robot_settings.py`, `force_push_tag.py`, `filter_branch_secret_scrub.py`, `rm_recursive_safe.py`).
- Push to origin → `/tmp/lift-push-restore.py all` (lifts the push deny, pushes, restores).
- Canonical wave-mode deny profile → `.claude/settings-wave-mode-profile.json`.

### Cross-session HEAD safety (REINFORCED 2026-05-30 — bit us twice this session)
- The hazard is the SHARED working tree `/home/stack/code/slop`. Orchestrator *subagents*
  are isolated (worktrees), but a session's OWN cwd is the main checkout — drafting/audit
  sessions `git switch -c docs/wave-draft-X` THERE and leave it checked out, so the NEXT
  session's commits LEAK onto that branch. This session: the deploy-hardening drafter left
  its branch checked out → the K-L charter commit landed on it (cherry-picked back); and
  stale batch-7/8 `worktree-agent-*` branches/worktrees lingered (pruned).
- **Rule:** while ANY orchestrator/drafter/audit session is using the main checkout, do NO
  main-side git ops there — wait, or isolate yourself (`git worktree add /tmp/slop-manager
  origin/main`). After such a session finishes, your FIRST action is `git switch main` +
  verify branch/tree state before anything. (Fixing this — sessions in dedicated worktrees
  — is folded into S-75's ritual scope.)
- Verify with `git -C`/abs-paths and trust exit codes, not scrollback (memory `feedback-orchestrator-cwd-verification`).

### Handoff hygiene — state durable facts, never volatile state (NEW 2026-05-30)
- A handoff must NOT assert another session's liveness / lock / run-state — that goes stale by
  read-time (this bit us: a prior handoff said the orchestrator was "still running"; it had closed
  by the time the next Manager started). State durable facts + pointers, and NAME the verification
  the next session must run (`.claude/run/status/`, worktrees, branches, session registry).
- The incoming session MUST obtain + READ the waited-on session's CLOSING OUTPUT before acting
  (the run-status file / final message). Not asking for it is how detail gets dropped.
- Memory `feedback-handoff-no-volatile-state`. Systematized by the Track-B handoff-integrity audit.

### BACKLOG triage (enforced; park rule STRENGTHENED 2026-05-30)
- Every entry: `[→ S-NN-stream]` | `[park: re-eval <DATE>]` | `[x]` | `[—]`.
- A `[park]` now REQUIRES all three: a **measurable** trigger, a **mandatory backstop
  re-eval DATE**, and an **owner** (Manager-retro interim / S-75 ritual permanent). A
  vague/dateless/already-fired trigger is invalid. All current undated parks carry a
  2026-07-15 backstop.
- `check_backlog_stale` only catches bare `[ ]` today — it does NOT yet flag overdue/
  dateless/fired parks (that gate is owed by S-75's ritual). Until then YOU enforce it at
  each batch-landing + the backstop date.
- Pure `[ ]` >14 days is a triage failure. Pre-batch planning includes a BACKLOG sweep.

### Walk-back log (enforced)
- Any doctrine rule REMOVAL needs an entry in `docs/WALK-BACK-LOG.md` (four questions).
  STRENGTHENINGS (like this session's park-rule tightening) are not walk-backs.
- `ms-enforce check_walkback_log` (warn-only) catches commits removing ≥3 lines from `.claude/ROBOT.md`, `.claude/AUTONOMOUS-DEFAULTS.md`, or `CLAUDE.md` without a log reference.

### Cleanup-wave doctrine
- "fix-all-failures" was walked back; focused waves don't expand scope.
- **Inverse:** dedicated cleanup waves drain accumulated pre-existing issues (S-57/S-58/S-66/S-67 pattern). When BACKLOG accumulates ≥10 open items in one category, draft a cleanup wave.

### Sensitive paths in acceptEdits (your session is acceptEdits, NOT bypassPermissions)
- Writes to `.claude/waves/` and `.claude/run/` trigger sensitive-file prompts; no silencing exists (documented `[—]` in ACCESS-REQUESTS). Prefer `docs/` where possible; use Bash heredocs for new files under `.claude/`.

### Multi-line commit messages
- Don't build them from a `!` prefix (Bash eats the quote). Use repeated `-m` flags or `git commit -F <file>`.

## Open meta-patterns (the structural backbone)

The user's "where do point-fixes hide structural patterns" analysis, updated 2026-05-30:
1. Sanctioned-exception pattern — LANDED (merge tool + S-68 toolkit).
2. Tool-enforced doctrine — LANDED (S-69 gates).
3. Walk-back log — LANDED.
4. Aging policy for warn-only gates → **batch-11 (deferred, owned).**
5. Test-data lifecycle → **batch-8 S-71 ✅ LANDED.**
6. Doctrine self-audit → **batch-11 (deferred, owned).**
7. Wave-file schema → addressed by batch-7's `_TEMPLATE.md` + validator.
8. **(NEW) Knowledge-lifecycle / reality-reconciliation** — the operator was the
   detector-of-last-resort for stale/dropped/un-owned facts → **batch-10 S-75
   (drafted/fire-ready).** Adds the 4th aging leg (probes age) and strengthened the park
   rule. The recurring theme: truth is reliable when **derived/reconciled against physics**,
   rots when **stored-and-trusted**; the fix is owned reconciliation, not more memory.

## Communication with the user
- Concise; the user is direct and decisive. They tolerate long responses when the meta-thinking IS the point.
- **Structural answers, not point-fixes.** When you catch yourself proposing a per-occurrence patch, step back and fix the class.
- **Formatting (memory `feedback-prompt-and-menu-formatting`):** the prompt comes LAST (never alongside open decisions); menus are numbered/labeled lists, not paragraphs; concise recs without whys; ALWAYS label selectable options with a number/letter; copy-paste prompts wrapped in `====` dividers with a "Prompt for X to do Y starts here:" header.
- They fire shell commands via the `!` prefix (it runs in their shell, bypassing your tool deny-list — useful for ssh/sudo you can't run).
- When they say "do this" they mean it; "think about this" wants analysis first.

## Helper scripts in `/tmp/` (verify with `ls /tmp/`; EPHEMERAL — not canonical)
- `/tmp/lift-push-restore.py` — lift push-deny → push origin main → restore. KEEPER (your push path).
- `/tmp/fix-detached-head.py` — FF main from a detached commit; recovery template.

## Open follow-up items
- `[→ S-74]` deploy-hardening — realized when batch-9 executes; flip `[x]` after it lands.
- `[→ batch-11]` enforcement-lifecycle core + the 2 woven adjacents — deferred (owned, re-eval 2026-07-15).
- `[→ S-75]` the gap-discovery ritual must monitor deferred-wave/parked triggers + flag dateless/overdue/fired parks (the automatic enforcement the park-rule strengthening still lacks).
- **Rocinante (test server) housekeeping** (operator-side; memory `project-rocinante-deploy`): ghost-container reconciliation via Settings → System Health; optional `.env` `MS_TRUSTED_HOSTS` dedup. The `check_push_status.sh` unpulled-detection edit is uncommitted in the v5 repo (operator commits it with their docs work).
- Parked items: all carry the 2026-07-15 backstop; the "Split CLAUDE.md" trigger has fired.

## What this session's prior Manager (me) did, and where you pick up

Done this session (2026-05-29 → 30):
1. **Landed batch-8 (S-71-TEST-DATA-HYGIENE)** — reviewed, merged (`96fd6a2`), swept, archived; logged the Rocinante deploy-hardening forensics into BACKLOG.
2. **Updated the Rocinante test server live** (08bbf42 → 55aded1, a 402-commit jump across the 2026-05-28 history rewrite) — `sudo ms-update` was silently broken; recovered by hand; the forensics became S-74. Corrected the false CLAUDE.md "no git on server" fact. Runbook in memory `project-rocinante-deploy`.
3. **Drafted + landed S-74-DEPLOY-HARDENING (batch-9)** — wave + launch prompt on main, dogfooded, with the post-update SHA-verify rider added.
4. **Ran the Knowledge-Lifecycle audit** (fresh Opus Auditor-Manager, 5-lens read-only fan-out + blind-spot critic) → **S-75 (batch-10)** + report on main, dogfooded. Two-owner architecture, GROUND-vs-XREF keystone, gap-discovery ritual.
5. **Strengthened doctrine** from the findings: subagent `git -C <worktree>` pin + filename-as-shared-symbol (batch-7 retro); **parks now require measurable trigger + backstop date + owner**; gave batch-11 readiness an owner + 2026-07-15 checkpoint; fixed batch-number drift (S-74=9, S-75=10, enforcement=11).
6. Refreshed this handoff.

A short 2026-05-30 coordination session then: fired S-74 (now executed + closed, pending review);
landed the Ring-0 working-tree check in the slop-process session-start hook; and scheduled 3
structural items (check_backlog_stale blast-radius, the combined coverage+handoff audit, the
no-volatile-state handoff doctrine) — all captured in the 4 new memories.

You pick up at: **S-74 has EXECUTED and its orchestrator has CLOSED — your first job is to verify
state, read `.claude/run/status/S-74.md`, then review + merge + sweep S-74** (incl. the two owed
sweep commits in Immediate next actions step 2). Then fire S-75, then the combined audit, then draft
batch-11. Nothing needs drafting before S-74 merges. See Immediate next actions.

## Final notes
- VERIFY no orchestrator/drafting/audit session owns the checkout before any main-side git op
  (`git worktree list` + `.claude/run/status/` + branches) — do not trust this doc's liveness claim,
  it is stale by read-time (see "Handoff hygiene"). At this doc's write-time none was running.
- Trust the audit trails — `docs/MERGE-LOG.md`, `docs/BACKLOG.md`, `.claude/run-archive/`, the memory dir — these are the institutional memory. But remember the lesson of this whole session: a stored claim can be stale; reconcile load-bearing facts against reality before relying on them.
- When in doubt, ask the user — they prefer one clarification question over silent wrong action.

Good luck. The infrastructure is solid; you're picking up at a clean state with two fire-ready batches and a clear queue.
