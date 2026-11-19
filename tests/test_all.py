"""source: a kept list rechecks every recorded bug in one copy."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers

PY = helpers.PY


def bug(ident, **extra):
    row = {
        "id": ident,
        "guards": "the value stays two",
        "test": "%s test_app.py" % PY,
        "expect": "value is 1",
    }
    row.update(extra)
    return row


class ListTests(helpers.Case):
    def _write_list(self, data, name="bugs.json"):
        text = data if isinstance(data, str) else json.dumps(data)
        self.repo.write(name, text)
        return os.path.join(self.repo.repo, name)

    def test_bad_list_problems(self):
        """source: every problem in a list is named before anything runs."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        outside = os.path.join(self.repo.base, "outside.py")
        data = {"bugs": [
            "not-an-object",
            {"extra": "x", "id": "bad-field", "guards": "g", "test": "t", "expect": "e", "fix": "abc"},
            {"guards": "g", "test": "t", "expect": "e", "fix": "abc"},
            {"id": "", "guards": "g", "test": "t", "expect": "e", "fix": "abc"},
            {"id": "nl", "guards": "a\nb", "test": "t", "expect": "e", "fix": "abc"},
            {"id": "num", "guards": "g", "test": 4, "expect": "e", "fix": "abc"},
            {"id": "same", "guards": "g", "test": "t", "expect": "e", "fix": "abc"},
            {"id": "same", "guards": "g", "test": "t", "expect": "e", "fix": "def"},
            {"id": "both", "guards": "g", "test": "t", "expect": "e", "fix": "abc", "file": "app.py", "find": "VALUE", "replace": "X"},
            {"id": "neither", "guards": "g", "test": "t", "expect": "e"},
            {"id": "fixline", "guards": "g", "test": "t", "expect": "e", "fix": ""},
            {"id": "keeptype", "guards": "g", "test": "t", "expect": "e", "fix": "abc", "keep": "app.py"},
            {"id": "keepon", "guards": "g", "test": "t", "expect": "e", "file": "app.py", "find": "VALUE", "replace": "X", "keep": ["app.py"]},
            {"id": "nofile", "guards": "g", "test": "t", "expect": "e", "find": "VALUE", "replace": "X"},
            {"id": "nofind", "guards": "g", "test": "t", "expect": "e", "file": "app.py", "replace": "X"},
            {"id": "norepl", "guards": "g", "test": "t", "expect": "e", "file": "app.py", "find": "VALUE"},
            {"id": "badrepl", "guards": "g", "test": "t", "expect": "e", "file": "app.py", "find": "VALUE", "replace": 3},
            {"id": "emptyfind", "guards": "g", "test": "t", "expect": "e", "file": "app.py", "find": "", "replace": "X"},
            {"id": "out", "guards": "g", "test": "t", "expect": "e", "file": outside, "find": "VALUE", "replace": "X"},
            {"id": "noexpect", "guards": "g", "test": "t", "fix": "abc"},
        ]}
        path = self._write_list(data, "bad.json")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 2)
        self.assertEqual(self.repo.copies(), [])
        wanted = [
            "a bug must be an object",
            "unknown field extra",
            "missing id",
            "id must be one line of text",
            "guards must be one line of text",
            "test must be one line of text",
            "the id same is used twice",
            "give fix, or file, find and replace, not both",
            "missing fix or file, find and replace",
            "fix must be one line of text",
            "keep must be a list of text",
            "keep is only for a fix commit",
            "missing file",
            "missing find",
            "missing replace",
            "replace must be text",
            "find must be one line of text",
            "is outside the repository",
            "missing expect",
        ]
        for phrase in wanted:
            self.assertIn(phrase, err, phrase)
        problems = [line for line in err.splitlines() if line.startswith("BAD LIST:")]
        self.assertIn("could not: the list has %d problems" % len(problems), err)
        self.assertGreaterEqual(len(problems), len(wanted))
        self.repo.assert_same(self, shot)

    def test_top_level_list_errors(self):
        """source: a list that cannot be read, or that names no bug, does no work."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        path = self._write_list("{", "bad.json")
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 2)
        self.assertIn("is not valid JSON", err)
        path = self._write_list({"color": 1, "bugs": [bug("one", fix="abc")]}, "bad.json")
        code, out, err = self.repo.run(["all", path])
        self.assertIn("has an unknown field color", err)
        path = self._write_list({"bugs": []})
        code, out, err = self.repo.run(["all", path])
        self.assertIn("names no bug, so nothing was checked", err)
        path = self._write_list({"nope": []}, "bad.json")
        code, out, err = self.repo.run(["all", path])
        self.assertIn("has no bugs field", err)
        path = self._write_list({"bugs": {}, }, "bad.json")
        code, out, err = self.repo.run(["all", path])
        self.assertIn("has no bugs field", err)
        for timeout in (True, 0, "soon"):
            path = self._write_list({"timeout": timeout, "bugs": [bug("one", fix="abc")]}, "bad.json")
            code, out, err = self.repo.run(["all", path])
            self.assertEqual(code, 2)
            self.assertIn("timeout is not a number of seconds", err)
        missing = os.path.join(self.repo.repo, "missing.json")
        code, out, err = self.repo.run(["all", missing])
        self.assertIn("could not be read", err)
        self.assertEqual(self.repo.copies(), [])

    def test_shared_test_runs_once_before(self):
        """source: one test string shared by three bugs is run once before any of them."""
        self.repo.write("app.py", "VALUE = 2\nOTHER = 5\nTHIRD = 7\n")
        counter = os.path.join(self.repo.base, "runs.txt")
        self.repo.write("test_app.py", (
            "import sys\n"
            "open(sys.argv[1], 'a').write(open('app.py').read().splitlines()[0] + '\\n')\n"
            "raise SystemExit(0)\n"
        ))
        self.repo.commit("start")
        command = "%s test_app.py %s" % (PY, counter)
        rows = []
        for ident, find, replace in (
            ("one", "VALUE = 2", "VALUE = 1"),
            ("two", "OTHER = 5", "OTHER = 0"),
            ("three", "THIRD = 7", "THIRD = 0"),
        ):
            rows.append({
                "id": ident, "guards": "a shared command", "test": command,
                "expect": "no such failure", "file": "app.py", "find": find, "replace": replace,
            })
        path = self._write_list({"bugs": rows})
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 1, out + err)
        with open(counter, "r") as handle:
            runs = handle.read().splitlines()
        self.assertEqual(len(runs), 4)
        self.assertEqual(runs[0], "VALUE = 2")
        self.assertNotIn("before    PASS", out)

    def test_second_bug_does_not_see_the_first(self):
        """source: the copy is restored after each bug, so the next bug sees today's file."""
        self.repo.write("app.py", "VALUE = 2\nOTHER = 5\n")
        self.repo.write("test_value.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
            "raise SystemExit(0 if app.OTHER == 5 else 1)\n"
        ))
        self.repo.write("test_other.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('leaked\\n')\n"
            "    raise SystemExit(1)\n"
            "if app.OTHER != 5:\n"
            "    sys.stderr.write('other moved\\n')\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        data = {"bugs": [
            bug("value", file="app.py", find="VALUE = 2", replace="VALUE = 1", test="%s test_value.py" % PY),
            {
                "id": "other", "guards": "the other number stays five",
                "test": "%s test_other.py" % PY, "expect": "other moved",
                "file": "app.py", "find": "OTHER = 5", "replace": "OTHER = 0",
            },
        ]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT value  the value stays two", out)
        self.assertIn("CAUGHT other  the other number stays five", out)
        self.assertIn("caught 2 of 2", out)
        self.assertNotIn("leaked", out)

    def test_only_and_unknown_id(self):
        """source: --only runs the named bug, and an unknown id stops the run."""
        self.repo.write("app.py", "VALUE = 2\nOTHER = 5\n")
        counter = os.path.join(self.repo.base, "runs.txt")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "open(sys.argv[1], 'a').write('run\\n')\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        command = "%s test_app.py %s" % (PY, counter)
        data = {"bugs": [
            bug("value", file="app.py", find="VALUE = 2", replace="VALUE = 1", test=command),
            bug("other", file="app.py", find="OTHER = 5", replace="OTHER = 0", test=command, expect="other"),
        ]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path, "--only", "value"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("caught 1 of 1", out)
        self.assertNotIn("other", out.split("caught 1 of 1")[0].split("CAUGHT value")[-1])
        with open(counter, "r") as handle:
            self.assertEqual(handle.read().count("run"), 2)
        code, out, err = self.repo.run(["all", path, "--only", "missing-id"])
        self.assertEqual(code, 2)
        self.assertIn("could not: no bug has the id missing-id", err)

    def test_stale_only_starts_no_test(self):
        """source: --stale-only reads the working files and does not start a test or a copy."""
        self.repo.write("app.py", "VALUE = 2\n")
        counter = os.path.join(self.repo.base, "runs.txt")
        self.repo.write("test_app.py", "import sys\nopen(sys.argv[1], 'w').write('ran')\n")
        self.repo.commit("start")
        command = "%s test_app.py %s" % (PY, counter)
        data = {"bugs": [
            bug("good", file="app.py", find="VALUE = 2", replace="VALUE = 1", test=command),
            bug("twice", file="app.py", find="VALUE", replace="X", test=command, guards="the word is unique"),
        ]}
        # VALUE occurs once. Use a doubled token for the stale bug.
        self.repo.write("app.py", "VALUE = 2\nMARK MARK\n")
        data["bugs"][1]["find"] = "MARK"
        path = self._write_list(data)
        shot = self.repo.snapshot()
        code, out, err = self.repo.run(["all", path, "--stale-only"])
        self.assertEqual(code, 1)
        self.assertIn("STALE twice  the text occurs 2 times in app.py; it must occur once", out)
        self.assertIn("2 bugs, 1 stale", out)
        self.assertNotIn("CAUGHT", out)
        self.assertFalse(os.path.exists(counter))
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)
        only_good = {"bugs": [data["bugs"][0]]}
        path = self._write_list(only_good, "good.json")
        code, out, err = self.repo.run(["all", path, "--stale-only"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("1 bug, 0 stale", out)
        self.assertEqual(self.repo.copies(), [])
        self.assertFalse(os.path.exists(counter))

    def test_not_green_list_and_empty_replace(self):
        """source: a shared red test marks each of its bugs, and an empty replacement is allowed."""
        self.repo.write("app.py", "VALUE = 2\nTOKEN = 'keep'\n")
        self.repo.write("test_app.py", "import sys\nsys.stderr.write('already red\\n')\nraise SystemExit(1)\n")
        self.repo.commit("start")
        command = "%s test_app.py" % PY
        data = {"bugs": [
            bug("one", file="app.py", find="VALUE = 2", replace="VALUE = 1", test=command),
            bug("two", file="app.py", find="TOKEN = 'keep'", replace="", test=command, guards="the token can be cleared"),
        ]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 1)
        self.assertIn("NOT GREEN one  the test fails before any bug is put back", out)
        self.assertIn("NOT GREEN two  the test fails before any bug is put back", out)
        self.assertIn("caught 0 of 2", out)

    def test_list_commit_that_is_not_a_commit_is_stale(self):
        """source: one bad fix name in a list is stale for that bug and the others still run."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        data = {"bugs": [
            {"id": "missing", "guards": "a commit that is not there", "test": "%s test_app.py" % PY,
             "expect": "value is 1", "fix": "no-such-commit-name"},
            bug("value", file="app.py", find="VALUE = 2", replace="VALUE = 1"),
        ]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 1, out + err)
        self.assertIn("STALE missing  no-such-commit-name is not a commit", out)
        self.assertIn("CAUGHT value  the value stays two", out)
        self.assertIn("caught 1 of 2", out)

    def test_default_list_path(self):
        """source: all with no list reads bugs.json at the top of the repository."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        self._write_list({"bugs": [bug("value", file="app.py", find="VALUE = 2", replace="VALUE = 1")]})
        code, out, err = self.repo.run(["all"])
        self.assertEqual(code, 0, out + err)
        self.assertIn("caught 1 of 1", out)

    def test_listed_fix_with_nothing_to_do_is_stale(self):
        """source: a listed fix with nothing to put back is stale, and the run continues."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.commit("start")
        empty = self.repo.git(
            "-c", "user.name=test",
            "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false",
            "commit", "--allow-empty", "-q", "-m", "empty",
        )
        self.assertEqual(empty.returncode, 0, empty.stderr.decode())
        empty_id = self.repo.head()
        self.repo.write("app.py", "VALUE = 2\nMARK MARK\n")
        fix = self.repo.commit("fix the value")
        command = "%s -c 'raise SystemExit(0)'" % PY
        data = {"bugs": [
            {"id": "empty", "guards": "an empty fix", "test": command, "expect": "x", "fix": empty_id},
            {"id": "kept", "guards": "a kept file", "test": command, "expect": "x", "fix": fix, "keep": ["app.py"]},
            {"id": "twice", "guards": "a repeated word", "test": command, "expect": "x",
             "file": "app.py", "find": "MARK", "replace": "NAME"},
        ]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 1, out + err)
        self.assertIn("STALE empty", out)
        self.assertIn("changed no file", out)
        self.assertIn("STALE kept", out)
        self.assertIn("every file the fix changed is kept; nothing to put back", out)
        self.assertIn("STALE twice", out)
        self.assertIn("caught 0 of 3", out)
        self.assertNotIn("could not:", err)
        code, out, err = self.repo.run(["all", path, "--stale-only"])
        self.assertEqual(code, 1, out + err)
        self.assertIn("STALE empty", out)
        self.assertIn("STALE kept", out)
        self.assertIn("3 bugs, 3 stale", out)
        self.assertEqual(self.repo.copies(), [])

    def test_find_must_differ(self):
        """source: a list swap whose two texts are the same is refused."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        data = {"bugs": [{
            "id": "same", "guards": "the texts differ", "test": "true", "expect": "x",
            "file": "app.py", "find": "VALUE = 2", "replace": "VALUE = 2",
        }]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 2, out + err)
        self.assertIn("BAD LIST: bug 1 (same): find and replace must differ", err)

    def test_one_problem(self):
        """source: one problem in a list is named in the singular."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        data = {"bugs": [{
            "id": "same", "guards": "the texts differ", "test": "true", "expect": "x",
            "file": "app.py", "find": "VALUE = 2", "replace": "VALUE = 2",
        }]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 2, err)
        self.assertIn("the list has 1 problem", err)
        self.assertNotIn("problems", err)

    def test_missing_list_names_the_path(self):
        """source: a missing default list names the path that was tried."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        code, out, err = self.repo.run(["all"])
        self.assertEqual(code, 2, err)
        self.assertIn("could not: no list at ", err)
        path = err.split("could not: no list at ", 1)[1].strip()
        self.assertEqual(
            os.path.realpath(path),
            os.path.realpath(os.path.join(self.repo.repo, "bugs.json")),
        )

    def test_list_command_cannot_start(self):
        """source: a list whose test cannot start says so, and the run does not call that a caught bug."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n")
        fix = self.repo.commit("fix the value")
        data = {"bugs": [
            bug("missing", fix=fix, test="no-such-command-zz"),
            bug("denied", fix=fix, test="exit 126"),
        ]}
        path = self._write_list(data)
        code, out, err = self.repo.run(["all", path])
        self.assertEqual(code, 1, out + err)
        self.assertIn("NOT GREEN missing  the test command could not start (exit 127)", out)
        self.assertIn("NOT GREEN denied  the test command could not start (exit 126)", out)
        self.assertIn("caught 0 of 2", out)

    def test_list_before_timeout(self):
        """source: a list whose test hits the time limit before a bug says it timed out."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n")
        fix = self.repo.commit("fix the value")
        pid = os.path.join(self.repo.base, "nap.pid")
        command = (
            "%s -c \"import os,sys,time; open('%s','w').write(str(os.getpid())); time.sleep(47)\""
            % (PY, pid)
        )
        data = {"timeout": 1, "bugs": [bug("slow", fix=fix, test=command)]}
        path = self._write_list(data)
        try:
            code, out, err = self.repo.run(["all", path], timeout=30)
            self.assertEqual(code, 1, out + err)
            self.assertIn(
                "NOT GREEN slow  the test timed out after 1 s before any bug was put back",
                out,
            )
        finally:
            if os.path.exists(pid):
                try:
                    with open(pid) as handle:
                        recorded = int(handle.read().strip() or "0")
                except ValueError:
                    recorded = 0
                if recorded:
                    try:
                        os.kill(recorded, 9)
                    except OSError:
                        pass
