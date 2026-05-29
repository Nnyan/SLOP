# ADR 0019 — Test-Data Isolation Policy

**Status:** Accepted 2026-05-29 (S-71-A)
**Decided by:** Robot batch-8 Stream A (S-71-TEST-DATA-HYGIENE)
**Supersedes:** none
**See also:** [ADR 0002 — Mocking Policy](0002-mocking-policy.md), Core Rule 4.12 (Mocking Discipline)
**Review by:** 2027-05-29

## Context

Batch-6 demonstrated the test-data-pollution failure class three times in rapid succession:

1. `robot_settings.py` verification wrote to the real `.claude/settings.local.json` (fixed `77fb678`
   by threading `target_paths["settings_local"]`).
2. `robot_settings.py` verification appended 9 real entries to `docs/SANCTIONED-OPS-LOG.md`
   (hand-stripped in `1435529`).
3. The `pkg-once` idempotency test ran a real `uv install` against the live package index
   (mocked in `1435529`).

All three share the same root cause: a test or verification path reached outside its fixture
sandbox and mutated committed, shared, or real-system state. Each failure required manual
intervention to undo. Without a written policy and a mechanical backstop, the same class
re-emerges whenever new tests are authored or existing verification paths are extended.

This ADR establishes the canonical, citable rule set. It is the test-data-isolation sibling of
ADR 0002 (Mocking Policy), which governs *what* to mock; this ADR governs *where* test output
may land. The two together fully characterise the safe test-authoring envelope.

## Decision

### Rule 1 — Fixtures write only under `tmp_path` (or `tmp_path_factory`)

Any file or directory a test creates must be rooted at a pytest `tmp_path` (or
`tmp_path_factory`-allocated directory). No test fixture may create files relative to the
repository root, relative to the working directory, or in any system directory.

Correct pattern:
```python
def test_writes_config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"key": "value"}')
    assert cfg.read_text() == '{"key": "value"}'
```

### Rule 2 — Protected real paths are read-only (or off-limits) during tests

No test may read or write:

- `.claude/settings.local.json` — personal/machine config; written by sanctioned tools only
- `docs/*` — any file under the `docs/` tree, including `docs/SANCTIONED-OPS-LOG.md`
- `requirements*.txt` — dependency manifests
- Real config/data dirs (`/var/lib/mediastack/`, `/srv/mediastack/config`, `/opt/mediastack/`)

Reading a *fixture data file* that lives under `tests/` or `catalog/` (e.g. a test manifest
YAML) is permitted — these are test assets checked into the repo for that purpose.

### Rule 3 — Install / package operations are mocked at the subprocess boundary

Any test that exercises code paths triggering `uv`, `pip`, `docker`, `apt`, `systemctl`, or
similar package/system operations must mock at the `subprocess` boundary — not at the project
boundary. See [ADR 0002 — Mocking Policy](0002-mocking-policy.md) for the boundary definition
and the canonical patching patterns.

No real network or package-index side effects are permitted during `pytest` runs.

### Rule 4 — Sanctioned tools redirect their audit log via `SLOP_AUDIT_LOG_PATH`

`tools/sanctioned/_audit.py::write_entry` accepts a `log_path` parameter (signature at
`_audit.py:135`, defaulting to `SANCTIONED_OPS_LOG = Path("docs/SANCTIONED-OPS-LOG.md")` at
`_audit.py:36`). Stream B (S-71-B) adds an environment-variable override: when
`SLOP_AUDIT_LOG_PATH` is set in the environment, `write_entry`'s effective default log path is
that value (an explicit `log_path=` argument still wins). Production callers with `SLOP_AUDIT_LOG_PATH`
unset see no behavior change.

**Convention for tests and verification paths:** set `SLOP_AUDIT_LOG_PATH` to a `tmp_path`
file (or pass `log_path=tmp_path/...` directly) so no test or verification run can touch the
committed `docs/SANCTIONED-OPS-LOG.md`. Example:

```python
def test_sanctioned_tool_audit(tmp_path, monkeypatch):
    log_file = tmp_path / "audit.md"
    monkeypatch.setenv("SLOP_AUDIT_LOG_PATH", str(log_file))
    # ... exercise write_entry ...
    assert log_file.exists()
    assert not Path("docs/SANCTIONED-OPS-LOG.md").read_text().endswith("test entry")
```

### Enforcement mechanism — `check_test_isolation` gate

