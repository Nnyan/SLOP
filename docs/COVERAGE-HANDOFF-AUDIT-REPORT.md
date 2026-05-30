# Coverage-Completeness & Handoff-Integrity Audit — Report

**Produced by:** the Opus **Auditor-Manager** session (Robot mode) + **7 read-only investigators**
(Track A: doctrine-invariants, code/data-invariants, operator-owned hunt, single-entity-hardcode
hunt; Track B: handoff-history, status-protocol, end-session+prompt-doctrine) + **1 phase-2
blind-spot critic**, 2026-05-30.
**Charter:** `docs/COVERAGE-HANDOFF-AUDIT.md`.
**Precedent reused:** `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md` (the GROUND-vs-XREF keystone).
**Status:** discovery/design output. Drives **batch-11 (Enforcement-Lifecycle)**.
**Branch:** `docs/audit-coverage-handoff` (committed, **NOT merged/pushed**).
**Gate confirmed:** S-74 (`f185769`) + S-75 (`9983ceb`/`e309c98`) both on main; HEAD==origin/main==`95dc0e0`.

This report is **independently derived from evidence and reconciled against physics**, not theory.
The Auditor-Manager re-ran every load-bearing claim against live repo state (dogfooding the
discipline the report prescribes — see §1). Where a subagent asserted a gate's behavior, the
Manager executed the gate.

---

## 0. The one-sentence finding (and the class that unifies it)

SLOP has built an impressive **gate library** but it is **warn-only end-to-end** for the entire
doctrine/process surface, and — the deeper finding — its few real GROUND gates share a single
silent failure mode the blind-spot critic named the **"GROUND-gate brownout":** *a probe that
degrades from GROUND to INDETERMINATE / unparseable / missing-input keeps returning the same
color as a match — the absence-of-ground path is indistinguishable from a pass.* Two instances are
**LIVE on `main` right now** (§0.1). The single highest-leverage batch-11 deliverable is therefore
**not** any individual point-fix but the long-deferred **probe-aging leg (ADR 0020 rule 4):** make
sustained INDETERMINATE a first-class, aging, **red-eligible** state — which closes all four known
brownouts as one class *and* makes the coming flood of new warn-only gates self-policing.

### 0.1 LIVE-RED — two defects on `main` this READ-ONLY audit cannot fix (Manager must act)

> **This audit commits only to `docs/audit-coverage-handoff` and is forbidden to touch `main`
> (Robot binding rules).** Both items below are verified live and routed to batch-11, but they are
> degrading *now* — the Manager should fix them on `main` out-of-band, ahead of batch-11, or
> explicitly accept the gap. Logged in `.claude/run/questions/COVERAGE-HANDOFF-AUDIT.md` (D1).

- **LR-1 (F7) — the keystone handoff gate is DEFEATED on main.** Commit `95dc0e0` (the current
  tip) rewrote the machine-parseable `- **origin/main at \`<SHA>\`**` bullet in
  `docs/MANAGER-HANDOFF.md` into prose ("VERIFY, don't trust these SHAs"). `check_handoff_freshness`
  now emits `INDETERMINATE — could not parse origin/main SHA` **permanently** (Manager reproduced
  live). A doc-hygiene improvement silently neutered the one load-bearing GROUND handoff gate.
- **LR-2 (GAP-1) — the S-75 reconciler has touched ZERO physics since it shipped.**
  `slop-reality-probe` was never installed on the deploy host; `ssh rocinante slop-reality-probe`
  exits `rc=127` (command-not-found). `tools/audit_doc_reality.py` treats this as INDETERMINATE and
  **exits 0** (Manager reproduced live: `0 verified, 0 DRIFT, 3 INDETERMINATE`, exit 0). The entire
  two-owner / GROUND-vs-XREF S-75 investment is silently null, and the aging-leg that ADR 0020
  specified to catch exactly this (Decision 3 rule 4) was never built.

---

## 1. Method & the dogfooded reconciliation

7 investigators fanned out read-only and concurrently (max-parallel per `feedback-wave-max-parallel`);
no worktrees (findings, not edits). A phase-2 critic then attacked the **merged** findings of both
tracks — derive-independently-first, then attack (the K-L Appendix-attack discipline). The
Auditor-Manager reconciled the highest-severity claims against physics rather than trusting the
subagents:

| Claim | Reconciliation against physics | Verdict |
|---|---|---|
| F7 handoff gate defeated | ran `check_handoff_freshness.py` → INDETERMINATE; `grep '\*\*origin/main at'` → none | **CONFIRMED** |
| GAP-1 probe never installed | ran `audit_doc_reality.py --host rocinante` → exit 0, 3 INDETERMINATE, rc=127 | **CONFIRMED** |
| `check_independent_review` is vaporware | `grep "def check_independent_review"` → absent | **CONFIRMED** |
| `audit_single_entity_hardcode.py` absent | `ls` → not found | **CONFIRMED** |
| ratchet skips `tools/` | `check_linecount.py:44` CATEGORIES has no `tools/` pattern | **CONFIRMED** |
| status-file lookup short-only | `merge_wave_to_main.py:208-223` searches `f"{wave_key}.md"` only | **CONFIRMED** |
| `check_coverage_rules` is XREF false-green | `ms-enforce:120` reads `data/coverage_map.json` text, returns False | **CONFIRMED** |
| probe-aging leg unbuilt | `grep dead_probe\|probe_age\|last_run` across `tools/`+`ms-enforce` → empty; ADR 0020:134 specifies it | **CONFIRMED** |

