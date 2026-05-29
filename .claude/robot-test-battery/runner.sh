#!/usr/bin/env bash
# Robot Test Battery Runner
#
# Usage:  bash .claude/robot-test-battery/runner.sh
#
# Creates a throwaway test environment at /tmp/robot-battery-test-<ts>/
# and prints the paste-ready prompt for the operator to use in a FRESH
# Claude Code session.
#
# IMPORTANT: CI cannot drive interactive Claude sessions. This script is
# operator-driven. Paste the printed prompt into a new Claude Code session
# that has NOT yet run any tools (fresh session = bypassPermissions applies
# from the start).

set -euo pipefail

TIMESTAMP=$(date +%s)
TEST_DIR="/tmp/robot-battery-test-${TIMESTAMP}"
BATTERY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTRUCTIONS="${BATTERY_DIR}/test-instructions.md"

# --- Create the throwaway test environment ---
mkdir -p "${TEST_DIR}"
git -C "${TEST_DIR}" init -q
git -C "${TEST_DIR}" config user.email "robot-battery@slop.test"
git -C "${TEST_DIR}" config user.name "Robot Battery"

# Seed a dummy file so the Edit tool test has something to work with
cat > "${TEST_DIR}/dummy.py" <<'EOF'
# Robot battery dummy file — safe to delete
def hello():
    return "hello"
EOF

git -C "${TEST_DIR}" add dummy.py
git -C "${TEST_DIR}" commit -q -m "seed: dummy file for battery tests"

# Copy the instructions into the test environment
cp "${INSTRUCTIONS}" "${TEST_DIR}/test-instructions.md"

# --- Print the paste-ready prompt ---
echo ""
echo "========================================================================"
echo "  Robot Test Battery — Operator Prompt (copy everything between lines)"
echo "========================================================================"
echo ""
cat <<PROMPT
I need you to run the Robot mode test battery. The test environment is at:
  ${TEST_DIR}/

The test instructions are in:
  ${TEST_DIR}/test-instructions.md

Read the file first, then execute each test in order (tests 1–30). For each
test, report the result as one of:
  SILENT   — no prompt, ran cleanly
  PROMPTED — a permission/safety prompt appeared (describe it)
  BLOCKED  — denied by the deny list (expected for tests 15–20)
  ERROR    — command failed (not a prompt, just an error — note it)

At the end, print a summary table:
  | Test # | Category | Result |
  |--------|----------|--------|
  ...

Then fill in RESULTS-TEMPLATE.md (also in the test environment dir) with the
results. Copy the completed template to stdout at the end.

Rules for this session:
- Work entirely within ${TEST_DIR}/ and /tmp/ for destructive tests.
- For test 10 (Read /etc/passwd) — read only the first 2 lines.
- For deny-list tests (15–20) — attempt the command/tool and confirm it is
  blocked; do not force-bypass.
- If NC-1 (python3 -c multi-statement) is listed, run it and document whether
  it prompted.
PROMPT

echo ""
echo "========================================================================"
echo ""
echo "Test environment: ${TEST_DIR}"
echo "Instructions:     ${TEST_DIR}/test-instructions.md"
echo ""
echo "Next steps:"
echo "  1. Open a FRESH Claude Code session (new terminal, not this one)."
echo "  2. Verify the session is using bypassPermissions:"
echo "       cat .claude/settings.local.json | grep defaultMode"
echo "  3. Paste the prompt above into the fresh session."
echo "  4. After the session completes, copy the results into:"
echo "       .claude/robot-test-battery/RESULTS-TEMPLATE.md"
echo ""
