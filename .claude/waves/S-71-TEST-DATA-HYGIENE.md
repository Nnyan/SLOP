# S-71-TEST-DATA-HYGIENE — Tests never touch real or shared state

## Goal
Make "a test may not read or write real, shared, or committed state" a property
the suite *enforces*, not a discipline each author must remember. Batch-6
demonstrated the failure class three times (settings.local.json pollution,
SANCTIONED-OPS-LOG pollution, a real `uv install` in `pkg-once`). This wave lands
a written policy, finishes the repo-relative-path root-cause fix, adds a warn-only
gate that flags new offenders, and sweeps the known remaining ones.

End state:
- A canonical, citable policy (`docs/adr/0019-test-data-isolation.md`) states the
  rules: fixtures use `tmp_path`; no writes to real `.claude/settings.local.json`,
  `docs/*`, `requirements*`, or real installers; `subprocess` for installs is mocked.
- The sanctioned-tool audit path can never be the real committed log during test or
  verification runs — enforced by a redirect convention, not by remembering to pass
  a path.
- `ms-enforce` carries a warn-only `check_test_isolation` gate that flags tests
  writing outside `tmp_path` or asserting against real repo files.
- The known offenders surfaced in batch-6 are swept, and S-66-B's over-broad
  `_isolate_config_data_dir` autouse fixture is narrowed.

## Context
- **Root-cause class, demonstrated 3× in batch-6:** (1) `robot_settings.py`
  verification wrote to the real `.claude/settings.local.json` (fixed `77fb678` by
  threading `target_paths["settings_local"]`); (2) `robot_settings.py` verification
  appended 9 real entries to `docs/SANCTIONED-OPS-LOG.md` (hand-stripped `1435529`);
  (3) the `pkg-once` idempotency test ran a real `uv install` (mocked in `1435529`).
- **`tools/sanctioned/_audit.py::write_entry` already accepts a `log_path` param**
  (signature at `_audit.py:135`, defaulting to `SANCTIONED_OPS_LOG =
  Path("docs/SANCTIONED-OPS-LOG.md")` at `_audit.py:36`). So the function-level fix
  is NOT the gap. The gap is that the sanctioned tools and their verification paths
  call `write_entry` **without** redirecting `log_path`, so an accidental real-tree
  write is one missing argument away. Five tools call it: `robot_settings.py`,
  `force_push_tag.py`, `filter_branch_secret_scrub.py`, `rm_recursive_safe.py`
  (and `__init__.py` re-exports it).
- **`docs/adr/` is the established policy home** — numbered ADRs `0001`–`0018` +
  `template.md`. `0002-mocking-policy.md` already covers mocking; this wave's policy
  is its test-data-isolation sibling and should cross-link it. Next free number is
  `0019`.
- **`ms-enforce` (repo root) registers checks as `def check_*() -> tuple[bool, str]`
  functions.** `check_referenced_files` (`ms-enforce:626`) is the canonical
  **warn-only** pattern to mirror: it shells to a `tools/check_*.py` script,
  collects `WARNING`-prefixed lines, and **always returns `True`** (never blocks).
  The new gate follows this shape exactly.
- **The over-broad fixture:** `tests/conftest.py:117` `_isolate_config_data_dir`
  (S-66 Stream B) is `autouse=True` and redirects `config.data_dir` for EVERY test.
  The `S-66-MERGE-1` decision (run-archive) verified that de-autousing it leaves the
  full suite unchanged (17/2631 — the known residual) — i.e. it is over-broad and
  safe to narrow to the provider-scope that actually needs it.
- **Authored with batch-7's machinery:** this is the first wave drafted from
  `.claude/waves/_TEMPLATE.md` with the per-stream `Model` column, and its
  pre-flight is run automatically by `tools/preflight_wave.py` /
  `tools/wave_complexity.py` (shipped batch-7, `ff27adb`).