The mechanical backstop is the `ms-enforce` warn-only gate `check_test_isolation`,
backed by `tools/check_test_isolation.py` (produced by S-71 Stream C). It mirrors the
`check_referenced_files` warn-only pattern: shells to the script, collects `WARNING`-prefixed
lines, and **always returns `True`** — it never blocks CI. Graduating the gate to blocking is
the later Enforcement-Lifecycle wave's job (batch-9, out of scope here).

The gate uses a conservative static heuristic over `tests/**`. It flags a test file when it
appears to write outside `tmp_path` or assert against real repo files — for example,
`open(...,"w")` / `.write_text(...)` on a path literal not derived from `tmp_path`, or
references to `docs/`, `.claude/settings.local.json`, or `requirements` as write or assert
targets.

**Known false-positive classes** (the gate does not flag these):

- **Reading a fixture data file** — `open("tests/fixtures/app.yaml")` or similar read-only
  access to committed test assets is not a violation of this policy.
- **Building a path string that is later joined under `tmp_path`** — constructing a string
  such as `base = "docs/SANCTIONED-OPS-LOG.md"` and then immediately using it as
  `tmp_path / base` is fine; the heuristic may warn on the literal alone. Suppress the warning
  with a `# test-isolation: ok` comment on the line, and note the reason.
- **Asserting that a real file is *unchanged*** — reading `docs/SANCTIONED-OPS-LOG.md` in a
  test to confirm it was NOT written to is a valid isolation check, not a violation. Document
  with a `# test-isolation: ok` comment.

### Exception clauses

- **Snapshot / golden-file tests** that write under a designated `tests/snapshots/` subdirectory
  are permitted — those files are committed test assets, not real operational state.
- **Integration tests explicitly marked `@pytest.mark.integration`** that require a live
  install environment may interact with real paths, but must restore any mutations (or be
  run in a disposable environment). These tests are excluded from the `check_test_isolation`
  gate by convention.

## Consequences

### Positive

- **Idempotent CI.** No test run can pollute committed files; re-runs on the same worktree
  produce identical outcomes.
- **Parallelism-safe.** Tests rooted at `tmp_path` are order-independent and safe to run
  with `pytest-xdist`.
- **Mechanical backstop.** The `check_test_isolation` gate surfaces new offenders at PR time
  (warn-only initially) without requiring authors to remember the policy.
- **Audit-log integrity.** `docs/SANCTIONED-OPS-LOG.md` reflects only real, human-authorised
  operations — never test side effects.

### Negative

- **Fixture boilerplate.** Tests that previously relied on real paths or autouse globals must
  be updated to accept a `tmp_path` argument and route writes there.
- **False positives from the gate.** The static heuristic will occasionally warn on benign
  patterns (see Known false-positive classes above). Suppress with `# test-isolation: ok`
  and a comment explaining why.
- **`SLOP_AUDIT_LOG_PATH` is an env-var contract.** CI harnesses and local dev scripts that
  run `ms-enforce` or sanctioned-tool verification need to set the variable (or leave it unset
  for production contexts). The risk of forgetting is low but non-zero.

### Neutral

- **Production audit behavior is unchanged.** `write_entry`'s real-log default for production
  CLI paths is unchanged; only test and verification paths redirect.
- **ADR 0002 (Mocking Policy) governs *what* to mock** — this ADR governs *where output lands*.
  The two policies compose; neither supersedes the other.
- **Graduating `check_test_isolation` to blocking** is explicitly out of scope here. Gate aging
  and escalation to CI-blocking is the Enforcement-Lifecycle wave (batch-9, S-70+S-72).

## Status

Accepted. Enforced via:

- **Process:** new tests follow this policy; reviewers cite this ADR when flagging real-path
  writes in code review.
- **Tooling:** `ms-enforce` warn-only `check_test_isolation` gate, backed by
  `tools/check_test_isolation.py`. Gate always returns `True`; surfaces warnings, never
  fails CI. Policy-doc referenced by the gate's docstring at
  `docs/adr/0019-test-data-isolation.md`.
- **Redirect convention:** `SLOP_AUDIT_LOG_PATH` environment variable (Stream B, S-71-B);
  set in all test and verification contexts that exercise `write_entry`.
- **Review trigger:** revisit when `check_test_isolation` is a candidate for CI-blocking
  promotion (expected batch-9), or when a new class of real-path write is discovered.
