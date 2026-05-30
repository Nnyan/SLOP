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

## 2026-05-30T15:33:43Z — robot_settings: push-then-restore (complete)

- **Tool:** robot_settings
- **Op:** push-then-restore (complete)
- **Pre-SHA:** 8c22fa1
- **Post-SHA:** 8c22fa1
- **Result:** OK
- **Caller:** stack
- **Notes:** target /home/stack/code/slop main; push deny restored unconditionally in finally block


## 2026-05-30T15:33:42Z — robot_settings: push-then-restore (start)

- **Tool:** robot_settings
- **Op:** push-then-restore (start)
- **Pre-SHA:** 8c22fa1
- **Post-SHA:** n/a
- **Result:** LIFTED
- **Caller:** stack
- **Notes:** push deny lifted; executing git -C /home/stack/code/slop push origin main

