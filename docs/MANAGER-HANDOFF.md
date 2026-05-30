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

## Current state (as of 2026-05-30 — S-74 + S-75 LANDED; combined audit CLOSED + report landed on main; batch-11 DRAFTED; LR-1 fixed)

**Handoff-freshness now grounded on `.handoff-sha` (LR-1 fix):** the origin/main SHA
this handoff was refreshed against lives in the committed `.handoff-sha` file, NOT in
prose here. `check_handoff_freshness` reads that artifact (absence → DRIFT). Right after
a batch lands, the gate legitimately reads DRIFT ("refresh the handoff") until the next
refresh bumps `.handoff-sha` — that is the designed nudge, not a defect. Always
`git rev-parse origin/main` to confirm live state.

**VERIFY, don't trust these SHAs (stale by read-time — handoff doctrine):** `git rev-parse origin/main`;
`git -C /home/stack/code/slop status`; `git worktree list` (expect only the main checkout); `ls
.claude/run/status/` (empty = no active wave); read `docs/MERGE-LOG.md` + `docs/REVIEW-LOG.md`
(newest-at-top) for what actually landed. Do not assume any session's liveness.

- **✅ Batch-9 = S-74-DEPLOY-HARDENING — LANDED + swept** (merged `f185769`, pushed). `tools/deploy_lib.sh`
  shared helper; `ms-update`/`deploy.sh` aligned (service-user, fetch+reset, build-HOME); `MS_PORT`
  canonical; `.env`-authoritative config (`override=False`). The 6 Rocinante BACKLOG entries are `[x]`;
  `docs/DEPLOY.md` is the ownership/update runbook. No real-server CI — a Rocinante confirmation run is
  optional (memory `project-rocinante-deploy`).
- **✅ Batch-10 = S-75-KNOWLEDGE-LIFECYCLE — LANDED + swept** (merged `9983ceb`, pushed). Two-owner
  reality-reconciliation: runtime RealityView in `backend/core/agent.py`; dev-time warn-only gates
  `check_doc_reality` / `check_handoff_freshness` / `check_fact_freshness`; the GROUND-vs-XREF keystone
  now in CLAUDE.md; the gap-discovery ritual in AUTONOMOUS-DEFAULTS. **The v5 SessionStart-hook
  one-liner was COMMITTED + pushed this session** (slop-process `2443ea4`) — no longer an owed
  cross-repo touchpoint. NOTE: the orchestrator wrote its closing status under the FULL wave name
  (`.claude/run-archive/2026-05-30-batch10/status/S-75.md`, archived) not the conventional short name —
  a status-filename gap, logged as Track-B evidence for the handoff audit.
- **✅ Combined Coverage+Handoff AUDIT — CLOSED + report landed on main.** Ran 2026-05-30 (fresh Opus
  Auditor-Manager + 7 read-only investigators + blind-spot critic). Deliverable
  `docs/COVERAGE-HANDOFF-AUDIT-REPORT.md` (both tracks + critic + P0–P9 + co-batching) committed on
  branch `docs/audit-coverage-handoff` and merged to main with this batch. Unifying finding: the
  **"GROUND-gate brownout"** (absence-of-ground returns the same color as a match). **Two LIVE-RED on
  main:** LR-1 (`check_handoff_freshness` defeated by the `95dc0e0` prose rewrite) — **FIXED this session**
  (grounded on `.handoff-sha`); LR-2 (`slop-reality-probe` never installed → S-75 reconciler touches zero
  physics, rc=127) — **OWED to the operator** (install on the host + put on the deploy path; see Open
  follow-ups). **F10** (the two-session / Manager-handoff-artifact gap — a Manager handoff must emit a
  distinct Manager-handoff prompt, not just the working launch prompt) was MISSED by the audit's Track B
  and caught at Manager review → folded into batch-11 S5 (BACKLOG).
