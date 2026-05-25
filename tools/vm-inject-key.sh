#!/usr/bin/env bash
# vm-inject-key.sh — inject ~/.ssh/mediastack.pub into a test VM via password auth
#
# Usage:
#   ./tools/vm-inject-key.sh <VM_IP> [USER] [SSH_KEY]
#
# Environment:
#   VM_PASS     VM password (prompted if not set)
#   JUMP_HOST   ProxyJump host (e.g. stack@10.0.1.60) for VMs not directly reachable
#
# Examples:
#   # Direct (rocinante):
#   VM_PASS=$(cat ~/.config/slop/secrets/rocinante_sudo) ./tools/vm-inject-key.sh 10.0.1.51
#
#   # Via jump server (matrix test VMs):
#   VM_PASS=$(cat ~/.config/slop/secrets/rocinante_sudo) JUMP_HOST=stack@10.0.1.60 ./tools/vm-inject-key.sh 10.0.3.25

set -euo pipefail

VM_IP="${1:-}"
VM_USER="${2:-stack}"
SSH_KEY="${3:-$HOME/.ssh/mediastack}"
PUBKEY="${SSH_KEY}.pub"

if [[ -z "$VM_IP" ]]; then
    echo "usage: $0 <VM_IP> [USER] [SSH_KEY]" >&2
    echo ""
    echo "env: VM_PASS=<password>  JUMP_HOST=user@host" >&2
    exit 1
fi

if [[ ! -f "$PUBKEY" ]]; then
    echo "error: public key not found: $PUBKEY" >&2
    exit 1
fi

if ! command -v sshpass &>/dev/null; then
    echo "error: sshpass not installed." >&2
    echo "  Install: sudo apt-get install -y sshpass" >&2
    exit 1
fi

# Prompt for password if not provided via environment
if [[ -z "${VM_PASS:-}" ]]; then
    read -rsp "Password for ${VM_USER}@${VM_IP}: " VM_PASS
    echo
fi

BASE_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

# Build jump-host options if set
if [[ -n "${JUMP_HOST:-}" ]]; then
    JUMP_OPTS="-o ProxyJump=${JUMP_HOST} -i ${SSH_KEY}"
    echo "Using jump host: ${JUMP_HOST}"
else
    JUMP_OPTS=""
fi

echo "Injecting key into ${VM_USER}@${VM_IP}..."

PUBKEY_CONTENT="$(cat "$PUBKEY")"

# Check if key is already present
if sshpass -p "$VM_PASS" ssh $BASE_OPTS $JUMP_OPTS "${VM_USER}@${VM_IP}" \
    "grep -qF '$PUBKEY_CONTENT' ~/.ssh/authorized_keys 2>/dev/null"; then
    echo "Key already present — skipping inject."
else
    # Inject key manually (ssh-copy-id doesn't support ProxyJump cleanly)
    sshpass -p "$VM_PASS" ssh $BASE_OPTS $JUMP_OPTS "${VM_USER}@${VM_IP}" \
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PUBKEY_CONTENT' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
    echo "Key injected."
fi

# Verify key-based auth works
echo "Verifying key auth..."
if ssh -i "$SSH_KEY" $BASE_OPTS ${JUMP_OPTS:-} "${VM_USER}@${VM_IP}" \
    "echo OK" 2>/dev/null | grep -q "^OK$"; then
    echo "OK — key auth working for ${VM_USER}@${VM_IP}"
    echo ""
    echo "Connect with:"
    if [[ -n "${JUMP_HOST:-}" ]]; then
        echo "  ssh -i ${SSH_KEY} -o ProxyJump=${JUMP_HOST} ${VM_USER}@${VM_IP}"
    else
        echo "  ssh -i ${SSH_KEY} ${VM_USER}@${VM_IP}"
    fi
else
    echo "FAIL — key auth did not work after inject. Check VM sshd config." >&2
    exit 1
fi
