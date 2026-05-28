# ADR 0009 — Infra-Slot Abstraction (Pluggable Provider Pattern)

**Status:** Accepted (backfilled 2026-05-08; the implicit decision dates from the v3 build, ~2024)
**Decided by:** OPUS during cleanup step 2.5.b (backfill)
**Supersedes:** none
**See also:** `backend/infra/`, `backend/infra/registry.py`, `backend/platform/wizard.py::step_deploy_infra`, [ADR 0010 (No plugin system)](0010-no-plugin-system.md)
**Review by:** 2028-05-08

> Enforcement: [automated — ms-coverage RULE `provider-failure-returns-result` anchored at `test_glance_failure_no_name_error`; `check_catalog_compliance` (Core Rule 5.5) enforces the slot enumeration; `tests/test_failure_paths.py` exercises each provider's `ProviderResult` contract]

---

## Context

The wizard configures and deploys five categories of infrastructure components:

| Slot | Examples | Role |
|---|---|---|
| `tunnel` | cloudflared, tailscale, headscale | Public reachability of the homelab |
| `auth` | tinyauth, authelia | SSO / password gate in front of Traefik |
| `vpn` | gluetun | VPN tunnel for download clients |
| `dashboard` | glance, homepage | App launcher landing page |
| `management` | dockge, portainer, dockhand, komodo | Container management UI |

Within each slot the user picks **one** provider (or none). The five slots are independent — picking gluetun for `vpn` has no bearing on which `dashboard` is selected.

Naive implementations of this would either:

- **Hardcode every provider in `step_deploy_infra`** with `if/elif` branches per provider. Adding a new provider means editing the wizard step. Step 2.7.h's complexity refactor would have been catastrophically harder under this shape.
- **Duplicate the deploy / verify / remove logic per provider** without sharing structure. Every new provider means re-writing the docker-compose-up plumbing.

A better abstraction: each provider is a class implementing a small interface (`deploy(cfg) → ProviderResult`, `remove() → ProviderResult`, `verify() → ProviderResult`). The wizard calls into the slot's selected provider via a registry lookup.

## Decision

`backend/infra/base.py` defines the abstract `InfraProvider` interface:

```python
class InfraProvider:
    slot: str             # 'tunnel' / 'auth' / 'vpn' / 'dashboard' / 'management'
    key: str              # provider key, unique within the slot ('cloudflared', 'tailscale', ...)
    display_name: str     # operator-facing label

    def deploy(self, cfg: dict[str, Any]) -> ProviderResult:
        """Render compose fragment + docker-compose up. Returns
        ProviderResult(ok, message, detail). Must NEVER raise —
        wizard contract per Core Rule 4.x."""

    def remove(self) -> ProviderResult: ...
    def verify(self) -> ProviderResult: ...
```

`backend/infra/registry.py` provides the registration mechanism:

```python
@register
class GluetunProvider(InfraProvider):
    slot = "vpn"
    key = "gluetun"
    display_name = "Gluetun"

    def deploy(self, cfg): ...
```

`@register` (a class decorator) inserts `(slot, key) → class` into a module-scope dict. `get_provider(slot, key)` returns the class; the wizard instantiates it and calls `.deploy(cfg)`.

Per-slot provider files live under `backend/infra/providers/`:
- `tunnels_cloudflared.py`, `tunnels_tailscale.py`, ...
- `auth_tinyauth.py`, `auth_authelia.py`
- `vpn_gluetun.py`
- `dashboard_glance.py`, `dashboard_homepage.py`
- `management_dockge.py`, `management_portainer.py`, ...

Each file imports `from backend.infra.registry import register` and decorates its provider class. Imports are wired via `backend/infra/providers/__init__.py` which imports each provider module — that triggers the `@register` decorator at import time and populates the registry.

The wizard's `step_deploy_infra` (post-2.7.h refactor) iterates each slot and dispatches via the registry — it has no knowledge of any specific provider. Adding a new provider is one new file + one line in `__init__.py`.

## Consequences

### Positive

- **New providers are additive.** A user wants to add Headscale support? Drop `tunnels_headscale.py` into `backend/infra/providers/`, import it from `__init__.py`, run `ms-test.py --section infra`. No wizard changes, no dispatch changes.
- **Each provider is a single self-contained file** — its compose fragment, env handling, and verification logic all live together. Easy to read; easy to test.
- **Step 2.7.h was tractable** because `step_deploy_infra` already delegated to the registry. The refactor split the per-slot wizard logic into helpers (`_deploy_tunnels`, `_deploy_auth`, ...) but the deeper structural work was already done by ADR 0009.
- **Tests can register a fake provider in a fixture.** `test_failure_paths.py` exercises `DockgeProvider` etc. directly; no `if/elif` ladder to mock.
- **The registry decouples wizard input from runtime dispatch.** The wizard stores the user's choice as `(slot="vpn", key="gluetun")`. At deploy time, the registry resolves that pair to the class. If the user re-imports the registry with a new entry, existing stored choices automatically pick up the new provider.

### Negative

- **The registry is module-scope global state.** Two test runs that both import the registry share its contents (mitigated by `@register` being idempotent — re-registering the same key is a no-op). Test fixtures that swap providers must `pop` and restore.
- **The interface is small but ossified.** Adding a new method (e.g. `migrate_v1_to_v2()`) means updating every existing provider OR providing a default `pass` implementation in the base class. We pay this cost in exchange for the clean decoupling.
- **Dynamic discovery via `__init__.py` imports** is a smell — vulture (Step 3.1's dead-code scanner) had to be configured with `@register` in its decorator whitelist because each `@register`-decorated class never has a direct call site. Without the whitelist, every provider class would show as "unused".
- **A provider registered for a slot it doesn't belong to crashes at instantiation, not at registration.** Mitigated by Core Rule 5.5 (catalog compliance) which checks `slot in {tunnel, auth, vpn, dashboard, management}`.

### Neutral

- **The pattern doesn't extend to apps in the catalog.** Apps (sonarr, plex, immich, ...) are NOT instances of the InfraProvider interface — they're declarative manifests in `catalog/apps/*.yaml` consumed by a single executor. The two surfaces are different problems with different abstractions.
- **The slot list is closed.** Adding a sixth slot (e.g. `notification` for ntfy/healthchecks) would require touching the wizard, the platform model, and the schema. Not zero-cost. We accept this; the five existing slots cover the foreseeable infra surface, and adding a slot is a deliberate architectural choice rather than a frequent operation.
- **The interface deliberately does NOT include `update()` or `migrate()`** — provider versioning is managed via container image tags + recompose, not via a provider-side migration API.

## Status

Accepted (backfilled). Documents a decision implicit in the v3/v4 build; ratified explicitly during cleanup step 2.5.b on 2026-05-08. No supersession in flight.