- **🟢 Batch-11 = ENFORCEMENT-LIFECYCLE — DRAFTED + fire-ready pending its pre-fire design review.** Wave
  file `.claude/waves/BATCH-11-ENFORCEMENT-LIFECYCLE.md` (10 streams, P0/S1 aging-engine hard-first) +
  single-orchestrator launch prompt `.claude/waves/BATCH-11-LAUNCH-PROMPT.md`. Absorbs the audit's P0–P9
  + all `[→ batch-11]` BACKLOG items (S-70+S-72 aging core = P0/S1; `check_backlog_stale` registry;
  `audit_single_entity_hardcode.py`; `check_independent_review` + artifact-existence leg; status-protocol
  additions; provenance + pre-commit-hook adjacents; the 42-finding drain; F10). **OWED before the
  operator fires it:** one independent review of the wave DESIGN (BACKLOG `[→ batch-11 — OWED before
  firing]`, ages red under `check_backlog_stale`). Re-eval checkpoint 2026-07-15.

**NEW DOCTRINE enshrined this session (all in CLAUDE.md — READ them; each was independently reviewed):**
- **No phantom owners; no silently-trusted manual step** — every operator-owned/deferred item resolves
  to done-now / real-owner+trigger / red-when-stale-signal; cross-repo touchpoints are owned + committed
  by the session that makes them (this killed the orphaned v5-hook).
- **Reuse-and-blast-radius checkpoint** — search the toolkit before building; when adapting, regression
  + red-path test + caller-map; parameterize the SEAM, not the coverage; `[red-signal: PENDING]` (the
  batch-11 scanner).
