#!/usr/bin/env python3
"""
tools/analyze-tests.py — Unified test quality and coverage analysis.

Scans all test surfaces (pytest suite, ms-test.py, live API) and produces
a prioritized list of what is and isn't tested. Designed to be run after
every significant code change to catch gaps before they reach production.

Usage:
    python3 tools/analyze-tests.py              # full report to terminal
    python3 tools/analyze-tests.py --report     # save TEST_ANALYSIS.md
    python3 tools/analyze-tests.py --new-tests  # generate test templates
    python3 tools/analyze-tests.py --contracts  # contract gap analysis only
"""

import ast
import json
import os
import pathlib
import re
import sys
from collections import defaultdict
from typing import Any

REPO = pathlib.Path(__file__).parent.parent
TESTS_DIR = REPO / "tests"
BACKEND_DIR = REPO / "backend"
FRONTEND = REPO / "frontend" / "src"

GREEN  = "\033[32m" if sys.stdout.isatty() else ""
RED    = "\033[31m" if sys.stdout.isatty() else ""
YELLOW = "\033[33m" if sys.stdout.isatty() else ""
BOLD   = "\033[1m"  if sys.stdout.isatty() else ""
RESET  = "\033[0m"  if sys.stdout.isatty() else ""


# ── Source extraction ─────────────────────────────────────────────────────────

def _read(p: pathlib.Path) -> str:
    try: return p.read_text(errors="replace")
    except: return ""


def extract_wizard_input_fields() -> dict[str, int]:
    """Parse WizardInput dataclass fields and count usages in steps."""
    src = _read(REPO / "backend" / "platform" / "wizard.py")
    m = re.search(r'class WizardInput:(.*?)(?=\n# ---|\ndef )', src, re.DOTALL)
    if not m:
        return {}
    fields = re.findall(r'^\s{4}(\w+)\s*:', m.group(1), re.MULTILINE)
    steps_src = src[src.find("def step_"):]
    return {f: len(re.findall(rf'\binp\.{f}\b', steps_src)) for f in fields}


def extract_frontend_options(vue_file: pathlib.Path) -> dict[str, list[str]]:
    """Extract all selectable option values from a Vue form."""
    src = _read(vue_file)
    options: dict[str, list[str]] = defaultdict(list)

    # infra slot options: { value: 'xxx' }
    for slot_block in re.finditer(
        r"slot:\s*['\"](\w+)['\"].*?options:\s*\[(.*?)\]", src, re.DOTALL
    ):
        slot = slot_block.group(1)
        vals = re.findall(r"value:\s*['\"]([^'\"]+)['\"]", slot_block.group(2))
        options[slot] = [v for v in vals if v != "none"]

    # DNS providers
    for k in re.findall(r"^\s{2}(\w+):\s*\{.*?vars:", src, re.MULTILINE):
        options["dns_provider"].append(k)

    # Cert resolvers
    for v in re.findall(r"<option value=\"([^\"]+)\">", src):
        if v not in ("letsencrypt", "zerossl", "buypass", "staging", "ollama", "groq"):
            options["cert_resolver_other"].append(v)

    return dict(options)


def extract_api_routes() -> list[tuple[str, str]]:
    """All (method, path) pairs from backend routers."""
    routes = []
    for f in (BACKEND_DIR / "api").glob("*.py"):
        for m in re.finditer(r'@router\.(get|post|put|delete|patch)\(["\']([^"\']+)["\']', _read(f)):
            routes.append((m.group(1).upper(), f"/api{m.group(2)}"))
    return sorted(routes)


def extract_wizard_steps() -> list[str]:
    """Return active wizard step names. Uses line-by-line parsing to avoid
    false positives from step function name appearing in STEPS tuples."""
    src = _read(REPO / "backend" / "platform" / "wizard.py")
    m = re.search(r"STEPS = \[(.*?)\]", src, re.DOTALL)
    if not m:
        return []
    steps = []
    for line in m.group(1).splitlines():
        match = re.search(r'"(\w+)"', line)
        if match:
            steps.append(match.group(1))
    return steps  # every other match is step name


def extract_infra_providers() -> dict[str, list[str]]:
    """Map slot → [provider_keys] from infra registry."""
    src = _read(REPO / "backend" / "infra" / "registry.py")
    providers: dict[str, list[str]] = defaultdict(list)
    for m in re.finditer(r'_REGISTRY\[\(["\']([\w]+)["\'],\s*["\']([\w]+)["\']\)\]', src):
        providers[m.group(1)].append(m.group(2))
    return dict(providers)


def load_all_tests() -> list[dict]:
    """Load all pytest test functions with quality signals."""
    records = []
    for f in sorted(TESTS_DIR.glob("test_*.py")):
        src = _read(f)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not (isinstance(fn, ast.FunctionDef) and fn.name.startswith("test_")):
                continue
            fn_src = ast.get_source_segment(src, fn) or ""
            records.append({
                "file": f.name,
                "name": fn.name,
                "src": fn_src,
                "has_assert": bool(re.search(r'\bassert\b|pytest\.raises', fn_src)),
                "uses_mock": bool(re.search(r'\bpatch\b|\bMagicMock\b', fn_src)),
                "lines": len(fn_src.splitlines()),
            })
    return records


