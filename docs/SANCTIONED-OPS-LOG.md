# Sanctioned-Ops Log

Audit trail for every sanctioned tool operation that is NOT a wave merge
(merge ops continue to write to `docs/MERGE-LOG.md`).  Each entry records
the tool, the operation performed, the pre/post state SHA (if applicable),
the result, the caller, and any explanatory notes.

**Why this log exists:** the sanctioned-channel toolkit (`tools/sanctioned/`)
gives every recurring deny-list workaround a single blessed code path with a
mandatory `try/finally` lift-restore.  This file is the tamper-evident receipt
for every such operation — so any lift that occurred during a session can be
audited after the fact.

**Entry format:**

```
## YYYY-MM-DDTHH:MM:SSZ — <tool>: <op>

- **Tool:** <tool>
- **Op:** <op>
- **Pre-SHA:** <sha | n/a>
- **Post-SHA:** <sha | n/a>
- **Result:** <result>
- **Caller:** <caller>
- **Notes:** <notes>
```

**Convention:** newest entries at the TOP (below the `---` divider).

---

## 2026-05-29T18:00:42Z — robot_settings: restore

- **Tool:** robot_settings
- **Op:** restore
- **Pre-SHA:** 5adc850
- **Post-SHA:** n/a
- **Result:** NO-OP (already canonical)
- **Caller:** stack
- **Notes:** settings.local.json permissions block matches wave-mode profile verbatim


## 2026-05-29T17:56:57Z — robot_settings: lift filter-branch

- **Tool:** robot_settings
- **Op:** lift filter-branch
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** LIFTED — awaiting operator action
- **Caller:** stack
- **Notes:** lifted 'filter-branch' deny rules: ['Bash(git filter-branch*)']; no operation performed (operator must act then call restore)


## 2026-05-29T17:56:57Z — robot_settings: lift checkout-main

- **Tool:** robot_settings
- **Op:** lift checkout-main
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** LIFTED — awaiting operator action
- **Caller:** stack
- **Notes:** lifted 'checkout-main' deny rules: ['Bash(git checkout main*)', 'Bash(git switch main*)']; no operation performed (operator must act then call restore)


## 2026-05-29T17:56:57Z — robot_settings: lift push

- **Tool:** robot_settings
- **Op:** lift push
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** LIFTED — awaiting operator action
- **Caller:** stack
- **Notes:** lifted 'push' deny rules: ['Bash(git push*)', 'Bash(git push -f*)', 'Bash(git push -u*)', 'Bash(git push --no-verify*)', 'Bash(git push --force*)']; no operation performed (operator must act then call restore)


## 2026-05-29T17:56:57Z — robot_settings: restore

- **Tool:** robot_settings
- **Op:** restore
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** NO-OP (already canonical)
- **Caller:** stack
- **Notes:** settings.local.json permissions block matches wave-mode profile verbatim


## 2026-05-29T17:56:57Z — robot_settings: restore

- **Tool:** robot_settings
- **Op:** restore
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** OK
- **Caller:** stack
- **Notes:** applied canonical wave-mode profile from /tmp/claude-1000/pytest-of-stack/pytest-911/test_restore_writes_audit_entr0/.claude/settings-wave-mode-profile.json


## 2026-05-29T17:56:57Z — robot_settings: restore

- **Tool:** robot_settings
- **Op:** restore
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** OK
- **Caller:** stack
- **Notes:** applied canonical wave-mode profile from /tmp/claude-1000/pytest-of-stack/pytest-911/test_restore_applies_profile_w0/.claude/settings-wave-mode-profile.json


## 2026-05-29T17:56:57Z — robot_settings: restore

- **Tool:** robot_settings
- **Op:** restore
- **Pre-SHA:** n/a
- **Post-SHA:** n/a
- **Result:** NO-OP (already canonical)
- **Caller:** stack
- **Notes:** settings.local.json permissions block matches wave-mode profile verbatim


## 2026-05-29T17:55:45Z — robot_settings: restore

- **Tool:** robot_settings
- **Op:** restore
- **Pre-SHA:** 5adc850
- **Post-SHA:** n/a
- **Result:** NO-OP (already canonical)
- **Caller:** stack
- **Notes:** settings.local.json permissions block matches wave-mode profile verbatim