- **Independent review for significant changes** — one independent pass BEFORE a significant change
  lands; depth-1, loop-free (a review's only output is a `docs/REVIEW-LOG.md` entry); trigger = a
  mechanical floor (doctrine files / new sanctioned tool / new `def check_` / irreversible git) + the
  `check_independent_review` gate (batch-11, `[red-signal: PARTIAL]`). The two reviews this session are
  the first REVIEW-LOG entries.
- **Two push paths** (repo-agnostic via `--repo`): `tools/sanctioned/lift_push_restore.py` = routine
  UNAUDITED (no receipt-loop); `robot_settings.py push-then-restore` = audited one-off. The `/tmp/`
  helper is SUPERSEDED — do not use it.
- **Meta-pattern #11** (write-time vs audit-time enforcement asymmetry) — the parent of the three
  checkpoints above: reconcile against an independent reference (toolkit / entity-set / independent mind)
  at write-time, not only at audit-time.

**Session arc (2026-05-30):** reviewed+merged+swept S-74 → fired+reviewed+merged+swept S-75 →
committed+pushed the v5 hook (killing a phantom-owner) → a deep structural thread enshrined the three
write-time checkpoints + meta-pattern #11, each dogfood-reviewed by a fresh Opus adversarial subagent
(both reviews recorded in `docs/REVIEW-LOG.md`). Combined audit ungated + ready.

## Wave queue (current)

Roadmap: `docs/POST-BATCH6-WAVE-MAP.md` (READ IT). Live sequence:

- **Batches 7 (S-73), 8 (S-71), 9 (S-74), 10 (S-75)** ✅ ALL LANDED + swept. Not queue items;
  their wave files are spent — don't re-fire.
- **Combined Coverage+Handoff AUDIT** — 🟢 UNGATED, ready to fire (NOT a code wave; read-only,
  produces batch-11). Present `.claude/waves/COVERAGE-HANDOFF-AUDIT-LAUNCH-PROMPT.md` to the operator.
- **Batch-11 = ENFORCEMENT-LIFECYCLE** — ⏸ drafted AFTER the audit reports. Scope grew this session
  (see Current state). Readiness trigger = ≥30d since the newest warn-only gate + gates exercised ≥2
  batches + a stable fired/never-fired classification across 2 reviews; **hard checkpoint 2026-07-15**.
  Spec: POST-BATCH6-WAVE-MAP §"Wave 3 — Readiness".

Parked items all carry a **2026-07-15 backstop re-eval** (strengthened park rule). The "Split
CLAUDE.md" park's trigger has FIRED (S-55-B landed) → needs a decision at the checkpoint. See BACKLOG
"Park backstop".

## Read order (after you finish this file)

1. **Memory** — `~/.claude/projects/-home-stack-code-slop/memory/MEMORY.md` (auto-loaded). Key NEW entries (2026-05-30): `feedback-handoff-no-volatile-state`, `project-coverage-completeness-audit`, `project-handoff-integrity-audit`, `project-backlog-stale-gate-blast-radius`; plus `project-knowledge-lifecycle-audit`, `project-rocinante-deploy`, `feedback-one-orchestrator-per-batch`, `feedback-orchestrator-cwd-verification`, `feedback-prompt-and-menu-formatting`, `feedback-manager-role-handoff` (points here).
2. **CLAUDE.md** (auto-loaded; BACKLOG triage — park rule strengthened; deploy fact corrected; one-orchestrator-per-batch).
3. **`.claude/ROBOT.md`** — Robot mode doctrine; BACKLOG triage discipline (strengthened park rule + the known enforcement gap); subagent preamble (`git -C <worktree>` pin).
4. **`.claude/AUTONOMOUS-DEFAULTS.md`** — default register (processor-pattern contract incl. filename-as-shared-symbol; worktree-artifact trap; dispatch pattern).
5. **`docs/BACKLOG.md`** — every item triaged; the "Park backstop" note + the `[→ S-74]`/`[→ batch-11]`/`[→ S-75]` entries.
6. **`docs/POST-BATCH6-WAVE-MAP.md`** — THE ROADMAP: batch-9 S-74 / batch-10 S-75 (Wave 4) / batch-11 Enforcement-Lifecycle (Wave 3, with the owned Readiness spec).
7. **`docs/KNOWLEDGE-LIFECYCLE-AUDIT.md`** (charter) + **`docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`** (the audit's findings — the reconciliation methodology, the 8-class taxonomy, why prior audits missed these).
8. **`.claude/waves/COVERAGE-HANDOFF-AUDIT-LAUNCH-PROMPT.md`** + **`docs/COVERAGE-HANDOFF-AUDIT.md`** — the ungated audit (your first job to present).
9. **`docs/MERGE-LOG.md`** + **`docs/REVIEW-LOG.md`** — audit trails (merges; independent reviews); newest at top.
10. **`tools/merge_wave_to_main.py`** + **`tools/sanctioned/`** — sanctioned merge channel + toolkit (incl. the two push paths); your primary handoff tools.
11. **`docs/WALK-BACK-LOG.md`** + **`docs/ACCESS-REQUESTS.md`** — doctrine-removal log; install/allow queue.
(Batch-6/7/8/9/10 wave files are landed/spent — don't re-fire.)

## Immediate next actions (audit CLOSED + landed; batch-11 DRAFTED; your first job is the batch-11 pre-fire review, then fire it)

**Two-session model — the operator runs the orchestrators, not you.** YOU generate + finalize each
launch prompt and PRESENT it in a `====` block (prompt-formatting doctrine); the operator opens a FRESH
session to run it. You coordinate, review, merge; you never run a wave/audit yourself. Orchestrators
self-report to `.claude/run/status/<wave>.md` — poll it; verify liveness, don't assume it. (Known gap:
status filename isn't pinned — glob both the short AND full wave name when looking for closing output.)

0. **VERIFY state first — do not trust the SHAs above.** `git rev-parse origin/main`; `git status`;
   `git worktree list` (expect only the main checkout); `ls .claude/run/status/` (empty = no active
   wave); read `docs/MERGE-LOG.md` + `docs/REVIEW-LOG.md` for what landed.
1. **Run the batch-11 pre-fire independent review** (OWED — BACKLOG `[→ batch-11 — OWED before firing]`).
   The wave DESIGN is High-complexity = a "significant change" → one fresh-Opus adversarial review +
   `docs/REVIEW-LOG.md` entry (grounded on a committed record) BEFORE presenting the launch prompt. Then
   present `.claude/waves/BATCH-11-LAUNCH-PROMPT.md` (single orchestrator, 10 streams, P0/S1 hard-first)
   to the operator for a fresh session. The audit (CLOSED) + batch-11 drafts already landed on main.
2. **LR-2 is OWED to the operator** — install `slop-reality-probe` on the Rocinante host and add it to
   the automated deploy path (`deploy_lib.sh` / `DEPLOY.md`) so the S-75 reconciler touches physics again
   (today rc=127 → 0 verified, exits 0). Until then doc-vs-reality stays INDETERMINATE. See Open
   follow-ups + memory `project-rocinante-deploy`.
3. **Each batch landing:** sweep (prune branches/worktrees, archive run-state to `.claude/run-archive/`,
   correct the MERGE-LOG entry), BACKLOG re-annotation, retro. **At 2026-07-15:** re-triage all parked
   items per the strengthened rule (the "Split CLAUDE.md" park trigger has already FIRED).
4. **For any significant change YOU author** (doctrine edit, new gate/sanctioned tool, irreversible
   git): follow the tiered independent-review discipline and record it in `docs/REVIEW-LOG.md`. Push
   routine via `tools/sanctioned/lift_push_restore.py` (NOT the superseded `/tmp` helper).

**Merge mechanics:** single-wave batches merge clean via the sanctioned tool. For
multi-branch batches with additive conflicts, use the merge-worktree integration pattern
(build off main in a scratch worktree, resolve keep-both, verify ms-enforce + suite, then
ONE clean sanctioned merge) — the batch-6 MERGE-LOG entry is the worked example.

## Working patterns / discipline

### Sanctioned channel hierarchy
- Merges to main → `tools/merge_wave_to_main.py` (runs ms-enforce branch-isolated, appends a MERGE-LOG entry to the working tree which YOU then commit/correct — push status + notes).
- Settings lift/restore + force-push + filter-branch + rm-recursive → `tools/sanctioned/` (`robot_settings.py`, `force_push_tag.py`, `filter_branch_secret_scrub.py`, `rm_recursive_safe.py`).
- Push to origin (ROUTINE) → `python3 tools/sanctioned/lift_push_restore.py [--repo PATH] [--branch NAME]` (lifts the push deny, pushes, restores; **unaudited** — no SANCTIONED-OPS-LOG receipt, so routine pushes don't loop). `--repo` pushes any `Nnyan/*` repo (e.g. `--repo /home/stack/v5`); default SLOP main. Canonical home of the ex-`/tmp/lift-push-restore.py` (promoted + generalized 2026-05-30).
- Push to origin (AUDITED one-off) → `python3 tools/sanctioned/robot_settings.py push-then-restore [--repo PATH] [--branch NAME]` — same lift/push/restore but **writes a SANCTIONED-OPS-LOG receipt**. Use ONLY when you want a tamper-evident receipt; NOT for routine pushes (the tracked receipt would dirty the tree on every push → commit→push→receipt loop). Routine pushes are already covered by git history + MERGE-LOG.
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
11. **(NEW) Write-time vs audit-time enforcement asymmetry** — sound principles ("fix the class",
    "reuse before build") live only as audit-time doctrine or narrow instances, never as proactive
    write-time forcing functions; the enforced "stay narrow" beats the merely-encouraged "blast
    radius" by default. Resolution = the Reuse-and-blast-radius checkpoint (CLAUDE.md) + its GROUND
    scanner (batch-11). NOTE: the meta-pattern's own resolution IS the scanner — without it, the
    meta-pattern is itself stored-and-trusted.

## Communication with the user
- Concise; the user is direct and decisive. They tolerate long responses when the meta-thinking IS the point.
- **Structural answers, not point-fixes.** When you catch yourself proposing a per-occurrence patch, step back and fix the class.
- **Formatting (memory `feedback-prompt-and-menu-formatting`):** the prompt comes LAST (never alongside open decisions); menus are numbered/labeled lists, not paragraphs; concise recs without whys; ALWAYS label selectable options with a number/letter; copy-paste prompts wrapped in `====` dividers with a "Prompt for X to do Y starts here:" header.
- They fire shell commands via the `!` prefix (it runs in their shell, bypassing your tool deny-list — useful for ssh/sudo you can't run).
- When they say "do this" they mean it; "think about this" wants analysis first.

## Helper scripts in `/tmp/` (verify with `ls /tmp/`; EPHEMERAL — not canonical)
- `/tmp/lift-push-restore.py` — **SUPERSEDED 2026-05-30** by `tools/sanctioned/lift_push_restore.py`
  (canonical, unaudited routine push, repo-agnostic via `--repo`). The `/tmp` copy is a stale
  duplicate; do not use it. (It was load-bearing-in-`/tmp` — exactly the rot the "No phantom owners"
  doctrine targets; promoting it into the toolkit closed that.)
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
