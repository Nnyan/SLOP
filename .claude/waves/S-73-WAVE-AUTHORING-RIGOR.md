# S-73-WAVE-AUTHORING-RIGOR — Make wave quality automated, not human-remembered

## Goal
Upgrade the wave-authoring machinery so that wave quality is a property of the
orchestrator's startup, not of a human remembering to pre-flight. Today the
4-agent fact-check pass is done by hand before a batch fires; this wave turns
that into a complexity-gated, mechanical pre-flight the orchestrator runs
automatically, plus the two authoring conventions that make waves legible to it:
a **per-stream `Model` column** and a **canonical `_TEMPLATE.md`**.

End state:
- Every wave file carries an optional per-stream `Model` column (blank = inherit
  the `**Models:**` default); the rubric for choosing the per-stream model lives
  in ROBOT.md.
- `tools/wave_complexity.py` scores any wave file → a tier (`Low`/`Medium`/`High`)
  from mechanical signals.
- The orchestrator startup sequence computes that tier and runs matching rigor,
  BLOCKING dispatch on any FALSE factual claim and writing
  `.claude/run/preflight/<wave>.md`.
- `tools/validate-wave-file.py` is the cheap Low-tier mechanical gate (extended).
- `.claude/waves/_TEMPLATE.md` is the first canonical wave skeleton.
- This wave file itself dogfoods the new Model column (see Parallelization).

## Context
- The manual pre-flight this batch did by hand (spot-checking every path claim and
  inbound-ref count against the live repo) is exactly the work the orchestrator
  startup sequence step 4 ("Pre-flight fact-check") already describes as its job,
  but has no tooling for. This wave supplies the tooling.
- `tools/validate-wave-file.py` already exists (~17 KB) as a path-claim +
  inbound-ref-count validator. It is the natural Low-tier mechanical gate; Stream C
  extends it rather than building a new tool.
- `tools/wave_complexity.py` does NOT exist yet — Stream B builds it. It joins the
  `tools/audit_*.py` / scanner family in spirit (pure stdlib, standalone-runnable,
  own tests) but is a *scorer*, not a warn-only ms-enforce gate.
- Every prior wave uses a single `**Models:**` line (e.g. S-69 line 58:
  `**Models:** coordinator = **opus** ... subagents = **sonnet**`). That line stays
  as the per-wave default; the new per-stream `Model` column overrides it per row.
- The existing Parallelization stream table (see S-69 lines 64–73) has columns
  `Stream | Order | Subagent type | Scope`. Stream A inserts a `Model` column.
