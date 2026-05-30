# SLOP — Claude Code Instructions

## Project overview

S.L.O.P. (Self-hosted Linux Orchestration Platform) — public repo (`Nnyan/SLOP`).
Backend: FastAPI + Python (`backend/`). Frontend: Vue 3 + TypeScript (`frontend/src/`).
Catalog: YAML manifests for 56 installable apps (`catalog/apps/`).
Backend tests run against a local venv; no external server required for unit tests.

## Walking back a doctrine rule — record the orphaned need

Every rule encodes a NEED. Walking back a rule without addressing the
underlying need leaves it orphaned — and orphaned needs re-surface later
as point-issues, hit one at a time.

When proposing to remove or soften a rule in `.claude/ROBOT.md`,
`.claude/AUTONOMOUS-DEFAULTS.md`, or this file, append an entry to
`docs/WALK-BACK-LOG.md` answering four questions: what was the rule
preventing, why walking back, what's the new mechanism for the underlying
need, and what's the failure mode of the new mechanism. The entry is
required before the walk-back commit lands.

`ms-enforce check_walkback_log` (warn-only initially) flags doctrine-removing
commits that don't reference a WALK-BACK-LOG entry.

Reference: `docs/WALK-BACK-LOG.md` for format and current entries.

## BACKLOG triage — no item stays bare `[ ]` open

