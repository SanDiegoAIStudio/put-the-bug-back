# Put the bug back

A test you wrote after a fix has never failed in front of you, so you do not know whether it checks the fix. Put the bug back for ten minutes and see if the test goes red.

## Quick start

From any directory inside your repository:

```
python3 put_the_bug_back.py commit FIX -- TEST COMMAND
```

```
python3 put_the_bug_back.py swap FILE --find OLD --replace NEW -- TEST COMMAND
```

The test command runs at the top of a copy of the repository. Each test run is stopped after 300 seconds unless you pass `--timeout N`, and `--repo PATH` reads a repository other than the one you are in. `python3 put_the_bug_back.py --help` lists every option.

## The exercise

Undo a fix on a branch, run its test, and expect red.
Put the fix back, run the test, and expect green.
Read the failure. It should name the bug, not a crash somewhere nearby.
The seven steps, the result table, and a worked example are in [EXERCISE.md](EXERCISE.md).

## Let the script do it

`sh examples/demo.sh` builds a small made-up quiz in a temporary folder, runs the checks below, and deletes the folder. Every name of a project, person, or product in the fixture and the examples is invented.

## What you get

This is the output of that script when `python3` is Python 3.9. With Python 3.14 the `ERROR:` line names the test twice: `ERROR: test_score_is_the_number_earned (unittest.loader._FailedTest.test_score_is_the_number_earned)`. On a git that names a new repository's first branch `master`, the last line reads `* master`.

```
1. commit fix-button
before    PASS
  put back: page.py
bug back  FAIL  the output holds "unexpectedly found"
bug gone  PASS
CAUGHT: red with the bug back, green without it
changelog line: put the bug back: red, then green
2. commit fix-share
before    PASS
  put back: page.py
bug back  PASS
bug gone  PASS
SURVIVED: the test passed with the bug back. It checks something else, or nothing.
3. commit fix-score
before    PASS
  put back: page.py, test_page.py
  note: fix-score also changed test_page.py, which looks like a test, so it went back too. To keep today's version: --keep 'test_page.py'
bug back  FAIL
E
======================================================================
ERROR: test_score_is_the_number_earned (unittest.loader._FailedTest)
----------------------------------------------------------------------
AttributeError: type object 'ResultPageTest' has no attribute 'test_score_is_the_number_earned'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
bug gone  PASS
WRONG REASON: the test went red, but not for the bug: the output does not hold "You scored 4 out of 5"
before    PASS
  put back: page.py
  kept as it is today: test_page.py
bug back  FAIL  the output holds "You scored 4 out of 5"
bug gone  PASS
CAUGHT: red with the bug back, green without it
changelog line: put the bug back: red, then green
4. commit fix-footer
before    PASS
STALE: could not put the bug back: conflict in page.py
The fix is tangled with later changes. Next time, commit a fix on its own.
5. all
CAUGHT button-link  the main button does not restart the quiz
SURVIVED share-score  the share control is only checked for being present
WRONG REASON score-wrong-words  the output does not hold "a phrase the failure never prints"
STALE footer-tangled  conflict in page.py
caught 1 of 4
CAUGHT button-link  the main button does not restart the quiz
caught 1 of 1
STALE footer-tangled  conflict in page.py
4 bugs, 1 stale
6. fixture untouched

HEAD 356f6d4c4075f3e42776d1c4001d363316388b8a
* main

```

## What the verdict means

| Verdict | What happened | What it means | What to do |
|---|---|---|---|
| CAUGHT | Red with the bug back, green without it | The test guards the fix | Nothing. Write down that you checked |
| SURVIVED | Green with the bug back | The test checks something else, or nothing | Change the test until it goes red with the bug back, then run the check again |
| WRONG REASON | Red, but from a crash or a timeout | The test fails for a reason other than the bug | Make it fail on an assertion about the bug, so a future crash cannot pass for a catch |
| STALE | You could not put the bug back cleanly | The fix is tangled with other changes | Next time, commit the fix on its own |
| NOT GREEN | The test fails before any bug is put back, or it does not pass again once the bug is gone | The suite is not green on the code you have | Make the suite green, then put the bug back |

`CAUGHT` without `--expect` is printed as `CAUGHT, REASON NOT CHECKED`. The exit code is still 0. Pass `--expect` with words from the failure and the tool checks them for you.

## Three ways to name the bug

