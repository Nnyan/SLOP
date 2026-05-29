# ADR 0018 — LLM Anonymization: Scrub Internal Identifiers Before External LLM Calls

- **Date:** 2026-05-28
- **Status:** Accepted
- **Deciders:** operator, Claude Sonnet 4.6 (S-61 wave, Stream B)
- **Supersedes:** none
- **See also:** `backend/agent/scrub.py`, `backend/health/checker.py::_dispatch_llm_call`, `docs/adr/0012-rule-addition-contract.md`
- **Review by:** 2027-05-28

> Enforcement: [automated — `ms-enforce::check_llm_outbound_scrubbed` (TIER_1); fails if `_dispatch_llm_call` routes cloud-provider text without passing through `scrub()`)]

## Context

When a cloud LLM provider is configured (any entry in `_CLOUD_PROVIDERS` in
`backend/core/agent.py`), the SLOP agent currently sends raw error text and
assembled diagnostic context to that provider without redaction. This context can
contain SLOP-internal identifiers that should never leave the host:

- **Absolute filesystem paths** — `/opt/mediastack/`, `/var/lib/mediastack/`,
  `/srv/mediastack/config/` — leak the host's install layout and can be used for
  targeted path traversal or social-engineering attacks against the operator.
- **Container names** — `mediastack-<app>-<n>` — reveal which applications are
  installed, their version/run counts, and internal naming conventions.
- **IPv4 / IPv6 literals** — reveal private network topology, internal IP
  assignments, and may expose VPN/tunnel addresses.
- **Internal usernames** — `mediastack`, `stack` — reveal system account names
  usable in brute-force or privilege-escalation reconnaissance.
- **Bearer tokens / API-key-like strings** — present in environment context,
  error output, or log fragments — would directly compromise integrated services
  if sent to a third-party provider.

This is a live data-egress risk for any operator who configures a cloud provider
(Groq, Cerebras, OpenRouter, Mistral, Cohere, Google, Anthropic, OpenAI, NIM, or
GAI). The central outbound choke point is
`backend/health/checker.py::_dispatch_llm_call`, which routes all LLM calls via
the `cloud_providers` branch to `_call_cloud_provider`.

**Why local providers are exempt:** Ollama, llamacpp, shimmy, and localai run
on-host. Text sent to them does not leave the machine. Applying scrub to on-host
providers would reduce diagnostic fidelity (e.g., a path-specific error would
become `<PATH>-specific error`) without any security benefit, because the data
never transits a network boundary.

**Why an opt-out flag is provided:** Certain operator-controlled diagnostic
scenarios — e.g., a self-hosted proxy that the operator trusts as equivalent to
local — may not need scrubbing. An `allow_raw: bool = False` kwarg on
`_dispatch_llm_call` provides an explicit, auditable escape hatch. Default is
`False` (scrub always). Opting out requires a deliberate code change, which is
visible in review and trackable in git history.

## Decision

### Scrub module

A new module `backend/agent/scrub.py` provides:

```python
def scrub(text: str, *, profile: str = "cloud") -> str:
    """Redact SLOP-internal identifiers from text bound for an external LLM."""

def is_external(provider: str) -> bool:
    """True iff provider is in the cloud set (import from core.agent)."""
```

The `scrub()` function is **pure, deterministic, and idempotent**:
`scrub(scrub(x)) == scrub(x)` for all inputs. It performs no I/O, no network
calls, and no database access. With `profile='local'` it returns the text
unchanged (passthrough for on-host providers).

### Scrub rules (applied in order, cloud profile only)

| Pattern | Placeholder | Rationale |
|---|---|---|
| Absolute paths starting with `/opt/`, `/var/lib/`, `/srv/`, `/home/` | `<PATH>` | Filesystem layout leak |
| Container names matching `mediastack-<word>-<digits>` | `<APP>` | Installed app enumeration |
| IPv4 addresses (`\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}`) | `<IP>` | Network topology leak |
| IPv6 addresses (standard and compressed forms) | `<IP>` | Network topology leak |
| Internal usernames `mediastack` and `stack` as word tokens | `<USER>` | Account enumeration |
| Bearer tokens / API-key-like strings (long alphanumeric sequences) | `<SECRET>` | Credential exfiltration |

