# Post-Batch-6 Wave Map (consolidation, 2026-05-29)

Condensed plan for the remaining not-drafted waves. Approved by the operator
2026-05-29. The five raw candidates from the original Tier-1–7 meta-analysis
(S-70, S-71, S-72, S-73, + an agent-code-quality cleanup) are condensed **by
underlying need** (not by shared mechanism) into **3 waves + 1 direct fix**.

This file is the SPEC the fresh drafting session(s) consume. Each brief below is
enough to author a full wave file from. The Manager (operator-assist) maintains
this map; fresh sessions do the drafting.

## Roadmap / sequencing

1. **Batch-7 = S-73 first, alone.** It upgrades the wave-authoring machinery
   (model column + automated pre-flight + `_TEMPLATE.md`); landing it first means
   every later wave is authored *with* it. Force-multiplier → goes first.
2. **Batch-8 = Test-Data-Hygiene**, drafted using S-73's new template. High value,
   freshly motivated by batch-6's pollution class.
3. **Later = Enforcement-Lifecycle (S-70+S-72)**, once the ~11 warn-only gates and
   the doctrine have *aged enough to have signal* (an aging policy needs history;
   the S-69 gates just shipped). Plant-now-harvest-later.
4. **Anytime = direct small-fix** the `scrub.py::is_external` egress-scrub leak
   (below the ≥10-item cleanup-wave threshold; not waved).

Velocity alternative: S-73 + Test-Data-Hygiene could co-batch in batch-7, but then
Test-Data is authored before S-73 lands (no new template). Default is sequenced.

---

## Wave 1 — S-73-WAVE-AUTHORING-RIGOR (draft now, batch-7)

**Need:** wave quality is automated, not dependent on a human remembering to
pre-flight (the manual 4-agent pass done this session should be the orchestrator's job).

**Deliverables:**
- **Per-stream `Model` column** in the Parallelization stream table; the existing
  `**Models:**` line stays as the default, the column overrides per-stream, blank =
  inherit. **Rubric** (document in ROBOT.md "Wave file conventions"): pick by a
  stream's dominant cognitive demand — Opus = irreducible judgment (ambiguous
  root-cause, cross-stream contract design, load-bearing refactor, security,
  plausible-but-wrong-passes-tests); Sonnet = bounded implementation to a clear
  spec (default); Haiku = mechanical/zero-judgment (apply classification,
  find/replace, rename, boilerplate). Guardrail: coordinator is already Opus +
  reviews every merge, so a stream earns Opus only if IT makes calls the
  coordinator can't catch; overrides carry a one-line justification.
- **`tools/wave_complexity.py`** — score a wave file → tier (Low/Medium/High) from
  mechanical signals: stream count; files created/modified; shared symbols across
  streams; refactor-vs-additive; sensitive paths (settings/doctrine/security/
  migrations); cross-wave file overlap; count of repo-claims; any Opus stream.
- **Complexity-gated pre-flight in the orchestrator startup** (ROBOT.md): compute
  tier → run matching rigor → BLOCK dispatch on any FALSE claim → write
  `.claude/run/preflight/<wave>.md`. Tiers: Low = `validate-wave-file.py` only;
  Medium = + one fact-check subagent (FALSE blocks); High = + processor-contract-
  pinned check + cross-wave disjointness + edited-wave consistency.
- **Extend `tools/validate-wave-file.py`** as the cheap Low-tier mechanical gate.
- **`.claude/waves/_TEMPLATE.md`** — first canonical skeleton: Goal, Context, Rules,
  Authorized deletions, Parallelization (with Model column), **Complexity &
  Pre-flight**, Deliverables, Verification, Out of scope, Cross-wave deps, Robot mode.
- **Dogfood:** author S-73's own file with the new Model column.

**Suggested streams (~5):** A=model-column+rubric+ROBOT.md conventions; B=
`wave_complexity.py`; C=validate-wave-file extension + orchestrator-startup
pre-flight doctrine; D=`_TEMPLATE.md`; E=pre-flight fact-check harness +
`.claude/run/preflight/` wiring.
**Processor-contract pins:** A and C+D both touch ROBOT.md "Wave file conventions"
— pin which stream owns which subsection. B (scorer) and C (validate-wave-file +
orchestrator) share the **tier-string contract** (`"Low"|"Medium"|"High"`) — pin it
verbatim. E consumes B's tier — pin the call interface.

