# CLAUDE.md Rules-to-Tests Audit

Generated 2026-05-28. Purpose: identify which CLAUDE.md rules can be migrated
to mechanical enforcement. Do NOT migrate rules in this file — it is a candidate
list only. Future waves consume it.

| Rule (CLAUDE.md section) | Testable? | Proposed test / enforcement | Estimated effort |
|---|---|---|---|
| **Project overview** | | | |
| Backend: FastAPI + Python (`backend/`). Frontend: Vue 3 + TypeScript (`frontend/src/`). Catalog: YAML manifests for 56 installable apps (`catalog/apps/`). | NO | Documentation-of-fact; counts change as apps are added | — |
| Backend tests run against a local venv; no external server required for unit tests. | NO | Documentation-of-fact (describes test environment, not a rule) | — |
| **Frontend architecture — NO business logic in view files** | | | |
| View files must contain only template markup, reactive refs wired to composables or direct API calls, and simple event handlers (one-liners). No functions/computed/reactive state beyond that. | PARTIAL | Vue SFC AST check: parse `<script setup>` blocks; flag any non-trivial function definition or computed > 5 lines; false positives likely for legitimate simple handlers | M |
| Before adding logic to a view, grep for similar logic in that view first. | NO | Process/workflow rule; not statically enforceable | — |
| If logic exceeds ~5 lines or is reusable, create or extend `frontend/src/composables/use<Feature>.ts`. | PARTIAL | Heuristic AST check on view `<script setup>` block size as a proxy; composable naming convention enforced by lint rule | M |
| File-size limits enforce the view logic rule (composables pattern satisfies both). | YES | Already enforced by `tools/check_linecount.py` + CI; the ratchet is the test | S |
| **File size limits (ratchet-enforced)** | | | |
| New files in `backend/core/**`, `backend/health/**`, `backend/manifests/**`, `backend/platform/**`, `backend/infra/**`, `backend/agent/**` must be under 500 lines (hard cap). | YES | `tools/check_linecount.py` already implements this; CI integration needed if not already wired | S |
| New files in `backend/api/**` must be under 800 lines (hard cap). | YES | Same tool — already categorized; ensure CI blocks on failure | S |
| New Vue view files in `frontend/src/views/**.vue` must be under 600 lines (hard cap). | YES | Same tool — already enforced | S |
| New frontend files (non-view) in `frontend/src/**` must be under 500 lines (hard cap). | YES | Same tool — already categorized | S |
| New CLI/installer files in `cli/**`, `installer/**` must be under 800 lines (hard cap). | YES | Same tool — already categorized | S |
| Test files under `tests/**`, `installer/tests/**` have 1000-line informational cap (does NOT fail CI). | YES | Same tool — informational check; verify it does not flip to failing | S |
| Existing oversize files are recorded in `.linecount-baseline.json` and may shrink but never grow. | YES | `tools/check_linecount.py --update-shrunk` pattern + CI diff check ensures baselines only shrink | S |
| CI fails the PR if a new file exceeds its hard cap or a baselined file grows. | YES | CI configuration check — verify `check_linecount.py` is wired into CI pipeline | S |
| Grandfathered violators (SetupView ~1711, SettingsView ~1369, etc.) should shrink over time, not grow. | YES | Covered by ratchet baseline check (grow = CI failure); shrink trend can be tracked via baseline diffs | S |
| **Catalog apps** | | | |
| YAML manifests: `catalog/apps/<key>.yaml` (naming + location convention). | YES | `ms-enforce` or CI check: all manifests in `catalog/apps/` must be `.yaml`; no manifests elsewhere | S |
| Docker Compose vars use `${VAR}` syntax (not Python `{var}`). | YES | `grep -rn` or ruff-equivalent check for `{[A-Z_]+}` (non-`$`-prefixed) in catalog YAML env blocks; fast static check | S |
| Known env vars written to `.env` by wizard: `PUID`, `PGID`, `TZ`, `CONFIG_ROOT`, `MEDIA_ROOT`, `DOMAIN`. | NO | Documentation-of-fact about the wizard; the list lives in `_SLOP_MANAGED_VARS` frozenset which is the canonical source | — |
| If a catalog app uses a var not in the known list, it resolves to empty string at runtime. | PARTIAL | Could lint manifests for unknown `${VAR}` references vs `_SLOP_MANAGED_VARS`; partial because auto_secrets and `:-` defaults are legitimate escapes | M |
| **Install flow** | | | |
| `POST /api/v1/apps/{key}/install` → background task → poll `GET /{key}/install/progress`. | NO | Documentation-of-architecture; covered by existing integration tests | — |
| Steps stored in `operation_steps` DB table. `clear_op_steps()` runs before each new install. | PARTIAL | Unit test asserting `clear_op_steps()` is called before install begins; already may exist | S |
| `__done__` sentinel signals completion. Frontend polls until `done: true`. | PARTIAL | Unit test checking that the sentinel is always emitted at end of install flow | S |
| **Path layout (standard install)** | | | |
| `/opt/mediastack/` is install_dir; `/var/lib/mediastack/` is MS_DATA_DIR; `/var/lib/mediastack/compose/` holds compose fragments; `/opt/mediastack/.env` is env_file; `config.config_root` is user app config dir. | NO | Documentation-of-fact about deployment paths; not verifiable without a running install | — |
| **Apply scripts / SSH** | | | |
| Apply scripts: Python only, no f-strings, no `{}` dict literals. | YES | `grep -rn` check or ruff rule targeting files matching apply-script naming pattern; check for f-string prefix and bare `{}` | S |
| No multi-line bash in SSH double-quoted args — Write script → scp → ssh execute. | PARTIAL | `grep` heuristic for multi-line strings inside `ssh … "…"` constructs; false positives from legitimate single-line args likely | M |
| No multi-line `python3 -c` — write to /tmp file and run. | PARTIAL | `grep` heuristic for `python3 -c` with embedded newlines; false positives possible; AST parse harder without executing | M |
| **Project facts — SLOP AI Agent distinction** | | | |
| SLOP AI Agent DB record: `key="slop_agent"`, `tier=0`, `category="agent"`, `status="running"`. | YES | Unit test asserting `ensure_agent_registered()` produces a record with those exact fields | S |
| `ensure_agent_registered()` runs at every startup. | YES | Unit/integration test: call startup sequence, assert function was invoked (mock or call-count check) | S |
| Agent health uses `subject_type="agent"` (never `subject_type="app"`). | YES | Unit test: assert all agent health records have `subject_type="agent"` and no app health records do | S |
| `GET /api/v1/health/agent` endpoint exists + `agent_status` field in `/api/v1/health/summary`. | YES | API schema test / response-shape test; assert both fields are present in responses | S |
| `get_all_apps(include_system=False)` excludes tier=0 entries from user-facing lists. | YES | Unit test: seed DB with a tier=0 app, call function, assert it is excluded from result | S |
| `AGENT_ROLE = "executive_manager"` constant in `backend/core/agent.py`. | YES | `grep` check or import test asserting constant value; very cheap | S |
| User LLM catalog apps (Ollama, llama.cpp, Open WebUI) are distinct from the SLOP AI Agent. | NO | Documentation-of-distinction; the tier=0 exclusion test above is the mechanical proxy | — |
| **Project facts — Three data directories** | | | |
| `/opt/mediastack/` (install_dir), `/var/lib/mediastack/` (MS_DATA_DIR via systemd), `/srv/mediastack/config` (user app config) are distinct paths. | NO | Documentation-of-fact about deployment topology; not verifiable in unit tests | — |
| **Project facts — Vue view files NO business logic** | | | |
| Vue view files must have no business logic (Rule-007 gates new files at 600 lines). | PARTIAL | See frontend architecture rule above; ratchet enforces size but not logic content | M |
| **Project facts — No git on target server** | | | |
| No git on target server — deploy = scp + sudo cp + systemctl restart. | NO | Documentation-of-fact about deployment method; enforced by code review not automation | — |
| **Project facts — Catalog has two CatalogEntry definitions** | | | |
| Any field added to `to_catalog_entry()` must also be added to the Pydantic model in `catalog.py` or FastAPI silently drops it. | YES | Round-trip test: call `to_catalog_entry()` on a real manifest, serialize through Pydantic model, assert all original fields are present | S |
| **Project facts — Custom install flow (two steps)** | | | |
| `POST /api/v1/apps/install-custom` registers manifest in `catalog/community/`, returns `{key}`. Then `POST /api/v1/apps/{key}/install` with `extra_env` starts the install. | PARTIAL | Integration test for the two-step flow exists or can be added; the exact sequence is testable but requires DB + file system setup | M |
| **Project facts — Port conflict linter** | | | |
| `_get_listening_ports()` reads `/proc/net/tcp` + `/proc/net/tcp6` for LISTEN-state ports. | YES | Unit test with mocked `/proc/net/tcp` fixture asserting correct port extraction | S |
| `lint_compose_yaml()` extracts host ports and checks against `StateDB` installed app `host_port` values and system ports. | YES | Unit test: provide a compose YAML with a known port conflict, assert conflict appears in `LintResult` | S |
| Conflicts appear in `LintResult.warnings` and `LintResult.port_conflicts`. | YES | Covered by the lint_compose_yaml unit test above; assert field names directly | S |
| **Project facts — Catalog template variables** | | | |
| `{config_root}` / `{media_root}` in volume `host:` paths are intentional — handled by `_expand_path()` in executor.py. | PARTIAL | Unit test for `_expand_path()` with a config_root substitution; already may exist; "intentional" framing means misuse detection is the harder direction | S |
| `${VAR}` refs in env blocks handled via `_SLOP_MANAGED_VARS`, `auto_secrets`, wizard, or `:-` defaults. | PARTIAL | Lint check: for each `${VAR}` in env blocks not in `_SLOP_MANAGED_VARS`, verify it has a `:-` default or is in auto_secrets; false positives for wizard-provisioned vars | M |
| `POSTGRES_PASSWORD` + `POSTGRES_USER` added to `_SLOP_MANAGED_VARS`. | YES | Unit test asserting both vars are members of the `_SLOP_MANAGED_VARS` frozenset in `backend/api/apps.py` | S |
| **Project facts — _SLOP_MANAGED_VARS** | | | |
| `_SLOP_MANAGED_VARS` is a module-level frozenset in `backend/api/apps.py` containing PUID, PGID, TZ, DOMAIN, CONFIG_ROOT, MEDIA_ROOT, POSTGRES_PASSWORD, POSTGRES_USER, VPN vars, etc. | YES | Unit test: import `_SLOP_MANAGED_VARS` from `backend/api/apps`, assert it is a frozenset and contains the listed canonical vars | S |
| **Project facts — Quick Stacks** | | | |
| `_DEFAULT_STACKS` in `backend/api/platform.py` is the single source of truth for Quick Stacks. | YES | Unit test: assert `_DEFAULT_STACKS` is defined at module level in `backend/api/platform.py` and is the only definition of default stacks | S |
| Customizations stored in `settings` table keys `custom_stacks` and `hidden_stacks` as JSON. | YES | Unit test: assert the exact key strings are used when reading/writing stack customizations | S |
| **Project facts — Community manifest directory** | | | |
| `catalog/community/` is under install_dir, owned by `mediastack` user, pre-created at installer step [5/8]. | NO | Deployment-time fact; ownership and pre-creation not verifiable in unit tests | — |
| `load_manifest()` searches `catalog/apps/` first, then `catalog/community/` as fallback. | YES | Unit test: place a manifest only in `catalog/community/`, call `load_manifest()`, assert it is found; place conflicting manifests in both dirs, assert `catalog/apps/` takes precedence | S |

## Summary

22 YES / 11 PARTIAL / 14 NO out of 47 total rules. Approximately 14 estimated sessions to migrate all YES rules (most are S-effort, a few M).
