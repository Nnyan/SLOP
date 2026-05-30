#!/usr/bin/env bash
# pre-commit-linecount.sh — File-size ratchet pre-commit hook
#
# Runs tools/check_linecount.py against the *staged* tree and blocks the
# commit on a ratchet violation (same rules as CI).
#
# Install (one-time):
#   bash tools/hooks/pre-commit-linecount.sh --install
#
# Manual install (alternative):
#   cp tools/hooks/pre-commit-linecount.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# If a pre-commit hook already exists, the installer appends a sourced call
# so existing hook logic is preserved.
#
# Uninstall:
#   rm .git/hooks/pre-commit   # or restore your prior hook

set -euo pipefail

# ── Installer mode ──────────────────────────────────────────────────────────
if [[ "${1:-}" == "--install" ]]; then
    hook_dir="$(git rev-parse --git-dir)/hooks"
    hook_path="$hook_dir/pre-commit"
    script_abs="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    install_line="bash \"$script_abs\""

    if [[ -f "$hook_path" ]]; then
        if grep -qF "$script_abs" "$hook_path" 2>/dev/null; then
            echo "pre-commit-linecount: already installed at $hook_path"
            exit 0
        fi
        # Append to existing hook
        echo "" >> "$hook_path"
        echo "# File-size ratchet (installed by tools/hooks/pre-commit-linecount.sh --install)" >> "$hook_path"
        echo "$install_line" >> "$hook_path"
        echo "pre-commit-linecount: appended to existing $hook_path"
    else
        {
            echo "#!/usr/bin/env bash"
            echo "# File-size ratchet (installed by tools/hooks/pre-commit-linecount.sh --install)"
            echo "$install_line"
        } > "$hook_path"
        chmod +x "$hook_path"
        echo "pre-commit-linecount: installed at $hook_path"
    fi
    exit 0
fi

# ── Hook mode (called by git pre-commit) ────────────────────────────────────
# Locate the repo root from the .git dir git provides.
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$repo_root" ]]; then
    echo "pre-commit-linecount: cannot determine repo root (not in a git repo?)" >&2
    exit 1
fi

check_script="$repo_root/tools/check_linecount.py"
if [[ ! -f "$check_script" ]]; then
    # Script missing — skip silently (don't block the commit; gate is advisory
    # if the tool itself is absent).
    exit 0
fi

# Prefer the project venv's Python for determinism.
venv_py="$repo_root/.venv/bin/python3"
if [[ -x "$venv_py" ]]; then
    py="$venv_py"
else
    py="python3"
fi

set +e
output=$("$py" "$check_script" 2>&1)
exit_code=$?
set -e

if [[ $exit_code -ne 0 ]]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  pre-commit: file-size ratchet violation — commit blocked    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "$output"
    echo ""
    echo "Fix: shrink the file, or run:"
    echo "  python3 tools/check_linecount.py --snapshot    # update baseline (deliberate)"
    echo "  python3 tools/check_linecount.py --update-shrunk  # shrink baseline entries"
    echo ""
    exit 1
fi

# Print any WARNINGs (informational, don't block)
if echo "$output" | grep -q "WARNING"; then
    echo "pre-commit-linecount: $output"
fi

exit 0
