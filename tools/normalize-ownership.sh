#!/usr/bin/env bash
# tools/normalize-ownership.sh — service-user ownership normalizer / auditor.
#
# Thin front-end over deploy_lib.sh::normalize_ownership (the SINGLE ownership
# normalizer) plus a read-only --check audit mode used by ms-enforce
# (check_ownership) and a --quiet flag used by ms-update.
#
# Usage:
#   normalize-ownership.sh [--quiet] [<install_dir> [<svc_user>]]
#       chown the tree to the service user + re-assert .env mode 600.
#   normalize-ownership.sh --check [<install_dir>]
#       read-only: exit 1 (and list offenders) if any tracked file is NOT owned
#       by the service user; exit 0 if clean. Mutates nothing.
#
# install_dir defaults to this script's repo root; svc_user is auto-detected via
# deploy_lib.sh::detect_service_user.
set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_repo_root="$(cd "$_here/.." && pwd)"
# shellcheck source=tools/deploy_lib.sh
source "$_here/deploy_lib.sh"

MODE="apply"
QUIET=0
POS=()
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    --quiet|-q) QUIET=1 ;;
    *) POS+=("$arg") ;;
  esac
done

INSTALL_DIR="${POS[0]:-$_repo_root}"
SVC_USER="${POS[1]:-$(detect_service_user "$INSTALL_DIR")}"

if [ "$MODE" = "check" ]; then
  # Read-only audit: list tracked files NOT owned by the service user.
  offenders=""
  while IFS= read -r f; do
    [ -e "$INSTALL_DIR/$f" ] || continue
    owner="$(stat -c %U "$INSTALL_DIR/$f" 2>/dev/null || echo '?')"
    if [ "$owner" != "$SVC_USER" ]; then
      offenders="${offenders}    ${f} (owned by ${owner})
"
    fi
  done < <(git -C "$INSTALL_DIR" ls-files 2>/dev/null || true)

  if [ -n "$offenders" ]; then
    [ "$QUIET" -eq 1 ] || printf 'wrong ownership (expected %s):\n%s' "$SVC_USER" "$offenders" >&2
    exit 1
  fi
  [ "$QUIET" -eq 1 ] || printf 'ownership clean (all tracked files owned by %s)\n' "$SVC_USER"
  exit 0
fi

# apply mode — delegate to the single normalizer.
normalize_ownership "$INSTALL_DIR" "$SVC_USER"