# ── Contract analysis ─────────────────────────────────────────────────────────

def analyze_wizard_contracts() -> list[dict]:
    """
    The key analysis: for every selectable option in the frontend wizard,
    verify it has a corresponding deploy/action path in the backend.
    This is what catches the Stage 3 infra gap.
    """
    issues = []
    wizard_src = _read(REPO / "backend" / "platform" / "wizard.py")
    steps_src = wizard_src[wizard_src.find("def step_"):]

    # 1. WizardInput fields that are never read by any step
    fields = extract_wizard_input_fields()
    for field, count in fields.items():
        if count == 0:
            issues.append({
                "severity": "CRITICAL",
                "category": "dead_field",
                "description": f"WizardInput.{field} sent by frontend but never read by any wizard step",
                "fix": f"Add inp.{field} usage to an appropriate wizard step",
            })

    # 2. Frontend infra options — checked by test_wizard_contracts.py::TestInfraSlotContracts
    #    Run: pytest tests/test_wizard_contracts.py -v for detailed provider coverage

    # 3. Wizard steps that exist but aren't in STEPS list
    defined_steps = re.findall(r'^def step_(\w+)\(', wizard_src, re.MULTILINE)
    active_steps = extract_wizard_steps()
    orphan_steps = [s for s in defined_steps if s not in active_steps and s != ""]
    for s in orphan_steps:
        issues.append({
            "severity": "MEDIUM",
            "category": "orphan_step",
            "description": f"step_{s}() is defined but not in STEPS list — never runs",
            "fix": f"Add ('{s}', step_{s}) to STEPS in the correct position",
        })

    # 4. Frontend form fields sent in payload but missing from WizardInput
    setup_src = _read(FRONTEND / "views" / "SetupView.vue")
    payload_match = re.search(r'body: JSON\.stringify\(payload\)', setup_src)
    payload_def = re.search(r'const payload = \{(.*?)\}', setup_src, re.DOTALL)
    if payload_def:
        sent_fields = re.findall(r'^\s+(\w+):', payload_def.group(1), re.MULTILINE)
        wi_fields = set(fields.keys())
        for sf in sent_fields:
            if sf not in wi_fields and sf not in ("eab_kid", "eab_hmac", "selected_stacks",
                                                    "infra_selections", "ntfy_url", "ntfy_topic",
                                                    "ntfy_enabled"):
                issues.append({
                    "severity": "HIGH",
                    "category": "missing_field",
                    "description": f"Frontend sends '{sf}' but WizardInput has no such field",
                    "fix": f"Add {sf} field to WizardInput dataclass",
                })

    return issues


def analyze_api_coverage(tests: list[dict]) -> list[dict]:
    """Routes that exist in backend but have no test coverage."""
    all_test_src = "\n".join(t["src"] for t in tests)
    ms_src = _read(REPO / "ms-test.py")
    all_coverage_src = all_test_src + "\n" + ms_src

    uncovered = []
    for method, path in extract_api_routes():
        # Strip path params and check if route is mentioned anywhere
        base = re.sub(r'\{[^}]+\}', '{id}', path)
        clean = base.replace("/api", "").replace("{id}", "")
        if clean not in all_coverage_src and base not in all_coverage_src:
            uncovered.append({
                "severity": "MEDIUM",
                "category": "uncovered_route",
                "description": f"{method} {path} — no test coverage",
                "fix": f"Add test for {method} {path}",
            })
    return uncovered


def analyze_flow_invariants() -> list[dict]:
    """
    Invariant checks: if X is selected, Y must exist/be-called.
    These are the only tests that catch integration gaps.
    """
    issues = []
    wizard_src = _read(REPO / "backend" / "platform" / "wizard.py")
    deploy_step = re.search(
        r'def step_deploy_infra\(.*?(?=\ndef step_)', wizard_src, re.DOTALL
    )
    deploy_src = deploy_step.group(0) if deploy_step else ""

    # Every non-none infra option should appear in deploy_infra
    frontend_opts = extract_frontend_options(FRONTEND / "views" / "SetupView.vue")
    for slot in ("auth", "tunnel", "vpn", "dashboard", "management"):
        for value in frontend_opts.get(slot, []):
            if value not in deploy_src:
                issues.append({
                    "severity": "CRITICAL",
                    "category": "no_deploy_action",
                    "description": f"'{value}' ({slot}) selected in wizard but not handled in step_deploy_infra",
                    "fix": f"Add _deploy('{slot}', '{value}', ...) call to step_deploy_infra",
                })
    return issues


# ── Report ────────────────────────────────────────────────────────────────────

def _sev_color(sev: str) -> str:
    return {
        "CRITICAL": RED + BOLD,
        "HIGH": RED,
        "MEDIUM": YELLOW,
        "LOW": "",
    }.get(sev, "")


