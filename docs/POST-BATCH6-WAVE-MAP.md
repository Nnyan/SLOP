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
3. **Batch-9 = DEPLOY-HARDENING (S-74)** — ADDED 2026-05-29 after the Rocinante
   live-update surfaced real `ms-update`/`deploy.sh` bugs (silent failure, ownership
   churn, `.env`-vs-systemd config, port-var mismatch). Near-term: a broken deploy
   path is operationally higher-priority than the deferred enforcement work. Brief
   in "Wave 4" below; status/lessons in `docs/BACKLOG.md` §"From Rocinante deploy session".
4. **Batch-10 = KNOWLEDGE-LIFECYCLE (S-75)** — ADDED 2026-05-29 from the K-L audit
   (`docs/KNOWLEDGE-LIFECYCLE-AUDIT.md` charter + `docs/KNOWLEDGE-LIFECYCLE-AUDIT-REPORT.md`).
   Two-owner reality-reconciliation + GROUND-vs-XREF discipline + gap-discovery ritual.
   **HARD-sequences after S-74** (shared `CLAUDE.md` deploy section; host-probe needs
   S-74's update path). Wave + launch prompt on main, fire-ready after batch-9 lands.
5. **Batch-11 (deferred) = Enforcement-Lifecycle (S-70+S-72)**, once the warn-only gates
   and the doctrine have *aged enough to have signal* (an aging policy needs history;
   the gate count GREW this session — S-71's `check_test_isolation` + S-75's new gates —
   so even less aged signal; deferral reinforced). Plant-now-harvest-later. NOT drafted.
   It absorbs S-75's forward-compatible **aging-engine** design contract and adds the
   4th aging leg (probes age, per the K-L audit) alongside gates/doctrine/facts. Two
   low-effort adjacents ride along: the pre-commit ratchet hook + `check_provenance` gate.
6. **Done = direct small-fix** the `scrub.py::is_external` egress-scrub leak (`cb58f70`).

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
**Parked items already woven here (2026-05-29):** the `write_entry`/scanner
shared-tree pollution fix (Deliverable 2) and narrowing S-66-B's
`_isolate_config_data_dir` autouse fixture (Deliverable 4) — both are core, not
adjacents (they ARE test-data hygiene).

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

**Bundled low-effort adjacents (woven from the parking lot 2026-05-29 — batch
efficiency, all enforcement-family; clearly bolt-ons, NOT the wave's core need):**
- **Pre-commit hook for the file-size ratchet** (was `[park]`): wire the existing
  `check_linecount` ratchet to run locally pre-commit, not just in CI. Low effort;
  enforcement-delivery, not lifecycle — keep it a small separate stream.
- **Provenance headers for generated files** (was `[park]`; trigger fired — S-55-B
  landed): add a warn-only `check_provenance` requiring `AUTO-GENERATED by …`
  headers on lockfiles / `.linecount-baseline.json` / coverage maps, + stamp the
  existing ones. A gate addition in the enforcement family.

**Suggested streams (~3–6):** core aging + relevance (≤4) + the 2 adjacents as
their own small streams.
**Processor-contract pins:** the core aging/relevance streams may edit ROBOT.md /
AUTONOMOUS-DEFAULTS — pin doctrine-doc ownership per stream (the S-59 A↔B lesson).
The adjacents are file-disjoint (a hooks/config file + a new `check_provenance`).
**Timing:** fire after the warn-only gates have accumulated run history (signal).
The adjacents have no timing dependency — they ride along whenever this fires.

---

## Wave 4 — DEPLOY-HARDENING (S-74; draft now, fire as batch-9)

**Need:** the update path is genuinely broken. On 2026-05-29 a live update of the
Rocinante test server (`/opt/mediastack`, service user `mediastack`, HTTPS git clone)
required ~10 manual recovery steps because `sudo ms-update` silently did nothing and
several assumptions were wrong. Full forensics in `docs/BACKLOG.md` §"From Rocinante
deploy session" and memory `project-rocinante-deploy`. Each item below is a confirmed,
reproduced bug — not speculation.

**Deliverables (all confirmed on a real box):**
- **`ms-update` runs git/pip/npm as the service user, not root.** Today it runs git as
  root on a service-user-owned repo → "dubious ownership"; its unguarded
  `git fetch ... 2>/dev/null` then dies under `set -euo pipefail` with stderr eaten →
  silent no-op. Fix: detect the service user (from `stat -c %U` on the repo or the
  systemd unit's `User=`) and run all file-touching git/pip/npm via `sudo -u <svcuser>`;
  use root only for `systemctl`. STOP swallowing fetch errors (drop `2>/dev/null`, or
  capture+surface). Ensure the existing `reset --hard origin/main` fallback is actually
  reachable (it currently dies at the fetch before it).
- **History-rewrite recovery.** Pre-2026-05-28 clones are diverged from `origin/main`
  (filter-branch scrub) — `git pull` cannot fast-forward; only `fetch` + `reset --hard
  origin/main` works. `ms-update` must detect divergence and reset cleanly (its
  fallback already does this once reachable).
- **Frontend build needs a writable HOME.** The service user has `HOME=/nonexistent`;
  `npm ci`/`npm run build` fail (`EACCES mkdir '/nonexistent'`). `ms-update`/`deploy.sh`
  must set `HOME` (e.g. `/tmp` or a dedicated cache dir) when building as the service
  user. Note `backend/static/` is gitignored → a `reset --hard` deletes the old built
  copy, so the build MUST run on every update (not skipped).
- **Ownership model — single source of truth.** Document + enforce: `/opt/mediastack`
  is owned by the service user; ALL file ops via `sudo -u <svcuser>`; root only for
  systemctl. `deploy.sh` should `chown` to the service user (not the invoking login
  user). Prevents the root-owned-`.git` / unreadable-`.env` churn seen this session.
- **`MS_PORT` vs `MEDIASTACK_PORT` naming.** `deploy.sh` bakes the unit `--port` from
  `MS_PORT` (default 8080); `ms-update` reads `MEDIASTACK_PORT`. A `.env` using the
  wrong name silently falls back to 8080. Pick ONE canonical name across deploy.sh +
  ms-update + docs.
- **App config: `.env` vs systemd `Environment=`.** `os.environ`-read settings
  (`MS_TRUSTED_HOSTS`, `DOMAIN`) are NOT populated from `.env` — the unit sets env via
  inline `Environment=` lines; the app reads `.env` only via Starlette `Config`. So
  editing `.env` for those vars silently does nothing. **Decide + implement ONE model:**
  either (a) call `load_dotenv()` at startup so `.env` works as the docs imply, OR
  (b) document that operator-facing env (trusted hosts, domain) lives in the systemd
  unit and give `deploy.sh`/wizard a clean way to set it. Pin the choice.
- **Docs.** Update install/update docs to the real model (CLAUDE.md already corrected
  `90bf54f`). Add a "recover a stale/diverged clone" runbook.

**Suggested streams (~3–4):** A=`ms-update` rewrite (run-as-service-user + guarded
fetch + reachable reset + build-HOME); B=`deploy.sh` alignment (ownership chown +
port-var canonicalization + build-HOME) ; C=config-mechanism decision (`load_dotenv`
vs systemd-Environment, implement + the `MS_TRUSTED_HOSTS`/`DOMAIN` path); D=docs +
recovery runbook.
**Processor-contract pins:** A and B share the **service-user detection** helper and
the **build-HOME convention** and the **canonical port-var name** — pin all three
verbatim. C owns the env-mechanism decision; A/B consume it.
**Verification caveat (pin in the wave):** these are shell/install scripts that can't
run in CI against a real server. Verification = `shellcheck` clean + logic review +
guarded dry-run (`--help`/no-op paths) + targeted unit tests where Python is involved.
Note this limit explicitly (it's the same gap the parked "install.sh test wave" covers).

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
