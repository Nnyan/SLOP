#!/usr/bin/env python3
"""tools/gen_dep_map.py — Regenerate ARCHITECTURE.md from source code.

Usage:
    python3 tools/gen_dep_map.py
    python3 tools/gen_dep_map.py --output docs/ARCHITECTURE.md

Scans backend Python and frontend Vue/TS files to produce:
- DB table read/write map per module
- API endpoint → module map
- Frontend view → API call map
- Inter-module import graph

Semantic annotations (critical contracts, key flows) are read from
tools/arch_annotations.json and merged into the output. Edit that file
to add new contracts without re-running the full scan.
"""
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend/src"
ANNOTATIONS_FILE = Path(__file__).parent / "arch_annotations.json"

TABLE_RE = re.compile(
    r'(?:FROM|JOIN|INTO|UPDATE|DELETE FROM|CREATE TABLE IF NOT EXISTS)\s+([a-z_]+)',
    re.IGNORECASE,
)
ROUTE_RE = re.compile(r'@router\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']')
API_CALL_RE = re.compile(r"fetch\(['\"`]/api/([^'\"` \)]+)", re.MULTILINE)
IMPORT_RE = re.compile(r'from\s+(backend\.[a-z_.]+)\s+import')
SKIP_WORDS = {
    'not','null','true','false','exists','none','case','when','then','else',
    'end','and','or','as','on','by','in','to','if','is','do','all','any',
    'set','key','row','id','ts','app','col','val','new','old','max','min',
    'sum','avg','count','limit','offset','where','group','order','having',
}


def scan_backend():
    table_ops = defaultdict(lambda: defaultdict(set))
    api_routes = {}
    imports_map = defaultdict(set)

    for py in sorted(BACKEND.rglob("*.py")):
        if "__pycache__" in str(py):
            continue
        try:
            src = py.read_text(errors="replace")
        except Exception:
            continue
        rel = str(py.relative_to(ROOT))

        for line in src.splitlines():
            m = TABLE_RE.search(line)
            if m:
                tbl = m.group(1).lower()
                if len(tbl) >= 4 and tbl not in SKIP_WORDS:
                    upper = line.upper().strip()
                    if any(upper.startswith(w) for w in ('SELECT','FROM','WHERE','JOIN','WITH','LEFT','INNER')):
                        table_ops[rel][tbl].add('read')
                    if any(upper.startswith(w) for w in ('INSERT','UPDATE','DELETE','REPLACE','CREATE')):
                        table_ops[rel][tbl].add('write')

        for m in ROUTE_RE.finditer(src):
            api_routes[f"{m.group(1).upper()} {m.group(2)}"] = rel

        for m in IMPORT_RE.finditer(src):
            imports_map[rel].add(m.group(1))

    return table_ops, api_routes, imports_map


def scan_frontend():
    vue_api_calls = defaultdict(set)
    for f in list(FRONTEND.rglob("*.vue")) + list(FRONTEND.rglob("*.ts")):
        if "node_modules" in str(f):
            continue
        try:
            src = f.read_text(errors="replace")
        except Exception:
            continue
        rel = str(f.relative_to(ROOT))
        for m in API_CALL_RE.finditer(src):
            endpoint = m.group(1).rstrip("'\"` ,)")
            vue_api_calls[rel].add("/api/" + endpoint)
    return vue_api_calls


def load_annotations():
    if ANNOTATIONS_FILE.exists():
        return json.loads(ANNOTATIONS_FILE.read_text())
    return {"contracts": [], "change_impacts": [], "key_flows": []}


