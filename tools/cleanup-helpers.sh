#!/usr/bin/env bash
# tools/cleanup-helpers.sh — utilities for Mediastack cleanup-step scripts
#
# This is a SOURCED library, not an executable. Use it like:
#
#   #!/usr/bin/env bash
#   set -euo pipefail
#   source /srv/mediastack/tools/cleanup-helpers.sh
#
#   ms_require_user stack
#   ms_require_pwd /srv/mediastack
#   ms_require_clean_tracked
#
#   ms_section "Step 1.X.Y — refactor frobs"
#   ms_replace_anchor docs/foo.md "$old_text" "$new_text" "foo line"
#   ms_pytest_baseline tests/test_comprehensive_contracts.py "153 passed.*2 failed"
#
#   git add docs/foo.md
#   ms_commit_simple commit-msg.txt
#
# Functions provided:
#
#   Sanity preamble:
#     ms_require_user <name>          die unless $(whoami) == name
#     ms_require_pwd <path>           die unless pwd == path
#     ms_require_clean_tracked         die unless tracked-file working tree is clean
#                                      (untracked files OK — covers the "library script
#                                       sitting in repo dir" case that bit us before)
#     ms_require_clean_full            die unless absolutely nothing is uncommitted
#
#   UI / flow control:
#     ms_section <text>               horizontal-rule banner header
#     ms_pause [<text>]               wait for user to press Enter; respects MS_AUTO=1
#                                      (skips pause; useful for testing/CI)
#     ms_log_ok <msg>                 print "  ✓ msg"
#     ms_log_skip <msg>               print "  ⊙ msg"
#     ms_log_warn <msg>               print "  ⚠ msg"
#     ms_log_fail <msg>               print "  ✗ msg" to stderr
#
#   Pytest:
#     ms_pytest_baseline <target> <pattern>
#                                      run pytest, pipefail-safe, fail unless the tail-3
#                                      output matches grep -E pattern. Required for any
#                                      project that has a known-failing baseline.
#
#   File editing:
#     ms_replace_anchor <file> <old> <new> [<label>]
#                                      idempotent text replacement. Reports applied /
#                                      already-current / anchor-missing distinctly.
#                                      Returns 0 on apply, 10 on already-current,
#                                      20 on missing anchor (so caller can branch).
#
#   Git lookups:
#     ms_sha_by_subject <pattern>     echo short SHA of single most recent commit whose
#                                      subject matches grep pattern. Dies on 0 or >1
#                                      matches (ambiguity is a bug, not a default).
#
#   Git commits:
#     ms_commit_simple <msg-file>     git commit with message read from file. Stage your
#                                      files with `git add` first. Echoes the resulting
#                                      short SHA. Avoids the amend pattern entirely —
#                                      see DESIGN NOTE below for why.
#
# DESIGN NOTE on self-referencing commits:
#   The previous session hit a bug where a commit message embedded a placeholder
#   for its own SHA, and we backfilled via `git commit --amend`. Result: the
#   pre-amend commit got orphaned, and any reference written using the captured
#   SHA pointed at unreachable history.
#
#   This library does NOT provide a `ms_commit_with_self_ref` helper because the
#   pattern is a fixed-point problem (a commit's SHA depends on its content,
#   which would depend on the SHA). Two clean alternatives:
#
#     (1) Two-commit pattern (recommended). Make the actual change as commit A.
#         Then in commit B, edit docs to embed A's SHA. Use ms_sha_by_subject if
#         you need to find A from later scripts.
#
#     (2) Don't embed SHAs in commit content. Reference work by commit subject
#         instead — subjects are stable and human-readable.
#
#   If you absolutely need both "single commit" and "self-SHA in content," accept
#   that you're stuck with the amend orphan problem and document it explicitly.
#
# Self-test:  bash tools/cleanup-helpers.sh --self-test
#             (creates a temp git repo, exercises each function, cleans up)

# ─── Refuse direct execution (except --self-test) ─────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ "${1:-}" != "--self-test" ]]; then
        echo "ERROR: This is a sourced library, not an executable." >&2
        echo "  Source it from a script:  source ${BASH_SOURCE[0]}" >&2
        echo "  Or run the self-tests:    bash ${BASH_SOURCE[0]} --self-test" >&2
        exit 64
    fi
