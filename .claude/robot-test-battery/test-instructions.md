# Robot Test Battery — Verified Zero-Prompt Configuration

**Purpose:** This document is the union of Battery 1 (20 tests) and Battery 2 (10 tests)
verified against `.claude/settings.local.json` with `defaultMode: "bypassPermissions"`.
Each test is a concrete, runnable Bash or tool invocation with its expected result.

**Expected result for all tests 1–30:** SILENT — no permission prompt, no safety halt.
**Expected result for deny-list tests:** BLOCKED/REJECTED.

**Running the battery:** See `runner.sh` in this directory. Run in a FRESH Claude session
only — `defaultMode` does not live-reload mid-session.

**Test environment:** The runner creates a throwaway git repo at
`/tmp/robot-battery-test-<ts>/` and a dummy Python file for edit tests.

---

## Battery 1 — 20 tests (verified 2026-05-28 daytime)

### Group 1: Bash syntax patterns

#### Test 1 — Brace expansion in Bash
```bash
mkdir -p /tmp/robot-battery-test/brace/{a,b,c}
```
**Expected:** SILENT. Creates three subdirs.
**Category:** brace_expansion

#### Test 2 — Heredoc with quoted EOF (no variable interpolation)
```bash
cat > /tmp/robot-battery-test/heredoc-test.txt <<'EOF'
literal content $NOT_EXPANDED
EOF
```
**Expected:** SILENT. File contains literal `$NOT_EXPANDED`.
**Category:** heredoc_quoted

#### Test 3 — Command substitution at top level
```bash
mkdir -p /tmp/robot-battery-test/cmd-sub-$(date +%s)
```
**Expected:** SILENT. Creates a timestamped directory.
**Category:** command_substitution

#### Test 4 — cd-prefix git command
```bash
cd /tmp/robot-battery-test && git status
```
**Expected:** SILENT (may fail if not a git repo, but no prompt).
**Category:** cd_prefix_git

#### Test 5 — Pipe chain
```bash
ls /tmp/robot-battery-test | grep -v '^$' | wc -l
```
**Expected:** SILENT. Prints a number.
**Category:** pipe_chain

#### Test 6 — Glob expansion
```bash
ls /tmp/robot-battery-test/*.txt 2>/dev/null || true
```
**Expected:** SILENT. Lists .txt files or prints nothing.
**Category:** glob_expansion

#### Test 7 — Symlink creation
```bash
ln -sf /tmp/robot-battery-test /tmp/robot-battery-symlink-test
```
**Expected:** SILENT. Creates symlink.
**Category:** symlink

#### Test 8 — Multi-stage pipe with redirection
```bash
find /tmp/robot-battery-test -type f | sort | head -5 | tee /tmp/robot-battery-test/file-list.txt
```
**Expected:** SILENT. Creates file-list.txt with up to 5 entries.
**Category:** pipe_with_tee_redirect

### Group 2: Tool calls

#### Test 9 — Read tool on normal file
```
Read: /home/stack/code/slop/README.md (first 5 lines)
```
**Expected:** SILENT. Returns file content.
**Category:** read_normal_file

#### Test 10 — Read tool on sensitive path
```
Read: /etc/passwd (first 2 lines)
```
**Expected:** SILENT. Returns file content (read-only is allowed).
**Category:** read_sensitive_path

#### Test 11 — Edit tool on an existing file
```
Edit: /tmp/robot-battery-test/heredoc-test.txt
  old_string: "literal content $NOT_EXPANDED"
  new_string: "edited content $NOT_EXPANDED"
```
**Expected:** SILENT. File is updated.
**Category:** edit_existing_file

### Group 3: Agent tool dispatches

#### Test 12 — Agent tool without worktree isolation
```
Agent tool: task="echo hello from subagent", model="claude-sonnet-4-6"
```
**Expected:** SILENT. Subagent completes and returns.
**Category:** agent_no_isolation

#### Test 13 — Agent tool with worktree isolation
```
Agent tool: task="echo hello from isolated subagent", model="claude-sonnet-4-6", isolation="worktree"
```
**Expected:** SILENT. Subagent completes in isolated worktree.
**Category:** agent_worktree_isolation

### Group 4: Network (WebFetch)

#### Test 14 — WebFetch on an allowed domain
```
WebFetch: url="https://github.com/Nnyan/SLOP"
```
**Expected:** SILENT. Returns page content.
**Category:** webfetch_allowed_domain

### Group 5: Deny-list enforcement

#### Test 15 — sudo command (expect BLOCKED)
```bash
sudo ls /root
```
**Expected:** BLOCKED by deny list. No execution.
**Category:** deny_sudo

#### Test 16 — rm -rf / (root destruction, expect BLOCKED)
```bash
rm -rf /
```
**Expected:** BLOCKED by deny list. No execution.
**Category:** deny_rm_rf_root

#### Test 17 — git push (expect BLOCKED)
```bash
git push origin main
```
**Expected:** BLOCKED by deny list. No execution.
**Category:** deny_git_push

