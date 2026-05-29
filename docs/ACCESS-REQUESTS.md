# Access Requests Queue

Single source of truth for tracked requests to install packages, upgrade
dependencies beyond what the S-49 refresh-train auto-resolves, or extend the
settings allow/deny list.

**Goal:** when any agent or session hits a need it can't satisfy directly,
record it here instead of prompting the user or silently leaking a prompt.
The queue is processed in batches (by hand today; by `tools/process_access_requests.py`
once S-59 lands).

## Convention for adding entries

Append a line to the appropriate category section using this format:

```
- `[STATUS]` **[category] subject** — one-line description / rationale.
  Requested by: <source> (date). Status: pending|applied|denied.
```

**Status markers:**
- `[ ]` pending review
- `[x]` applied — settings/state updated
- `[—]` denied or superseded — see reason

**Categories:**
- `[install]` — new package, tool, or system binary to install
- `[upgrade]` — bump a dep beyond what S-49 refresh-train auto-resolves (e.g., when a cap blocks the upgrade and a workaround is being requested)
- `[allow]` — settings allow-list addition (WebFetch domain, Bash pattern, sensitive path)
- `[deny]` — settings deny-list addition (rare; tightens restrictions)

**Source provenance:** name the wave-stream + observation file, or the session/turn that surfaced it, plus the date. This is the audit trail.

## How requests get processed

**Today (manual bootstrap):**
1. User (or assisting Claude session) reviews pending entries.
2. Approved entries get applied via the helper-script pattern (see `/tmp/access-requests-setup.py` for a template).
3. Entry status flips from `[ ]` to `[x]` with a one-line note: "applied YYYY-MM-DD via <method>".

**Future (S-59 candidate):**
1. `tools/process_access_requests.py` reads pending entries.
2. Category-allowed requests auto-apply (e.g., trusted-domain WebFetch additions, dev-dep installs).
3. Other categories surface for human review with diff preview.
4. ms-enforce warns when pending count exceeds a threshold or when any entry is >30 days old without movement.
5. Integration with S-49's refresh-train so `[upgrade]` requests feed the same PR pipeline.

## Doctrine pointers

- `.claude/ROBOT.md` § "The binding rules" — agents in Robot mode MUST write a queue entry instead of calling AskUserQuestion when they hit a need they can't satisfy.
- `.claude/AUTONOMOUS-DEFAULTS.md` § "Category: tool / settings / permission" — defaults updated to point at this queue.

---

## `[install]` — New packages / tools to install

- `[x]` **[install] `pip-audit>=2.7.0`** — Required for S-49 refresh-train's audit-regression-abort feature to be fully operational. Was already in `requirements-dev.txt` (from a prior wave) but not actually installed in `.venv`. Requested by: S-49-B-2 observation (2026-05-28). **Applied 2026-05-29 via `uv pip install pip-audit` into project venv (v2.10.0). First audit run confirmed exactly one CVE: PYSEC-2026-161 in starlette 0.52.1, the known BadHost mitigated by TrustedHostMiddleware.**

## `[upgrade]` — Dep upgrades blocked or pending external action

- `[ ]` **[upgrade] `starlette` 0.52.1 → 1.0.2+** — Underlying lib for CVE-2026-48710 (BadHost) fix. Blocked by `prometheus-fastapi-instrumentator==7.1.0` cap `starlette<1.0.0`. Latest of that package is 7.1.0 (March 2025) — no version yet lifts the cap. SLOP exposure already mitigated by TrustedHostMiddleware (S-46) running outermost in middleware chain. Status: pending upstream movement on `prometheus-fastapi-instrumentator`. Requested by: this session (2026-05-29). Re-check trigger: file an issue at https://github.com/trallnag/prometheus-fastapi-instrumentator/ if no movement by 2026-09; alternatively, find a maintained alternative Prometheus instrumentation library that allows Starlette 1.x.

## `[allow]` — Settings allow-list additions

- `[x]` **[allow] `WebFetch(domain:nvd.nist.gov)`** — CVE detail fetches from NIST. Used during CVE research (e.g., CVE-2024-24762 + CVE-2026-48710 sweep). Applied earlier this session via ad-hoc edit; logged here retroactively for audit trail. Requested by: this session 2026-05-29 (and earlier turns). Status: applied.
- `[x]` **[allow] `WebFetch(domain:osv.dev)`** — CVE detail fetches from OSV.dev (Google's vulnerability DB). Applied 2026-05-29 via `/tmp/access-requests-setup.py`.
- `[x]` **[allow] `WebFetch(domain:security-tracker.debian.org)`** — CVE detail fetches from Debian Security Tracker. Applied 2026-05-29 via `/tmp/access-requests-setup.py`.
- `[x]` **[allow] `Bash(ls /tmp/*)`** — Glob listing of /tmp/ contents (used for helper-script cleanup, debug). Was prompting in this session pre-add. Applied 2026-05-29.
- `[x]` **[allow] `Bash(ls /tmp)`** — Bare /tmp/ listing. Applied 2026-05-29.
- `[x]` **[allow] `Read(/tmp/**)`** — Read tool access to /tmp/ for helper scripts. Applied 2026-05-29.
- `[x]` **[allow] `Bash(.venv/bin/pip-audit *)`**, `Bash(pip-audit *)`, `Bash(/home/stack/code/slop/.venv/bin/pip-audit *)` — Three variants of pip-audit invocation paths. Applied 2026-05-29 alongside pip-audit install.
- `[x]` **[allow] `.claude/waves/` + `.claude/run/` write access** (6 entries: Bash heredoc `cat >` patterns + Write/Edit tool globs for both paths). These paths leak in acceptEdits sessions per ROBOT.md doctrine v4 caveats — `.claude/` exemption list only covers commands/agents/skills/worktrees, not waves/ or run/. Orchestrator + processor sessions write to these constantly (wave drafts, status files, decision files). Requested by: this session 2026-05-29 (one prompt during S-59 wave draft heredoc). **Applied 2026-05-29 via `/tmp/apply-waves-run-allows.py` queue-bootstrap pattern.** Patterns added: `Bash(cat > /home/stack/code/slop/.claude/waves/*)`, `Bash(cat > /home/stack/code/slop/.claude/run/*)`, `Write(/home/stack/code/slop/.claude/waves/**)`, `Edit(/home/stack/code/slop/.claude/waves/**)`, `Write(/home/stack/code/slop/.claude/run/**)`, `Edit(/home/stack/code/slop/.claude/run/**)`.

## `[deny]` — Settings deny-list additions

- (none currently)

---

## Applied / archive

When an entry has been applied AND its effect is stable for > 60 days, prune
to a one-line summary or remove entirely. The git history of this file is
the long-term audit trail.

## Related references

- `docs/BACKLOG.md` — broader project work queue (this file is access-requests subset)
- `.claude/ROBOT.md` § "The binding rules" — Robot doctrine integration
- `.claude/AUTONOMOUS-DEFAULTS.md` § "tool / settings / permission" — default behaviors
- `.claude/waves/S-49-DEP-REFRESH-TRAIN.md` — upgrade-train infrastructure
- `.claude/waves/S-59-*.md` (when drafted) — processor automation