fi

# ─── Logging primitives ───────────────────────────────────────────────────────
ms_log_ok()    { printf '  ✓ %s\n' "$*"; }
ms_log_skip()  { printf '  ⊙ %s\n' "$*"; }
ms_log_warn()  { printf '  ⚠ %s\n' "$*"; }
ms_log_fail()  { printf '  ✗ %s\n' "$*" >&2; }

ms_section() {
    local text="${1:-}"
    printf '\n════════════════════════════════════════════════════════════════════════\n'
    printf '  %s\n' "$text"
    printf '════════════════════════════════════════════════════════════════════════\n'
}

ms_pause() {
    local prompt="${1:-Press Enter to continue, or Ctrl+C to abort.}"
    if [[ "${MS_AUTO:-0}" == "1" ]]; then
        return 0
    fi
    printf '\n%s\n' "$prompt"
    read -r _ || true
}

# ─── Sanity preamble ──────────────────────────────────────────────────────────
ms_require_user() {
    local expected="$1"
    local actual
    actual="$(whoami)"
    if [[ "$actual" != "$expected" ]]; then
        ms_log_fail "must run as user '$expected' (currently '$actual')"
        return 1
    fi
}

ms_require_pwd() {
    local expected="$1"
    local actual
    actual="$(pwd)"
    if [[ "$actual" != "$expected" ]]; then
        ms_log_fail "must run from '$expected' (currently '$actual')"
        return 1
    fi
}

ms_require_clean_tracked() {
    if ! git diff --quiet HEAD --; then
        ms_log_fail "tracked files have uncommitted changes — commit/stash first"
        git status --short
        return 1
    fi
    if ! git diff --quiet --cached HEAD --; then
        ms_log_fail "staged but uncommitted changes — commit or reset first"
        git status --short
        return 1
    fi
}

ms_require_clean_full() {
    if [[ -n "$(git status --porcelain)" ]]; then
        ms_log_fail "working tree dirty (including untracked) — commit/stash/clean first"
        git status --short
        return 1
    fi
}

# ─── Pytest (pipefail-safe) ───────────────────────────────────────────────────
ms_pytest_baseline() {
    local target="$1"
    local pattern="$2"

    local raw
    raw=$( { python3 -m pytest "$target" -q 2>&1 || true; } )

    local tail_lines
    tail_lines=$(echo "$raw" | tail -3)
    printf '%s\n' "$tail_lines"

    if ! printf '%s' "$tail_lines" | grep -qE "$pattern"; then
        ms_log_fail "pytest summary did not match pattern: $pattern"
        echo "  Full output (last 25 lines):" >&2
        printf '%s\n' "$raw" | tail -25 >&2
        return 1
    fi
    ms_log_ok "pytest baseline matches: $pattern"
}

# ─── File editing ─────────────────────────────────────────────────────────────
ms_replace_anchor() {
    local file="$1"
    local old="$2"
    local new="$3"
    local label="${4:-anchor in $file}"

    if [[ ! -f "$file" ]]; then
        ms_log_fail "$label: file does not exist ($file)"
        return 30
    fi

    python3 - "$file" "$old" "$new" "$label" <<'PY'
import sys
from pathlib import Path

file_path, old, new, label = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
src = Path(file_path).read_text()

# Priority: check anchor presence first. If `old` is in src, we have work to do
# regardless of whether `new` happens to also appear elsewhere (e.g. as a
# substring of unrelated text). Only treat as already-current when the anchor
# is GONE and the replacement is present.
if old in src:
    new_src = src.replace(old, new, 1)
    Path(file_path).write_text(new_src)
    print(f"  ✓ {label}: applied")
    sys.exit(0)
elif new in src:
    print(f"  ⊙ {label}: already current")
    sys.exit(10)
else:
    print(f"  ⚠ {label}: anchor not found in {file_path}")
    sys.exit(20)
PY
}