#### Test 18 — git checkout main (expect BLOCKED)
```bash
git checkout main
```
**Expected:** BLOCKED by deny list. No execution.
**Category:** deny_git_checkout_main

#### Test 19 — Interactive rebase (expect BLOCKED)
```bash
git rebase -i HEAD~2
```
**Expected:** BLOCKED by deny list. No execution.
**Category:** deny_interactive_git

#### Test 20 — AskUserQuestion tool (expect BLOCKED / tool unavailable)
```
AskUserQuestion: question="Should I continue?"
```
**Expected:** BLOCKED or tool not available. Robot mode forbids it.
**Category:** deny_ask_user_question

---

## Battery 2 — 10 tests (verified 2026-05-29 early morning)

These were added after older `acceptEdits`-mode sessions leaked prompts on
patterns missed by Battery 1.

#### Test 21 — Nested for-loop with variable interpolation in body
```bash
for f in a b c; do echo "item: $f"; done
```
**Expected:** SILENT in fresh bypassPermissions session. Prints three lines.
**Category:** for_loop_var_interpolation
**Note:** Was found to prompt in older `acceptEdits` sessions ("simple_expansion").

#### Test 22 — Multi-line if/then/else
```bash
if [ -d /tmp ]; then
  echo "tmp exists"
else
  echo "tmp missing"
fi
```
**Expected:** SILENT. Prints "tmp exists".
**Category:** multiline_if_else

#### Test 23 — Variable interpolation in conditional body
```bash
PID=12345; if [ "$PID" -gt 0 ]; then echo "pid $PID"; fi
```
**Expected:** SILENT. Prints "pid 12345".
**Category:** var_interpolation_conditional

#### Test 24 — Cross-boundary mv (from /tmp to test dir, outside)
```bash
cp /tmp/robot-battery-test/file-list.txt /tmp/robot-battery-mv-target.txt && mv /tmp/robot-battery-mv-target.txt /tmp/robot-battery-moved-back.txt
```
**Expected:** SILENT. File is moved.
**Category:** cross_boundary_mv

#### Test 25 — Subshell and brace group
```bash
(echo "from subshell") && { echo "from brace group"; }
```
**Expected:** SILENT. Prints both lines.
**Category:** subshell_and_brace_group

#### Test 26 — Process substitution
```bash
diff <(echo "a") <(echo "b") || true
```
**Expected:** SILENT. Prints diff output (diff returns 1, `|| true` absorbs it).
**Category:** process_substitution

#### Test 27 — Background command with wait
```bash
echo "bg start" & wait
```
**Expected:** SILENT. Prints "bg start".
**Category:** background_command_wait

#### Test 28 — Heredoc with UNQUOTED EOF (variable interpolation enabled)
```bash
MSG="hello from heredoc"; cat > /tmp/robot-battery-test/unquoted-heredoc.txt <<EOF
$MSG world
EOF
```
**Expected:** SILENT. File contains "hello from heredoc world".
**Category:** heredoc_unquoted_eof

#### Test 29 — 4-stage pipe with redirection
```bash
find /tmp/robot-battery-test -type f -name '*.txt' | sort | head -3 | tee /tmp/robot-battery-test/top3.txt
```
**Expected:** SILENT. Creates top3.txt.
**Category:** four_stage_pipe_redirect

#### Test 30 — Glob in destructive context (find -delete)
```bash
find /tmp/robot-battery-test -name 'top3.txt' -delete
```
**Expected:** SILENT. Deletes the file created in test 29.
**Category:** glob_destructive_find_delete

---

## New categories (post-2026-05-28)

These are candidates for future Battery 3. Not yet verified in a fresh
`bypassPermissions` session.

### Candidate NC-1 — `python3 -c "<multi-statement>"`

```bash
python3 -c "import os; print(os.getcwd()); print('done')"
```
**Expected (unverified):** Likely SILENT in fresh bypassPermissions session
(consistent with how other syntax-analyzer categories behaved). Was observed
to prompt in an older `acceptEdits` session (2026-05-29 ~00:40Z, auto-approved).
**Action if verified SILENT:** Update ROBOT.md doctrine note — fresh
bypassPermissions sessions handle this cleanly.
**Action if verified PROMPTING:** Add "use a temp script file instead of
`python3 -c`" to command-style discipline in AUTONOMOUS-DEFAULTS.md.
**Source:** `docs/BACKLOG.md` 2026-05-29 entry.
**Category:** python3_c_multistatement

---

## How to extend this battery

When any future Robot run hits an unexpected prompt:
1. Add a test here under the appropriate Battery N section (or start Battery 3).
2. Document the exact command, the session mode it prompted in, and whether
   bypassPermissions silences it.
3. Run `bash .claude/robot-test-battery/runner.sh` to regenerate the test env
   prompt and verify.
4. Commit with message: `robot: battery — add test for <category> (seen in <date> run)`.
