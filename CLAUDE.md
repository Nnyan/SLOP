# SLOP — Claude Code Instructions

## Project overview

S.L.O.P. (Self-hosted Linux Orchestration Platform) — public repo (`Nnyan/SLOP`).
Backend: FastAPI + Python (`backend/`). Frontend: Vue 3 + TypeScript (`frontend/src/`).
Catalog: YAML manifests for 56 installable apps (`catalog/apps/`).
Backend tests run against a local venv; no external server required for unit tests.

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

## Frontend architecture rule — NO business logic in view files

**View files (`frontend/src/views/*.vue`) must contain only:**
- Template markup
- Reactive refs wired to composables or direct API calls
- Simple event handlers (one-liners)

**Before adding any function, computed, or reactive state to a view file:**
1. `grep -n "function\|computed\|const.*=.*ref\|const.*=.*computed" frontend/src/views/<File>.vue` — check if similar logic already exists before creating a new one.
2. If the logic exceeds ~5 lines or is reusable, create or extend `frontend/src/composables/use<Feature>.ts` instead.

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
  enforced by tests/test_rules_migration_batch1.py (S-55-B).
  API: `GET /api/v1/health/agent` + `agent_status` field in `/api/v1/health/summary`.
- **User LLM catalog apps** (Ollama, llama.cpp, Open WebUI): what users install for their own AI use.

**Three data directories (standard install) — all different:**
| Path | Purpose |
|------|---------|
| `/opt/mediastack/` | Code + venv (install_dir) |
| `/var/lib/mediastack/` | Runtime data, DB, compose fragments (MS_DATA_DIR via systemd) |
| `/srv/mediastack/config` | User app config dirs (set via wizard, stored in platform DB + .env) |

**Vue view files — NO business logic.** See above. Rule-007 gates new files at 600 lines.

**No git on target server** — deploy = scp + sudo cp + systemctl restart.

**Catalog has two `CatalogEntry` definitions** — `loader.py` dataclass AND `catalog.py` Pydantic
response model. Field sync is enforced by tests/test_rules_migration_batch1.py::TestCatalogEntryFieldSync (S-55-B).

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
enforced by tests/test_rules_migration_batch1.py::TestSlopManagedVars (S-55-B).

**Quick Stacks** — `_DEFAULT_STACKS` in `backend/api/platform.py` is the single source of truth.
Customisations stored in `settings` table keys `custom_stacks` and `hidden_stacks` as JSON.

**Community manifest directory** — `catalog/community/` under install_dir. Owned by `mediastack`
user. Installer pre-creates it after `fetch_repo()` at step [5/8]. `load_manifest()` searches
`catalog/apps/` first, then `catalog/community/` as fallback.
