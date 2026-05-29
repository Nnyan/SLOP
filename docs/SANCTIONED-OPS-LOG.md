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