**The keystone rubric (reused verbatim from K-L):** a tier / handoff step is **"covered" ONLY if its
gate can go RED against PHYSICS** (GROUND). Doctrine-only / warn-only / an unenforced checklist =
**YELLOW, not green.** This report does not rubber-stamp.

**Critical framing correction (META):** the `ms-enforce` `TIER_0/1/2` labels are **execution-order
buckets (speed), NOT enforce-vs-warn tiers.** A check blocks the run **iff its function returns
`False`** (`ms-enforce` `sys.exit(0 if failures==0)`). Reading the `return` of every gate:
**every doctrine/process gate returns `True` unconditionally → all warn-only (YELLOW).** Only
code-quality gates (`check_linecount`, `check_catalog_env_var_syntax`, migrations/schema-sync,
`check_track_status`, semgrep/ruff/mypy/bandit, and — see §4 — the XREF `check_coverage_rules`)
return `False` = blocking.

---

## 2. Track A — Coverage-Completeness (snapshot)

### 2.1 Tiered-invariant inventory + coverage classification

| Invariant / tier | Members | Class | Gate / mechanism (file:line) | RED vs physics? | Gap |
|---|---|---|---|---|---|
| **3 repo rings** | SLOP / slop-process (`/home/stack/v5`) / mediastack | **UNCOVERED** | only SLOP handoff-SHA (`check_handoff_freshness.py:57-75`); Ring-0 WIP hook lives in slop-process | partial, SLOP-only, warn | no SLOP gate covers the other two rings' sync/WIP/queue |
| **BACKLOG triage states** | `[→]`/`[park]`/`[x]`/`[—]`/`[ ]` | **Warn + partial UNCOVERED** | `audit_backlog_stale.py:61-77` (warn) | XREF; no physics | only bare `[ ]`>14d flagged; `[park]`/`[→]` auto-clean; **dateless silently skipped** (`:178-180`) |
| **Park-rule triad** | trigger / backstop-date / owner | **Doctrine-only** | prose (`ROBOT.md:19-25`) | no probe | zero enforcement of any leg |
| **4 aging legs** | facts / doctrine / gate / **probes** | **1 warn-GROUND, 1 weak, 2 UNBUILT** | facts: `audit_fact_freshness.py` (GROUND, warn); doctrine: `check_doc_decay` (ADR dates only) | facts only | **gate-aging + probes-age UNBUILT** (ADR 0020:134) |
| **ms-enforce gate set** | ~55 `check_*` | split | `ms-enforce` | code-gates yes; doctrine-gates no | ~20 doctrine gates warn-only; several doctrine rules have NO gate (below) |
| **Sanctioned-channel hierarchy** | 9 denies + ~60 no-exceptions | **Warn + XREF-only** | `check_sanctioned_channels_complete` (`ms-enforce:1395`) | **NO** (deny-string vs doc-table) | a deny pointing at a deleted/broken tool passes; **lift→restore cycle never probed** (§4c) |
| **K-L reconciler-trust vocab** | GROUND/XREF/INDETERMINATE/UNPROBED | **Doctrine-only** | defined CLAUDE.md; applied per-probe | n/a | no meta-gate verifies a probe claiming `verified` touches physics |
| **Independent-review trigger** | mechanical-floor vs declared | **UNCOVERED** | `check_independent_review` **DOES NOT EXIST** | no | CLAUDE.md self-stamps PENDING; acyclicity is unverifiable prose |
| **Walk-back-log discipline** | doctrine-removal commits | **Warn; no artifact leg** | `check_walkback_log` (`ms-enforce:1197`) | partial (numstat GROUND) but satisfied by **message-token presence only** (`:1249`) | a commit msg with "walkback" passes with no actual entry |
| **File-size ratchet categories** | 6 named categories | **Covered** (named) **+ UNCOVERED escapees** | `check_linecount.py:44-81` (blocking, real LOC) | YES for the 6 | **`tools/`, `backend/scripts/`, root `*.py`, `migrations/` UNCAPPED** (`classify()`→None→continue); `.sh`/`.yaml`/`.json` outside the extension aperture |
| **3 data dirs** | `/opt`,`/var/lib`,`/srv/.../config` | **UNCOVERED (values)** | `_defaults.py` (2 of 3); `audit_doc_reality.py` reconciles only is-git/owner/port | partial | path values not reconciled; `/srv/mediastack/config` has **no SoT constant** |
| **Dual CatalogEntry** | `to_catalog_entry()` ↔ Pydantic | **Covered (w/ hole) + doc-rot** | `test_rules_migration_batch1.py:222-268` (CI) | YES (raises on mismatch) | **doc claim FALSE** (no `CatalogEntry` in loader.py); test 1 checks only first manifest |
| **`_SLOP_MANAGED_VARS`** | frozenset | **Covered** | `test_..._batch1.py:39-86` (import+AST) | YES | mirror is XREF (acceptable) |
| **Quick Stacks `_DEFAULT_STACKS`** | platform.py SoT | **UNCOVERED** | none | no | a default stack referencing a dead app-key is uncaught |
| **Catalog env-var `${VAR}` syntax** | all manifests | **Covered** | `check_catalog_env_var_syntax` (blocking) | YES (parses YAML) | env: only (by design) |
| **Catalog manifest invariants** | 57 apps | **Covered (fields) + UNCOVERED (port uniqueness)** | `validate_manifests.yml`; `TestCatalogCompliance` | YES (fields) | no catalog-wide host-port uniqueness check |
| **Wave-file schema** | `.claude/waves/*.md` | **Warn-only** | `check_wave_file_preflight` returns True; `preflight_wave.py` orchestrator-time only | partial | broken wave passes ms-enforce/CI |
| **Cross-session HEAD / test isolation** | shared checkout | **Warn-only** | `check_test_isolation` (heuristic, returns True) | no | + **orphaned-worktree hazard has no signal** (§4d F8) |
| **Migration discipline** | `migrations/NNN_*` | **Covered** | `ms-enforce:442-534` (4 blocking GROUND) | YES (regen-and-compare) | solid |
| **AGENT_* constants / tier-0 exclusion** | agent.py | **Covered** | `test_..._batch1.py:94-214` (real StateDB) | YES | solid |
| **CI↔ms-enforce split (meta)** | invariant tests | **Hole** | tests ride `test.yml`, not `ms-enforce` | n/a | `ms-enforce --fast` does not run CatalogEntry/managed-vars/agent tests |

