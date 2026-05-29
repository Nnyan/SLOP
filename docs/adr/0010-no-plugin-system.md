# ADR 0010 — No Plugin System

**Status:** Accepted (backfilled 2026-05-08; the implicit decision dates from the v3 build, ~2024)
**Decided by:** OPUS during cleanup step 2.5.b (backfill)
**Supersedes:** none
**See also:** [ADR 0009 (Infra-slot abstraction)](0009-infra-slot-abstraction.md), [ADR 0011 (Single-tenant assumption)](0011-single-tenant-assumption.md)
**Review by:** 2027-05-08

> Enforcement: [manual — architectural negation; the absence of a plugin loader, `mediastack-plugin-*` discovery, or `@before_install`-style hook decorators is the proof. Reviewers reject PRs that introduce a runtime hook/entry-point/plugin-discovery surface.]

---

## Context

Mediastack offers user-facing extension points in two places:

1. **Custom catalog manifests.** Users can drop a YAML file into `catalog/community/` (or use the API to install one from a GitHub URL) to add a new app to their catalog. The community catalog is gitignored — entries are user-supplied and not curated.
2. **Custom infra providers.** A user could conceivably add <!-- TEMPLATE: backend/infra/providers/auth_my_custom_sso.py --> (a hypothetical example; this file does not exist) to support an auth backend not shipped with Mediastack.

Beyond those two, every other extension would require **a plugin system**: a documented stable API surface that third-party Python code can target, dynamically loaded at runtime, with versioning and isolation guarantees.

Plugin systems are seductive: they look like maintenance leverage ("users can extend without us touching code") but they are expensive:

| Cost | Meaning |
|---|---|
| **Stable API surface** | Once published, internal refactors are constrained by the plugin contract. Step 2.7's complexity refactors would have been substantially harder if `_install_inner` was a public plugin entry point. |
| **Versioning** | Plugins built against v0.1 must keep working against v0.2, v0.3, ... or each version must declare its compatibility window. Either way: contract management. |
| **Isolation** | A plugin that crashes must NOT crash Mediastack. Sandboxing Python code in-process is hard. The orthodox answer is sub-processes, which adds operational surface. |
| **Discovery** | Where do plugins come from? Pip? A custom registry? Manual file drop? Each option has security implications. |
| **Documentation** | Plugin authors need API docs that stay accurate. Internal API docs can drift; published API docs cannot. |
| **Support** | "I installed plugin X and now Y is broken" — diagnosing third-party plugin interactions is a recurring tax. |

A plugin system is justified when there's evidence of demand for plugins that the core team can't or shouldn't ship. For a single-tenant homelab management tool with a controlled scope, that evidence is absent.

## Decision

**Mediastack does not have a plugin system.**

The two existing extension points (custom catalog manifests, custom infra providers via direct file drop) are intentionally not framed as a plugin API:

- **Custom catalog manifests** are validated against the same schema as curated manifests; they don't get extra capabilities. They're a data extension, not a code extension.
- **Custom infra providers** require dropping a Python file into the repo and importing it from `backend/infra/providers/__init__.py`. This is a **fork**, not a plugin. The user is editing Mediastack's source tree; their changes are subject to merge conflicts on every Mediastack update, and Mediastack provides no compatibility guarantees beyond the abstract `InfraProvider` interface (ADR 0009).

When a user wants behaviour Mediastack doesn't ship, the answer is one of:

1. **Use the existing surface.** Most "I want X" requests resolve to "X is already supported via Y".
2. **Open a feature request.** If the use case is general, it ships in a future Mediastack release.
3. **Fork.** If the use case is too specific to land upstream, fork Mediastack and maintain the change locally. Mediastack's small surface and clean module boundaries make forking practical for users with engineering capacity.

Mediastack will NOT add:

- A discoverable plugin API (e.g. `mediastack-plugin-*` pip packages).
- A runtime hook system (`@before_install` / `@after_health_check` decorators that third-party code can register).
- Sandboxed plugin execution.
- A plugin marketplace, store, or registry.

## Consequences

### Positive

- **Internal refactors are unconstrained.** Step 2.7's 9-function complexity refactor was tractable because no external code depended on the function signatures. A plugin system would have made each refactor a breaking-change exercise.
- **Operations stays simple.** `mediastack` is one process running one codebase. There's no "what plugins are loaded" diagnostic step in support.
- **Security surface is bounded.** No third-party Python loaded into the Mediastack process. Whatever exploits exist live in the Mediastack codebase + its pinned dependencies, both of which are auditable.
- **Documentation effort scales with the codebase, not with the third-party ecosystem.** No plugin API docs to maintain; no compatibility matrix to publish.
- **The fork-don't-plugin path is an honest answer.** Users who NEED a custom provider get one (write the file, import it). Users who just want a feature get pointed at the feature request track. The decision tree is small.

### Negative

- **Some users will want plugins** and will be disappointed by the answer. Particularly: power users who want to integrate with their custom infrastructure (e.g. a homegrown backup system, a non-standard reverse proxy). Their options are fork or do without.
- **The community catalog grows unchecked.** Custom manifests are user-supplied; their quality varies. We mitigate via schema validation + the security tests in `tests/test_non_catalog_installs.py` (path-traversal sanitization etc.). We do NOT mitigate via curation — the community catalog is gitignored and unmoderated.
- **No revenue model around plugins.** Mediastack is open-source homelab software; this isn't a real con. But it does foreclose certain commercial paths (e.g. a paid plugin marketplace).

### Neutral

- **The decision is reversible** but increasingly costly. Adding a plugin system later means picking a stable cut of the internal surface and committing to it; the longer Mediastack runs without one, the more "internal" surface there is to consider.
- **The existing infra-slot pattern (ADR 0009) is plugin-shaped without being a plugin system.** The interface is small, the dispatch is registry-based, and adding a provider is one file. If a user really wants to extend Mediastack, this is the seam.
- **The catalog format IS effectively a plugin contract** for the limited "describe a Docker app" surface. Custom catalog YAML files are extensions, just not Python-code extensions. We accept the maintenance cost of the catalog schema (Core Rule 5.5).

## Status

Accepted (backfilled). Documents a decision implicit in the v3/v4 build; ratified explicitly during cleanup step 2.5.b on 2026-05-08. No supersession in flight.
