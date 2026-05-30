#!/usr/bin/env bash
# tools/normalize-ownership.sh — thin shim around deploy_lib.sh::normalize_ownership.
#
# Kept so any external/legacy call site (and the historical ms-update reference)
# resolves to the SINGLE ownership normalizer in tools/deploy_lib.sh rather than a
# drifting second copy.
#
# Usage: normalize-ownership.sh <install_dir> <svc_user>
set -euo pipefail

_here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=tools/deploy_lib.sh
source "$_here/deploy_lib.sh"

normalize_ownership "$@"
