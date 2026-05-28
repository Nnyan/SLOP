# OPTIONAL — File-size remediation (Phases 2–5)

## Status: PARKED — do not execute without explicit go-ahead from the user.

This wave is deliberately not assigned an S-NN number. It is the parked
follow-on to `S-45-RATCHET.md`, recording the deferred remediation phases so
they remain visible during routine wave planning and are not silently forgotten.

## Why parked

Honest effort-vs-gain assessment (2026-05-27): 10–15 sessions of pure
refactoring on a working solo-dev project is hard to justify on user value.
The ratchet system installed by S-45-RATCHET bounds future growth at near-zero
cost. Files in `.linecount-baseline.json` will shrink opportunistically as
feature work touches them — paid for by work that was happening anyway.

## Re-evaluation trigger

Open this wave if any of the following becomes true:
1. **3+ files have grown ratchet-blocked but unsplit** — meaning real feature
   work is being held back by the cap (not just minor edits).
2. **A new contributor joins SLOP** — large-file friction multiplies with team size.
3. **LLM-context limits keep hitting** on specific files during agent work
   (e.g., wave agents repeatedly fail on `executor.py` or `api/platform.py`).
4. **Sustained low feature pressure** — opportunity cost of refactoring drops
   below the value of cleanup.

Default re-evaluation date if none of the above triggers: **2026-08-27** (~3 months
after S-45-RATCHET installation). Project memory `project-file-size-ratchet`
holds the bookkeeping.

## Phase 2 — Pilot one split (ALWAYS the first sub-wave if this is unparked)

**Goal:** Prove the split pattern works before committing to Phases 3–5.

**Target file (recommended):** `backend/health/checker.py` (1504 lines, relatively
isolated state-machine logic). Fallback: `backend/platform/wizard.py` (1126,
more coupled but more representative of the harder splits).

**Deliverable:** Split the chosen file into a package:
- `backend/health/checker/__init__.py` re-exporting public surface
- `backend/health/checker/dispatcher.py` — entry point + orchestration
- `backend/health/checker/checks/` — one module per check type
- `backend/health/checker/helpers.py` — pure helpers

Then run `python3 tools/check_linecount.py --update-shrunk` to refresh the
baseline (the original 1504-line entry should disappear; new files must all
land under 500).

**Verification:** Full test suite passes, `ms-enforce` exits 0, manual smoke
of the health dashboard.

**Estimated effort:** 1 session (~3 hrs).

**Decision gate after Phase 2:** Based on actual coupling pain encountered,
decide whether to proceed with Phases 3–5 or stop here.

## Phase 3 — Backend remediation (10 files >800 outside views/tests)

| File | Lines | Suggested split | Risk |
|---|---|---|---|
| `backend/manifests/executor.py` | 2011 | dispatcher + step modules + helpers | high |
| `backend/api/platform.py` | 1926 | router package: setup/wizard/stacks | medium |
| `backend/api/health.py` | 1908 | router package: agent/system/apps | medium |
| `backend/api/apps.py` | 1729 | router package: install/lifecycle/custom (watch `_SLOP_MANAGED_VARS` coupling) | high |
| `backend/health/checker.py` | 1504 | covered in Phase 2 | — |
| `backend/platform/wizard.py` | 1126 | or covered in Phase 2 | — |
| `backend/api/models.py` | 1095 | router + service split | low |
| `backend/core/system_eval.py` | 1076 | check modules + aggregator | low |
| `backend/health/context_assembler.py` | 990 | barely over; trim only | low |
| `installer/uninstall.py` | 862 | barely over; trim only | low |
| `backend/core/state.py` | 840 | split by aggregate root | medium |

**Parallelization:** Per the max-parallel rule, group non-overlapping files
into parallel sub-waves. The four API router files share `_SLOP_MANAGED_VARS`
and the FastAPI app composition — sequence them within one stream. The other
six are independent and can run as parallel agents in worktrees.

**Estimated effort:** 5–7 sessions (or 2–3 wall-clock with full parallelization).

## Phase 4 — Frontend remediation (3 views >800)

- `frontend/src/views/SetupView.vue` (2038)
- `frontend/src/views/SettingsView.vue` (1757)
- `frontend/src/views/ModelsView.vue` (1187)

**Pattern:** Extract to `frontend/src/composables/use<Feature>.ts` (existing rule).
The composables directory currently has only 2 entries — this phase grows it
substantially.

**Critical:** Each view is an install / settings / models flow. Manual browser
verification of every interactive path is required — typecheck + unit tests
will not catch UI regressions.

**Parallelization:** All three views are independent files — full parallel.

**Estimated effort:** 4–5 sessions (or 1.5–2 wall-clock parallelized).

## Phase 5 — Lock the ratchet

- Run `python3 tools/check_linecount.py --update-shrunk` to record all new
  smaller baselines as the new ceilings.
- Review remaining baseline entries: any file now well under its category cap
  should be removed from the baseline entirely so it falls under the standard cap.
- Update CLAUDE.md with any new patterns learned during Phases 2–4.

**Estimated effort:** ~0.5 sessions.

## Out of scope (deliberate)

- Tests over 1000 lines (informational only by ratchet rule).
- Pre-commit hook (decision is CI-only).
- Splitting files purely to hit the soft cap — only the hard cap is mandatory.