**Doctrine rules with NO backing gate (Doctrine-only / UNCOVERED):** park-rule triad;
independent-review floor (gate PENDING); cross-repo touchpoint ownership; reuse-and-blast-radius
checkpoint (self-stamped PENDING; `audit_single_entity_hardcode.py` absent); the ~20
`_not-mechanically-enforced_` Robot binding rules; "one orchestrator per batch" (gate is a
timestamp heuristic, warn-only).

### 2.2 Named hunt (i) — operator-owned / phantom-owner blast radius

Doctrine: every operator-owned/deferred item resolves to **(a)** done-now / **(b)** real owner+trigger
/ **(c)** a red-when-stale signal. *A manual step is "covered" ONLY if skipping it can go red.*

| Manual step | Where | Resolution | Red-when-stale? | Phantom-owner GAP? |
|---|---|---|---|---|
| **Install `slop-reality-probe` on host** | ships in repo; consumed `audit_doc_reality.py:133,160` | **NONE** (no deploy step) | **NO** (exit 0 forever) | **YES — the Ring-0 nominee (LR-2)** |
| Operator starts a session (sole probe trigger) | SessionStart hook | (c)-ish, session-relative | **NO** if no session runs | PARTIAL (accepted design; no backstop) |
| INDETERMINATE-persistence aging | ADR 0020:134 | **NONE** (unbuilt) | **NO** | **YES** (the catcher is itself unbuilt) |
| `[park]` entries: fired/dateless/ownerless (Split-CLAUDE, auto-bisect, 5 code-TODO parks) | `BACKLOG.md:54,55,92,93,107,108,116` | event-trigger, no owner | only one manual blanket-backstop (2026-07-15) | **PARTIAL** (un-enforced backstop guarding un-enforced steps) |
| The park-enforcement gate itself | `ROBOT.md:46-52` | **NONE** (owed, unbuilt) | **NO** | **YES** |
| Stale phantom-owner line in handoff | `MANAGER-HANDOFF.md:244` ("operator commits it with their docs work") | already done (`v5@2443ea4`) but line survives | n/a | resolved-but-rot (the exact banned phrasing, inside the doc that teaches the ban) |
| `.linecount-baseline --update-shrunk`, MERGE-LOG entry, handoff SHA, ACCESS-REQUESTS | various | (c) | **YES** (real gates) | NO — best-in-class examples |
| memory-file writes / pruning | `AUTONOMOUS-DEFAULTS.md:531` | (c) partial | staleness only, not missing-write | weak |

### 2.3 Named hunt (ii) — single-entity-hardcoded tools/gates

**One confirmed finding, already triaged:** `check_backlog_stale` / `audit_backlog_stale.py:85`
(`repo / "docs" / "BACKLOG.md"`) + wrapper `ms-enforce:1486` (`--repo str(REPO)` only) — hardcoded
to SLOP's single triage queue when the set is the 3 rings (slop-process `docs/TODO.md` ~84KB,
mediastack). Already `[→ batch-11]` (`BACKLOG.md:57`) with the `(repo,file,syntax)` registry plan
and a companion red-signal-tool entry (`:58`).