Rules are applied as regex substitutions in the order listed. Order matters for
correctness: path scrubbing runs before username scrubbing so that
`/home/stack/foo` becomes `<PATH>/foo` rather than `/<USER>/foo` (the former
is more informative to the LLM while leaking nothing; the latter is confusing).

### Integration point

`backend/health/checker.py::_dispatch_llm_call` is the single outbound choke
point. The cloud-dispatch branch (`if provider in cloud_providers`) must apply
`scrub(prompt)` before the HTTP call. An `allow_raw: bool = False` kwarg is
threaded to `_dispatch_llm_call` for the documented opt-out. When `allow_raw`
is `True`, the prompt is sent unmodified; this is the operator's explicit
acknowledgement that the provider is trusted with raw internal text.

### Exception: local providers

`profile='local'` (or equivalently, when `is_external(provider)` returns
`False`) the prompt is passed through unchanged. Local providers are defined as
any provider NOT in `_CLOUD_PROVIDERS` — currently: `ollama`, `llamacpp`,
`shimmy`, `localai`, and any unrecognized provider string (fail-safe: unknown
providers are treated as local to avoid blocking novel on-host setups).

### ms-enforce gate

`ms-enforce::check_llm_outbound_scrubbed` (TIER_1) uses AST/grep to verify that
`_dispatch_llm_call` in `backend/health/checker.py` routes cloud-provider text
through `scrub(...)`. Specifically it checks that:

1. The function `_dispatch_llm_call` exists in `checker.py`.
2. A `scrub(` call or `scrub(prompt` pattern is present in the cloud-dispatch
   branch of the function body.
3. The import `from backend.agent.scrub import scrub` (or equivalent) exists in
   `checker.py`.

The check **intentionally fails** until Stream C integrates the call. Stream C's
commit is what causes this check to go green on the merged wave branch.

## Consequences

### Positive

- Internal hostnames, paths, usernames, IPs, and secrets are never sent to
  third-party LLM providers in normal operation.
- The opt-out mechanism is explicit and auditable (requires a code change, not
  a config flag).
- `scrub()` is pure and idempotent — safe to call multiple times without
  accumulating placeholders or corrupting JSON structure.
- The ms-enforce gate prevents future refactors from accidentally bypassing
  scrubbing on the cloud path.

### Negative

- Diagnostic fidelity is slightly reduced for cloud-LLM operators: the LLM
  sees `<PATH>` instead of `/var/lib/mediastack/state.db`. In practice, the
  LLM's diagnostic reasoning is not path-dependent (it reasons about error
  types, not specific paths), so fidelity loss is minimal.
- One additional regex pass per LLM call. The cost is sub-millisecond for
  typical prompt sizes (a few KB); negligible relative to the HTTP latency of
  the cloud provider call.

### Neutral

- Local-provider operators (ollama, llamacpp) see no change in behavior.
- The `allow_raw` flag is not exposed in the UI; it is a code-level escape hatch
  for advanced operator use only.
- This ADR does not govern non-LLM egress (telemetry, webhook calls, etc.).
  Those are separate concerns under their own future ADRs.

## Status

Accepted. Enforcement:

- **Automated:** `ms-enforce::check_llm_outbound_scrubbed` (TIER_1) — fails if
  the cloud path in `_dispatch_llm_call` does not call `scrub()`.
- **Tests:** `tests/test_agent_scrub.py` (golden redaction, idempotency,
  local passthrough, empty/None safety — Stream A deliverable).
- **Integration test:** `tests/test_agent_scrub_integration.py` (mock httpx,
  assert cloud payloads are scrubbed, local payloads are not — Stream C
  deliverable).
- **Review trigger:** when `_CLOUD_PROVIDERS` membership changes, or when a new
  LLM call path is added outside `_dispatch_llm_call`.
