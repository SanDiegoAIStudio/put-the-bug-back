# Put the bug back

A test you wrote after a fix has never failed in front of you. Until it does, you do not know whether it checks the fix or checks nothing. Ten minutes settles it.

## The exercise

1. Pick a bug you fixed recently that has a test guarding it.
2. Make a branch: `git switch -c put-the-bug-back`
3. Undo only the fix. If it was one commit, `git revert --no-commit <fix-commit>` does it; otherwise edit the line back by hand.

When the fix commit also changed the test, the revert takes today's test away too (or leaves the test file in conflict), so bring today's test back with `git checkout HEAD -- path/to/the/test` before step 4.

4. Run the test that guards it. Expect red.
5. Read the failure. It should name the bug in words you would recognize, not a crash somewhere nearby.
6. Put the fix back: `git revert --abort` if you used revert in step 3, or `git restore .` if you edited the line by hand. Run the test again and expect green.
7. Delete the branch. Run `git status` first; it should be clean. Then: `git switch - && git branch -D put-the-bug-back`

## What the result tells you

| What you saw | What it means | What to do |
|---|---|---|
| Red with the bug back, green without it | The test guards the fix | Nothing. Write down that you checked |
| Green with the bug back | The test checks something else, or nothing | Change the test until step 4 goes red, then run all seven steps again |
| Red, but from a crash or a timeout | The test fails for a reason other than the bug | Make it fail on an assertion about the bug, so a future crash cannot pass for a catch |
| You could not put the bug back cleanly | The fix is tangled with other changes | Next time, commit the fix on its own |

## A worked example (made up)

A quiz's result page had a big button that linked back to the quiz and restarted it. The fix removed that link. The browser test checks that clicking the main button does not land on the quiz's first question. Putting the old link back made the test fail on that check; removing it again made every check pass.

## Make it a habit

Before you merge a fix, do steps 2 to 6 once. If you keep a changelog, add one line: "put the bug back: red, then green".