- **Processor-pattern contract applies (AUTONOMOUS-DEFAULTS § "Processor-pattern
  contract"):** this wave has parallel streams that share symbols. Every shared
  symbol is PINNED verbatim in Deliverables below so no stream is free to drift the
  interface. The three contracts are: (1) the tier-string contract between B
  (producer) and C+E (consumers); (2) the Model-column table format between A
  (producer) and B (consumer, the scorer reads the column); (3) the ROBOT.md
  "Wave file conventions" subsection ownership between A, C, and D.
- This wave is the force-multiplier that goes FIRST in batch-7 (per
  `docs/POST-BATCH6-WAVE-MAP.md` roadmap): landing it means every later wave
  (batch-8 Test-Data-Hygiene onward) is authored *with* the new template and gated
  by the new pre-flight.

## Rules to follow
- **Additive only.** New files (`wave_complexity.py`, `_TEMPLATE.md`, their tests,
  the preflight harness) + additive doctrine subsections + one new table column.
  No file deletions, no rewrites of existing wave files.
- **Pure stdlib for the scorer + harness.** `tools/wave_complexity.py` and the
  pre-flight harness use stdlib only, matching the existing `tools/audit_*.py` and
  `tools/validate-wave-file.py` tooling. No new dependencies.
- **Pin before drift.** No stream may invent a shape for a shared symbol. The pins
  in Deliverables are binding. If a stream finds a pin wrong or impossible, it
  HALTS and writes a blocker (the wave file is wrong) — it does NOT guess a new
  shape at runtime (AUTONOMOUS-DEFAULTS § "Processor-pattern contract").
- **Blank Model cell = inherit.** The per-stream column NEVER replaces the
  `**Models:**` default line; a blank cell inherits it. Existing waves with no
  column are valid and unchanged (grandfathered).
- **Pre-flight BLOCKS on FALSE, not on WARN.** A factual claim proven FALSE against
  the live repo blocks dispatch. Missing-but-to-be-created paths, approximate
  claims, and stylistic findings are NOT blocking. Conservative by design — mirror
  `validate-wave-file.py`'s "only FAIL on clearly-claimed-existing-and-missing".
- **Backward-compatible tooling.** `validate-wave-file.py`'s existing behavior and
  exit semantics must not regress; Stream C extends, it does not rewrite.

## Authorized deletions
None. This wave is purely additive: two new tool files
(`tools/wave_complexity.py`, the pre-flight harness), one new template
(`.claude/waves/_TEMPLATE.md`), their test files, additive ROBOT.md /
AUTONOMOUS-DEFAULTS subsections, and one new column in the Parallelization table
convention. No files are removed.

## Parallelization

**Models (per-wave default):** coordinator = **opus** (cross-stream contract
enforcement: three pinned contracts span A↔B and B↔C↔E, and the
ROBOT.md subsection merge needs synthesis), subagents = **sonnet** unless the
per-stream `Model` column below overrides.

Five streams. All five are parallel from dispatch: every cross-stream symbol is
pinned verbatim in Deliverables, so consumers (B, C, E) build against the pin
rather than waiting for the producer (A, B) to merge. This dogfoods the
processor-contract rule — pinning is precisely what buys the parallelism.

| Stream | Model | Order | Subagent type | Scope |
|---|---|---|---|---|
| A — Model column + rubric + ROBOT.md conventions | **opus** | parallel | `general-purpose` in worktree | Define the per-stream `Model` column format + authoring rubric; write ROBOT.md "Wave file conventions" → "### Per-stream Model column" subsection |
| B — `tools/wave_complexity.py` scorer | **opus** | parallel | `general-purpose` in worktree | Score a wave file → tier; owns the tier-string contract + scoring calibration |
| C — `validate-wave-file.py` extension + pre-flight doctrine | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Extend the Low-tier validator; write ROBOT.md startup-sequence complexity-gate doctrine + "### Complexity-gated pre-flight" subsection |
| D — `.claude/waves/_TEMPLATE.md` | **haiku** | parallel | `general-purpose` in worktree | Assemble the canonical wave skeleton from the enumerated section list; ROBOT.md "### Canonical wave template" pointer subsection |
| E — pre-flight fact-check harness + `.claude/run/preflight/` wiring | _(blank → sonnet)_ | parallel | `general-purpose` in worktree | Build the Medium/High-tier fact-check harness consuming B's tier; wire the `.claude/run/preflight/` artifact dir |

**Per-stream Model justification (one line each — required by the rubric this wave introduces):**
- **A = opus** — authors the rubric and the Model-column contract that B parses and
  every future wave consumes. Load-bearing convention design: a subtly-wrong rubric
  passes review yet mis-guides all future authoring; the coordinator can't easily
  catch a plausible-but-wrong rubric. (Rubric criterion: cross-stream contract design.)
- **B = opus** — owns the tier-string contract AND the score→tier calibration. A
  mis-calibrated threshold passes B's own unit tests but silently mis-gates every
  future wave's pre-flight rigor — the textbook "plausible-but-wrong-passes-tests"
  case the rubric reserves for Opus.
- **C = sonnet (inherit)** — extends an existing validator and writes doctrine to a
  fully-enumerated spec (the Low/Medium/High → rigor mapping is spelled out in this
  wave). Bounded implementation against a clear spec; the default tier.
- **D = haiku** — assembles a Markdown skeleton from a section list already
  enumerated in this wave (Goal, Context, Rules, … Robot mode). Mechanical,
  zero-judgment boilerplate; the coordinator (opus) reviews the merged template, so
  any nuance miss is catchable. (Rubric criterion: mechanical / boilerplate.)
- **E = sonnet (inherit)** — builds a harness against C's pinned tier→rigor mapping
  and B's pinned `score_wave()` interface. Bounded implementation against two pinned
  contracts; no irreducible judgment it makes alone.

## Deliverables per stream

### Stream A — Per-stream `Model` column + authoring rubric + ROBOT.md conventions
1. **Model-column table format (PINNED — A produces, B's scorer consumes verbatim):**
   - The Parallelization stream table gains a `Model` column immediately after
     `Stream`. Header cell text is exactly `Model`.
   - A cell value is one of: `**opus**`, `**sonnet**`, `**haiku**` (bold,
     lowercase), OR a blank/`_(blank → <model>)_` cell meaning "inherit the
     `**Models:**` default line". The scorer (B) treats a cell containing the
     case-insensitive token `opus` as an Opus stream for its "any Opus stream"
     signal; blank/inherit cells inherit the default-line model.
   - Each wave with per-stream overrides MUST carry a "Per-stream Model
     justification" block (one line per overridden stream), as this file does.
2. **The rubric**, written into ROBOT.md (see subsection ownership below): pick a
   stream's model by its dominant cognitive demand —
   - **Opus** = irreducible judgment (ambiguous root-cause, cross-stream contract
     design, load-bearing refactor, security, plausible-but-wrong-passes-tests).
   - **Sonnet** = bounded implementation to a clear spec (the default).
   - **Haiku** = mechanical / zero-judgment (apply a classification, find/replace,
     rename, boilerplate assembly).
   - **Guardrail:** the coordinator is already Opus and reviews every merge, so a
     stream earns Opus only if IT makes calls the coordinator cannot catch.
     Every override carries a one-line justification.
3. **ROBOT.md subsection (PINNED ownership — A owns this subsection ONLY):** add
   `### Per-stream Model column` under `## Wave file conventions`. Contains the
   column format (1) + the rubric (2). A does NOT touch C's or D's subsections.

### Stream B — `tools/wave_complexity.py` (scorer)
1. **Tier-string contract (PINNED — B produces, C and E consume verbatim):**
   - The three tier strings are EXACTLY `"Low"`, `"Medium"`, `"High"`
     (capitalized, no other casing, no synonyms). Expose them as module constants:
     `TIER_LOW = "Low"`, `TIER_MEDIUM = "Medium"`, `TIER_HIGH = "High"`, and
     `VALID_TIERS = ("Low", "Medium", "High")`.
   - **Python API (PINNED signature):**
     `score_wave(wave_path) -> dict` returning a dict with at least:
     `{"tier": <one of VALID_TIERS>, "score": int, "signals": dict, "reasons": list[str]}`.
     `wave_path` accepts `str` or `pathlib.Path`. The function never raises on a
     well-formed wave file; on an unreadable/missing file it raises
     `FileNotFoundError` (callers handle).
   - **CLI (PINNED):** `python3 tools/wave_complexity.py <wave-file> [--repo .]`
     prints a human summary and emits the bare tier string (`Low`/`Medium`/`High`)
     as the FINAL stdout line, so shell consumers can `tail -1`. Exit 0 always
     (scoring is informational; gating/blocking is the harness's job, not the
     scorer's).
2. **Signals** (mechanical, from the wave-file text + light repo lookups): stream
   count; files created/modified; shared symbols across streams (count of
   "PINNED" markers / explicitly-shared symbols); refactor-vs-additive; sensitive
   paths touched (`.claude/settings*`, ROBOT.md, AUTONOMOUS-DEFAULTS, `backend/`
   security/migrations); cross-wave file overlap; count of repo-claims (path +
   inbound-ref assertions); presence of any Opus stream (parsed from the Model
   column per A's pinned format).
3. **Score → tier calibration:** a documented, deterministic mapping from the
   weighted signals to one of the three tiers. Document the thresholds in the
   module docstring (a reviewer must be able to see why a given wave scored its tier).
4. `tests/test_wave_complexity.py` — fixtures covering a Low wave (single additive
   stream), a Medium wave (multi-stream, some repo claims), and a High wave
   (shared symbols + sensitive paths + an Opus stream). Assert `tier` is always in
   `VALID_TIERS` and the CLI's final line is the bare tier.

### Stream C — `validate-wave-file.py` extension + complexity-gate doctrine
1. **Extend `tools/validate-wave-file.py`** as the Low-tier mechanical gate:
   preserve all existing behavior + exit semantics (no regression); add the ability
   to report results in a form the pre-flight harness can consume (E reads it).
   The validator remains conservative (FAIL only on clearly-claimed-existing-but-
   missing paths and exact-count inbound-ref mismatches).
2. **Tier-string consumer (consumes B's PINNED contract):** any place C compares or
   branches on a tier uses the exact strings `"Low"`/`"Medium"`/`"High"` and may
   import `VALID_TIERS` from `tools/wave_complexity.py`. C does NOT redefine the
   strings.
3. **ROBOT.md doctrine (PINNED ownership — C owns these regions ONLY):**
   - Add `### Complexity-gated pre-flight` under `## Wave file conventions`
     documenting the tier → rigor mapping:
     - **Low** = `tools/validate-wave-file.py` only.
     - **Medium** = Low + one fact-check subagent (a claim proven FALSE BLOCKS dispatch).
     - **High** = Medium + processor-contract-pinned check (every shared symbol is
       pinned) + cross-wave disjointness + edited-wave consistency.
   - Edit the existing `### Orchestrator startup sequence` step 4 ("Pre-flight
     fact-check") to: compute the tier via `tools/wave_complexity.py`, run the
     matching rigor, BLOCK dispatch on any FALSE claim, and write
     `.claude/run/preflight/<wave>.md`. C edits step 4's prose ONLY; E owns the
     `.claude/run/preflight/` entry in the "File and directory layout" block (a
     different region — no overlap with C).

### Stream D — `.claude/waves/_TEMPLATE.md` (canonical skeleton)
1. Create `.claude/waves/_TEMPLATE.md` — the first canonical wave skeleton, section
   order EXACTLY: Goal, Context, Rules to follow, Authorized deletions,
   Parallelization (**with the `Model` column** per A's pinned format + a
   "Per-stream Model justification" stub), **Complexity & Pre-flight**, Deliverables
   per stream, Verification, Out of scope, Cross-wave dependencies, Robot mode.
   Each section carries a one-line `<!-- guidance -->` comment, not prose.
2. The Parallelization stub table uses A's pinned column format verbatim (header
   `Model`, bold-lowercase model cells, blank = inherit).
3. **ROBOT.md subsection (PINNED ownership — D owns this subsection ONLY):** add
   `### Canonical wave template` under `## Wave file conventions` — a short pointer:
   "New waves start from `.claude/waves/_TEMPLATE.md`." D does NOT touch A's or C's
   subsections.

### Stream E — pre-flight fact-check harness + `.claude/run/preflight/` wiring
1. Build the pre-flight harness that the orchestrator invokes at startup:
   - **Consumes B's PINNED interface:** calls `score_wave(wave_path)` (or the CLI
     final-line tier) to get the tier, branches on `"Low"`/`"Medium"`/`"High"`
     using B's `VALID_TIERS`.
   - **Consumes C's PINNED tier→rigor mapping:** Low → run extended
     `validate-wave-file.py`; Medium → + dispatch one fact-check subagent; High →
     + processor-contract-pinned check + cross-wave disjointness + edited-wave
     consistency.
   - Writes the result to `.claude/run/preflight/<wave>.md` (a report listing each
     claim checked, PASS/FALSE, and an overall DISPATCH-OK / BLOCKED verdict).
     BLOCKED iff any claim is FALSE.
2. **Wire `.claude/run/preflight/` (PINNED ownership — E owns this ROBOT.md region
   ONLY):** add the `preflight/` entry to the "File and directory layout (per run)"
   block in ROBOT.md (it sits alongside `status/`, `decisions/`, `blockers/`,
   `observations/`, `log/`). `.claude/run/` is already gitignored; confirm
   `preflight/` inherits that. E does NOT edit the "Wave file conventions" section
   (A/C/D territory) nor step 4 of the startup sequence (C's prose).
3. `tests/test_preflight_harness.py` — fixtures driving a Low/Medium/High wave
   through the harness; assert a FALSE claim yields a BLOCKED verdict and a
   `.claude/run/preflight/<wave>.md` (use `tmp_path`, never the real run dir).

## Complexity & Pre-flight (dogfood — this wave's own tier)
**Tier: High.** Signals: 5 streams; three PINNED shared-symbol contracts spanning
A↔B and B↔C↔E; touches sensitive doctrine paths (ROBOT.md, AUTONOMOUS-DEFAULTS);
two Opus streams. Any one of {shared symbols, sensitive paths, Opus stream} pushes
toward High; all three present ⇒ High.

**Rigor applied:** because `tools/wave_complexity.py` and the pre-flight harness are
what THIS wave builds, the High-tier pre-flight for S-73 itself is run **manually**
by the drafting/operator pass (the by-hand 4-agent fact-check this batch already
does): verify every pinned symbol is present in Deliverables, confirm cross-wave
disjointness, and confirm referenced files (`tools/validate-wave-file.py`) exist.
From batch-8 onward the tooling this wave ships runs that rigor automatically.

## Verification
1. `python3 -m pytest tests/test_wave_complexity.py tests/test_preflight_harness.py -v`
   — all pass. (Plus `validate-wave-file`'s existing tests if present — no regression.)
2. `python3 tools/wave_complexity.py .claude/waves/S-73-WAVE-AUTHORING-RIGOR.md`
   exits 0 and prints `High` as its final line (this wave dogfoods to High).
3. `python3 tools/validate-wave-file.py .claude/waves/S-73-WAVE-AUTHORING-RIGOR.md`
   passes (no false path/inbound-ref failures against the live repo).
4. **Tier-string contract holds:** a test asserts `wave_complexity.VALID_TIERS ==
   ("Low", "Medium", "High")` and that the harness (E) and validator (C) branch on
   exactly those strings (no stray lower-cased or abbreviated tier variants remain
   in the validator or harness source).
5. **Model-column contract holds:** the scorer (B) correctly flags this wave's two
   `**opus**` cells as Opus streams; a blank/inherit cell is NOT flagged.
6. `.claude/waves/_TEMPLATE.md` exists with all 11 sections in the pinned order,
   including the `Model` column in its Parallelization stub.
7. `python3 ms-enforce` exits 0 — no new warnings introduced by the doctrine edits.
8. ROBOT.md `## Wave file conventions` contains the three disjoint new subsections
   (A: Per-stream Model column; C: Complexity-gated pre-flight; D: Canonical wave
   template) and the startup-sequence step 4 references the complexity gate;
   `.claude/run/preflight/` appears in the file-layout block (E).
9. Running E's harness on this wave file produces `.claude/run/preflight/S-73-WAVE-AUTHORING-RIGOR.md`
   with verdict DISPATCH-OK (all pinned claims present, all path claims resolve).

## Out of scope
- **Graduating any pre-flight finding to a blocking CI gate beyond the
  dispatch-time block.** The pre-flight blocks the orchestrator at startup; it is
  NOT a new `ms-enforce` TIER_1/TIER_2 check. (Aging/graduation of gates is the
  later Enforcement-Lifecycle wave, S-70+S-72.)
- **Retro-fitting the `Model` column onto existing wave files.** Only S-73 dogfoods
  it; prior waves stay grandfathered (blank = inherit).
- **Test-data hygiene** (batch-8 Test-Data-Hygiene) — authored AFTER this wave lands,
  using the new template. Not this wave.
- **Auto-tuning models from run history** — the rubric is a human-authored heuristic;
  no learning loop here.
- **Replacing `validate-wave-file.py` or the `tools/audit_*.py` family** — Stream C
  extends the validator; it does not consolidate the tooling.

## Cross-wave dependencies (EXPLICIT)
- Depends ONLY on current `origin/main` (`cb58f70` as of 2026-05-29 — the
  scrub.py egress fix; orchestrator re-confirms `git rev-parse origin/main` at
  startup and rebases the wave branch if main has advanced).
- **No upstream code dependency.** S-73 is the FIRST and (per the roadmap) ONLY wave
  in batch-7. It is a *downstream prerequisite* for batch-8 (Test-Data-Hygiene is
  authored using this wave's `_TEMPLATE.md`), but that is an authoring convenience,
  not a code dependency — nothing in batch-8 imports S-73's symbols.
- **Intra-wave shared touch-points** (all pinned above, resolved keep-both per
  AUTONOMOUS-DEFAULTS § "Intra-wave merge conflict ... multiple streams"):
  - ROBOT.md `## Wave file conventions` — A, C, D each own a disjoint NEW subsection.
  - ROBOT.md `### Orchestrator startup sequence` step 4 (C) vs "File and directory
    layout" block (E) — disjoint regions.
  - `tools/wave_complexity.py` `VALID_TIERS` — B produces, C + E import (no edit).
  - Parallelization `Model` column format — A produces, B parses (no edit).
- File-disjoint with all other not-yet-drafted waves (Test-Data-Hygiene,
  Enforcement-Lifecycle). Batch-6 is already merged to main; no in-flight overlap.

## Robot mode (autonomous execution)
Operate under `.claude/ROBOT.md` doctrine. Five streams (A–E) parallel from start —
every shared symbol is pinned, so consumers build against the pin (this dogfoods
the processor-contract rule). Coordinator merges all streams to
`wave/S-73-wave-authoring-rigor` in a dedicated `.claude/worktrees/merge-S-73`
worktree (detached HEAD), never main. The one knowingly-shared file is ROBOT.md
(three disjoint additive subsections + two disjoint region edits) — resolve any
additive conflict keep-both at the whole-block level (NEVER `merge=union`) and log a
`S-73-MERGE-N.md` decision. Post-wave merge to main goes through
`python3 tools/merge_wave_to_main.py wave/S-73-wave-authoring-rigor`.

Invocation: `in Robot mode: execute the wave defined in .claude/waves/S-73-WAVE-AUTHORING-RIGOR.md as orchestrator.`
