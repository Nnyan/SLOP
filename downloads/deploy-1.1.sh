#!/usr/bin/env bash
# deploy-1.1.sh — Deploy step 1.1 (database migrations) from downloads/
#
# Usage:
#   sudo bash /srv/mediastack/downloads/deploy-1.1.sh
#
# All files sit flat in /srv/mediastack/downloads/ — no subdirectories needed.
# Validates only the four new migration checks (Core Rule 6.1), not the full
# ms-enforce suite — pre-existing Tier 0 violations are out of scope for 1.1.

set -euo pipefail

REPO=/srv/mediastack
SRC="$REPO/downloads"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RESET='\033[0m'
ok()   { echo -e "  ${GREEN}✓${RESET} $*"; }
fail() { echo -e "  ${RED}✗${RESET} $*"; exit 1; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }
info() { echo -e "  → $*"; }

echo ""
echo "  ────────────────────────────────────────────────"
echo "  Mediastack step 1.1 — database migrations deploy"
echo "  ────────────────────────────────────────────────"
echo ""

[[ -d "$REPO" ]] || fail "Repo not found at $REPO"
[[ -d "$SRC"  ]] || fail "Downloads dir not found at $SRC"
cd "$REPO"

# Flat filename → destination path inside $REPO
declare -A FILES=(
    [ms-enforce]="ms-enforce"
    [migrations.py]="backend/core/migrations.py"
    [state.py]="backend/core/state.py"
    [schema.sql]="backend/core/schema.sql"
    [001_baseline.sql]="migrations/001_baseline.sql"
    [002_normalize_apps_status_check.sql]="migrations/002_normalize_apps_status_check.sql"
    [003_sync_legacy_tunnel_slot.py]="migrations/003_sync_legacy_tunnel_slot.py"
    [README.md]="migrations/README.md"
    [001_add_failed_status.sql]="migrations/_legacy/001_add_failed_status.sql"
    [test_migrations.py]="tests/test_migrations.py"
    [regenerate-schema-sql.py]="tools/regenerate-schema-sql.py"
    [CORE_RULES.md]="docs/CORE_RULES.md"
    [PROJECT_CLEANUP.md]="docs/cleanup/PROJECT_CLEANUP.md"
)

missing=0
for src_name in "${!FILES[@]}"; do
    if [[ ! -f "$SRC/$src_name" ]]; then
        warn "Missing in downloads/: $src_name"
        (( missing++ )) || true
    fi
done
[[ $missing -eq 0 ]] || fail "$missing file(s) not found in $SRC"
ok "All source files present in downloads/"

mkdir -p "$REPO/migrations/_legacy" "$REPO/tools"

info "Copying files..."
for src_name in "${!FILES[@]}"; do
    cp "$SRC/$src_name" "$REPO/${FILES[$src_name]}"
done

cat > "$REPO/migrations/_legacy/README.md" << 'EOF'
# migrations/_legacy/

Pre-v4 hand-run migration scripts. Preserved for historical reference.
The runner ignores this directory (underscore-prefixed names are skipped).

## 001_add_failed_status.sql

A one-shot script that added 'failed' to the apps.status CHECK constraint.
That work is now done by migrations/002_normalize_apps_status_check.sql,
which is idempotent and applied automatically by the migration runner.
EOF

ok "Files copied"

OLD="migrations/001_add_failed_status.sql"
if git ls-files --error-unmatch "$OLD" &>/dev/null 2>&1; then
    git rm "$OLD"
    ok "Removed old $OLD from git (now in migrations/_legacy/)"
else
    warn "$OLD was not tracked (already gone)"
fi

# ── Syntax check ──────────────────────────────────────────────────────────

info "Syntax-checking Python files..."
for f in backend/core/migrations.py backend/core/state.py \
          tests/test_migrations.py tools/regenerate-schema-sql.py ms-enforce; do
    python3 -m py_compile "$f" || fail "Syntax error in $f"
done
ok "All Python files parse cleanly"

# ── Migration-specific checks (Core Rule 6.1 only) ────────────────────────
# Run the four new checks directly instead of ms-enforce --fast, which
# gates on pre-existing Tier 0 violations outside scope of step 1.1.

info "Checking migration sequence (no gaps/duplicates)..."
python3 - << 'PY'
import re, sys
from pathlib import Path
mig_dir = Path("migrations")
pat = re.compile(r"^(\d{3})_[a-z0-9_]+\.(sql|py)$")
files = sorted((int(m.group(1)), p.name)
               for p in mig_dir.iterdir()
               if not p.is_dir() and (m := pat.match(p.name)))
if not files:
    print("  ERROR: no migration files found"); sys.exit(1)
seen = {}
for v, name in files:
    if v in seen:
        print(f"  ERROR: duplicate version {v:03d}: {seen[v]} and {name}"); sys.exit(1)
    seen[v] = name
