# Review Log

Audit trail of independent reviews of significant changes — see CLAUDE.md § "Independent review for significant changes". One entry per significant change: the reviewer, the charge, key findings, and the author's per-finding **reconciliation** (accept/reject + why). The reconciliation line — not "reviewed: yes" — is the point: it records that the author checked the reviewer's findings against physics and what they did about each. Each entry should cite a durable, committed review record. Newest at top.

---

## 2026-05-30 — Independent-review discipline (this doctrine, dogfooded)

- **Change:** the "Independent review for significant changes" doctrine itself (CLAUDE.md) + `docs/REVIEW-LOG.md` + the batch-11 `check_independent_review` gate.
- **Reviewer:** fresh Opus adversarial subagent (derive-own-design-then-attack), charged to hunt for a loop or a freeze.
- **Key findings → reconciliation:**
  - G1 (highest) the gate checks token-presence, not review-occurrence → theater that the promotion machinery could bless into a blocking string-check. **Accepted + refined:** cite a **committed** artifact (not a `/tmp` transcript — the rot we just killed) + an artifact-existence GROUND leg; `[red-signal: PARTIAL]`; hard stop on auto-promotion. (Also checked the reviewer's "auto-promote on timer" claim against doctrine: promotion is a *deliberate* act, not silent — but a false-green would mislead the promoter, so the hard-stop stands.)
  - G2 acyclicity asserted not enforced. **Accepted:** statically exclude REVIEW-LOG + the gate's own def from the trigger, in code.
  - G3 narrow-below-floor recorded reason = stored-and-trusted rot in the dangerous direction. **Accepted — better asymmetry:** no narrow-below-floor; floor is code, flex lives above it; tighten the floor only via reviewed doctrine change.
  - G4 proceed-and-owe has no forcing function. **Accepted:** owed reviews are BACKLOG entries under `check_backlog_stale` (age-red).
  - G5 free widening is cost-deferred to throughput. **Accepted:** reviewer weight by tier (four-question → subagent → separate session).
  - G6 subagent independence partly fictional (author writes the charge). **Accepted:** irreversible tier gets a fixed-charge separate session.
  - G7 floor gameable for non-path triggers. **Accepted:** two honest tiers (mechanical floor vs declared advisory).
  - Bonus: doctrine *removals* have the four-question walk-back; *additions* had none → extend four-question to additions (the floor tier).
- **Record:** key findings captured in this entry (the live subagent transcript was ephemeral `/tmp` — exactly why the doctrine now requires a *committed* artifact going forward). Landed in the same commit as this file.

## 2026-05-30 — Reuse-and-blast-radius checkpoint

- **Change:** the "Reuse-and-blast-radius checkpoint" doctrine (CLAUDE.md) + the batch-11 `audit_single_entity_hardcode.py` scanner + the audit-charter fold-in.
- **Reviewer:** fresh Opus adversarial subagent (derive-then-attack).
- **Key findings → reconciliation:**
  - GAP-1 no red-signal → the checkpoint is an unenforced checklist (yellow, not green). **Accepted:** added the GROUND scanner (batch-11) + honest `[red-signal: PENDING]` stamp.
  - GAP-2 "before authoring ANY tool" too heavy → dead opt-in gate. **Accepted:** scoped the mandatory part to known plural sets / sibling families.
  - GAP-3 collision with focused-wave scope. **Accepted:** "parameterize the seam, not the coverage" + BACKLOG the uncovered members.
  - GAP-4 "insert an error" hand-waving. **Accepted:** a regression test feeding known-bad input asserting DRIFT/non-zero (the `check_handoff_freshness` pattern).
  - GAP-6 self-exemplifying (the frontend grep rule). **Accepted:** generalized CLAUDE.md:156 as the `.vue` instance in the same stroke.
  - GAP-7 the recorded reuse note is itself stored-and-trusted rot. **Accepted:** marked it XREF-class (rationale, not assurance).
  - Reviewer's "day-one true-positive" (`lift_push_restore.py`'s `SETTINGS_PATH` hardcode): **reconciled against code → it is a JUSTIFIED hardcode** (the deny lifted is the running SLOP session's, always SLOP). Not a bug; it is the scanner's false-positive-suppression test case (the recorded-reason exemption).
- **Record:** landed in commit `e0b310d` (doctrine: Reuse-and-blast-radius checkpoint…). Live subagent transcript was ephemeral.
