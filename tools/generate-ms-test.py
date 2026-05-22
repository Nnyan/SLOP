#!/usr/bin/env python3
"""
generate-ms-test.py — Generate the Mediastack comprehensive test suite via AI.

Usage:
    python3 tools/generate-ms-test.py [--model opus|sonnet|haiku] [--output ms-test.py]

The script:
  1. Reads the live codebase to build a rich context document
  2. Sends a carefully engineered prompt to the Anthropic API
  3. Streams the generated test script to the output file
  4. Prints a summary of what was generated

Models:
    opus    — claude-opus-4-6     (deepest reasoning, best coverage, slower)
    sonnet  — claude-sonnet-4-6   (fast, still excellent, default)
    haiku   — claude-haiku-4-5-20251001 (quickest, less thorough)

Requires:
    ANTHROPIC_API_KEY environment variable
    pip install anthropic

Run from the repo root:
    python3 tools/generate-ms-test.py --model opus
"""

import argparse
import os
import pathlib
import subprocess
import sys
import textwrap

REPO = pathlib.Path(__file__).parent.parent
MODELS = {
    "opus":   "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
}


# ── Context builders ──────────────────────────────────────────────────────────

def _read(path: pathlib.Path, max_lines: int = 9999) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
        if len(lines) > max_lines:
            half = max_lines // 2
            lines = lines[:half] + [f"... [{len(lines)-max_lines} lines omitted] ..."] + lines[-half:]
        return "\n".join(lines)
    except Exception:
        return f"[could not read {path}]"


def _routes() -> str:
    """Extract all API routes from the backend."""
    out = []
    for f in sorted((REPO / "backend" / "api").glob("*.py")):
        try:
            prefix_map = {
                "apps.py": "/api/apps", "health.py": "/api/health",
                "infra.py": "/api/infra", "models.py": "/api/models",
                "platform.py": "/api/platform", "quickstart.py": "/api/quickstart",
                "registry.py": "/api/registry", "routing.py": "/api/routing",
                "settings.py": "/api/settings", "storage.py": "/api/storage",
                "catalog.py": "/api/catalog",
            }
            prefix = prefix_map.get(f.name, f"/api/{f.stem}")
            for line in f.read_text().splitlines():
                stripped = line.strip()
                for method in ("get", "post", "put", "delete", "patch"):
                    if stripped.startswith(f"@router.{method}("):
                        path = stripped.split('"')[1] if '"' in stripped else stripped.split("'")[1] if "'" in stripped else "?"
                        out.append(f"  {method.upper():7} {prefix}{path}")
        except Exception:
            pass
    return "\n".join(out)


def _schema() -> str:
    schema_file = REPO / "backend" / "core" / "schema.sql"
    return _read(schema_file)


def _known_bugs() -> str:
    """The actual bugs we found in production — tests must catch regressions."""
    return textwrap.dedent("""
    KNOWN PRODUCTION BUGS (all fixed — tests must prevent regression):

    1.  Health cycle returned "All apps healthy" when 0 apps were checked.
        Root cause: frontend discarded runCycle() response, counted errors
        in empty checks.value array (0 errors = "healthy"). Test must
        assert apps_checked > 0 when apps with status=running exist.

    2.  Stage 8 (app install) never ran after wizard deploy.
        Root cause: setTimeout auto-advanced to Stage 8 but bypassed
        nextStage() where installStacks() was called. Test must confirm
        apps are actually installed after a wizard run.

    3.  "Platform is configured" screen hijacked Stage 8.
        Root cause: platformStore.fetchStatus() set isReady=true BEFORE
        forceSetup=true, switching template to configured screen mid-wizard.
        Test must confirm wizard stays on stage 8 after fetchStatus.

    4.  ms-check: "ok: command not found" during orphan auto-remove.
        Root cause: function named `pass` not `ok`. &&/|| chain caused
        sqlite3 to delete record successfully, then ok failed, then ||
        showed "could not auto-remove" for a record that WAS removed.
        Test: verify pass/ok/warn/fail functions exist by name in ms-check.

    5.  Infra_selections Pydantic validation rejected tunnels=["a","b"].
        Root cause: dict[str, str] type; frontend sends list for tunnel.
        Fixed to dict[str, Any]. Test: POST /wizard/run with tunnels as
        list must not return 422.

    6.  Orphaned DB records persisted after failed installs.
        Root cause: install wrote DB record before compose fragment;
        on failure, fragment not created, record stayed. Test: failed
        install (fragment not created) must leave DB clean.

    7.  ms-update showed identical SHAs: OLD_COMMIT == NEW_COMMIT.
        Root cause: OLD_COMMIT captured AFTER silent self-update pull.
        Test: OLD_COMMIT line appears before any git pull line in script.

    8.  Wizard async job race: step_callback not in run_wizard signature.
        Fixed — but test must confirm /wizard/run-async creates a job_id
        and /wizard/status/{job_id} returns steps as they complete.

    9.  Health checks never ran because cycle filtered status="running"
        but newly installed apps had status="installed". Verify installed
        apps transition to "running" after compose up.

    10. Ghost compose fragments (yaml with no DB entry) accumulated silently.
        Test: install then delete DB record → ms-check must flag the orphan.
        Test: ms-update cleanup must remove the fragment.
    """).strip()