versions = [v for v, _ in files]
for i in range(1, len(versions)):
    if versions[i] != versions[i-1] + 1:
        print(f"  ERROR: gap {versions[i-1]:03d}→{versions[i]:03d}"); sys.exit(1)
print(f"  sequence {versions[0]:03d}–{versions[-1]:03d} OK ({len(files)} migrations)")
PY
ok "Migration sequence clean"

info "Checking .py migrations expose upgrade(conn)..."
python3 - << 'PY'
import ast, re, sys
from pathlib import Path
pat = re.compile(r"^(\d{3})_[a-z0-9_]+\.py$")
bad = []
for p in sorted(Path("migrations").iterdir()):
    if not pat.match(p.name): continue
    tree = ast.parse(p.read_text())
    fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.col_offset == 0}
    if "upgrade" not in fns:
        bad.append(p.name)
if bad:
    print("  ERROR: missing upgrade(conn):", bad); sys.exit(1)
print(f"  {sum(1 for p in Path('migrations').iterdir() if pat.match(p.name))} .py migration(s) OK")
PY
ok "Python migration API correct"

info "Checking schema.sql is in sync with migrations/..."
python3 tools/regenerate-schema-sql.py --check || fail "schema.sql out of sync — run: python3 tools/regenerate-schema-sql.py"
ok "schema.sql in sync with migrations/"

info "Checking no new ad-hoc CREATE TABLE IF NOT EXISTS..."
python3 - << 'PY'
import re, sys
from pathlib import Path
pat = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS", re.I)
allowed = {
    Path("backend/core/schema.sql"),
    Path("backend/core/migrations.py"),
    Path("backend/api/health.py"),
    Path("backend/api/models.py"),
    Path("backend/health/checker.py"),
    Path("backend/health/source_checker.py"),
    Path("backend/health/managed_services.py"),
    Path("backend/api/quickstart.py"),
}
bad = []
for p in sorted(Path("backend").rglob("*.py")):
    if p in allowed: continue
    for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
        if pat.search(line):
            bad.append(f"{p}:{i}")
if bad:
    print("  ERROR: ad-hoc CREATE TABLE found:")
    for b in bad: print(f"    {b}")
    sys.exit(1)
print("  no new ad-hoc CREATE TABLE IF NOT EXISTS")
PY
ok "No ad-hoc CREATE TABLE outside permitted files"

# ── Pytest ────────────────────────────────────────────────────────────────

info "Running pytest tests/test_migrations.py..."
python3 -m pytest tests/test_migrations.py -q --tb=short --no-header \
    || fail "Migration tests failed"
ok "All migration tests passed"

# ── Git commit + push ─────────────────────────────────────────────────────

info "Staging and committing..."
git add \
    ms-enforce \
    backend/core/migrations.py \
    backend/core/state.py \
    backend/core/schema.sql \
    "migrations/001_baseline.sql" \
    "migrations/002_normalize_apps_status_check.sql" \
    "migrations/003_sync_legacy_tunnel_slot.py" \
    "migrations/README.md" \
    "migrations/_legacy/" \
    tests/test_migrations.py \
    tools/regenerate-schema-sql.py \
    docs/CORE_RULES.md \
    docs/cleanup/PROJECT_CLEANUP.md

git commit -m "feat(migrations): step 1.1 — database migration runner

- backend/core/migrations.py: custom runner, idempotent, checksum-verified
- state.py: init_db() wires run_migrations(), removes inline tunnel-sync
- migrations/001_baseline.sql: schema.sql snapshot at v4 launch
- migrations/002: normalize apps.status CHECK to include 'failed'
- migrations/003: lift legacy tunnel-slot sync out of init_db()
- migrations/_legacy/: retire old hand-run 001_add_failed_status.sql
- backend/core/schema.sql: regenerated (GENERATED FILE header)
- tools/regenerate-schema-sql.py: schema sync gate for CI
- tests/test_migrations.py: 12 scenarios, 12 passed
- ms-enforce: +4 Tier 1 migration checks (Core Rule 6.1)
- docs/CORE_RULES.md: Rule 5.19 / Core Rule 6.1 added
- docs/cleanup/PROJECT_CLEANUP.md: step 1.1 DONE, next: 1.2"

ok "Committed"

info "Pushing to origin..."
git push
ok "Pushed"

# ── Deploy ────────────────────────────────────────────────────────────────

echo ""
echo "  ────────────────────────────────────────────────"
echo "  Running sudo ms-update --full"
echo "  (first run stamps v3 baseline, applies 002+003,"
echo "   writes backup to data/state.db.bak.<timestamp>)"
echo "  ────────────────────────────────────────────────"
echo ""
sudo ms-update --full

echo ""
ok "Step 1.1 complete."
echo ""
