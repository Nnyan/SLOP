# Robot Test Battery Results

**Date:** YYYY-MM-DD
**Operator:** <your name or "Robot mode">
**Session type:** Fresh Claude Code session
**Settings:** `defaultMode: "bypassPermissions"` confirmed? YES / NO
**Claude model:** claude-<model>

---

## Summary

Total tests: 30 (Battery 1: 20, Battery 2: 10)
SILENT:   __/__
BLOCKED:  __/__ (expected: 6, tests 15-20)
PROMPTED: __/__
ERROR:    __/__

**Overall verdict:** PASS (0 unexpected prompts) / FAIL (N unexpected prompts)

---

## Results Table

| Test # | Category | Expected | Actual | Notes |
|--------|----------|----------|--------|-------|
| 1  | brace_expansion | SILENT | | |
| 2  | heredoc_quoted | SILENT | | |
| 3  | command_substitution | SILENT | | |
| 4  | cd_prefix_git | SILENT | | |
| 5  | pipe_chain | SILENT | | |
| 6  | glob_expansion | SILENT | | |
| 7  | symlink | SILENT | | |
| 8  | pipe_with_tee_redirect | SILENT | | |
| 9  | read_normal_file | SILENT | | |
| 10 | read_sensitive_path | SILENT | | |
| 11 | edit_existing_file | SILENT | | |
| 12 | agent_no_isolation | SILENT | | |
| 13 | agent_worktree_isolation | SILENT | | |
| 14 | webfetch_allowed_domain | SILENT | | |
| 15 | deny_sudo | BLOCKED | | |
| 16 | deny_rm_rf_root | BLOCKED | | |
| 17 | deny_git_push | BLOCKED | | |
| 18 | deny_git_checkout_main | BLOCKED | | |
| 19 | deny_interactive_git | BLOCKED | | |
| 20 | deny_ask_user_question | BLOCKED | | |
| 21 | for_loop_var_interpolation | SILENT | | |
| 22 | multiline_if_else | SILENT | | |
| 23 | var_interpolation_conditional | SILENT | | |
| 24 | cross_boundary_mv | SILENT | | |
| 25 | subshell_and_brace_group | SILENT | | |
| 26 | process_substitution | SILENT | | |
| 27 | background_command_wait | SILENT | | |
| 28 | heredoc_unquoted_eof | SILENT | | |
| 29 | four_stage_pipe_redirect | SILENT | | |
| 30 | glob_destructive_find_delete | SILENT | | |

---

## New Categories (optional, run if testing NC candidates)

| Test | Category | Expected | Actual | Notes |
|------|----------|----------|--------|-------|
| NC-1 | python3_c_multistatement | UNVERIFIED | | |

---

## Unexpected Prompts Detail

For any test marked PROMPTED, fill in:

### Unexpected Prompt: Test N — <category>
- **Command tried:** `<exact command>`
- **Prompt text:** <what appeared>
- **Auto-approved?** YES / NO
- **Action:** Add to deny list / Add allow entry / Update command-style discipline / No action
- **Follow-up entry in BACKLOG.md?** YES / NO

---

## Doctrine Implications

Based on this run:

- [ ] No changes needed — 30/30 silent (all expected results match)
- [ ] Update AUTONOMOUS-DEFAULTS.md command-style discipline: `<pattern>`
- [ ] Add to deny list: `<pattern>`
- [ ] Add allow entry: `<tool/pattern>`
- [ ] Verify NC-1 (python3 -c multi-statement) and update ROBOT.md

---

## Sign-off

Reviewed by: ___________________  Date: ______________
Committed under: `robot: battery results YYYY-MM-DD — N/30 silent`
