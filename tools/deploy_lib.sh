#!/usr/bin/env bash
# tools/deploy_lib.sh — shared deploy helpers for ms-update and deploy.sh.
#
# Source-able library. Defines functions ONLY; no top-level side effects, so it
# is safe to `source` from a script running under `set -euo pipefail`.
#
#   source "<install_dir>/tools/deploy_lib.sh"
#
# PINNED public contract (do NOT rename or change signatures — both ms-update and
# deploy.sh depend on these exact names/signatures):
#
#   detect_service_user <install_dir>   -> echoes the canonical service user
#   build_home                          -> echoes the canonical writable build HOME
#   normalize_ownership <install_dir> <svc_user>
#                                       -> chowns tree + re-asserts .env mode 600
#
# Guard against double-sourcing (idempotent — re-sourcing just re-defines the
# same functions, which is harmless, but the guard avoids redundant work).
if [ -n "${_SLOP_DEPLOY_LIB_SOURCED:-}" ]; then
  return 0 2>/dev/null || true
fi
_SLOP_DEPLOY_LIB_SOURCED=1

# detect_service_user <install_dir>
# Echoes the canonical service user, resolved in this PINNED order:
#   1. stat -c %U <install_dir>        (owner of the install tree)
#   2. systemctl show mediastack -p User --value
#   3. literal "mediastack"
# Each step is guarded so a failure (or empty result) falls through to the next.
detect_service_user() {
  install_dir="$1"
  user=""

  # 1) Owner of the install dir.
  if [ -n "$install_dir" ]; then
    user="$(stat -c %U "$install_dir" 2>/dev/null || true)"
  fi
  if [ -n "$user" ] && [ "$user" != "UNKNOWN" ]; then
    printf '%s\n' "$user"
    return 0
  fi

  # 2) systemd unit's configured User=.
  if command -v systemctl >/dev/null 2>&1; then
    user="$(systemctl show mediastack -p User --value 2>/dev/null || true)"
  fi
  if [ -n "$user" ]; then
    printf '%s\n' "$user"
    return 0
  fi

  # 3) Hard fallback.
  printf '%s\n' "mediastack"
  return 0
}

# build_home
# Echoes the canonical writable build HOME for the service user. The service user
# is typically a system account with HOME=/nonexistent, which breaks npm; callers
# run `sudo -u "$SVC_USER" env HOME="$(build_home)" npm …`.
build_home() {
  printf '%s\n' "${MS_BUILD_HOME:-/tmp}"
}

# normalize_ownership <install_dir> <svc_user>
# The SINGLE ownership normalizer. Chowns the whole install tree to
# <svc_user>:<svc_user> and re-asserts that .env is mode 600 (it carries
# secrets; a world-readable .env is a leak, and an unreadable one crash-loops
# the service). Idempotent; safe to run repeatedly.
normalize_ownership() {
  install_dir="$1"
  svc_user="$2"

  if [ -z "$install_dir" ] || [ -z "$svc_user" ]; then
    printf 'normalize_ownership: usage: normalize_ownership <install_dir> <svc_user>\n' >&2
    return 2
  fi
  if [ ! -d "$install_dir" ]; then
    printf 'normalize_ownership: not a directory: %s\n' "$install_dir" >&2
    return 1
  fi

  chown -R "$svc_user:$svc_user" "$install_dir"

  if [ -f "$install_dir/.env" ]; then
    chmod 600 "$install_dir/.env"
  fi

  return 0
}