- **Processor-pattern contract applies** (AUTONOMOUS-DEFAULTS § "Processor-pattern
  contract"): parallel streams share three symbols — the policy-doc path, the gate
  name, and the test-redirect convention — all PINNED verbatim in Deliverables so no
  stream drifts the interface.

## Rules to follow
- **Additive-leaning.** New files (the ADR, the gate, the `check_test_isolation`
  script, tests) + small edits to existing tools/tests. The only behavioral edits to
  existing code are: narrowing one autouse fixture (D) and sandboxing audit-log
  writes in tool verification (B). No broad refactors.
- **Pure stdlib for the gate + scanner**, matching `tools/check_*.py` and `ms-enforce`
  (no new dependencies).
- **The new gate is WARN-ONLY.** `check_test_isolation` always returns `True` (mirror
  `check_referenced_files`); it never fails CI. Graduating it to blocking is the
  later Enforcement-Lifecycle wave's job (out of scope here — gate aging is batch-9).
- **No regression to existing tests.** Narrowing the autouse fixture (D) MUST leave
  the full suite green (the `S-66-MERGE-1` verification is the baseline: 17/2631
  known residual, unchanged). If narrowing breaks a test, that test gets an explicit
  opt-in to the fixture — it is NOT left silently relying on a global.
- **Pin before drift.** No stream invents a shape for a shared symbol. If a pin is
  wrong or impossible, the stream HALTS and writes a blocker — it does not guess
  (AUTONOMOUS-DEFAULTS § "Processor-pattern contract").
- **Backward-compatible audit API.** `write_entry`'s existing signature and default
  must not change behavior for production callers; B adds a redirect mechanism,
  it does not remove the `log_path` default.

## Authorized deletions
None outright. Two **in-place narrowings/edits** are authorized and bounded:
- D may change `tests/conftest.py:117` `_isolate_config_data_dir` from `autouse=True`
  to an explicitly-requested fixture (and add the opt-in to whichever tests need it).
- B may edit the sanctioned tools' **verification/test entry points** to pass a
  sandboxed `log_path`. No deletion of `write_entry`, `SANCTIONED_OPS_LOG`, or any
  production audit call.

## Parallelization

**Models (per-wave default):** coordinator = **opus** (three pinned cross-stream
contracts + the gate-heuristic synthesis need review across streams), subagents =
**sonnet** unless the per-stream `Model` column below overrides.

Four streams, all parallel from dispatch: every cross-stream symbol is pinned
verbatim in Deliverables, so consumers build against the pin rather than waiting for
the producer to merge.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — Test-data-isolation policy (ADR 0019) | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Author `docs/adr/0019-test-data-isolation.md`; owns the policy-doc path + the canonical rule list; cross-links ADR 0002 |
| B — Audit-log redirect / sandbox | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Make sanctioned-tool verification never write the real log; owns the redirect convention contract |
| C — `check_test_isolation` warn-only gate | **opus** | parallel | `general-purpose` in worktree | Design + build the heuristic gate + `tools/check_test_isolation.py` + tests; owns the gate-name contract |
| D — Sweep offenders + narrow autouse fixture | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Narrow `_isolate_config_data_dir`; sweep batch-6 offenders; rename `test_preflight_harness.py`→`test_preflight_wave.py` |

**Per-stream Model justification (one line each — required by the rubric in ROBOT.md § "Per-stream Model column"):**
- **A = sonnet (inherit)** — authors a policy doc to a need already fully enumerated
  in this wave + ADR 0002 as a template; bounded documentation, the coordinator
  reviews the rules. Bounded implementation to a clear spec.
- **B = sonnet (inherit)** — threads an existing `log_path` param + adds an env-var
  redirect; the mechanism is spelled out below. Bounded implementation; the
  coordinator catches any missed caller at merge review.
- **C = opus** — designs the test-isolation **heuristic** and its false-positive
  taxonomy. A plausible-but-wrong heuristic passes its own unit tests yet either
  drowns the suite in false warnings (→ ignored, the aging problem) or misses the
  very offender class it exists to catch. Irreducible judgment the coordinator can't
  easily catch from a green test run — the rubric's "plausible-but-wrong-passes-tests".
- **D = sonnet (inherit)** — narrows one fixture and sweeps a known, enumerated
  offender list (the `S-66-MERGE-1` decision already scoped exactly what to narrow,
  with a verified-safe baseline). Bounded; full-suite-green is the catchable check.

## Complexity & Pre-flight
**Tier: High** (confirmed by `tools/wave_complexity.py`: score 26 → High). Signals:
4 streams; PINNED shared-symbol contracts (policy-doc path, gate name, redirect
convention); touches sensitive enforcement/test-infra paths (`ms-enforce`,
`tests/conftest.py`); one Opus stream (C). Shared symbols + sensitive paths + an
Opus stream all present ⇒ the High floor.

**Rigor applied (automatic, batch-7 machinery):** the orchestrator runs
`tools/preflight_wave.py` on this file at startup — it computes the tier via
`tools/wave_complexity.py` and applies the matching rigor (High = extended
`validate-wave-file.py` + fact-check subagent + processor-contract-pinned check +
cross-wave disjointness + edited-wave consistency), BLOCKING dispatch on any FALSE
claim and writing `.claude/run/preflight/S-71-TEST-DATA-HYGIENE.md`. This wave's
factual claims (file paths, line numbers, the `write_entry` signature, the
`check_referenced_files` warn-only pattern) are written to be verifiable against
live `main`.

## Deliverables per stream

### Stream A — Test-data-isolation policy (ADR 0019)
1. **Policy-doc path (PINNED — A produces; C's gate docstring + tests reference it):**
   the policy lives at exactly `docs/adr/0019-test-data-isolation.md`, following the
   `docs/adr/template.md` ADR format and the `0001`–`0018` numbering.
2. Content — the canonical rule list:
   - Fixtures write only under `tmp_path` (or `tmp_path_factory`).
   - No test reads/writes real `.claude/settings.local.json`, `docs/*` (incl.
     `SANCTIONED-OPS-LOG.md`), `requirements*.txt`, or real config/data dirs.
   - Installs / package operations (`uv`, `pip`, `docker`) are mocked at the
     `subprocess` boundary — no real network/package side effects (cross-link
     `0002-mocking-policy.md`).
   - Sanctioned tools under test redirect their audit log per the convention B owns.
   - Document the warn-only `check_test_isolation` gate (C) as the mechanical backstop
     and its known false-positive classes.
3. Add the ADR to `docs/MAP.md` if the MAP tracks ADRs (check; the orphan/doc gate
   `check_referenced_files` flags docs absent from MAP).

### Stream B — Audit-log redirect / sandbox (PINNED: redirect convention)
1. **Redirect convention (PINNED — B produces; A documents it, C's gate may detect
   violations of it):**
   - Add an environment-variable override to `tools/sanctioned/_audit.py`: when
     `SLOP_AUDIT_LOG_PATH` is set, `write_entry`'s effective default log path is that
     value (explicit `log_path=` argument still wins). Production unset → unchanged
     behavior (writes the real `docs/SANCTIONED-OPS-LOG.md`).
   - Convention string for tests/verification: set `SLOP_AUDIT_LOG_PATH` to a
     `tmp_path` file (or pass `log_path=tmp_path/...`) so no verification run can
     touch the committed log.
2. Audit the five `write_entry` callers (`robot_settings.py`, `force_push_tag.py`,
   `filter_branch_secret_scrub.py`, `rm_recursive_safe.py`, `__init__.py` re-export):
   ensure each tool's `--verify`/self-test path (the one batch-6 polluted via
   `robot_settings.py`) honors the redirect — production CLI paths stay on the real log.
3. Tests: a test proving that with `SLOP_AUDIT_LOG_PATH` set, `write_entry` writes the
   tmp file and the real `docs/SANCTIONED-OPS-LOG.md` is untouched (use `tmp_path`,
   `monkeypatch.setenv`).

### Stream C — `check_test_isolation` warn-only gate (PINNED: gate name)
1. **Gate name (PINNED — C produces; A's policy references it verbatim):** the
   ms-enforce check function is exactly `check_test_isolation`, backed by
   `tools/check_test_isolation.py`. It mirrors `check_referenced_files`
   (`ms-enforce:626`): shells to the script, collects `WARNING`-prefixed lines,
   **always returns `True`** (warn-only, never blocks CI).
2. `tools/check_test_isolation.py` (pure stdlib): a conservative heuristic over
   `tests/**` that flags a test file when it appears to write outside `tmp_path` or
   assert against real repo files — e.g. `open(...,"w")`/`.write_text(...)` on a path
   literal that is NOT derived from `tmp_path`/`tmp_path_factory`, or references to
   `docs/`, `.claude/settings.local.json`, `requirements` as write/assert targets.
   Emit `WARNING [test-isolation] <file>:<line> <reason>`. **Document the
   false-positive classes** (e.g. reading a fixture data file is fine; building a
   path string that is later joined under tmp_path).
3. Register `check_test_isolation` in `ms-enforce` alongside the other warn-only
   checks (same tuple-returning shape; appears in the warn-only group, NOT a blocking
   TIER). C edits ms-enforce ONLY to add this one check + its registration — it does
   not touch other checks.
4. `tests/test_check_test_isolation.py`: fixtures with a clean test (tmp_path only)
   and a dirty test (writes `docs/x.md`); assert the dirty one warns and the clean one
   does not. Use `tmp_path`; the script must not warn on its own test fixtures.

### Stream D — Sweep offenders + narrow the autouse fixture
1. **Narrow `_isolate_config_data_dir`** (`tests/conftest.py:117`): change from
   `autouse=True` to an explicitly-requested fixture (e.g. rename to
   `isolate_config_data_dir` without autouse, or scope it to the provider tests that
   need it). Add the opt-in to the tests that actually exercise
   `GlanceDashboardProvider`/`HomepageProvider` `cfg_dir.mkdir()`. **Verify the full
   suite stays green** at the `S-66-MERGE-1` baseline (17/2631 known residual,
   unchanged) — this is the wave's hard acceptance gate for D.
2. Sweep the batch-6 offender class for any remaining real-tree writers not already
   fixed in `77fb678`/`1435529`; convert each to `tmp_path` / mocked `subprocess`.
   If the new `check_test_isolation` gate (C) surfaces offenders, fix the ones inside
   this wave's scope and log the rest to BACKLOG `[→ batch-9]` (do not scope-creep).
3. **Cosmetic carry-over from batch-7:** rename `tests/test_preflight_harness.py` →
   `tests/test_preflight_wave.py` (it tests `tools/preflight_wave.py`); update the
   module docstring + any references in `.claude/waves/S-73-WAVE-AUTHORING-RIGOR.md`
   are historical and stay as-is.

## Verification
1. `python3 -m pytest -q` — full suite green at the known baseline (17/2631 residual,
   unchanged); D's fixture-narrowing introduces no new failures.
2. `python3 -m pytest tests/test_check_test_isolation.py tests/test_preflight_wave.py -v`
   — all pass.
3. **Redirect proven:** a test shows `SLOP_AUDIT_LOG_PATH=<tmp>` routes `write_entry`
   to the tmp file and leaves `docs/SANCTIONED-OPS-LOG.md` byte-unchanged.
4. `python3 ms-enforce` exits 0 — `check_test_isolation` runs, is warn-only (never
   flips the overall result to fail), and reports cleanly (or only documented-FP
   warnings) on the current tree.
5. **Gate name + policy-path contracts hold:** the ADR references the gate as
   `check_test_isolation`; the gate docstring references `docs/adr/0019-test-data-isolation.md`.
6. `docs/adr/0019-test-data-isolation.md` exists, follows the ADR template, and
   cross-links `0002-mocking-policy.md`; added to `docs/MAP.md` if ADRs are tracked there.
7. `_isolate_config_data_dir` is no longer `autouse=True`; a grep confirms the tests
   that need it opt in explicitly.
8. `tests/test_preflight_harness.py` no longer exists; `tests/test_preflight_wave.py`
   does and passes.

## Out of scope
- **Graduating `check_test_isolation` to a blocking gate.** It ships warn-only;
  aging/escalation of warn-only gates is the later Enforcement-Lifecycle wave
  (batch-9, S-70+S-72). Adding it here would pre-empt that wave's aging policy.
- **A broad test-suite refactor.** Only the enumerated offenders + the one autouse
  fixture are touched. Other test smells go to BACKLOG, not this wave (no
  fix-all-failures).
- **Changing production audit behavior.** `write_entry`'s real-log default for
  production CLI paths is unchanged; only test/verification paths redirect.
- **The cosmetic `scrub.py` bare-"stack" over-redaction** — parked until agent-code
  debt accumulates (per POST-BATCH6-WAVE-MAP).

## Cross-wave dependencies (EXPLICIT)
- Depends ONLY on current `origin/main` (`2a8de40` as of 2026-05-29 — batch-7 landed;
  the orchestrator re-confirms `git rev-parse origin/main` at startup and rebases the
  wave branch if main has advanced).
- **Uses batch-7's machinery** (`_TEMPLATE.md`, `wave_complexity.py`,
  `preflight_wave.py`) for authoring + pre-flight — an authoring/tooling dependency,
  NOT a code import. Nothing in this wave imports S-73's symbols.
- **Intra-wave shared touch-points** (all pinned above):
  - Policy-doc path `docs/adr/0019-test-data-isolation.md` — A produces, C references.
  - Gate name `check_test_isolation` — C produces, A references.
  - Redirect convention (`SLOP_AUDIT_LOG_PATH` + tmp_path rule) — B produces, A
    documents, C may detect violations of.
  - `ms-enforce` — only C edits it (adds one check). No other stream touches it →
    no intra-wave conflict on that file.
  - `tests/conftest.py` — only D edits it. `docs/adr/` — only A adds a file.
- **File-disjoint with batch-9 (Enforcement-Lifecycle):** batch-9 adds gate-*aging*
  (`audit_gate_age.py`) + doctrine audit + the provenance/pre-commit adjacents; it
  does not touch this wave's gate body, the ADR, or the audit redirect. Sequencing:
  batch-8 lands first; batch-9's aging policy later consumes `check_test_isolation`
  as one of the warn-only gates it ages.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine. Four streams (A–D) parallel from start —
every shared symbol is pinned, so consumers build against the pin. The streams are
largely file-disjoint: A adds `docs/adr/0019-...`, B edits `_audit.py` + sanctioned
tool verification paths, C adds `tools/check_test_isolation.py` + one registration in
`ms-enforce`, D edits `tests/conftest.py` + sweeps offenders + renames a test file.
The only file more than one stream could touch is `tests/` broadly (B and C and D all
add/modify test files) — keep each stream's new test files distinctly named
(`test_audit_redirect.py`, `test_check_test_isolation.py`, etc.) to avoid collisions;
if two streams must edit the same existing test, resolve keep-both and log a
`S-71-MERGE-N.md` decision. Coordinator merges all streams to
`wave/S-71-test-data-hygiene` in a dedicated `.claude/worktrees/merge-S-71` worktree
(detached HEAD), never main. Post-wave merge to main goes through
`python3 tools/merge_wave_to_main.py wave/S-71-test-data-hygiene`.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-71-TEST-DATA-HYGIENE.md as orchestrator.`