The commands below were run in the made-up repository, with `python3 put_the_bug_back.py` pointing at this tool.

Undo the commit that fixed the bug. The test command after `--` is run as given, with no shell.

```
python3 put_the_bug_back.py commit fix-button --expect "unexpectedly found" -- python3 -m unittest test_page.ResultPageTest.test_main_button_does_not_restart
```

```
before    PASS
  put back: page.py
bug back  FAIL  the output holds "unexpectedly found"
bug gone  PASS
CAUGHT: red with the bug back, green without it
changelog line: put the bug back: red, then green
```

Or name one exact piece of text: the text as it stands today, then the buggy text. `$1`, `\n` and `&` in the replacement stay as typed.

```
python3 put_the_bug_back.py swap page.py --find "main = '<button id=\"main\">See your answers</button>'" --replace "main = '<a id=\"main\" href=\"/quiz/start\">Try again</a>'" --expect "unexpectedly found" -- python3 -m unittest test_page.ResultPageTest.test_main_button_does_not_restart
```

```
before    PASS
bug back  FAIL  the output holds "unexpectedly found"
bug gone  PASS
CAUGHT: red with the bug back, green without it
changelog line: put the bug back: red, then green
```

Or keep a list and rerun it. In a list the test is one string, run by `/bin/sh -c`.

```
python3 put_the_bug_back.py all bugs.json
```

```
CAUGHT button-link  the main button does not restart the quiz
SURVIVED share-score  the share control is only checked for being present
WRONG REASON score-wrong-words  the output does not hold "a phrase the failure never prints"
STALE footer-tangled  conflict in page.py
caught 1 of 4
```

## A fix committed with its test

If the fix commit also changed a test, that test goes back too, and the tool says so.

```
python3 put_the_bug_back.py commit fix-score --expect "You scored 4 out of 5" -- python3 -m unittest test_page.ResultPageTest.test_score_is_the_number_earned
```

```
before    PASS
  put back: page.py, test_page.py
  note: fix-score also changed test_page.py, which looks like a test, so it went back too. To keep today's version: --keep 'test_page.py'
bug back  FAIL
E
======================================================================
ERROR: test_score_is_the_number_earned (unittest.loader._FailedTest)
----------------------------------------------------------------------
AttributeError: type object 'ResultPageTest' has no attribute 'test_score_is_the_number_earned'

----------------------------------------------------------------------
Ran 1 test in 0.000s

FAILED (errors=1)
bug gone  PASS
WRONG REASON: the test went red, but not for the bug: the output does not hold "You scored 4 out of 5"
```

`--keep` takes a glob, matched against the path from the top of the repository, and you can pass it more than once. Today's test stays, and the bug in the other file is what the test sees:

```
python3 put_the_bug_back.py commit fix-score --keep 'test_*.py' --expect "You scored 4 out of 5" -- python3 -m unittest test_page.ResultPageTest.test_score_is_the_number_earned
```

```
before    PASS
  put back: page.py
  kept as it is today: test_page.py
bug back  FAIL  the output holds "You scored 4 out of 5"
bug gone  PASS
CAUGHT: red with the bug back, green without it
changelog line: put the bug back: red, then green
```

## Keep the bugs you fixed

`bugs.json` at the top of the repository is the list `all` reads when you do not name one. It is a JSON object. `bugs` is required. `timeout` and `link` are optional and mean the same as `--timeout` and `--link`.

| Field | Required | What it is |
|---|---|---|
| id | yes | A short name, used once in the list |
| guards | yes | One line: what the test protects |
| test | yes | The command. One string, run by the shell |
| expect | yes | Text the failure must contain. Nobody is reading the output |
| fix | one or the other | The commit that fixed the bug. Optional `keep`: a list of globs |
| file, find, replace | one or the other | Swap this exact text. `replace` may be empty |

`python3 put_the_bug_back.py all` runs every bug and ends with `caught N of M`.

`python3 put_the_bug_back.py all --only button-link` runs that one bug.

```
CAUGHT button-link  the main button does not restart the quiz
caught 1 of 1
```

`python3 put_the_bug_back.py all --stale-only` makes no copy and runs no test. It prints the stale bugs and then `M bugs, K stale`.

```
STALE footer-tangled  conflict in page.py
4 bugs, 1 stale
```

A pre-commit hook: `python3 put_the_bug_back.py all`

