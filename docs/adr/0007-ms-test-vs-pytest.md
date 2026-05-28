# ADR 0007 — `ms-test.py` (custom integration runner) Alongside pytest

**Status:** Accepted (backfilled 2026-05-08; the implicit decision dates from the v3 build, ~2024)
**Decided by:** OPUS during cleanup step 2.5.b (backfill)
**Supersedes:** none
**See also:** `ms-test.py`, `tests/`, Core Rule 2.5 (Behavioural Coverage) — enforced by ms-enforce, [`docs/adr/0002-mocking-policy.md`](0002-mocking-policy.md)

---

## Context

Mediastack tests at three levels:

1. **Unit tests** — pure-Python, no I/O, fast. Live in `tests/test_*.py` and run under pytest.
2. **Integration tests** — real SQLite, real `tmp_path` filesystem, real `httpx.TestClient` against the FastAPI app. Also live under `tests/test_*.py` per ADR 0002 (real fakes).
3. **Cross-layer flow tests** — exercise scenarios that touch shell scripts, the running API server, the catalog YAML, the operator-facing CLI tools, the OS environment. These are what `ms-test.py` runs.

The level 3 surface is real: every cleanup pass surfaces a bug that no unit or integration test could have caught because the bug lived in the seam between layers (e.g. `ms-update` invokes systemctl which restarts the API server which reads `.env` which is consumed by a Pydantic validator). pytest CAN technically run these scenarios — but the ergonomics are wrong:

- pytest tests run in-process. Spawning a subprocess to invoke `ms-update` and asserting on the side effects is awkward inside a pytest fixture.
- pytest's collection / scoping model is built around test functions, not "phase 1: setup an environment, phase 2: run a 30-step scenario, phase 3: tear down". The phase-2 step IS the test.
- pytest output (`.`s and dots) is not the right shape for a 30-minute integration scenario where each step has its own check + report.

`ms-test.py` is a Python script that runs a curated set of cross-layer scenarios with rich output (`✓ Phase A.1 — wizard reaches step 4 in 12.3s`). It supplements pytest, it doesn't replace it.

## Decision

Mediastack maintains BOTH test runners, with a clear division of labour:

| Runner | Scope | Invocation | When to add a test |
|---|---|---|---|
| **pytest** (`tests/`) | Unit + integration | `python -m pytest` (CI; pre-commit hook via ms-enforce) | When the test fits in a single Python function with fixtures. Most tests live here. |
| **`ms-test.py`** | Cross-layer flows | `python3 ms-test.py [--section X]` (manual; release rehearsal) | When the test invokes a CLI tool, talks to a running server over HTTP, or asserts on filesystem effects produced by a multi-step shell pipeline. |

`ms-test.py` is sectioned (A through Z+) by behavioural area:

- **A** — wizard end-to-end (run the wizard, expect platform reaches `ready`).
- **B** — install lifecycle (install sonarr, observe DB + filesystem + container).
- **C** — manifest catalog integrity.
- **D** — data flow contracts (settings written by component X are read by component Y).
- **E** — frontend-backend contracts (Vue calls hit registered endpoints).
- ... etc., growing as bugs surface that need a cross-layer regression test.

Each section is independently runnable (`--section B`). Failures emit machine-readable JSON when `--json` is set so a release-gate script can parse them.

`ms-test.py` is NOT run by ms-enforce (heavy; would block the pre-commit pipeline). It runs:
- Manually before a release tag (`./ms-test.py` on the release candidate).
- As part of `ms-update --tests` (the operator's "update + run all tests" mode).
- In CI as a separate, slower pipeline that doesn't gate merges (informational only).

## Consequences

### Positive

- **Cross-layer bugs get a test home.** Without `ms-test.py`, real bugs that span layers stay unwritten because they don't fit a pytest function shape.
- **Section-by-section iteration.** Sections are added when a bug class is discovered; they accumulate as institutional memory. The `# Bug found YYYY-MM-DD: ...` comment near each section is a postmortem record.
- **Operator-facing.** `python3 ms-test.py` produces output an operator can read: section headers, per-test pass/fail with timing, summary at the end. pytest output is for developers.
- **Doesn't bloat the pytest run.** Fast pytest (under 2 minutes) stays a tight pre-commit loop. `ms-test.py` (5–30 minutes depending on sections) runs out-of-band.

### Negative

- **Two test surfaces to maintain.** A bug fix may require updating BOTH a pytest unit test AND an `ms-test.py` cross-layer scenario. The discipline is "fix the unit test surface; only touch ms-test.py if the cross-layer behaviour itself changed".
- **Custom runner = custom maintenance.** `ms-test.py` has its own assertion helpers, output formatting, JSON serialisation. pytest brings all of that for free. Each year of `ms-test.py` evolution is a year of someone re-implementing what pytest already does.
- **Two `--help` surfaces** for new contributors to learn. (Step 2.8.c locked the `ms-test.py --help` snapshot to make the surface visible at code-review time.)

### Neutral

- **Coverage is split.** `ms-coverage` (the rule-coverage scanner) sees pytest tests for unit/integration coverage and `ms-test.py` sections for cross-layer coverage. Both feed the same coverage map (`data/coverage_map.json`).
- **`ms-test.py --self-improve` exists** — uses an LLM to generate new sections from observed failures. Currently low-priority feature; sections are mostly written by hand from postmortem evidence.

## Status

Accepted (backfilled). Documents a decision implicit in the v3/v4 build; ratified explicitly during cleanup step 2.5.b on 2026-05-08. No supersession in flight.