def _test_categories() -> str:
    return textwrap.dedent("""
    REQUIRED TEST CATEGORIES — cover ALL of these:

    A. INFRASTRUCTURE SANITY
       - DB file exists and is readable; WAL mode is enabled
       - All 34 tables from schema.sql exist with correct column names
       - compose/ directory exists and is writable
       - .env file exists (if platform configured)
       - Docker socket reachable (skip gracefully if not)
       - ms-check shell function names: pass, warn, fail, info, section
         (NOT ok, NOT error — those are undefined)

    B. API ROUTE SMOKE TESTS (every single route)
       - Every GET returns 200 or expected non-500 code
       - Every POST with empty/minimal body returns 400/422, not 500
       - Response Content-Type is application/json for all JSON routes
       - No route returns a Python traceback in body
       - Routes with {key} param: test with real key AND nonexistent key

    C. SCHEMA VALIDATION (every response)
       - Check that response JSON has required fields (not just 200 OK)
       - /api/health/apps returns list of {app_key, check_name, status, summary}
       - /api/platform/status returns {status, domain, ...}
       - /api/platform/prereqs returns {checks: [...], system: {...}}
       - /api/settings/system returns {os, cpu, ram, gpu, docker, ...}
       - /api/health/scheduler returns {running, last_cycle_ago?, apps_checked?}

    D. DATA FLOW INTEGRITY (write → read → confirm)
       - PUT /api/settings → GET /api/settings → values match
       - POST install app → GET /api/apps/{key} → status, host_port, image all set
       - POST health run → GET /api/health/apps → results exist, counts non-zero
       - POST /api/health/maintenance-windows → GET → window exists
       - POST /api/health/pending-fixes/{id}/approve → GET pending-fixes → removed
       - PUT /api/settings (health interval) → GET /api/health/scheduler → interval matches

    E. STATE MACHINE CORRECTNESS
       - Platform status: pending → (after wizard) → ready → (after reset) → pending
       - App status: installing → running (success) OR failed (failure)
       - Apps with status=failed must NOT appear in health cycle (status="running" filter)
       - Apps with no compose fragment must not be health-checked (pre-check gate)
       - Infra slot: empty → active (deploy) → empty (remove)

    F. SILENT FAILURE DETECTION — the most dangerous category
       - /api/health/run with 0 running apps: response.apps_checked must equal 0
         (NOT a success with count=0 being reported as "all healthy")
       - Install that writes DB record but fails before fragment: record must be absent
       - /wizard/run-async: response must have job_id; status poll must return steps
       - /api/platform/wizard/run with status=ready: must return 409, not 200
       - Orphan cleanup: DB record with no fragment → cleanup removes record, not just warns
       - Health counts: sum(ok+warning+error) must equal total apps checked

    G. FRONTEND ↔ BACKEND CONTRACT TESTS
       - POST /wizard/run with infra_selections.tunnels as LIST ["a","b"]: must NOT 422
       - POST /wizard/run with infra_selections.tunnels as STRING "a": must NOT 422
       - POST /wizard/run with tunnels=[] (empty): must work
       - GET /api/health/apps: every item has app_key (not just key)
       - GET /api/apps: items have display_name, status, category, host_port
       - Settings payload: ntfy_enabled as bool, disk_warn_percent as int, not string

    H. DEPENDENCY CHAIN TESTS
       - App with postgres dependency: managed postgres service must exist or install fails gracefully
       - App A depends on app B: installing A without B must warn or fail gracefully, not crash
       - Traefik must be running for health checks on web-exposed apps to pass
       - LLM diagnosis must run even if Ollama offline (falls back to cloud or returns graceful message)

    I. CLEANUP AND ORPHAN TESTS
       - ms-check ghost check: insert fake record in DB with no fragment → warns
       - ms-check auto-remove: same scenario when run as root → removes and reports
       - ms-update cleanup: orphan record removed on next update
       - Startup cleanup: orphan record removed when app restarts
       - health_check_history prune: more than 500 rows per app+check triggers prune

    J. SHELL SCRIPT INTEGRITY (ms-check, ms-update)
       - All bash functions referenced are defined (grep for usages and definitions)
       - OLD_COMMIT captured before git pull lines in ms-update
       - ms-check exits 0 on all-pass, 1 on warnings-only, 2 on errors
       - All section() calls have corresponding content
       - All sqlite3 calls reference the correct $DB_PATH variable

    K. END-TO-END FLOWS (requires real instance or fixtures)
       - Flow 1: Create platform config → run prereqs → get system profile pre-populated
       - Flow 2: Run health cycle → get results → approve a fix → fix applied
       - Flow 3: Install app → health check runs → compose fragment exists → DB record matches
       - Flow 4: Reset platform → status=pending → re-run → status=ready
       - Flow 5: Orphan scenario → cleanup → no orphan remains

    L. PERFORMANCE / REGRESSION GUARDS
       - /api/health/run completes within 120 seconds for 20 apps
       - /api/platform/prereqs completes within 10 seconds
       - DB has no unbounded tables (health_check_history capped)
       - No sqlite3 table exceeds 10,000 rows unless explicitly expected
    """).strip()