**Cleared (do NOT re-flag):** `lift_push_restore.py:46 SETTINGS_PATH` (recorded SLOP-session
scope-reason, docstring `:27-30`); `lift_push_restore.py`/`robot_settings.py push-then-restore`
(genuinely `--repo`-parameterized); the `tools/sanctioned/` family; `check_linecount.py` CATEGORIES
(exemplary registry — copy this shape); `audit_doc_reality.py` (`--repo`/`--host` parameterized);
`audit_todos.py`/`audit_archived_observations.py`/`audit_wave_out_of_scope.py` (SLOP-internal
coverage gates whose operand is not a plural-set member).

> **Critic caveat (heed it):** the "all-clear except the known one" result reflects a **narrow
> aperture**, not a clean system. The hunt is framed around "hardcoded *entity* from a plural set,"
> so it structurally cannot see the **hardcoded *set* hardcodes** — `check_linecount.py`'s
> `INCLUDED_EXTENSIONS`/`EXCLUDED_DIR_NAMES` frozensets (`:87,:90`) are themselves an uncovered
> plural set with no freshness signal. The uncapped-`tools/` finding (§2.1) is the narrow instance.

---

## 3. Track B — Handoff-Integrity (longitudinal)

### 3.1 Handoff failure-mode taxonomy (anchored to history)

- **F1 Volatile-state assertion.** Handoff states a peer session's liveness as fact.
  `02769fe:24` "⚠️ BATCH-7 IS RUNNING RIGHT NOW" — contradicted by MERGE-LOG (`4989d87` 13:23;
  fully landed `8c2415c` 13:55); the next handoff flipped to "LANDED" 18 min later. Sub-30-min
  half-life. (memory `feedback-handoff-no-volatile-state`.)
- **F2 Phantom liveness as first-action.** The volatile claim is wired into the incoming session's
  FIRST instruction (`13cf95a`, `02769fe:33`) — if the awaited session already closed, the incoming
  session waits on a ping that never comes. Fixed by step-0 VERIFY (`2ff7c97:110`).
- **F3 Dropped closing-output.** No gate detects whether the incoming session read the prior
  session's closing output (the actual payload). Honor-system.
- **F4 Status-filename convention drift.** Orchestrator wrote `S-75-KNOWLEDGE-LIFECYCLE.md`; Manager
  looked for `S-75.md`, found nothing, falsely logged "ended WITHOUT status." **Verified:**
  `merge_wave_to_main.py:208-223` `_find_status_file` searches `f"{wave_key}.md"` only (no full-name
  fallback); `_extract_wave_key:243` reduces to `S-NN`; ROBOT.md `<wave>` token (`:104,:424`) is
  never defined as short-vs-full. Missing file → None → **silently skipped as pass**.
- **F5 Phantom `/tmp` pointers as payload.** Up to 15 refs to `/tmp/lift-push-restore.py` as
  load-bearing handoff state; `/tmp` is wiped between sessions. Drained 15→6 via promotion to
  `tools/sanctioned/`; remaining refs now defanged.
- **F6 Duplicate-commit noise.** `13cf95a`/`37d96d4` byte-identical — history pollution.
- **F7 GROUND-gate brownout (LIVE RED).** See §0.1 LR-1. The fix the investigator proposed
  ("restore the parseable bullet") is **partially isomorphic to the disease** (re-creates a
  human-maintained prose token); the grounded fix is to **derive** the declared SHA from a committed
  machine artifact (e.g. a `.handoff-sha` written by `merge_wave_to_main.py`) and reconcile *that*
  vs `git rev-parse` — plus harden the gate so **absence → DRIFT, not INDETERMINATE**.
- **F8 (critic) Orphaned-worktree / shared-checkout hazard.** `MANAGER-HANDOFF.md:156-162` declares
  the shared tree a hazard defended by *convention* only. No lock/gate/probe detects concurrent
  writes or a leftover worktree from a crashed orchestrator. (`check_test_isolation` is a heuristic,
  warn-only.)
- **F9 (critic) REVIEW-LOG incoming-read signal.** Same defect as F3, applied to reviews: nothing
  detects whether the author read the reviewer's findings before acting.

### 3.2 Why the seamless handoffs worked (derive the positive pattern)

From the exemplars (`203c6c7`, `2ff7c97`, `840d593`): **store only durable facts + verification
instructions, never volatile state.** Concretely — (1) derived-not-asserted state (SHA always
paired with "confirm live: `git rev-parse origin/main`"); (2) an explicit **step-0 VERIFY gate**
before any action, handling both still-running and closed; (3) the **named closing-output as the
payload** ("READ IT FIRST"); (4) pointers to durable newest-at-top logs (MERGE-LOG, REVIEW-LOG) for
"what actually landed"; (5) liveness reframed as a **check with both outcomes handled**, never a
fact. This is the Knowledge-Lifecycle keystone applied to handoffs: derive/reconcile at use-time.

### 3.3 The Handoff Protocol (per-type, with red-when-stale signals)

