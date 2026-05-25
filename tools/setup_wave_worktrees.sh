#!/usr/bin/env bash
# setup_wave_worktrees.sh — create or remove per-session git worktrees for parallel waves
#
# Usage:
#   ./tools/setup_wave_worktrees.sh setup   S-24-A S-24-B S-24-C
#   ./tools/setup_wave_worktrees.sh cleanup S-24-A S-24-B S-24-C
#
# setup:   creates /home/stack/code/slop-wave/<session-id> on branch wave/<session-id>
# cleanup: removes worktrees and branches after merge

set -euo pipefail

SLOP_REPO="/home/stack/code/slop"
WAVE_BASE="/home/stack/code/slop-wave"

cmd="${1:-}"
shift || true

if [ -z "$cmd" ]; then
    echo "Usage: $0 <setup|cleanup> <session-id> [session-id ...]" >&2
    exit 1
fi

if [ "$cmd" != "setup" ] && [ "$cmd" != "cleanup" ]; then
    echo "Error: first argument must be 'setup' or 'cleanup', got: $cmd" >&2
    exit 1
fi

if [ "$#" -eq 0 ]; then
    echo "Error: at least one session ID required" >&2
    exit 1
fi

# Validate that SLOP_REPO is a git repo
if ! git -C "$SLOP_REPO" rev-parse --git-dir >/dev/null 2>&1; then
    echo "Error: $SLOP_REPO is not a git repository" >&2
    exit 1
fi

if [ "$cmd" = "setup" ]; then
    # Create wave base directory if it doesn't exist
    mkdir -p "$WAVE_BASE"

    created=0
    skipped=0
    for session_id in "$@"; do
        worktree_path="$WAVE_BASE/$session_id"
        branch_name="wave/$session_id"

        if [ -d "$worktree_path" ]; then
            echo "Warning: worktree already exists at $worktree_path — skipping"
            skipped=$((skipped + 1))
            continue
        fi

        git -C "$SLOP_REPO" worktree add "$worktree_path" -b "$branch_name" main
        echo "Created worktree: $worktree_path (branch: $branch_name)"
        created=$((created + 1))
    done

    echo ""
    echo "Created $created worktree(s). Dispatch sessions with:"
    for session_id in "$@"; do
        echo "  cd $WAVE_BASE/$session_id && ..."
    done
    if [ "$skipped" -gt 0 ]; then
        echo "($skipped already existed — skipped)"
    fi

elif [ "$cmd" = "cleanup" ]; then
    removed=0
    failed=0
    for session_id in "$@"; do
        worktree_path="$WAVE_BASE/$session_id"
        branch_name="wave/$session_id"

        git -C "$SLOP_REPO" worktree remove "$worktree_path" --force \
            && echo "Removed worktree: $worktree_path" \
            || { echo "Warning: could not remove worktree $worktree_path (continuing)"; failed=$((failed + 1)); }

        git -C "$SLOP_REPO" branch -d "$branch_name" 2>/dev/null \
            && echo "Deleted branch: $branch_name" \
            || echo "Note: branch $branch_name not found or already deleted (skipping)"

        removed=$((removed + 1))
    done

    # Remove wave base dir if empty
    if [ -d "$WAVE_BASE" ] && [ -z "$(ls -A "$WAVE_BASE" 2>/dev/null)" ]; then
        rmdir "$WAVE_BASE"
        echo "Removed empty directory: $WAVE_BASE"
    fi

    echo ""
    echo "Cleanup complete: processed $removed session(s)."
    if [ "$failed" -gt 0 ]; then
        echo "($failed worktree removal(s) failed — check output above)"
    fi
fi
