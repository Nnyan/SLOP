#!/usr/bin/env bash
# capture-evidence-f16.sh — forensic capture for RETEST_F16_FIX
# Run as: sudo bash /tmp/capture-evidence-f16.sh
set -euo pipefail

DEST=/tmp/retest_f16_evidence
mkdir -p "$DEST"

sudo cat /opt/mediastack/.installer-state.json > "$DEST/installer-state.json"
stat /var/lib/mediastack > "$DEST/data-dir-stat.txt"
stat -c "%U:%G %a" /var/lib/mediastack >> "$DEST/data-dir-stat.txt"
systemctl status mediastack --no-pager -l > "$DEST/service-status.txt"
ss -tlnp > "$DEST/port-binding.txt"
sudo journalctl -u mediastack --no-pager -n 50 > "$DEST/journal-tail.txt"
id mediastack > "$DEST/install-user.txt"

echo "Evidence captured at $DEST"
ls "$DEST"