def generate(output: Path):
    print("Scanning backend Python files…")
    table_ops, api_routes, imports_map = scan_backend()
    print("Scanning frontend Vue/TS files…")
    vue_api_calls = scan_frontend()
    print("Loading annotations…")
    annotations = load_annotations()

    # Build reverse maps
    table_readers = defaultdict(list)
    table_writers = defaultdict(list)
    for mod, tables in table_ops.items():
        for tbl, ops in tables.items():
            if 'read' in ops:
                table_readers[tbl].append(mod.split('/')[-1])
            if 'write' in ops:
                table_writers[tbl].append(mod.split('/')[-1])

    module_to_routes = defaultdict(list)
    for route, mod in api_routes.items():
        module_to_routes[mod].append(route)

    lines = []
    lines.append("# Mediastack — Architecture & Dependency Map")
    lines.append("")
    lines.append(f"> Auto-generated {date.today().isoformat()} · "
                 f"{len(api_routes)} routes · "
                 f"{len(set(t for tv in table_ops.values() for t in tv))} DB tables")
    lines.append("> Run `python3 tools/gen_dep_map.py` to regenerate.")
    lines.append("")
    lines.append("## Contents")
    lines.append("1. [Layer Overview](#layer-overview)")
    lines.append("2. [Critical Contracts](#critical-contracts)")
    lines.append("3. [Database Tables](#database-tables)")
    lines.append("4. [API Endpoints by Module](#api-endpoints-by-module)")
    lines.append("5. [Frontend → API Calls](#frontend--api-calls)")
    lines.append("6. [Change Impact Lookup](#change-impact-lookup)")
    lines.append("7. [Key Flows](#key-flows)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Layer Overview")
    lines.append("")
    lines.append("```")
    lines.append("Frontend (Vue 3)          10 views, Tailwind, Pinia store")
    lines.append("     ↕ HTTP/JSON")
    lines.append("Backend  (FastAPI)        126 endpoints, Python 3.12")
    lines.append("  ├─ api/                 HTTP routers — one file per domain")
    lines.append("  ├─ core/                state.py, config.py, docker_client.py")
    lines.append("  ├─ health/              checker, scheduler, context_assembler")
    lines.append("  ├─ manifests/           loader (55 YAML), executor")
    lines.append("  ├─ infra/               providers for 5 infra slot types")
    lines.append("  └─ platform/            wizard, storage")
    lines.append("     ↕ SQLite WAL / filesystem")
    lines.append("Data     (Host filesystem)")
    lines.append("  ├─ state.db             SQLite — app registry, health, ops")
    lines.append("  ├─ data/compose/*.yaml  One per installed app — read by Docker daemon")
    lines.append("  ├─ .env                 Secrets — must be 600 permissions")
    lines.append("  └─ config/<app>/        App config dirs")
    lines.append("     ↕ docker.sock")
    lines.append("Docker   (Host daemon)    Manages all app containers")
    lines.append("```")
    lines.append("")

    # Critical contracts from annotations
    lines.append("---")
    lines.append("")
    lines.append("## Critical Contracts")
    lines.append("")
    lines.append("Violating any of these causes **silent** failures.")
    lines.append("")
    for c in annotations.get("contracts", []):
        lines.append(f"### {c['title']}")
        lines.append("")
        lines.append(c['detail'])
        lines.append("")
        if c.get('affected'):
            lines.append("**Affected:** " + ", ".join(f"`{m}`" for m in c['affected']))
            lines.append("")

    # DB tables
    lines.append("---")
    lines.append("")
    lines.append("## Database Tables")
    lines.append("")
    all_tables = sorted(set(list(table_readers) + list(table_writers)))
    for tbl in all_tables:
        readers = sorted(set(table_readers.get(tbl, [])))
        writers = sorted(set(table_writers.get(tbl, [])))
        if not readers and not writers:
            continue
        lines.append(f"### `{tbl}`")
        if writers:
            lines.append(f"**Writes:** {', '.join(f'`{w}`' for w in writers)}")
        if readers:
            lines.append(f"**Reads:** {', '.join(f'`{r}`' for r in readers)}")
        lines.append("")

    # API endpoints
    lines.append("---")
    lines.append("")
    lines.append("## API Endpoints by Module")
    lines.append("")
    for mod in sorted(module_to_routes):
        mod_name = mod.split('/')[-1]
        routes = sorted(module_to_routes[mod])
        lines.append(f"### `{mod_name}` ({len(routes)} endpoints)")
        for r in routes:
            lines.append(f"- `{r}`")
        lines.append("")

    # Frontend → API
    lines.append("---")
    lines.append("")
    lines.append("## Frontend → API Calls")
    lines.append("")
    for view in sorted(vue_api_calls):
        view_name = view.split('/')[-1]
        endpoints = sorted(vue_api_calls[view])
        if not endpoints:
            continue
        lines.append(f"### `{view_name}` ({len(endpoints)} calls)")
        for ep in endpoints:
            lines.append(f"- `{ep}`")
        lines.append("")

    # Change impact lookup from annotations
    lines.append("---")
    lines.append("")
    lines.append("## Change Impact Lookup")
    lines.append("")
    lines.append("*If I change X, what else must I update?*")
    lines.append("")
    for item in annotations.get("change_impacts", []):
        lines.append(f"### Change: `{item['what']}`")
        for impact in item['impacts']:
            lines.append(f"- {impact}")
        lines.append("")

    # Key flows
    lines.append("---")
    lines.append("")
    lines.append("## Key Flows")
    lines.append("")
    for flow in annotations.get("key_flows", []):
        lines.append(f"### {flow['name']}")
        lines.append("")
        for step in flow['steps']:
            lines.append(f"- {step}")
        lines.append("")

    doc = "\n".join(lines)
    output.write_text(doc)
    print(f"Written: {output} ({len(lines)} lines, {len(doc):,} chars)")


if __name__ == "__main__":
    output = Path("ARCHITECTURE.md")
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--output" and i + 1 < len(sys.argv[1:]):
            output = Path(sys.argv[i + 2])
    generate(output)