| Handoff type | Durable payload (store) | Verify-at-use (never store) | Red-when-stale signal |
|---|---|---|---|
| **session→session / Manager→Manager** | prose state + pointers to MERGE-LOG/REVIEW-LOG | `git rev-parse origin/main`; `git worktree list`; `ls run/status/` | `check_handoff_freshness` **derived from a committed `.handoff-sha`**, absence→DRIFT |
| **orchestrator launch** | the wave file + the launch prompt (file + one-line pointer) | preflight; gate confirmation | `preflight_wave.py` red on BLOCKED |
| **orchestrator return** | `.claude/run/status/<S-NN>.md` (canonical SHORT name) | read the terminal `**State:**` marker | new gate: missing/misnamed file → DRIFT; non-terminal State at merge → block (§3.5) |
| **end-session wind-down** | refreshed handoff + memory + MERGE-LOG + triaged BACKLOG | — | `check_session_winddown` Stop-hook (§3.4) |

### 3.4 End-session wind-down — currently VIBES; the fix

**Structural fact:** there is **NO `hooks` block** in SLOP (`.claude/settings.json` does not exist;
`settings.local.json` has `permissions` only). The "SessionStart hook" `check_push_status.sh` is run
**by convention**, not harness-registered. So there is **zero machine-enforced session boundary** —
every end-session step is silently skippable.

**Proposed:** create a committed `.claude/settings.json` with a `SessionStart` hook (the existing
`check_push_status.sh`) and a `Stop` hook running a new **`check_session_winddown`** aggregator that
reuses the existing gates (handoff-freshness, status-COMPLETE, MERGE-LOG, backlog-stale,
push-status) **plus one new GROUND leg**: memory-index orphan detection (every `*.md` in the memory
dir has a `MEMORY.md` line — touches the filesystem, may assert verified/DRIFT). Land warn-only;
promote per the standard trigger.

> **Critic caveat — do not oversell the hook (§4f).** A Stop hook that exits non-zero **re-prompts /
> surfaces feedback; it does NOT retroactively force** a push or memory-write the session never did,
> and may be ignored during teardown. And the hook config is itself text in `settings.json` with no
> probe asserting it is registered and firing — **it becomes the next F7** (a single point of
> failure that silently disarms the whole boundary). The Stop hook is necessary but **secondary, and
> must NOT ship before the brownout detector** (§5 P0), or it becomes another un-watched GROUND gate.

### 3.5 Orchestrator↔Manager status protocol (charter §5 — bake into the STANDARD template)

S-74 proved the **Manager (reader)** side is robust (it can read closing output + detect blockers
unprompted). The **emitter** side is unspecified. Add these to the standard `.claude/ROBOT.md`
orchestrator template (NOT a one-off prompt):

1. **Top-of-file marker — mandatory first non-blank line:** `**State:** RUNNING` where State ∈
   `RUNNING | BLOCKED | NEEDS-INPUT | COMPLETE | CLOSED`. The Manager polls this line.
2. **Pinned filename:** `.claude/run/status/<S-NN>.md` — the **SHORT** wave key (e.g. `S-75.md`,
   NOT `S-75-KNOWLEDGE-LIFECYCLE.md`); must match `_extract_wave_key()`. Add the same one-liner to
   `_TEMPLATE.md` and the launch-prompt template. Backstop: `_find_status_file` gains a
   `glob(f"{wave_key}*.md")` fallback that **WARNs on inexact match** (visible, not silently
   absorbed).
3. **Non-blocking questions channel:** on ambiguity, do NOT block / do NOT `AskUserQuestion` —
   proceed via `AUTONOMOUS-DEFAULTS.md` and append the question + the default taken + the authorizing
   rule to `.claude/run/questions/<S-NN>.md`. (Resolves the zero-prompt-Robot tension.)
4. **Terminal write:** "set `**State:** CLOSED` as your final action before ending."
5. **Manager poll-loop** (`/loop` or scheduled wakeup, ~5 min — runs finish in minutes):
   `grep '^\*\*State:\*\*' run/status/*.md` + `ls run/blockers/ run/questions/`; terminate when all
   waves show a terminal State with no open blocker; escalate on BLOCKED/NEEDS-INPUT; flag a
   `RUNNING` older than threshold as possibly-hung.

**Red-when-missing gate (the keystone leg):** a new check that, for every wave branch at merge-time,
asserts (a) a status file exists at the canonical SHORT path (filesystem GROUND → else DRIFT, not
skip — today `_find_status_file`→None is a silent pass), and (b) its first line is a **terminal**
State token (not `RUNNING`); BLOCKED/NEEDS-INPUT blocks the merge gate. *This session is dogfooding
the protocol — see `.claude/run/status/COVERAGE-HANDOFF-AUDIT.md` (State marker + questions channel).*

### 3.6 Prompt doctrine (formalize memory `feedback-prompt-and-menu-formatting` → doctrine)

Proposed section for `.claude/ROBOT.md` (note: this edit **trips the independent-review mechanical
floor** — the batch-11 wave landing it carries the four-question rationale + a REVIEW-LOG entry;
honestly stamped advisory, no physics red-signal because formatting is a Communication/taste rule):

- **WHEN to surface a prompt:** only when *all decisions it depends on are resolved*. If any choice
  is open, ASK FIRST (labeled menu), get the answer, surface the prompt in a *later* turn — never in
  the same turn as an open decision.
- **Single-sentence vs full:** full prompts saved to `.claude/waves/<WAVE-ID>.md` + a one-line
  pointer (`SLOP repo /home/stack/code/slop — read .claude/waves/<WAVE-ID>.md and execute every
  deliverable exactly as specified.`); inline prompts only for trivial one-offs.