def build_prompt(repo: pathlib.Path) -> str:
    arch = _read(repo / "ARCHITECTURE.md", max_lines=200)
    schema = _schema()
    routes = _routes()
    bugs = _known_bugs()
    categories = _test_categories()

    # Sample a few key source files for structure context
    checker_head = _read(repo / "backend" / "health" / "checker.py", max_lines=80)
    executor_head = _read(repo / "backend" / "manifests" / "executor.py", max_lines=60)
    state_head   = _read(repo / "backend" / "core" / "state.py", max_lines=80)

    prompt = f"""You are a principal engineer tasked with writing the most comprehensive
automated test suite possible for Mediastack v4 — a homelab media stack manager.

Your output is a single executable Python file: ms-test.py

=== SYSTEM OVERVIEW ===
{arch}

=== COMPLETE DATABASE SCHEMA ===
{schema}

=== ALL API ROUTES (130+) ===
{routes}

=== KNOWN PRODUCTION BUGS (must not regress) ===
{bugs}

=== REQUIRED TEST CATEGORIES (cover ALL of these) ===
{categories}

=== KEY SOURCE FILE EXCERPTS ===

backend/health/checker.py (first 80 lines):
{checker_head}

backend/manifests/executor.py (first 60 lines):
{executor_head}

backend/core/state.py (first 80 lines):
{state_head}

=== WHAT ALREADY EXISTS ===
The repo has 799 pytest unit tests across 20 files (9,342 lines total).
They test individual functions in isolation, mostly with mocks.
They do NOT test:
  - Cross-layer data flow integrity (write→DB→read→response)
  - Shell script function naming correctness
  - Frontend type contracts matching backend expectations
  - Silent failure modes (operations that "succeed" but do nothing)
  - Real end-to-end flows without mocks

ms-test.py must be COMPLEMENTARY — it tests what pytest cannot.

=== REQUIREMENTS FOR ms-test.py ===

1.  SINGLE FILE — one Python script, no dependencies beyond stdlib + requests
    (optionally uses `sqlite3`, `subprocess`, `json`, `pathlib`, `typing`)

2.  CONFIGURABLE — reads BASE_URL from env (default http://localhost:8000),
    reads API_KEY from env if needed, accepts --section filter arg

3.  STRUCTURED OUTPUT:
    - Prints: [PASS] [FAIL] [SKIP] [WARN] prefix for every test
    - Groups tests into sections matching the categories above
    - Summary at end: total PASS/FAIL/SKIP counts per section
    - Exit code 0 if all pass, 1 if any fail, 2 if critical failures
    - Optional --json flag for machine-readable output

4.  PROGRESSIVE — tests that depend on earlier ones use results:
    if /api/platform/status returns pending, skip wizard-dependent tests

5.  SAFE — never deletes real data, never installs apps on a live system
    unless --destructive flag passed; uses dry-run checks where possible

6.  COVERAGE TRACKING — at the end, list which API routes were tested,
    which DB tables were touched, which flows were verified

7.  SKIP GRACEFULLY — if Docker is not available, skip Docker tests.
    If Traefik is not running, skip Traefik tests. Print reason.

8.  SILENT FAILURE TESTS are MANDATORY — these are the highest-priority:
    Every test that checks for "0 when should be non-zero" or "success
    message when operation did nothing" must be present.

9.  SHELL SCRIPT TESTS — read ms-check and ms-update as text files,
    grep for function calls vs definitions, verify OLD_COMMIT position,
    check for undefined function names.

10. DATA ROUND-TRIPS — for every settable resource, write a value,
    read it back, assert they match. This catches silent drops.

Write the complete ms-test.py now. It should be at minimum 800 lines,
cover all 12 categories, and include clear comments explaining WHY each
test exists and what failure mode it catches.

Begin immediately with the file content. Do not add preamble."""

    return prompt


