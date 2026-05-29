# S-61-AGENT-ANONYMIZATION — Scrub SLOP-internal identifiers before external LLM calls

## Goal
Close a live data-egress leak: when a cloud LLM provider is configured, the agent
currently sends raw error text + assembled context (which can contain hostnames,
filesystem paths, usernames, IPs, container IDs) to that external provider. This
wave adds a deterministic scrub layer at the outbound boundary, default-on for
cloud providers, with an ms-enforce check so future edits can't bypass it.

## Context
- Central outbound choke point: `backend/health/checker.py::_dispatch_llm_call`
  (used by `classify_with_llm` via `_query_llm_for_diagnosis`). The cloud-vs-local
  decision uses `_CLOUD_PROVIDERS` / `_LOCAL_OAI_PROVIDERS` frozensets in
  `backend/core/agent.py`.
- Local providers (ollama/llamacpp on-host) are NOT external egress — scrub is
  cloud-only by default, with a per-call opt-out flag.
- ADRs live in `docs/adr/`; highest is `0017`. This wave adds `0018`. Adding an
  ms-enforce check is governed by ADR-0012 (rule-addition contract) and verified
  by `ms-enforce::check_rule_contract` — Stream B must satisfy that contract.

## Rules to follow
- `backend/agent/**` hard cap 500. `scrub.py` is a PURE, deterministic, network-free,
  idempotent function.
- Default-on for cloud; opt-out only via an explicit argument.
- Follow `docs/adr/template.md` for the new ADR.

## Authorized deletions
- None.

## Parallelization
**Models:** coordinator = **opus**. Streams A∥B concurrent; C integrates after A
merges (imports `scrub`).

| Stream | Model | Subagent type | Scope |
|---|---|---|---|
| A — scrub module | sonnet | `general-purpose` in worktree | `backend/agent/scrub.py` (new), `tests/test_agent_scrub.py` (new) |
| B — ADR + ms-enforce check | sonnet | `general-purpose` in worktree | `docs/adr/0018-llm-anonymization.md` (new), `ms-enforce` (edit: add `check_llm_outbound_scrubbed`), rule-contract entry per ADR-0012 |
| C — call-site integration | sonnet | `general-purpose` in worktree | `backend/health/checker.py` (edit `_dispatch_llm_call`), `tests/test_agent_scrub_integration.py` (new) |

## Deliverables

### Stream A — `backend/agent/scrub.py`
Exact public signatures (Streams B and C code against these):
```python
def scrub(text: str, *, profile: str = "cloud") -> str:
    """Redact SLOP-internal identifiers from text bound for an external LLM.
    Redacts → stable placeholders:
      absolute paths (/opt/mediastack, /var/lib/mediastack, /srv/...) → <PATH>
      container names (mediastack-<app>-<n>)                          → <APP>
      IPv4 / IPv6 literals                                            → <IP>
      internal usernames (mediastack, stack)                         → <USER>
      bearer/API-key-like tokens                                     → <SECRET>
    Pure, deterministic, idempotent. profile='local' returns text unchanged."""

def is_external(provider: str) -> bool:
    """True iff provider is in the cloud set (import from core.agent)."""
```
Tests: golden redaction per category, idempotency (`scrub(scrub(x)) == scrub(x)`),
`profile='local'` passthrough, empty/None-safe.

### Stream B — ADR + ms-enforce checker
- `docs/adr/0018-llm-anonymization.md`: rationale, scrub rules, threat model
  (data egress to third-party LLMs), local-exempt decision, opt-out flag.
- `ms-enforce::check_llm_outbound_scrubbed`: in the existing ms-enforce style
  (AST/grep, matching neighbors like `check_write_read_cycles`), assert that
  `_dispatch_llm_call` routes external-provider text through `scrub(...)`. Fails
  if a cloud dispatch path sends un-scrubbed text. Register per the rule-addition
  contract so `check_rule_contract` passes.

### Stream C — integration into `_dispatch_llm_call`
- At the top of the external-provider branch: `if is_external(provider): prompt = scrub(prompt)`
  (single choke point). Add an `allow_raw: bool = False` kwarg threaded for the
  documented opt-out.
- Integration test: configure a cloud provider, capture the outbound payload
  (mock httpx), assert identifiers are redacted; configure a local provider,
  assert passthrough.

## Verification
1. `.venv/bin/pytest tests/test_agent_scrub.py tests/test_agent_scrub_integration.py -v` — pass.
2. `python3 ms-enforce` — exit 0 on the integrated wave branch (incl. the new
   `check_llm_outbound_scrubbed` and `check_adr_enforcement`/`check_rule_contract`).
3. No `frontend/` changes.

## Out of scope
- The router work (S-62). The ms-enforce check is written so the FUTURE router
  wiring must also route through scrub.
- Scrubbing non-LLM egress (telemetry, etc.).

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine v4. A and B parallel; C dispatched after
A merges to `wave/S-61-agent-anonymization` (C imports scrub). Coordinator merges
all to `wave/S-61-agent-anonymization`, never main.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-61-AGENT-ANONYMIZATION.md as orchestrator.`