- **Ordering:** prompt is LAST; pre-prompt content under labeled headers; no actionable text after
  the prompt except a short waiting line.
- **Menus not paragraphs;** every option labeled with a number/letter.
- **Concise recommendation, no whys;** if multiple options are right, say so.
- **Block format:** `Prompt for <AGENT> to do <GOAL> starts here:` then `====` divider, readable
  lines (no run-on, no tables inside), closing `====`.

### 3.7 Automate-vs-ask catalog (high-leverage rows)

| Step | Currently | Automatable? | Mechanism | Needs human? |
|---|---|---|---|---|
| push main / cross-repo touchpoint commit | ASK (handoff pattern) | **YES** | `lift_push_restore.py --repo <path>` already exists; replace "handoff pattern (default)" with "lift pattern" | only diff-review |
| run session-start / end checks | convention | **YES** | register as SessionStart/Stop hooks (§3.4) | no |
| memory-index completeness | vibes | **YES** (GROUND vs FS) | Stop-hook orphan leg | *what* to remember = judgment |
| host doc-vs-reality reconcile | ASK (ambient SSH) | detection YES, auth NO | rides operator SSH | **auth genuinely human** |
| irreversible git (filter-branch/force-push/scrub) | ASK (separate review session) | **NO (by design)** | — | **yes** |
| memory prune / merge-rollback-fix decision | ASK | **NO** | — | **yes (taste)** |

---

## 4. Blind-spot critic — the deep layer (attack of the merged findings)

- **(a) Reflexivity trap — worse than K-L's.** `docs/REVIEW-LOG.md` **self-confesses** that its
  founding entries cite ephemeral `/tmp` transcripts — the Independent-Review doctrine's own record
  violates its own "durable, committed record, NOT a `/tmp` transcript" rule. A review-log entry is
  text-vs-nothing (XREF with no second text). **This audit's own batch-11 target list is itself a
  stored-and-trusted store** that nothing reconciles ("was every finding fixed?") at batch-11-close,
  with no `last_verified` and no freshness signal — born rotting. *Mitigation baked in:* §5 P5 makes
  the target list reconcilable; this report is on a tracked branch (promotion discipline), not the
  gitignored run-archive.
- **(b) The false-green master.** `check_coverage_rules` (`ms-enforce:120`) is the **one
  doctrine-adjacent gate that returns `False` (blocking)** — and it is **pure XREF**: it reads
  `data/coverage_map.json` and checks each rule has a *named* enforcement entry. It can bless a rule
  "covered" when the named gate itself returns True unconditionally. The single blocking coverage
  gate launders warn-only gates into "covered." Neither investigator named it.
- **(c) Unenumerated tier — the sanctioned-tool lift→restore PHYSICS.** Both tracks audited the
  sanctioned-channel *doc table* (XREF) and the push-tool *lineage*, but **nobody probes that after a
  sanctioned push the deny is actually back**. If `lift_push_restore.py`'s restore silently no-ops
  (wrong path, swallowed exception, settings schema drift), the repo is left with pushes UN-denied —
  a safety-rail regression with no watcher. *The tools that bypass the rails have no rail watching
  them.*
- **(d) Handoff modes F8/F9** (in §3.1).
- **(e) The flood that eats its own children.** Every fix here lands warn-only (doctrine mandates
  it); promotion needs N=5 clean runs + UNPROBED≈0 + **a deliberate human act**, with **no forcing
  function and no gate-aging leg**. So the response to "too much is warn-only" is *more warn-only
  gates* whose promotion depends on the already-bottlenecked human — and each new gate is a future
  F7 (it can brown out, and the leg meant to catch dark gates is the one nobody built).
- **(f) The Stop-hook is not the GROUND boundary it's sold as** (caveat in §3.4).
- **(g) THE CLASS: "GROUND-gate brownout."** F7, the S-75 null, `audit_status_file_freshness`
  unparseable→`continue` (`:200`), and `audit_backlog_stale` dateless→skip (`:21`) are **one failure
  mode, not four incidents:** *the absence-of-ground path returns the same color as the match path.*
  INDETERMINATE / unparseable / missing-input / no-date all collapse to "not red." No gate treats
  **sustained INDETERMINATE** as a defect. This is the K-L "cure is isomorphic to the disease" rule
  generalized: a GROUND gate becomes the disease the moment its ground goes unreachable **unless
  INDETERMINATE is itself tracked, aging, and red-eligible.**

---

## 5. THE prioritized blast-radius target list → batch-11

