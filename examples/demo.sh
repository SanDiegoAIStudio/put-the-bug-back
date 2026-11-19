#!/bin/sh
# Run the made-up quiz fixture through the six checks. Removes its temp folder on exit.

set -eu

root=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
tool="$root/put_the_bug_back.py"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/quiz-demo.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export HOME="$tmp/home"
export TMPDIR="$tmp/work"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
mkdir -p "$HOME" "$TMPDIR"

repo="$tmp/harbor"
sh "$root/examples/make_fixture.sh" "$repo" >/dev/null

head_before=$(git -C "$repo" rev-parse HEAD)
branches_before=$(git -C "$repo" branch --list)

fail() {
    echo "$1"
    exit 1
}

run_tool() {
    out="$1"
    shift
    set +e
    python3 "$tool" "$@" >"$out" 2>"$out.err"
    code=$?
    set -e
    printf '%s\n' "$code" >"$out.code"
}

need() {
    if ! grep -F -q -- "$2" "$1"; then
        fail "missing: $2"
    fi
}

code_is() {
    got=$(cat "$1.code")
    if [ "$got" != "$2" ]; then
        fail "exit $got, wanted $2"
    fi
}

no_error() {
    if [ -s "$1.err" ]; then
        fail "the tool wrote to stderr"
    fi
}

button="python3 -m unittest test_page.ResultPageTest.test_main_button_does_not_restart"
share="python3 -m unittest test_page.ResultPageTest.test_share_control_is_present"
score="python3 -m unittest test_page.ResultPageTest.test_score_is_the_number_earned"
footer="python3 -m unittest test_page.ResultPageTest.test_footer_names_the_quiz"

echo "1. commit fix-button"
run_tool "$tmp/part1" commit fix-button --repo "$repo" --expect "unexpectedly found" -- $button
cat "$tmp/part1"
no_error "$tmp/part1"
need "$tmp/part1" "before    PASS"
need "$tmp/part1" "bug back  FAIL  the output holds \"unexpectedly found\""
need "$tmp/part1" "bug gone  PASS"
need "$tmp/part1" "CAUGHT: red with the bug back, green without it"
code_is "$tmp/part1" 0

echo "2. commit fix-share"
run_tool "$tmp/part2" commit fix-share --repo "$repo" -- $share
cat "$tmp/part2"
no_error "$tmp/part2"
need "$tmp/part2" "SURVIVED: the test passed with the bug back. It checks something else, or nothing."
code_is "$tmp/part2" 1

echo "3. commit fix-score"
run_tool "$tmp/part3" commit fix-score --repo "$repo" --expect "You scored 4 out of 5" -- $score
cat "$tmp/part3"
no_error "$tmp/part3"
need "$tmp/part3" "which looks like a test, so it went back too"
if grep -F -q "CAUGHT:" "$tmp/part3" || grep -F -q "CAUGHT," "$tmp/part3"; then
    fail "part 3 was CAUGHT"
fi
code_is "$tmp/part3" 1
run_tool "$tmp/part3b" commit fix-score --repo "$repo" --keep "test_*.py" --expect "You scored 4 out of 5" -- $score
cat "$tmp/part3b"
no_error "$tmp/part3b"
need "$tmp/part3b" "CAUGHT: red with the bug back, green without it"
need "$tmp/part3b" "kept as it is today: test_page.py"
code_is "$tmp/part3b" 0

echo "4. commit fix-footer"
run_tool "$tmp/part4" commit fix-footer --repo "$repo" -- $footer
cat "$tmp/part4"
no_error "$tmp/part4"
need "$tmp/part4" "STALE: could not put the bug back:"
need "$tmp/part4" "The fix is tangled with later changes. Next time, commit a fix on its own."
code_is "$tmp/part4" 1

echo "5. all"
run_tool "$tmp/part5" all "$repo/bugs.json" --repo "$repo"
cat "$tmp/part5"
no_error "$tmp/part5"
need "$tmp/part5" "CAUGHT button-link"
need "$tmp/part5" "SURVIVED share-score"
need "$tmp/part5" "WRONG REASON score-wrong-words"
need "$tmp/part5" "STALE footer-tangled"
need "$tmp/part5" "caught 1 of 4"
code_is "$tmp/part5" 1
run_tool "$tmp/part5b" all "$repo/bugs.json" --repo "$repo" --only button-link
cat "$tmp/part5b"
no_error "$tmp/part5b"
need "$tmp/part5b" "caught 1 of 1"
code_is "$tmp/part5b" 0
run_tool "$tmp/part5c" all "$repo/bugs.json" --repo "$repo" --stale-only
cat "$tmp/part5c"
no_error "$tmp/part5c"
need "$tmp/part5c" "STALE footer-tangled"
need "$tmp/part5c" "4 bugs, 1 stale"
code_is "$tmp/part5c" 1

echo "6. fixture untouched"
status=$(git -C "$repo" status --porcelain)
printf '%s\n' "$status"
head_after=$(git -C "$repo" rev-parse HEAD)
branches_after=$(git -C "$repo" branch --list)
printf '%s\n' "HEAD $head_after"
printf '%s\n' "$branches_after"
left=$(find "$tmp" -name 'put-the-bug-back-*' -print)
printf '%s\n' "$left"
if [ -n "$status" ]; then
    fail "git status --porcelain was not empty"
fi
if [ "$head_before" != "$head_after" ]; then
    fail "HEAD changed"
fi
if [ "$branches_before" != "$branches_after" ]; then
    fail "the branch list changed"
fi
if [ -n "$left" ]; then
    fail "a put-the-bug-back folder was left behind"
fi
