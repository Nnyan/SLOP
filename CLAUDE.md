# SLOP — Claude Code Instructions

## Project overview

S.L.O.P. (Self-hosted Linux Orchestration Platform) — public repo (`Nnyan/SLOP`).
Backend: FastAPI + Python (`backend/`). Frontend: Vue 3 + TypeScript (`frontend/src/`).
Catalog: YAML manifests for 56 installable apps (`catalog/apps/`).
Dev/private repo: `Nnyan/mediastack`. Test server: rocinante (10.0.1.51).

## Frontend architecture rule — NO business logic in view files

**View files (`frontend/src/views/*.vue`) must contain only:**
- Template markup
- Reactive refs wired to composables or direct API calls
- Simple event handlers (one-liners)

**Before adding any function, computed, or reactive state to a view file:**
1. `grep -n "function\|computed\|const.*=.*ref\|const.*=.*computed" frontend/src/views/<File>.vue` — check if similar logic already exists before creating a new one.
2. If the logic exceeds ~5 lines or is reusable, create or extend `frontend/src/composables/use<Feature>.ts` instead.

**Hard line limit: 600 lines per new view file.**
Existing violators (SetupView ~1711, SettingsView ~1369, ModelsView ~1182, HealthView ~752, CatalogView ~642 in SLOP) are grandfathered but should shrink over time, not grow.

## Catalog apps

- YAML manifests: `catalog/apps/<key>.yaml`
- Docker Compose vars use `${VAR}` syntax (not Python `{var}`)
- Known env vars written to `.env` by wizard: `PUID`, `PGID`, `TZ`, `CONFIG_ROOT`, `MEDIA_ROOT`, `DOMAIN`
- If a catalog app uses a var not in that list, it will resolve to empty string at runtime

## Install flow

`POST /api/v1/apps/{key}/install` → background task → poll `GET /{key}/install/progress`
Steps in `operation_steps` DB table. `clear_op_steps()` runs before each new install.
`__done__` sentinel signals completion. Frontend polls until `done: true`.

## Path layout (on rocinante / standard install)

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