Ordered by leverage. Each names its generalizing mechanism and **its own failure mode + red-signal**
(per charter §8 — a new mechanism that can't go red is theater).

**P0 — GROUND-gate brownout detector = the probe-aging leg (ADR 0020 rule 4).** *Build FIRST,
before any new warn-only gate.* One cross-cutting reconciler: for every registered probe, record per
run whether it reached ground (`verified`/`DRIFT`) or browned out
(`INDETERMINATE`/unparseable/missing-input/no-date); flag any probe that has **not touched physics in
N runs** (sibling to `.factprobe-baseline.json`'s shrink-only ratchet). *Blast radius:* closes F7,
LR-2/S-75-null, `audit_status_file_freshness:200`, `audit_backlog_stale:21` **as one class**, and
makes P1–P9 self-policing (a new gate that browns out ages red). *Failure mode:* the brownout
baseline is itself stored state — missing baseline = "establish, don't alarm"; distinguish
*configured-host rc127* (DRIFT — should be installed) from *no-host-configured* (quiet) so a
deliberately-headless context doesn't cry wolf. *Red-signal:* a probe in the registry with no
ground-touch in N runs → DRIFT.

**P1 — Fix the two LIVE-RED brownouts (LR-1, LR-2).** (LR-1) Re-add a machine-parseable SHA — but
**derived**: `merge_wave_to_main.py` writes `.handoff-sha`; `check_handoff_freshness` reconciles that
vs `git rev-parse`; **absence → DRIFT not INDETERMINATE**. (LR-2) Move `slop-reality-probe` install
onto the automated deploy path (`deploy_lib.sh`/`DEPLOY.md`) so it rides every `git pull`. Both then
covered by P0's red-eligible INDETERMINATE. *(Manager may fix on main ahead of batch-11 — see §0.1.)*

**P2 — Cross-repo `(repo, file, syntax)` triage-queue registry.** Generalize `check_backlog_stale`
over the 3 rings (SLOP `BACKLOG.md` now; slop-process `docs/TODO.md` + mediastack `[→]`/`[park]`
deferred with trigger+date+owner). Unify with the per-ring handoff/WIP/queue probes so **one
registry drives all per-ring reconcilers**. *Failure mode:* a ring absent from the registry is
silently unwatched → the registry itself becomes a tier the coverage audit re-checks (assert every
on-disk ring has a row). *Red-signal:* registered repo unreachable → INDETERMINATE (caught by P0);
ring on disk with no row → DRIFT.

**P3 — Park-rule triad enforcement.** Extend `audit_backlog_stale` so each `[park]` requires a
parseable backstop `re-eval YYYY-MM-DD` (DRIFT if missing/past), a non-vague trigger (INCONSISTENT,
lower-tier, on a vagueness denylist), and an owner token; each `[→ batch-NN]` DRIFTs if that batch
already landed (cross-check MERGE-LOG); **close the dateless-skip escape hatch** (`:178-180`).
*Failure mode:* vagueness heuristic over/under-fires → hard DRIFT only on the mechanical legs
(missing/past date, landed batch), INCONSISTENT for vagueness.

**P4 — Session-boundary hooks** (`.claude/settings.json` + `check_session_winddown` Stop hook +
SessionStart `check_push_status.sh` + memory-index orphan GROUND leg). *Build AFTER P0.* *Failure
mode (§4f):* the hook config silently disarms → P0 must register the hook-config itself as a probe
("is the Stop hook present and firing?"); a non-zero Stop exit re-prompts, it does not force —
honestly stamp it advisory.

**P5 — Status-protocol template + red-on-missing-status gate** (§3.5): pin the short filename, add
the `**State:**` marker + questions channel + terminal-CLOSED to the standard template, and the
merge-time gate (missing/misnamed → DRIFT; non-terminal State → block). Reconcile the **batch-11
target list itself** at batch-close (close the reflexivity trap §4a): a gate asserting every P-item
here is either landed (cite the commit/gate) or carries a live BACKLOG `[→]`.

**P6 — Sanctioned-channel GROUND leg** (§4c): for each registry-row tool, assert the file exists +
imports + calls lift/restore/audit (AST), and a per-tool **red-path test** (feed a crash, assert the
deny is restored). *Failure mode:* AST presence ≠ correct ordering → the red-path test is the real
proof.

**P7 — Walk-back-log + (eventual) independent-review artifact-existence leg.** Add to
`check_walkback_log` the GROUND leg that a doctrine-removal commit actually added a dated
WALK-BACK-LOG entry (numstat add non-empty), not just a message token. Build the PENDING
`check_independent_review` with its specced artifact-existence GROUND leg (cited record missing →
DRIFT) — and ground REVIEW-LOG entries on a **committed** record, never `/tmp` (§4a).

**P8 — Ratchet aperture fix:** add a catch-all `uncategorized` category (or a shrink-only
UNCATEGORIZED counter) so `classify()` can never return None for an included extension; widen
`INCLUDED_EXTENSIONS` to flag oversize `.sh`/`.yaml`. *Failure mode:* too-generous catch-all cap is
theater → baseline current violators and pick a real cap.

**P9 — Point coverage gaps** (lower-tier queue, not all-failures): `_DEFAULT_STACKS` referential test;
catalog-wide host-port uniqueness (with intended-collision allowlist); correct the false CatalogEntry
doc claim + union-over-all-manifests in field-sync test 1; reconcile the 3 data-dir path values +
add `/srv/mediastack/config` SoT; surface that invariant tests ride `test.yml` not `ms-enforce`.

---

## 6. Co-batching analysis for batch-11 (Enforcement-Lifecycle)

Batch-11 absorbs three streams: **(A)** this audit's targets, **(B)** the `check_backlog_stale`
registry (P2, already a `[→ batch-11]` BACKLOG item), **(C)** the deferred Enforcement-Lifecycle
core (S-70 + S-72). The aging-engine is a **shared DESIGN contract**, not a delivery coupling.

**Hard sequence (single dependency):** **P0 (brownout/probe-aging engine) lands FIRST on the batch
branch**, because P1, P4, P5, P6, P7 all rely on "INDETERMINATE is red-eligible" to be non-theatrical
(per §4e/§4g, shipping any of them before P0 manufactures future F7s). P0 ⊃ the S-70/S-72 aging-engine
core — so **the deferred Enforcement-Lifecycle core and P0 are the same stream** (design already
shared per S-75 §7). Build it once.

**Max-parallel streams (file-disjoint, all after P0 merges to the batch branch):**

| Stream | Targets | Primary files (disjoint) | Model |
|---|---|---|---|
| **S1 — aging engine / brownout (= P0 + S-70/S-72 core)** | P0 | new `tools/audit_probe_aging.py` + `.probe-health-baseline.json`; `ms-enforce` registration | opus |
| **S2 — cross-repo registry** | P2 | `tools/audit_backlog_stale.py` (→ `(repo,file,syntax)`), `ms-enforce:1486` | opus |
| **S3 — park-triad** | P3 | `tools/audit_backlog_stale.py` parser legs | sonnet |
| **S4 — session hooks + wind-down** | P4 | new `.claude/settings.json`, new `tools/check_session_winddown.py` | opus |
| **S5 — status protocol + gate** | P5 | `.claude/ROBOT.md` template, `_TEMPLATE.md`, `tools/merge_wave_to_main.py`, new status gate | sonnet |
| **S6 — sanctioned GROUND leg** | P6 | `tools/check_sanctioned_*`, red-path tests | opus |
| **S7 — walkback/indep-review artifact legs** | P7 | `ms-enforce` `check_walkback_log`, new `check_independent_review` | opus |
| **S8 — ratchet aperture** | P8 | `tools/check_linecount.py` CATEGORIES + extension set | sonnet |
| **S9 — point coverage** | P9 | `backend/api/platform.py` test, manifest port test, `test_rules_migration_batch1.py`, CLAUDE.md doc-fix | sonnet |

**Disjointness caveats (Manager to resolve at wave-authoring):** S2 and S3 both touch
`audit_backlog_stale.py` → **must be ONE stream or sequenced** (S2 reshapes the file's I/O signature,
S3 adds parser legs — author S2 first, S3 against its result; or fold into one). S5 and S7 both touch
`ms-enforce` registration but at distinct, non-overlapping check blocks (append-only) — parallel-safe
if each only adds its own `check_` + registration line. Everything depends on **S1 merged first**.

**Doctrine triggers to honor in the wave files:** S4/S5/S7 + the §3.6 prompt-doctrine edit all touch
`CLAUDE.md`/`.claude/ROBOT.md`/`AUTONOMOUS-DEFAULTS.md` or add a `tools/sanctioned/` file or a
`def check_` → each **trips the independent-review mechanical floor** and needs the four-question
rationale + a REVIEW-LOG entry (grounded on a committed record). No WALK-BACK-LOG entry is needed for
the additions (they are strengthenings); only a softening of an existing rule would trip it.

---

## 7. Honest limits + each new mechanism's failure mode

- **No audit eliminates friction-surfaced gaps** — it converts an infinite trickle into a bounded,
  prioritized inventory the system owns. The coverage registry, the Handoff Protocol, and **this
  report** can all rot; each named its own failure mode + red-signal above (the registry → §5 P2;
  the Stop hook → §4f/P4; the target list → §4a/P5).
- **The brownout detector (P0) is the lynchpin** — if it is itself never run (no SessionStart hook
  yet) it browns out too. P0 + P4 are mutually reinforcing but P0 must not *depend* on P4: register
  P0 in `ms-enforce` (runs on every push) so it has a non-hook trigger.
- **Consensus error** (doc *and* reality both wrong) remains invisible to reconciliation.
- **The operator stays triage-of-last-resort** — the win is bounded/batched inventory, not
  elimination of the human; the flood risk (§4e) is real and is precisely what P0 self-polices.

---

## 8. Deliverables produced by this audit

1. This report (`docs/COVERAGE-HANDOFF-AUDIT-REPORT.md`).
2. The §5 prioritized blast-radius target list (P0–P9) + §6 co-batching analysis → batch-11.
3. The §3.5 orchestrator status-protocol template additions (charter §5 deliverable).
4. Dogfooded status protocol: `.claude/run/status/COVERAGE-HANDOFF-AUDIT.md` (State marker) +
   `.claude/run/questions/COVERAGE-HANDOFF-AUDIT.md` (non-blocking channel).

> **Reflexivity note (dogfooding):** committed to the tracked branch `docs/audit-coverage-handoff`,
> not the gitignored run-archive. The Manager reviews this report and drafts batch-11 from §5/§6;
> the LIVE-RED items (§0.1) warrant out-of-band attention on `main` first.