A CI step: `python3 put_the_bug_back.py all`

Record a kept bug as a text swap. A commit id in the list goes stale after a rebase or a squash, and the text does not.

## What it does to your repository

It reads. Git is run with `-C` on your repository, and only to look: resolve a commit, list files, read a diff, read a blob, and merge three temporary files. It does not switch a branch, write the index, stash, make a worktree, or write a file under your repository.

Each run copies the working tree as it stands. That is the files `git ls-files` reports that exist on disk: tracked files as they are now, with edits that are not committed, and untracked files that are not ignored. Ignored files are not in the copy. The mode is kept, and a symlink is copied as a symlink. The copy lives in a temporary folder named `put-the-bug-back-` plus some characters. It is removed when the tool ends, including after an error, after Ctrl-C, after a terminate, and after a hang-up. `--keep-copy` leaves it and prints `copy kept: PATH`. A stop, a closed output pipe, and an unexpected error remove the copy even when `--keep-copy` was passed.

`--link PATH` (repeatable) places a link to the real file or folder, so a test that writes through it writes into the repository. The path is inside the repository. It is often an ignored folder of installed dependencies.

After the tool writes files in one step, it gives them one modification time: a whole second, later than the clock at the write, and at least one second later than each file's previous time. It starts the test once a second more has passed after that time. That wait is under two seconds, or under three when a file had changed in the second before the write, and when a file's previous time was in the future it lasts until two to three seconds past that time. A build that looks only at whole-second times then sees the changed source as newer than a product the before run just built.

The test command does not receive `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_COMMON_DIR`, or `GIT_PREFIX`. The tool's own git calls keep the environment they were started with.

Before copying, the tool adds up the file sizes. Above `--max-mb` (default 200) it copies nothing and exits 2 with `could not: the copy would be N MB (limit M MB); raise it with --max-mb`.

## Exit codes

- `0` means every bug was caught.
- `1` means any other verdict.
- `2` means the tool could not do its work.
- `130` is an interrupt, `143` is a terminate, and `129` is a hang-up.

## Limits

- Every run copies the tracked files and the new files, which is slow on a large repository.
- The test command's standard input is empty.
- A process the test command leaves running when it exits is not stopped by the tool, and neither is one it starts in a session of its own.
- A `kill -9` of the tool leaves the copy and the test command behind.
- Ignored folders are not copied. A test that writes into a linked folder writes into the real one, and so does the tool when it puts back a file the fix deleted from that folder.
- The copy is not a git repository, so a test that asks git about the project fails there.
- The test command runs on this machine with this environment, so a test that talks to a real database or service does that with the bug back as well.
- `--expect` is plain text found anywhere in the output, and without it the tool cannot tell a failure about the bug from any other failure.
- A commit id in a kept list goes stale after a rebase or a squash.
- A merge commit and the first commit cannot be the fix.
- Binary files are not merged.
- A file the fix deleted comes back as an ordinary file with mode 644, so an executable script loses its executable bit and a symlink comes back as a file that holds the link's target.
- A test command that exits 126 or 127 is read as one that could not start, which is what the shell means by those numbers, and the verdict is WRONG REASON.
- One bug at a time, never two together.
- It needs git, sh, and a Unix-like system, and the checks ran on macOS with Python 3.9 and Python 3.14.

## Tests

From this folder:

```
python3 -m unittest discover -s tests -v
python3 tests/mutate.py
```

The first command runs 96 tests, which took about five minutes on the Mac they were tested on. They need git and sh.

`bugs.json` in this folder is this tool's own kept list: 62 bugs, each a text swap in `put_the_bug_back.py` with the test that guards it. `python3 tests/mutate.py` copies this folder into a temporary git repository with an empty home folder of its own, runs `put_the_bug_back.py all` on that list there, and prints what `all` printed. It took about nine minutes on the same Mac. A real run ends with:

```
caught 62 of 62
```

It exits 0 when every bug in the list was caught and the list holds at least 50 bugs, and 1 otherwise. A run still going after 30 minutes is stopped and exits 1. It exits 2 when it cannot make the temporary repository, or when no `python3` sits beside the Python that runs it.

## License

MIT. See [LICENSE](LICENSE).

## Built at San Diego AI Studio

This tool comes out of San Diego AI Studio, the builders' community in San Diego, where builders show the systems they run. More projects: https://sandiegoaistudio.com/projects
