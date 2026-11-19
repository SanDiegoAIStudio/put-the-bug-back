"""source: commit mode puts a fix back in a throwaway copy and reads the test."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers

PY = helpers.PY


def value_test(note):
    return (
        "import app, sys\n"
        "if app.NOTE != \"%s\":\n"
        "    sys.stderr.write(\"note moved\\n\")\n"
        "    raise SystemExit(1)\n"
        "if app.VALUE != 2:\n"
        "    sys.stderr.write(\"value is %%s\\n\" %% app.VALUE)\n"
        "    raise SystemExit(1)\n"
    ) % note


class CommitTests(helpers.Case):
    def _fix_value(self, note="old"):
        self.repo.write("app.py", "VALUE = 1\n\nNOTE = '%s'\n" % note)
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n\nNOTE = '%s'\n" % note)
        return self.repo.commit("fix the value")

    def test_caught(self):
        """source: a test that fails on its assertion while the fix is undone is caught."""
        fix = self._fix_value()
        self.repo.write("test_app.py", value_test("old"))
        self.repo.commit("guard the value")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["commit", fix, "--expect", "value is 1", "--", PY, "test_app.py"])
        self.assertEqual(err, "")
        self.assertEqual(code, 0)
        self.assertIn("before    PASS", out)
        self.assertIn('bug back  FAIL  the output holds "value is 1"', out)
        self.assertIn("bug gone  PASS", out)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)
        self.assertNotIn("CAUGHT, REASON NOT CHECKED:", out)
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_changelog_line(self):
        """source: a caught fix offers one changelog line the author can copy."""
        fix = self._fix_value()
        self.repo.write("test_app.py", value_test("old"))
        self.repo.commit("guard the value")
        code, out, err = self.repo.run(["commit", fix, "--expect", "value is 1", "--", PY, "test_app.py"])
        self.assertEqual(code, 0, out)
        self.assertIn("changelog line: put the bug back: red, then green", out)

    def test_later_change_stays(self):
        """source: a later edit a few lines away survives undoing the fix."""
        self.repo.write("app.py", "VALUE = 1\n\nNOTE = 'old'\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n\nNOTE = 'old'\n")
        fix = self.repo.commit("fix the value")
        self.repo.write("app.py", "VALUE = 2\n\nNOTE = 'new'\n")
        self.repo.write("test_app.py", value_test("new"))
        self.repo.commit("rename the note")
        code, out, err = self.repo.run(["commit", fix, "--expect", "value is 1", "--", PY, "test_app.py"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)
        self.assertNotIn("note moved", out)

    def test_survived(self):
        """source: a test that never looks at the undone line still passes."""
        fix = self._fix_value()
        self.repo.write("test_app.py", "import app\nraise SystemExit(0 if app.NOTE == 'old' else 1)\n")
        self.repo.commit("guard the note only")
        code, out, err = self.repo.run(["commit", fix, "--expect", "value is 1", "--", PY, "test_app.py"])
        self.assertEqual(code, 1)
        self.assertIn("bug back  PASS", out)
        self.assertIn("SURVIVED: the test passed with the bug back. It checks something else, or nothing.", out)

    def test_wrong_reason(self):
        """source: a red test that does not mention the expected text is the wrong reason."""
        fix = self._fix_value()
        self.repo.write("test_app.py", value_test("old"))
        self.repo.commit("guard the value")
        code, out, err = self.repo.run(["commit", fix, "--expect", "a phrase the failure never prints", "--", PY, "test_app.py"])
        self.assertEqual(code, 1)
        self.assertIn("WRONG REASON: the test went red, but not for the bug: the output does not hold \"a phrase the failure never prints\"", out)
        self.assertIn("value is 1", out)

    def test_unchecked(self):
        """source: a red run without expected text is caught and the failure is left to read."""
        fix = self._fix_value()
        self.repo.write("test_app.py", value_test("old"))
        self.repo.commit("guard the value")
        code, out, err = self.repo.run(["commit", fix, "--", PY, "test_app.py"])
        self.assertEqual(code, 0, out)
        self.assertIn("value is 1", out)
        self.assertIn("CAUGHT, REASON NOT CHECKED: red with the bug back, green without it. Read the failure above: it should name the bug. Pass --expect with words from it and the tool checks that for you.", out)
        self.assertNotIn("changelog line:", out)

    def test_stale_conflict(self):
        """source: a later rewrite of the fixed lines does not revert cleanly."""
        self.repo.write("app.py", "LINE = 'base'\n")
        self.repo.commit("start")
        self.repo.write("app.py", "LINE = 'fixed'\n")
        fix = self.repo.commit("fix the line")
        self.repo.write("app.py", "LINE = 'rewritten later'\n")
        self.repo.commit("rewrite the same line")
        code, out, err = self.repo.run(["commit", fix, "--", "true"])
        self.assertEqual(code, 1)
        self.assertIn("before    PASS", out)
        self.assertIn("STALE: could not put the bug back: conflict in app.py", out)
        self.assertFalse(any(line.startswith("bug back") for line in out.splitlines()))

    def test_not_green_before(self):
        """source: a test that already fails is not used to judge the bug."""
        fix = self._fix_value()
        lines = "".join("LINE-%d\n" % i for i in range(20))
        self.repo.write("test_app.py", "import sys\nsys.stderr.write(%r)\nraise SystemExit(1)\n" % lines)
        self.repo.commit("a red test")
        code, out, err = self.repo.run(["commit", fix, "--", PY, "test_app.py"])
        self.assertEqual(code, 1)
        self.assertIn("before    FAIL", out)
        self.assertIn("NOT GREEN: the test fails before any bug is put back", out)
        self.assertIn("LINE-19", out)
        self.assertNotIn("LINE-0\n", out)
        self.assertNotIn("bug back", out)

    def test_not_green_after(self):
        """source: the suite must pass again once the bug has been taken back out."""
        fix = self._fix_value()
        marker = os.path.join(self.repo.base, "seen")
        self.repo.write("check.py", (
            "import os, sys\n"
            "marker = sys.argv[1]\n"
            "if os.path.exists(marker):\n"
            "    sys.stderr.write('ran again\\n')\n"
            "    raise SystemExit(1)\n"
            "open(marker, 'w').write('x')\n"
            "raise SystemExit(0)\n"
        ))
        self.repo.commit("guard once")
        code, out, err = self.repo.run(["commit", fix, "--", PY, "check.py", marker])
        self.assertEqual(code, 1)
        self.assertIn("NOT GREEN: the test did not pass again once the bug was gone", out)
        self.assertNotIn("CAUGHT:", out)

    def test_added_file(self):
        """source: undoing a fix that added a file removes that file when it is unchanged."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        self.repo.write("extra.py", "yes\n")
        fix = self.repo.commit("add the extra file")
        self.repo.write("test_app.py", (
            "import os, sys\n"
            "if not os.path.isfile('extra.py'):\n"
            "    sys.stderr.write('extra.py is gone\\n')\n"
            "    raise SystemExit(1)\n"
            "raise SystemExit(0 if open('extra.py').read() == 'yes\\n' else 1)\n"
        ))
        self.repo.commit("guard the extra file")
        code, out, err = self.repo.run(["commit", fix, "--expect", "extra.py is gone", "--", PY, "test_app.py"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)
        self.assertIn("put back: extra.py", out)

    def test_deleted_file(self):
        """source: undoing a fix that deleted a file writes that file back when it is still absent."""
        self.repo.write("bad.py", "bug\n")
        self.repo.commit("start")
        os.remove(os.path.join(self.repo.repo, "bad.py"))
        fix = self.repo.commit("remove the bad file")
        self.repo.write("test_app.py", (
            "import os, sys\n"
            "if os.path.exists('bad.py'):\n"
            "    sys.stderr.write('bad.py came back\\n')\n"
            "    raise SystemExit(1)\n"
            "raise SystemExit(0)\n"
        ))
        self.repo.commit("guard the removal")
        code, out, err = self.repo.run(["commit", fix, "--expect", "bad.py came back", "--", PY, "test_app.py"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)

    def test_note_and_keep(self):
        """source: a fix that also changed a test file says so."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.write("test_app.py", "import app\nraise SystemExit(0 if app.VALUE == 1 else 1)\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        fix = self.repo.commit("fix the value and its test")
        code, out, err = self.repo.run(["commit", fix, "--expect", "value is 1", "--", PY, "test_app.py"])
        self.assertEqual(code, 1)
        self.assertNotIn("CAUGHT:", out)
        self.assertIn("which looks like a test, so it went back too. To keep today's version: --keep 'test_app.py'", out)

    def test_keep_everything(self):
        """source: keeping every file the fix changed leaves nothing to put back."""
        fix = self._fix_value()
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["commit", fix, "--keep", "app.py", "--", "true"])
        self.assertEqual(code, 2)
        self.assertIn("could not: every file the fix changed is kept; nothing to put back", err)
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_merge_commit(self):
        """source: a merge commit is not a fix, because it has more than one parent."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.commit("start")
        base = self.repo.branch()
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.write("other.py", "SIDE = 1\n")
        self.repo.commit("side work")
        self.repo.git("checkout", "-q", base)
        merged = self.repo.git(
            "-c", "user.name=test",
            "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false",
            "merge", "-q", "--no-ff", "--no-edit", "side",
        )
        self.assertEqual(merged.returncode, 0, merged.stderr.decode())
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["commit", self.repo.head(), "--", "true"])
        self.assertEqual(code, 2)
        self.assertIn("is a merge commit; name the commit that holds the fix", err)
        self.assertTrue(err.startswith("could not: "))
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_unknown_commit(self):
        """source: a name that is not a commit stops before any copy is made."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.commit("start")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["commit", "no-such-commit-name", "--", "true"])
        self.assertEqual(code, 2)
        self.assertIn("could not: no-such-commit-name is not a commit", err)
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_first_commit(self):
        """source: the first commit has no parent to restore."""
        self.repo.write("app.py", "VALUE = 1\n")
        first = self.repo.commit("start")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["commit", first, "--", "true"])
        self.assertEqual(code, 2)
        self.assertIn("is the first commit; there is no earlier version to go back to", err)
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_binary_is_stale(self):
        """source: a binary file is not merged, so the fix is reported stale."""
        self.repo.write("data.bin", b"a\0b")
        self.repo.commit("start")
        self.repo.write("data.bin", b"a\0c")
        fix = self.repo.commit("change the binary")
        code, out, err = self.repo.run(["commit", fix, "--", "true"])
        self.assertEqual(code, 1)
        self.assertIn("data.bin is binary", out)
        self.assertIn("STALE: could not put the bug back:", out)

    def test_tangled_followup(self):
        """source: a conflict tells the author to commit the fix alone."""
        self.repo.write("app.py", "LINE = 'base'\n")
        self.repo.commit("start")
        self.repo.write("app.py", "LINE = 'fixed'\n")
        fix = self.repo.commit("fix the line")
        self.repo.write("app.py", "LINE = 'rewritten later'\n")
        self.repo.commit("rewrite the same line")
        code, out, err = self.repo.run(["commit", fix, "--", "true"])
        self.assertEqual(code, 1, out + err)
        self.assertIn("The fix is tangled with later changes. Next time, commit a fix on its own.", out)

    def test_keep_leaves_the_test(self):
        """source: a keep glob leaves today's test file in place."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.write("test_app.py", "import app\nraise SystemExit(0 if app.VALUE == 1 else 1)\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        fix = self.repo.commit("fix the value and its test")
        code, out, err = self.repo.run([
            "commit", fix, "--keep", "test_*.py", "--expect", "value is 1", "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)
        self.assertIn("kept as it is today: test_app.py", out)

    def test_binary_followup(self):
        """source: a binary fix offers keep or swap, not the tangled-commit sentence."""
        self.repo.write("data.bin", b"a\0b")
        self.repo.commit("start")
        self.repo.write("data.bin", b"a\0c")
        fix = self.repo.commit("change the binary")
        code, out, err = self.repo.run(["commit", fix, "--", "true"])
        self.assertEqual(code, 1, out + err)
        self.assertIn("Keep that file as it is today with --keep, or name the bug with swap.", out)
        self.assertNotIn("tangled", out)

    def test_kept_line_only_when_a_file_was_kept(self):
        """source: the kept line is printed only when a file was kept."""
        fix = self._fix_value()
        code, out, err = self.repo.run(["commit", fix, "--", "true"])
        self.assertEqual(code, 1, out + err)
        self.assertIn("put back:", out)
        self.assertNotIn("kept as it is today:", out)

    def test_keep_glob_that_matches_nothing(self):
        """source: a keep glob that matches nothing still puts the bug back."""
        fix = self._fix_value()
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("guard")
        code, out, err = self.repo.run([
            "commit", fix, "--keep", "no-such-*", "--expect", "value is 1", "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT:", out)
        self.assertIn("put back:", out)
        self.assertNotIn("kept as it is today:", out)

    def test_mode_only_fix_is_caught(self):
        """source: a fix that only makes a script executable is put back, and the repository stays as it was."""
        path = self.repo.write("run.sh", "#!/bin/sh\nexit 0\n", mode=0o644)
        self.repo.commit("start")
        os.chmod(path, 0o755)
        fix = self.repo.commit("make the script executable")
        self.repo.write("check.py", (
            "import os, sys\n"
            "if not os.access('run.sh', os.X_OK):\n"
            "    sys.stderr.write('not executable\\n')\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("guard the bit")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run([
            "commit", fix, "--expect", "not executable", "--", PY, "check.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT:", out)
        self.repo.assert_same(self, shot)

    def test_mode_changed_since_the_fix(self):
        """source: a file whose executable bit changed after the fix is stale."""
        path = self.repo.write("run.sh", "#!/bin/sh\nexit 0\n", mode=0o644)
        self.repo.commit("start")
        os.chmod(path, 0o755)
        fix = self.repo.commit("make the script executable")
        os.chmod(path, 0o644)
        code, out, err = self.repo.run(["commit", fix, "--", "true"])
        self.assertEqual(code, 1, out + err)
        self.assertIn("run.sh changed mode since the fix", out)
        self.assertIn("STALE:", out)