def print_report(all_issues: list[dict], tests: list[dict]) -> None:
    print(f"\n{BOLD}{'═'*70}{RESET}")
    print(f"{BOLD}MEDIASTACK UNIFIED TEST COVERAGE REPORT{RESET}")
    print(f"{'═'*70}")

    # Summary counts
    by_sev: dict[str, list] = defaultdict(list)
    for issue in all_issues:
        by_sev[issue["severity"]].append(issue)

    no_assert = [t for t in tests if not t["has_assert"]]
    mocked    = [t for t in tests if t["uses_mock"]]

    print(f"\n  Pytest tests:          {len(tests):>4}  ({len(no_assert)} no-assert, {len(mocked)} mocked)")
    print(f"  Critical issues:       {len(by_sev['CRITICAL']):>4}  {RED}← fix before next deploy{RESET}")
    print(f"  High issues:           {len(by_sev['HIGH']):>4}")
    print(f"  Medium issues:         {len(by_sev['MEDIUM']):>4}")

    for sev in ("CRITICAL", "HIGH", "MEDIUM"):
        group = by_sev[sev]
        if not group:
            continue
        print(f"\n{_sev_color(sev)}── {sev} ({len(group)}){RESET}")
        by_cat: dict[str, list] = defaultdict(list)
        for i in group:
            by_cat[i["category"]].append(i)
        for cat, items in by_cat.items():
            print(f"\n  {BOLD}{cat.replace('_',' ').title()}{RESET}")
            for item in items[:8]:
                print(f"    • {item['description']}")
                print(f"      Fix: {YELLOW}{item['fix']}{RESET}")
            if len(items) > 8:
                print(f"    ... and {len(items)-8} more")


def save_report(all_issues: list[dict], tests: list[dict]) -> None:
    lines = [
        "# Mediastack Unified Test Coverage Report",
        "",
        f"| Metric | Count |",
        f"|---|---|",
        f"| Pytest tests | {len(tests)} |",
        f"| Tests with no assertions | {sum(1 for t in tests if not t['has_assert'])} |",
        f"| Tests using mocks | {sum(1 for t in tests if t['uses_mock'])} |",
        f"| Critical issues | {sum(1 for i in all_issues if i['severity']=='CRITICAL')} |",
        f"| High issues | {sum(1 for i in all_issues if i['severity']=='HIGH')} |",
        "",
        "## Issues by Category",
        "",
    ]
    by_cat: dict[str, list] = defaultdict(list)
    for i in all_issues:
        by_cat[f"{i['severity']}:{i['category']}"].append(i)
    for key in sorted(by_cat):
        sev, cat = key.split(":", 1)
        lines.append(f"### {sev}: {cat.replace('_',' ').title()}")
        for item in by_cat[key]:
            lines.append(f"- **{item['description']}**")
            lines.append(f"  - Fix: `{item['fix']}`")
        lines.append("")
    out = REPO / "TEST_ANALYSIS.md"
    out.write_text("\n".join(lines))
    print(f"\n{GREEN}✓{RESET} Report saved: {out}")


def generate_new_tests(all_issues: list[dict]) -> None:
    """Generate test stubs for all identified gaps."""
    stubs = ['"""auto-generated test stubs from analyze-tests.py"""\n']
    stubs.append("import pytest\nfrom pathlib import Path\n")

    for i, issue in enumerate(all_issues[:20]):
        name = re.sub(r'[^\w]', '_', issue['description'].lower())[:60]
        stubs.append(f"""
def test_{name}_{i}():
    \"\"\"
    {issue['severity']}: {issue['description']}
    Fix: {issue['fix']}
    \"\"\"
    # TODO: implement
    raise NotImplementedError("Gap: {issue['description'][:60]}")
""")

    out = REPO / "tests" / "test_generated_gaps.py"
    out.write_text("\n".join(stubs))
    print(f"\n{GREEN}✓{RESET} Test stubs: {out} ({len(all_issues)} gaps)")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--report",    action="store_true")
    p.add_argument("--new-tests", action="store_true")
    p.add_argument("--contracts", action="store_true")
    args = p.parse_args()

    print("Analyzing...", end=" ", flush=True)
    tests = load_all_tests()
    contract_issues = analyze_wizard_contracts()
    invariant_issues = analyze_flow_invariants()
    api_issues = analyze_api_coverage(tests) if not args.contracts else []
    all_issues = contract_issues + invariant_issues + api_issues
    print(f"done. {len(all_issues)} issues found.")

    if args.contracts:
        # Just show contract/invariant issues
        critical = [i for i in all_issues if i["severity"] == "CRITICAL"]
        for i in critical:
            print(f"  {RED}CRITICAL{RESET}: {i['description']}")
        return

    print_report(all_issues, tests)
    if args.report:
        save_report(all_issues, tests)
    if args.new_tests:
        generate_new_tests(all_issues)


if __name__ == "__main__":
    main()