def generate(model_key: str, output: pathlib.Path) -> None:
    try:
        import anthropic
    except ImportError:
        print("ERROR: `anthropic` not installed. Run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    model = MODELS[model_key]
    print(f"  Model:  {model}")
    print(f"  Output: {output}")
    print(f"  Building context from repo... ", end="", flush=True)

    prompt = build_prompt(REPO)
    print(f"done ({len(prompt):,} chars)")
    print(f"  Sending to API (streaming)...\n")

    client = anthropic.Anthropic(api_key=api_key)

    output.parent.mkdir(parents=True, exist_ok=True)
    total_tokens = 0

    with output.open("w") as f:
        with client.messages.stream(
            model=model,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
            system=(
                "You are a principal engineer writing a comprehensive automated test suite. "
                "Output ONLY the Python source code. No markdown, no explanation, no fences. "
                "Start directly with the shebang line or a module docstring."
            ),
        ) as stream:
            chars = 0
            for text in stream.text_stream:
                f.write(text)
                f.flush()
                chars += len(text)
                if chars % 2000 < len(text):
                    print(f"  ... {chars:,} chars written", end="\r")

        usage = stream.get_final_message().usage
        total_tokens = usage.input_tokens + usage.output_tokens
        print(f"\n  Complete: {chars:,} chars, {total_tokens:,} tokens")

    # Quick sanity check
    content = output.read_text()
    test_count = content.count("[PASS]") + content.count("[FAIL]") + content.count("def test_")
    section_count = content.count("SECTION") + content.count("# ──")
    print(f"\n  Generated: ~{len(content.splitlines())} lines")
    print(f"  Contains:  {content.count('def test_')} test functions")
    print(f"  Sections:  ~{section_count} section markers")
    print(f"\n  Run with:  python3 {output.name}")
    print(f"  Or:        python3 {output.name} --section D  (just data flow tests)")


def main() -> None:
    p = argparse.ArgumentParser(description="Generate Mediastack comprehensive test suite via AI")
    p.add_argument("--model", choices=list(MODELS), default="sonnet",
                   help="Model to use (default: sonnet)")
    p.add_argument("--output", type=pathlib.Path, default=REPO / "ms-test.py",
                   help="Output file path (default: ms-test.py in repo root)")
    args = p.parse_args()

    print(f"\nMediastack Test Generator")
    print(f"{'─' * 40}")
    generate(args.model, args.output)


if __name__ == "__main__":
    main()
