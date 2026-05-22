#!/usr/bin/env bash
# tools/normalize-ownership.sh — Reset all project files to the service user.
#
# Why this exists:
#   `sudo ms-update`, `sudo deploy.sh`, and similar root-invoked commands can
#   create root-owned files in the working tree (git pull as root, file writes
#   from heredocs, etc). Mixed ownership breaks `git add`, breaks editor saves
#   from the service user, and silently rots until someone hits a permission
#   error.
#
#   This script normalizes the entire repo to ${SERVICE_USER}:${SERVICE_USER}
#   while leaving runtime-mutable directories alone (.venv, caches that may
#   legitimately be written by other contexts).
#
# Discovery:
#   The service user is whoever owns the repo root directory itself (matches
#   the convention used by ms-update's existing .git self-heal).
#
# Usage:
#   sudo /srv/mediastack/tools/normalize-ownership.sh
#   sudo /srv/mediastack/tools/normalize-ownership.sh --check    # report only
#   sudo /srv/mediastack/tools/normalize-ownership.sh --quiet    # CI/cron mode
#
# Idempotent — safe to re-run.

set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
SERVICE_USER="$(stat -c "%U" "$REPO")"
SERVICE_GROUP="$(stat -c "%G" "$REPO")"

CHECK_ONLY=0
QUIET=0
for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=1 ;;
        --quiet) QUIET=1 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown flag: $arg" >&2; exit 2 ;;
    esac
done

# Directories that may legitimately be owned by other users at runtime.
# Pruned from the find walk and never touched.
EXCLUDE_PATHS=(
    "$REPO/.venv"
    "$REPO/__pycache__"
    "$REPO/node_modules"
    "$REPO/frontend/node_modules"
    "$REPO/frontend/dist"
    "$REPO/frontend/.vite"
    "$REPO/data/compose"    # written by backend at runtime; service-user OK but don't fight it
)

# Build find prune args
PRUNE_ARGS=()
for p in "${EXCLUDE_PATHS[@]}"; do
    PRUNE_ARGS+=(-path "$p" -prune -o)
done

[[ $QUIET -eq 0 ]] && echo "  → Scanning $REPO for non-${SERVICE_USER} ownership..."

# Find files NOT owned by the service user, excluding pruned paths.
WRONG=$(find "$REPO" \
    "${PRUNE_ARGS[@]}" \
    \( -not -user "$SERVICE_USER" -o -not -group "$SERVICE_GROUP" \) \
    -print 2>/dev/null | wc -l)

if [[ $WRONG -eq 0 ]]; then
    [[ $QUIET -eq 0 ]] && echo "  ✓ All files owned by ${SERVICE_USER}:${SERVICE_GROUP}"
    exit 0
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
    echo "  ✗ Found $WRONG file(s) with wrong ownership:"
    find "$REPO" \
        "${PRUNE_ARGS[@]}" \
        \( -not -user "$SERVICE_USER" -o -not -group "$SERVICE_GROUP" \) \
        -printf "    %u:%g  %p\n" 2>/dev/null | head -20
    if [[ $WRONG -gt 20 ]]; then
        echo "    ... and $((WRONG - 20)) more"
    fi
    exit 1
fi

# Must be root to chown
if [[ "$EUID" -ne 0 ]]; then
    echo "  ✗ $WRONG file(s) need ownership reset — re-run with sudo" >&2
    exit 1
fi

[[ $QUIET -eq 0 ]] && echo "  → Resetting $WRONG file(s) to ${SERVICE_USER}:${SERVICE_GROUP}..."

find "$REPO" \
    "${PRUNE_ARGS[@]}" \
    \( -not -user "$SERVICE_USER" -o -not -group "$SERVICE_GROUP" \) \
    -exec chown "${SERVICE_USER}:${SERVICE_GROUP}" {} + 2>/dev/null

[[ $QUIET -eq 0 ]] && echo "  ✓ Normalized — all files now ${SERVICE_USER}:${SERVICE_GROUP}"