`docs/BACKLOG.md` is not a forever-parking lot. Every entry must be in one of:
`[→ S-NN-stream]` (scheduled), `[park: re-eval <DATE>]` (deferred with a **measurable
trigger + a mandatory backstop re-eval date + an owner** — see `.claude/ROBOT.md`
§"BACKLOG triage discipline"; a vague/dateless/already-fired trigger is NOT valid),
`[x]` (done), or `[—]` (won't fix with reason). Pure `[ ]` without an assigned
target is not a valid long-term state.

Pre-batch planning includes a BACKLOG review. Items >14 days bare `[ ]` are
triage failures, not normal pending. Cleanup waves (S-57, S-58, S-66, S-67
pattern) are how accumulated pre-existing work gets drained — the no-fix-all-
failures rule applies to focused waves, NOT to dedicated cleanup waves.

Reference: `.claude/ROBOT.md` § "BACKLOG triage discipline" and
`.claude/AUTONOMOUS-DEFAULTS.md` § "BACKLOG entry sits bare `[ ]` for >14 days".

## Robot mode dispatch — ONE orchestrator per batch (not one per wave)

When firing the next Robot batch, the default is **ONE Opus orchestrator session
that handles all waves in the batch** — not one orchestrator session per wave.
The single orchestrator reads all wave files, dispatches all parallel streams
together (subagents in worktrees), waits for any sequential dependencies, then
merges each stream into its appropriate wave branch.

Reference: `.claude/ROBOT.md` § "Launching a Robot run" — architecture; and
`.claude/AUTONOMOUS-DEFAULTS.md` § "Category: orchestrator dispatch pattern".

**The only time multiple orchestrator sessions are warranted:** when a later
wave has a hard dependency on an earlier wave being merged to main first (rare;
state this dependency explicitly in the wave file when present).

This rule was lost briefly between Round 2 and the planned next batch (one
orchestrator-per-wave prompts were drafted by mistake). The pattern is
documented here so future sessions generating prompts do not deviate.

## No phantom owners; no silently-trusted manual step

Deferring work to "later, when someone does the related thing" is **not** assigning an
owner — it orphans the work, which then rots unmonitored. Every operator-owned or
deferred item must resolve to one of:

- **(a)** done **now**, by the session that surfaced it;
- **(b)** a **real owner** (a role/session actually scheduled to act) plus a **real
  trigger** (a date or a measurable event); or
- **(c)** a **freshness signal that goes red when it goes stale**.

"The operator will do it with their docs work," "fire when the signal accrues," and an
ownerless `[park]` are the same defect — a phantom owner. An operator-owned step with no
red-when-stale signal is a coverage gap of the same class as an unreconciled state tier.
This composes with the K-L keystone below: *a manual step is only "covered" if skipping
it can go red.*

**Corollary — cross-repo touchpoints.** A change to another repo (e.g. `v5` /
slop-process, mediastack) is **owned and committed by the session that makes it**, then
and there — never deferred to an unscheduled future session. The owning session commits
it; the push rides the standard sanctioned channel (`tools/sanctioned/lift_push_restore.py
--repo <path>` — the repo-agnostic **routine** push; `robot_settings.py push-then-restore`
is the **audited** variant for the rare one-off you want a SANCTIONED-OPS-LOG receipt for).
There is no hard "operator owns repo X"
boundary: the commit needs no human, and the push is the same deny-lift the Manager
already drives. "Operator owns repo X" is convention, and convention is a rot generator —
reclassify it.

This is an addition/strengthening, not a walk-back (no WALK-BACK-LOG entry required).

## Reuse-and-blast-radius checkpoint

A write-time forcing function, sibling to "No phantom owners" above. When authoring a tool /
gate / fix whose operand is a member of a KNOWN plural set (the 3 repo rings, the file-size
ratchet categories, the sanctioned-channel hierarchy, the BACKLOG-triage queues), OR whose home
directory already has a sibling family (`tools/`, `tools/sanctioned/`,
`frontend/src/composables/`):

- **(a) Reuse.** Check the sibling family for an existing/adaptable solution BEFORE building new.
  Adapting one requires all three: run its suite (regression) + a test that feeds a known-bad
  input and asserts DRIFT/non-zero exit (proving the new path can go red — the
  `check_handoff_freshness` pattern) + map every caller/side-effect (blast radius). The recorded
  reuse note is *rationale* (XREF-class — it may flag INCONSISTENT, never assert "verified"); it
  is NOT a green light.
- **(b) Blast radius.** PARAMETERIZE THE INTERFACE over the set (a `--repo`/registry param), NOT
  the implementation. Ship the one entity in scope; file a BACKLOG `[→]`/`[park]` (trigger +
  backstop date + owner) for the uncovered members. Hardcoding a single entity when the set is
  plural is a defect UNLESS the scope-reason is recorded. When the set is genuinely open at
  write-time, the obligation is the SEAM (a registry, not a hardcode) plus a freshness signal on
  the registry itself — you needn't know all members, but you must not foreclose them.

This composes with focused-wave discipline: you generalize the SIGNATURE (cheap, in-scope), never
pre-implement the COVERAGE (expensive, deferred). It is the general form of the frontend
"grep before you create" rule below, which is its `.vue` instance.

`[red-signal: PENDING — `tools/audit_single_entity_hardcode.py` (routed to batch-11). Interim
enforcement = the combined Coverage+Handoff audit's single-entity-hardcode target list + Manager
batch-landing review.]` (This is honestly stamped PENDING so it is not mistaken for green — per the
keystone, a checklist with no red-signal is yellow.)

## Independent review for significant changes

The third face of meta-pattern #11 (reconcile against an independent reference at write-time): the toolkit (Reuse checkpoint), the entity set (Blast radius), and — here — an **independent mind**. A significant change gets one independent review BEFORE it lands. Designed so it can never loop or freeze.

**Trigger — two honest tiers:**
- **Mechanical floor** (gate-detectable, ungameable-without-a-trace): a commit that touches `CLAUDE.md` / `.claude/ROBOT.md` / `.claude/AUTONOMOUS-DEFAULTS.md`, adds a file under `tools/sanctioned/`, adds a `def check_` to `ms-enforce`, or invokes an irreversible-git sanctioned tool (filter-branch / force-push / secret-scrub). The floor **statically excludes `docs/REVIEW-LOG.md` and `check_independent_review` itself** — so a review (whose only output is a REVIEW-LOG entry) can never trigger a review (acyclicity in code, not prose; changing the exclusion requires a WALK-BACK-LOG entry).
- **Declared** (advisory, audit-caught, NOT gate-enforced): plural-set blast-radius, a High-complexity wave *design*. The gate cannot detect these; they rely on author honesty + the standing audits. Do not market them as enforced.

**Reviewer by tier (cost gradient):**
- Doctrine edit/addition → a self-administered **four-question rationale** (the walk-back four questions, extended to additions: what need, why this mechanism, its failure mode, its red-signal). Cheap; the 80%.
- New enforcement mechanism (gate / sanctioned tool) → an author-prompted **fresh Opus adversarial subagent** (derive-independently-then-attack), advisory only.
- Irreversible git → a **full separate session** with a fixed, doctrine-pinned charge the author cannot rewrite (subagent independence is partly fictional when the author writes the charge).

**Termination (depth = 1, enforced):** a review's only output is a REVIEW-LOG entry + advisory findings — never a vote/veto. The author **reconciles findings against physics and records the reconciliation** (accept/reject per finding + why); the reviewer is XREF-class (flags, never asserts "verified"). No review-of-the-review; synthesis errors are caught at audit-time, not by infinite pre-review.

**Elasticity (wider/tighter, loop-free):** widen freely in the advisory layer (more read-only review is safe); the floor always fires. **Tighten the floor only via a reviewed doctrine change** (which trips WALK-BACK-LOG) — never a casual recorded note, because under-review is the dangerous direction. There is no narrow-below-floor channel.

**Escape valve (no freeze):** for genuine urgency, proceed-and-owe — but the owed review is a **BACKLOG entry under `check_backlog_stale`** (it ages red), not a free log line, so "always urgent → never reviewed" self-polices.

**Mechanism + red-signal (honest):** `docs/REVIEW-LOG.md` — one entry per significant change: reviewer, charge, key findings, and the author's per-finding reconciliation; it cites a **durable, committed** review record (NOT a `/tmp` transcript — that is itself the phantom-pointer rot). `check_independent_review` (batch-11) reuses the `check_walkback_log` shape (numstat floor-path + message token) PLUS an **artifact-existence GROUND leg** (cited record missing ⇒ DRIFT). `[red-signal: PARTIAL]` — GROUND on *fabrication*, UNPROBED on *substance* (substance rides the audit + Manager batch-landing review). **Hard stop: never auto-promote to blocking on the clean-run timer until the GROUND leg lands** — a string-presence check that goes clean would otherwise mislead a promoter into blessing theater.

## Knowledge-Lifecycle & reconciliation

SLOP is reliable where truth is **derived/reconciled against physical ground truth
at use-time** (the line ratchet reads real LOC; the port linter reads `/proc/net/tcp`;
the SLOP AI Agent reconciles live containers-vs-DB) and rots where truth is
**stored-and-trusted** (CLAUDE.md facts, memory files, `MANAGER-HANDOFF.md`). The fix
is **methodology — derive + reconcile + a freshness signal that can fail loudly — not
a bigger memory store.** Full rationale: `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`;
durable decision: ADR 0020 (`docs/adr/0020-knowledge-lifecycle.md`).

**The single discipline:** *a green light is only trustworthy if it can go red against
physics.* A probe that cannot fail against ground truth is theater — do not build it.

**Pinned reconciler-trust vocabulary (defined ONCE here; all probes/streams use it
verbatim):**

- **GROUND** — a probe that touches physics (a socket, the Docker socket, the
  filesystem, `git rev-parse`, process env) and therefore MAY assert `verified`.
- **XREF** — a text-vs-text comparison; may only flag `INCONSISTENT`, never assert
  `verified`.
- **INDETERMINATE** — ground truth was unreachable; emitted LOUDLY, never silently
  downgraded to `OK`.
- **UNPROBED** — no probe exists for this fact yet; counted by a ratchet that may
  shrink, never grow; never blessed as `verified`.

**Verdict tokens** every probe emits: `verified` (GROUND match) · `DRIFT` (GROUND
mismatch) · `INCONSISTENT` (XREF mismatch) · `INDETERMINATE` (unreachable). **Only
`DRIFT` on a load-bearing claim files to BACKLOG**; `INCONSISTENT`/low-confidence go to
a lower-tier queue that does not count against BACKLOG triage discipline. Findings
dedup (update, never re-file).

**No silent pass.** A green light means "I touched reality and it matched" — never "I
had nothing to check." A probe that can't reach ground truth emits `INDETERMINATE`,
never `OK`. **Probes age (the fourth leg of the aging trilogy):** a probe that touched
nothing this run is a candidate-dead probe → flagged; `UNPROBED` rows ratchet down,
never up. **Apply `last_verified`/`verify_probe` frontmatter ONLY where a real probe
exists** — a `last_verified` with no probe behind it is false assurance, defeated by
date-bumping.

**Two-owner firewall (HARD):** the SLOP AI Agent (`backend/core/agent.py`) is
**runtime-only** — it emits a reality view of the running instance and never reads or
adjudicates docs. All dev-time/process/doc knowledge is owned by a **separate dev-time
reconciler** (`tools/audit_doc_reality.py` → `ms-enforce check_doc_reality`,
warn-only) that derives + reconciles + files `[gap-discovery]` BACKLOG entries and
**never accumulates** its own store. Doc-vs-host reconciliation rides the operator's
**ambient SSH** at SessionStart (no tool stores a credential); host unreachable ⇒
`INDETERMINATE`.

**Promotion-to-blocking trigger:** all Knowledge-Lifecycle gates land **TIER_1
warn-only**. A gate earns promotion to blocking only when BOTH hold: (a) clean signal
across N consecutive runs (recommend N=5, no benign false `DRIFT`), AND (b) its
`UNPROBED` ratchet is at/near zero for the class it governs. Promotion is a deliberate
recorded act, never silent (Enforcement-Lifecycle wave's job).

## Frontend architecture rule — NO business logic in view files

**View files (`frontend/src/views/*.vue`) must contain only:**
- Template markup
- Reactive refs wired to composables or direct API calls
- Simple event handlers (one-liners)

**Before adding any function, computed, or reactive state to a view file:**
1. `grep -n "function\|computed\|const.*=.*ref\|const.*=.*computed" frontend/src/views/<File>.vue` — check if similar logic already exists before creating a new one.
2. If the logic exceeds ~5 lines or is reusable, create or extend `frontend/src/composables/use<Feature>.ts` instead.

This grep-before-you-create step is the `.vue` INSTANCE of the general "Reuse-and-blast-radius
checkpoint" above (its parent rule) — `frontend/src/composables/` is the sibling family you search
first. The general rule governs all sibling families and known plural sets, not just views.

**File-size limits for views are enforced globally — see the "File size limits (ratchet-enforced)" section below.** Vue views fall under the `frontend/src/views/**.vue` category (600-line hard cap).
Existing violators (SetupView ~1711, SettingsView ~1369, ModelsView ~1182, HealthView ~752, CatalogView ~642 in SLOP) are grandfathered but should shrink over time, not grow.

## File size limits (ratchet-enforced)

Files have category-tiered size caps enforced by a CI ratchet. New files must come in under their category hard cap. Existing oversize files are recorded in `.linecount-baseline.json` and may shrink but never grow. CI fails the PR if either rule is broken.

| Category | Soft (warn) | Hard / ratchet ceiling |
|---|---|---|
| Production code: `backend/core/**`, `backend/health/**`, `backend/manifests/**`, `backend/platform/**`, `backend/infra/**`, `backend/agent/**` | 400 | **500** |
| API routers: `backend/api/**` | 600 | **800** |
| Vue views: `frontend/src/views/**.vue` | 500 | **600** (existing rule) |
| Frontend other: `frontend/src/**` excluding views | 400 | **500** |
| CLI / installer: `cli/**`, `installer/**` | 600 | **800** |
| Tests: `tests/**`, `installer/tests/**` | — | **1000** informational, does NOT fail CI |

### How to update the baseline

- **Intentionally shrunk a file:** run `python3 tools/check_linecount.py --update-shrunk` and commit the refreshed `.linecount-baseline.json`.
- **Need to split a baselined file:** split it, then run `--update-shrunk` (or regenerate with `--snapshot`) to refresh.
- **Need to (rarely) raise a baseline:** edit `.linecount-baseline.json` by hand; include justification in the commit message. Discouraged.

### How it interacts with the frontend "no business logic in views" rule

The two rules compose: views have a 600-line hard cap AND must contain no business logic. The composables pattern (`frontend/src/composables/use<Feature>.ts`) is how you satisfy both — extracting logic out of the view both keeps the view under cap and keeps reusable logic in a testable, shared location.

## Catalog apps

- YAML manifests: `catalog/apps/<key>.yaml`
- Known env vars written to `.env` by wizard: `PUID`, `PGID`, `TZ`, `CONFIG_ROOT`, `MEDIA_ROOT`, `DOMAIN`
- If a catalog app uses a var not in that list, it will resolve to empty string at runtime

## Install flow

`POST /api/v1/apps/{key}/install` → background task → poll `GET /{key}/install/progress`
Steps in `operation_steps` DB table. `clear_op_steps()` runs before each new install.
`__done__` sentinel signals completion. Frontend polls until `done: true`.

## Path layout (standard install)

| Path | Purpose |
|------|---------|
| `/opt/mediastack/` | Code + venv (install_dir) |
| `/var/lib/mediastack/` | Runtime data, DB, compose fragments (MS_DATA_DIR) |
| `/var/lib/mediastack/compose/` | Per-app docker-compose fragments |
| `/opt/mediastack/.env` | Secrets + config (env_file) |
| `config.config_root` | User app config dirs (set by wizard, stored in platform DB) |

## Apply scripts / SSH

- Apply scripts: Python only, no f-strings, no `{}` dict literals
- No multi-line bash in SSH double-quoted args — Write script → scp → ssh execute
- No multi-line `python3 -c` — write to /tmp file and run

## Project facts

Stable architectural truths. Moved here from HANDOFF.md on 2026-05-24 (S2a split).

**SLOP AI Agent ≠ User LLM catalog apps.** Critical distinction:
- **SLOP AI Agent**: the core executive manager of the SLOP application — responsible for
  SLOP's own continuity. It is NOT a catalog app health watcher bolted on as an afterthought.
  Its primary responsibility is ensuring SLOP itself is running and healthy: it monitors all
  managed components, detects failures, and drives automated remediation.
  Module: `backend/core/agent.py`. Constants (AGENT_ROLE, AGENT_KEY, AGENT_TIER, AGENT_CATEGORY,
  AGENT_SUBJECT_TYPE) and the `get_all_apps(include_system=False)` tier-0 exclusion are
  enforced by tests/test_rules_migration_batch1.py (S-55-B). <!-- verify: grep -q "^AGENT_KEY" backend/core/agent.py && echo OK -->
  API: `GET /api/v1/health/agent` + `agent_status` field in `/api/v1/health/summary`.
- **User LLM catalog apps** (Ollama, llama.cpp, Open WebUI): what users install for their own AI use.

**Three data directories (standard install) — all different:**
| Path | Purpose |
|------|---------|
| `/opt/mediastack/` | Code + venv (install_dir) |
| `/var/lib/mediastack/` | Runtime data, DB, compose fragments (MS_DATA_DIR via systemd) |
| `/srv/mediastack/config` | User app config dirs (set via wizard, stored in platform DB + .env) |

**Vue view files — NO business logic.** See above. Rule-007 gates new files at 600 lines.

**Deploy = git pull on the target, NOT scp.** The install dir (`/opt/mediastack`)
is an HTTPS git clone of `Nnyan/SLOP`, updated via `ms-update` / `deploy.sh --update`
(`git fetch` + pull/reset to `origin/main`) then `systemctl restart mediastack`. The
tree is owned by the **service user `mediastack`** — run git/pip/npm as that user
(`sudo -u mediastack ...`); use root only for `systemctl`. App env (e.g.
`MS_TRUSTED_HOSTS`) comes from the systemd unit's inline `Environment=` lines, NOT
from `.env` (which the app reads only via Starlette `Config`, never into `os.environ`).
(Corrected 2026-05-29: the prior "no git on target server / scp + sudo cp" note
described an older layout and was false — verified on the Rocinante test server. Known
`ms-update`/ownership/port bugs tracked in `docs/BACKLOG.md` §"From Rocinante deploy session".)

**Catalog has two `CatalogEntry` definitions** — `loader.py` dataclass AND `catalog.py` Pydantic
response model. Field sync is enforced by tests/test_rules_migration_batch1.py::TestCatalogEntryFieldSync (S-55-B). <!-- verify: grep -q "class CatalogEntry" backend/api/catalog.py && echo OK -->

**Custom install flow (two steps)**:
1. `POST /api/v1/apps/install-custom` → registers manifest in `catalog/community/` — returns `{key}`.
2. `POST /api/v1/apps/{key}/install` with `extra_env` → actually starts the background install.

**Port conflict linter** (added session 14):
- `_get_listening_ports()` reads `/proc/net/tcp` + `/proc/net/tcp6` for LISTEN-state ports.
- `lint_compose_yaml()` extracts host ports, checks against `StateDB` installed app `host_port` values and system ports.
- Conflicts appear in `LintResult.warnings` (auto-rendered in SettingsView + CatalogView) and `LintResult.port_conflicts` (structured list for future frontend use).

**Catalog template variables** (clarified session 14):
- `{config_root}` / `{media_root}` in volume `host:` paths → **intentional** — handled by `_expand_path()` in executor.py.
- `${VAR}` refs in env: blocks → handled via `_SLOP_MANAGED_VARS`, `auto_secrets`, wizard, or `:-` defaults.
- `${VAR}` syntax (not Python `{var}`) enforced by ms-enforce `check_catalog_env_var_syntax` (S-55-B).

**_SLOP_MANAGED_VARS** — module-level frozenset in `backend/api/apps.py`. Canonical membership
enforced by tests/test_rules_migration_batch1.py::TestSlopManagedVars (S-55-B). <!-- verify: grep -q "^_SLOP_MANAGED_VARS" backend/api/apps.py && echo OK -->

**Quick Stacks** — `_DEFAULT_STACKS` in `backend/api/platform.py` is the single source of truth. <!-- verify: grep -q "^_DEFAULT_STACKS" backend/api/platform.py && echo OK -->
Customisations stored in `settings` table keys `custom_stacks` and `hidden_stacks` as JSON.

**Community manifest directory** — `catalog/community/` under install_dir. Owned by `mediastack`
user. Installer pre-creates it after `fetch_repo()` at step [5/8]. `load_manifest()` searches
`catalog/apps/` first, then `catalog/community/` as fallback.