---

## Wave 2 — TEST-DATA-HYGIENE (merge S-71 + batch-6 root-cause; draft after S-73 lands)

**Need:** tests never touch real/shared state. Demonstrated three times in batch-6
(settings.local.json + SANCTIONED-OPS-LOG pollution; `pkg-once` real `uv install`).

**Deliverables:**
- **Test-data lifecycle policy doc** (e.g. `docs/adr/` or `docs/TEST-DATA-POLICY.md`):
  fixtures use `tmp_path`; NO writes to real `.claude/settings.local.json`,
  `docs/*`, `requirements*`, or real installers; mock `subprocess` for installs.
- **Finish the repo-relative-path root-cause fix:** the settings-path half is DONE
  (`target_paths["settings_local"]` threaded through the appliers, commit `77fb678`).
  Remaining: `tools/sanctioned/_audit.py::write_entry` + any scanner output default
  to the real committed file → thread a log-path / sandbox tool verification so
  committed logs never accumulate test entries (caused the SANCTIONED-OPS-LOG
  pollution stripped in `1435529`).
- **Warn-only ms-enforce gate `check_test_isolation`** — flag tests that write
  outside `tmp_path` or assert against real repo files (heuristic; document FP classes).
- **Sweep** remaining offenders surfaced in batch-6 (`S-66-MERGE-1` decision lists
  the `_isolate_config_data_dir` autouse-fixture over-broadness — narrow it here).

**Suggested streams (~3–4):** A=policy doc; B=write_entry/scanner path-threading +
sandbox; C=`check_test_isolation` gate + tests; D=sweep offenders + narrow the
autouse fixture.
**Processor-contract pins:** pin the policy-doc path + the gate name; B and C both
relate to "tmp redirect" — pin the redirect convention.

---

## Wave 3 — ENFORCEMENT-LIFECYCLE (merge S-70 + S-72; draft when gates/doctrine have aged)

**Need:** keep the accumulated enforcement + doctrine layer from rotting. A gate is
the mechanized form of a doctrine rule; aging the gates and pruning stale doctrine
are two faces of "is this enforcement still earning its keep?"

**Deliverables:**
- **Aging policy for warn-only gates:** track when each gate went warn-only +
  escalation policy (warn → fail after N days / M consecutive clean runs) +
  `tools/audit_gate_age.py`. (~11 warn-only TIER_1 gates now: check_walkback_log,
  check_access_requests_stale, check_orchestrator_dispatch_pattern,
  check_sanctioned_channels_complete, + the 7 S-69 gates.)
- **Doctrine relevance audit:** `tools/audit_doctrine_relevance.py` (flag doctrine
  rules with no enforcing gate AND no recent reference) + a periodic-review ritual.
- Policy docs + ms-enforce integration.

**Suggested streams (~3–4).**
**Processor-contract pins:** BOTH streams may edit ROBOT.md / AUTONOMOUS-DEFAULTS —
pin doctrine-doc ownership per stream (the S-59 A↔B lesson).
**Timing:** fire after the warn-only gates have accumulated run history (signal).

---

## Direct fix (not a wave) — scrub.py is_external egress leak

`backend/agent/scrub.py::is_external` decides whether to scrub via the imported
`_CLOUD_PROVIDERS` constant, NOT the `cloud_providers` routing param that
`_dispatch_llm_call` actually routes on. Identical today, but a provider added to
routing without `_CLOUD_PROVIDERS` would skip the scrub → silent egress leak.
Align the scrub decision to the same set routing uses. Small + security-relevant →
direct fix with a test, outside the wave flow. (The cosmetic `scrub.py` bare-"stack"
over-redaction parks until agent-code debt accumulates.)

---

## Drafting handoff

Fresh bypassPermissions session(s) draft the wave files into `.claude/waves/` from
the briefs above (avoids the acceptEdits sensitive-path friction). Sequence: S-73
now; Test-Data-Hygiene after S-73 lands; Enforcement-Lifecycle later. The Manager
supplies each session a one-line pointer to this file + the target wave name.