# ─── Git lookups ──────────────────────────────────────────────────────────────
ms_sha_by_subject() {
    local pattern="$1"
    local matches
    matches=$(git log --format='%h' --grep="$pattern" --all 2>/dev/null || true)

    if [[ -z "$matches" ]]; then
        ms_log_fail "no commit found matching subject: $pattern"
        return 1
    fi

    local count
    count=$(printf '%s\n' "$matches" | wc -l)
    if [[ "$count" -gt 1 ]]; then
        ms_log_fail "$count commits match subject '$pattern' — refusing to guess:"
        printf '%s\n' "$matches" >&2
        return 2
    fi

    printf '%s' "$matches"
}

# ─── Git commits ──────────────────────────────────────────────────────────────
ms_commit_simple() {
    local msg_file="$1"

    if [[ ! -f "$msg_file" ]]; then
        ms_log_fail "commit message file does not exist: $msg_file"
        return 1
    fi

    if git diff --cached --quiet; then
        ms_log_fail "ms_commit_simple called with no staged changes"
        return 1
    fi

    git commit --quiet -F "$msg_file"
    git rev-parse --short HEAD
}

# ─── Self-tests ───────────────────────────────────────────────────────────────
_ms_self_test() {
    local tmpdir
    tmpdir=$(mktemp -d -t cleanup-helpers-test.XXXXXX)
    trap "rm -rf '$tmpdir'" EXIT

    local pass=0 fail=0
    _t() {
        local label="$1"; shift
        if "$@"; then
            printf '  PASS  %s\n' "$label"
            pass=$((pass + 1))
        else
            printf '  FAIL  %s (exit=%d)\n' "$label" $?
            fail=$((fail + 1))
        fi
    }
    _t_expect_exit() {
        local expected="$1" label="$2"; shift 2
        ( "$@" ) >/dev/null 2>&1
        local got=$?
        if [[ "$got" -eq "$expected" ]]; then
            printf '  PASS  %s (exit=%d)\n' "$label" "$got"
            pass=$((pass + 1))
        else
            printf '  FAIL  %s (expected exit %d, got %d)\n' "$label" "$expected" "$got"
            fail=$((fail + 1))
        fi
    }

    cd "$tmpdir"
    git init -q -b main
    git config user.email "test@test"
    git config user.name "test"
    echo "initial" > README.md
    git add README.md
    git commit -q -m "initial commit"

    ms_section "Self-test: cleanup-helpers.sh"

    _t "ms_require_user current"   ms_require_user "$(whoami)"
    _t_expect_exit 1 "ms_require_user wrong"   ms_require_user "definitely_not_a_user_xyz"

    _t "ms_require_pwd matches"   ms_require_pwd "$(pwd)"
    _t_expect_exit 1 "ms_require_pwd wrong"   ms_require_pwd "/nonexistent"

    _t "ms_require_clean_tracked clean"   ms_require_clean_tracked
    echo "dirty" >> README.md
    _t_expect_exit 1 "ms_require_clean_tracked dirty"   ms_require_clean_tracked
    git checkout -- README.md
    echo "junk" > untracked.txt
    _t "ms_require_clean_tracked tolerates untracked"   ms_require_clean_tracked
    _t_expect_exit 1 "ms_require_clean_full rejects untracked"   ms_require_clean_full
    rm untracked.txt

    cat > sample.md <<'EOF'
Line A: hello world
Line B: foo bar
Line C: baz qux
EOF
    git add sample.md
    git commit -q -m "add sample"

    _t "ms_replace_anchor applies" \
        ms_replace_anchor sample.md "Line B: foo bar" "Line B: NEW VALUE" "test edit"
    grep -q "Line B: NEW VALUE" sample.md \
        && { printf '  PASS  replacement persisted to disk\n'; pass=$((pass + 1)); } \
        || { printf '  FAIL  replacement NOT persisted\n'; fail=$((fail + 1)); }

    _t_expect_exit 10 "ms_replace_anchor idempotent" \
        ms_replace_anchor sample.md "Line B: foo bar" "Line B: NEW VALUE" "test edit"

    _t_expect_exit 20 "ms_replace_anchor missing anchor" \
        ms_replace_anchor sample.md "totally absent text" "ABSOLUTELY-NOT-IN-FILE-9876" "missing"

    _t_expect_exit 30 "ms_replace_anchor missing file" \
        ms_replace_anchor /no/such/file "x" "y" "missing file"

    cat > regression.md <<'EOF'
This file already mentions the new value: TARGET-STATE
But the anchor SOURCE-STATE is also still here and needs replacing.
EOF
    _t "ms_replace_anchor applies when both old and new present" \
        ms_replace_anchor regression.md "SOURCE-STATE" "TARGET-STATE" "regression"
    if ! grep -q "SOURCE-STATE" regression.md && [[ $(grep -c "TARGET-STATE" regression.md) -eq 2 ]]; then
        printf '  PASS  both-present case correctly replaced (now 2x TARGET-STATE)\n'
        pass=$((pass + 1))
    else
        printf '  FAIL  both-present case did not replace correctly\n'
        cat regression.md
        fail=$((fail + 1))
    fi

    cat > multi.md <<'EOF'
START
foo
bar
baz
END
EOF
    local old=$'foo\nbar\nbaz'
    local new=$'one\ntwo\nthree\nfour'
    _t "ms_replace_anchor multi-line" \
        ms_replace_anchor multi.md "$old" "$new" "multi"
    grep -q "four" multi.md \
        && { printf '  PASS  multi-line replacement persisted\n'; pass=$((pass + 1)); } \
        || { printf '  FAIL  multi-line replacement NOT persisted\n'; fail=$((fail + 1)); }

    git add sample.md multi.md regression.md
    git commit -q -m "fix(things): the unique subject line aaa"

    local found_sha
    found_sha=$(ms_sha_by_subject "the unique subject line aaa")
    local expected_sha
    expected_sha=$(git rev-parse --short HEAD)
    if [[ "$found_sha" == "$expected_sha" ]]; then
        printf '  PASS  ms_sha_by_subject finds known commit (%s)\n' "$found_sha"
        pass=$((pass + 1))
    else
        printf '  FAIL  ms_sha_by_subject mismatch (got %s, expected %s)\n' "$found_sha" "$expected_sha"
        fail=$((fail + 1))
    fi

    _t_expect_exit 1 "ms_sha_by_subject no match" \
        ms_sha_by_subject "definitely not a real subject xyzzy"

    echo "more" >> multi.md
    git add multi.md
    git commit -q -m "fix(things): the unique subject line aaa"
    _t_expect_exit 2 "ms_sha_by_subject ambiguous" \
        ms_sha_by_subject "the unique subject line aaa"

    echo "another change" > other.md
    git add other.md
    cat > /tmp/_test_msg.txt <<'EOF'
test(thing): a clean commit

Body line.
EOF
    local new_sha
    new_sha=$(ms_commit_simple /tmp/_test_msg.txt)
    if [[ "$new_sha" == "$(git rev-parse --short HEAD)" ]]; then
        printf '  PASS  ms_commit_simple returns correct SHA (%s)\n' "$new_sha"
        pass=$((pass + 1))
    else
        printf '  FAIL  ms_commit_simple SHA mismatch\n'
        fail=$((fail + 1))
    fi
    rm -f /tmp/_test_msg.txt

    _t_expect_exit 1 "ms_commit_simple nothing staged" \
        ms_commit_simple /etc/hostname

    mkdir -p inner_test
    cat > inner_test/test_smoke.py <<'PY'
def test_passes_one(): assert True
def test_passes_two(): assert True
def test_fails():       assert False
PY
    if python3 -c 'import pytest' >/dev/null 2>&1; then
        _t "ms_pytest_baseline matches pattern" \
            ms_pytest_baseline inner_test/ "1 failed.*2 passed|2 passed.*1 failed"
        _t_expect_exit 1 "ms_pytest_baseline mismatched pattern" \
            ms_pytest_baseline inner_test/ "999 passed"
    else
        printf '  SKIP  ms_pytest_baseline (pytest not installed)\n'
    fi

    MS_AUTO=1
    _t "ms_pause respects MS_AUTO" ms_pause "would normally block here"
    unset MS_AUTO

    cd /

    printf '\n────────────────────────────────────────────────────────────────────────\n'
    printf 'Self-test results: %d passed, %d failed\n' "$pass" "$fail"
    printf '────────────────────────────────────────────────────────────────────────\n'

    [[ "$fail" -eq 0 ]]
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]] && [[ "${1:-}" == "--self-test" ]]; then
    _ms_self_test
    exit $?
fi
