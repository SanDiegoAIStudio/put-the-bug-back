"""source: swap mode replaces one exact piece of text and reads the test."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers

PY = helpers.PY


class SwapTests(helpers.Case):
    def _app(self):
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")

    def test_caught(self):
        """source: swapping the guarded text back makes the assertion fail."""
        self._app()
        shot = self.repo.snapshot()
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "value is 1", "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("before    PASS", out)
        self.assertIn("bug back  FAIL  the output holds \"value is 1\"", out)
        self.assertIn("bug gone  PASS", out)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_absolute_path_inside(self):
        """source: an absolute path that stays inside the repository is the same file."""
        self._app()
        path = os.path.join(self.repo.repo, "app.py")
        code, out, err = self.repo.run([
            "swap", path, "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "value is 1", "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)

    def test_survived(self):
        """source: a test that does not read the swapped text still passes."""
        self._app()
        self.repo.write("test_app.py", "raise SystemExit(0)\n")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 1)
        self.assertIn("SURVIVED: the test passed with the bug back. It checks something else, or nothing.", out)

    def test_wrong_reason(self):
        """source: red output that lacks the expected words is the wrong reason."""
        self._app()
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "a phrase the failure never prints", "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 1)
        self.assertIn("the output does not hold \"a phrase the failure never prints\"", out)
        self.assertIn("WRONG REASON: the test went red, but not for the bug:", out)

    def test_unchecked(self):
        """source: without expected text the red run is caught and the failure is shown."""
        self._app()
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 0, out)
        self.assertIn("CAUGHT, REASON NOT CHECKED:", out)
        self.assertIn("value is 1", out)

    def test_stale_twice(self):
        """source: text that occurs more than once is not swapped."""
        self.repo.write("app.py", "one one\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "one", "--replace", "two", "--", "true",
        ])
        self.assertEqual(code, 1)
        self.assertIn("STALE: could not put the bug back: the text occurs 2 times in app.py; it must occur once", out)
        self.assertNotIn("The fix is tangled", out)
        self.assertFalse(any(line.startswith("bug back") for line in out.splitlines()))

    def test_overlap(self):
        """source: a second search starts one byte later, so overlapping copies count."""
        self.repo.write("app.py", "aaa\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "aa", "--replace", "b", "--", "true",
        ])
        self.assertEqual(code, 1)
        self.assertIn("the text occurs 2 times in app.py; it must occur once", out)

    def test_missing_file(self):
        """source: a missing file is stale, and the passing test is not asked about a bug."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "missing.py", "--find", "VALUE", "--replace", "OTHER", "--", "true",
        ])
        self.assertEqual(code, 1)
        self.assertIn("before    PASS", out)
        self.assertIn("missing.py is missing", out)
        self.assertFalse(any(line.startswith("bug back") for line in out.splitlines()))

    def test_not_green_before(self):
        """source: swap mode also refuses a test that fails before the text changes."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", "import sys\nsys.stderr.write('already red\\n')\nraise SystemExit(1)\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 1)
        self.assertIn("already red", out)
        self.assertIn("NOT GREEN: the test fails before any bug is put back", out)

    def test_not_green_after(self):
        """source: after a swap, the test has to pass again on the restored file."""
        self.repo.write("app.py", "VALUE = 2\n")
        marker = os.path.join(self.repo.base, "seen")
        self.repo.write("check.py", (
            "import os, sys\n"
            "if os.path.exists(sys.argv[1]):\n"
            "    sys.stderr.write('ran again\\n')\n"
            "    raise SystemExit(1)\n"
            "open(sys.argv[1], 'w').write('x')\n"
            "raise SystemExit(0)\n"
        ))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "check.py", marker,
        ])
        self.assertEqual(code, 1)
        self.assertIn("NOT GREEN: the test did not pass again once the bug was gone", out)

    def test_literal_replacement(self):
        """source: $1, a backslash-n and & in the replacement stay characters, not patterns."""
        record = os.path.join(self.repo.base, "seen.bin")
        self.repo.write("token.txt", "HELLO")
        self.repo.write("check.py", (
            "import sys\n"
            "data = open('token.txt', 'rb').read()\n"
            "open(sys.argv[1], 'ab').write(data + b'\\n---\\n')\n"
            "sys.stdout.write(repr(data) + '\\n')\n"
            "raise SystemExit(0 if data == b'HELLO' else 1)\n"
        ))
        self.repo.commit("start")
        replacement = "cost $1 & \\n end"
        code, out, err = self.repo.run([
            "swap", "token.txt", "--find", "HELLO", "--replace", replacement,
            "--expect", "$1", "--", PY, "check.py", record,
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("$1", out)
        with open(record, "rb") as handle:
            parts = handle.read().split(b"\n---\n")
        self.assertEqual(parts[1], replacement.encode("utf-8"))
        self.assertNotIn(b"\n", parts[1])
        self.assertIn(b"$1", parts[1])
        self.assertIn(b"&", parts[1])

    def test_outside_path(self):
        """source: a path that leaves the repository is refused before a copy is made."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        outside = os.path.join(self.repo.base, "outside.txt")
        with open(outside, "w") as handle:
            handle.write("nope\n")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run([
            "swap", outside, "--find", "nope", "--replace", "yes", "--", "true",
        ])
        self.assertEqual(code, 2)
        self.assertIn("is outside the repository", err)
        self.assertTrue(err.startswith("could not: "))
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)
        code, out, err = self.repo.run([
            "swap", "../outside.txt", "--find", "nope", "--replace", "yes", "--", "true",
        ])
        self.assertEqual(code, 2)
        self.assertIn("outside.txt is outside the repository", err)

    def test_signal(self):
        """source: a test killed by a signal is red for the wrong reason."""
        self.repo.write("run.sh", "exit 0\n")
        os.chmod(os.path.join(self.repo.repo, "run.sh"), 0o755)
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "run.sh", "--find", "exit 0", "--replace", "kill -TERM $$",
            "--", "/bin/sh", "run.sh",
        ])
        self.assertEqual(code, 1)
        self.assertIn("WRONG REASON: the test went red, but not for the bug: killed by signal 15", out)

    def test_exit_127(self):
        """source: a command that cannot start is red for the wrong reason."""
        self.repo.write("run.sh", "exit 0\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "run.sh", "--find", "exit 0", "--replace", "exec does-not-exist-ptbb",
            "--", "/bin/sh", "run.sh",
        ])
        self.assertEqual(code, 1)
        self.assertIn("WRONG REASON: the test went red, but not for the bug: the command could not start", out)

    def test_empty_find_and_same_text(self):
        """source: an empty find, or a find equal to its replacement, is a usage error."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "", "--replace", "x", "--", "true",
        ])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("usage:"))
        self.assertEqual(out, "")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 2", "--", "true",
        ])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("usage:"))
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "", "--", "true",
        ])
        self.assertEqual(code, 2)
        self.assertIn("--expect must not be empty", err)

    def test_rebuild_when_source_is_newer(self):
        """source: a build step that trusts whole-second times rebuilds a source that was old."""
        src = self.repo.write("src.py", "TOKEN = 'GOOD'\n")
        self.repo.write("build.py", (
            "import os, sys\n"
            "src = 'src.py'\n"
            "out = 'product.txt'\n"
            "src_m = int(os.stat(src).st_mtime)\n"
            "prod_m = int(os.stat(out).st_mtime) if os.path.exists(out) else -1\n"
            "if src_m > prod_m:\n"
            "    open(out, 'w').write(open(src).read())\n"
            "text = open(out).read()\n"
            "if 'GOOD' not in text:\n"
            "    sys.stderr.write('product has %s\\n' % text.strip())\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        old = time.time() - 3600
        os.utime(src, (old, old))
        product = os.path.join(self.repo.repo, "product.txt")
        with open(product, "w") as handle:
            handle.write("TOKEN = 'GOOD'\n")
        code, out, err = self.repo.run([
            "swap", "src.py", "--find", "GOOD", "--replace", "BAD!",
            "--expect", "product has TOKEN = 'BAD!'", "--", PY, "build.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT:", out)

    def test_imported_module_same_length(self):
        """source: a same-length swap in an imported module is caught when the file time moves."""
        src = self.repo.write("mod.py", "VALUE = 'AAAA'\n")
        self.repo.write("check.py", (
            "import importlib.util\n"
            "import os\n"
            "import py_compile\n"
            "import sys\n"
            "src = 'mod.py'\n"
            "pyc = 'mod.pyc'\n"
            "src_m = int(os.stat(src).st_mtime)\n"
            "prod_m = int(os.stat(pyc).st_mtime) if os.path.exists(pyc) else -1\n"
            "if src_m > prod_m:\n"
            "    py_compile.compile(src, cfile=pyc, doraise=True)\n"
            "spec = importlib.util.spec_from_file_location('mod', pyc)\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "if module.VALUE != 'AAAA':\n"
            "    sys.stderr.write('value is %s\\n' % module.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        old = time.time() - 3600
        os.utime(src, (old, old))
        code, out, err = self.repo.run([
            "swap", "mod.py", "--find", "AAAA", "--replace", "BBBB",
            "--expect", "value is BBBB", "--", PY, "check.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT:", out)

    def test_stamp_is_whole_and_not_in_the_future(self):
        """source: a swapped file's time is a whole second and not later than the clock."""
        self.repo.write("app.py", "VALUE = 2\n")
        record = os.path.join(self.repo.base, "stamp.txt")
        self.repo.write("check.py", (
            "import os, sys, time\n"
            "body = open('app.py').read()\n"
            "if 'VALUE = 2' in body:\n"
            "    raise SystemExit(0)\n"
            "stamp = os.stat('app.py').st_mtime\n"
            "now = time.time()\n"
            "open(sys.argv[1], 'w').write('%r %r\\n' % (stamp, now))\n"
            "sys.stderr.write('stamped\\n')\n"
            "raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "stamped", "--", PY, "check.py", record,
        ])
        self.assertEqual(code, 0, out + err)
        with open(record, "r") as handle:
            text = handle.read().split()
        stamp = float(text[0])
        now = float(text[1])
        self.assertEqual(stamp, int(stamp))
        self.assertLessEqual(stamp, now)

    def test_bytes_that_are_not_text(self):
        """source: a swap still reads a file that holds a byte that is not text."""
        self.repo.write("app.py", b"one one\n\xff\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "one", "--replace", "two", "--", "true",
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("the text occurs 2 times", out)
        self.assertNotIn("Traceback", out + err)

    def test_direct_start_failure(self):
        """source: a test program that cannot be started is an error, not a verdict."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", "no-such-program-ptbb",
        ])
        self.assertEqual(code, 2, out + err)
        self.assertIn("could not: the test command could not start:", err)
        self.assertNotIn("NOT GREEN", out)
        self.assertNotIn("Traceback", out + err)
        self.assertEqual(self.repo.copies(), [])

    def test_before_timeout_message(self):
        """source: a time limit before any bug is put back says the test timed out."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        pid = os.path.join(self.repo.base, "nap.pid")
        try:
            code, out, err = self.repo.run([
                "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
                "--timeout", "1", "--",
                PY, "-c",
                "import os,sys,time; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(47)",
                pid,
            ], timeout=30)
            self.assertEqual(code, 1, out + err)
            self.assertIn("NOT GREEN: the test timed out after 1 s before any bug was put back", out)
            self.assertNotIn("WRONG REASON", out)
        finally:
            if os.path.exists(pid):
                try:
                    recorded = int(open(pid).read().strip() or "0")
                except ValueError:
                    recorded = 0
                if recorded:
                    try:
                        os.kill(recorded, 9)
                    except OSError:
                        pass

    def test_signal_shows_the_tail(self):
        """source: a signal on the bug-back run still shows the last lines of output."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("check.py", (
            "import os, sys, signal\n"
            "if 'VALUE = 2' in open('app.py').read():\n"
            "    raise SystemExit(0)\n"
            "for i in range(20):\n"
            "    sys.stdout.write('LINE-%d\\n' % i)\n"
            "sys.stdout.flush()\n"
            "os.kill(os.getpid(), signal.SIGTERM)\n"
        ))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "check.py",
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("WRONG REASON:", out)
        self.assertIn("LINE-19", out)
        self.assertNotIn("LINE-0\n", out)
        self.assertNotIn("LINE-4\n", out)

    def test_link_outside_is_refused(self):
        """source: a link that points outside the repository is refused."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        outside = os.path.join(self.repo.base, "outside")
        os.makedirs(outside)
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--link", outside, "--", "true",
        ])
        self.assertEqual(code, 2, out + err)
        self.assertIn("outside the repository", err)
        self.assertEqual(self.repo.copies(), [])

    def test_relative_paths_from_the_start_directory(self):
        """source: a relative file and a relative link are taken from the directory the tool was started in."""
        self.repo.write(".gitignore", "vendor\n")
        os.makedirs(os.path.join(self.repo.repo, "vendor"))
        self.repo.write("vendor/lib.txt", "lib\n")
        os.makedirs(os.path.join(self.repo.repo, "nested"))
        self.repo.write("nested/app.py", "VALUE = 2\n")
        self.repo.commit("start")
        nested = os.path.join(self.repo.repo, "nested")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--link", os.path.join("..", "vendor"), "--keep-copy",
            "--", PY, "-c", "import sys; raise SystemExit(1)",
        ], cwd=nested)
        try:
            self.assertEqual(code, 1, out + err)
            self.assertIn("NOT GREEN", out)
            self.assertIn("copy kept:", out)
            kept = out.split("copy kept: ", 1)[1].splitlines()[0]
            link = os.path.join(kept, "vendor")
            self.assertTrue(os.path.islink(link), out + err)
            self.assertEqual(os.path.realpath(link), os.path.realpath(os.path.join(self.repo.repo, "vendor")))
        finally:
            if "copy kept:" in out:
                kept = out.split("copy kept: ", 1)[1].splitlines()[0]
                if os.path.isdir(kept):
                    os.chmod(kept, 0o700)
                    import shutil
                    shutil.rmtree(kept, ignore_errors=True)
