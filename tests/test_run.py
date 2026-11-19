"""source: the entry point returns an exit code and puts its handlers back."""
import io
import json
import os
import shutil
import signal
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers
import put_the_bug_back as tool

PY = helpers.PY
HANDLED = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def reset_state():
    tool.STATE.stopped = False
    tool.STATE.child = None
    tool.STATE.copy_dir = None
    tool.STATE.temps = []
    tool.STATE.stdout_silenced = False
    tool.STATE.force_remove = False
    tool.STATE.keep = False


def call_main(argv):
    reset_state()
    out = io.StringIO()
    err = io.StringIO()
    old_out = sys.stdout
    old_err = sys.stderr
    sys.stdout = out
    sys.stderr = err
    try:
        code = tool.main(list(argv))
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
    return code, out.getvalue(), err.getvalue()


class RunTests(helpers.Case):
    def setUp(self):
        self.saved_signals = {}
        for sig in HANDLED:
            self.saved_signals[sig] = signal.getsignal(sig)
        self.saved_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        self.addCleanup(lambda: signal.pthread_sigmask(signal.SIG_SETMASK, self.saved_mask))
        self.addCleanup(self._restore_signals)
        super(RunTests, self).setUp()

    def _restore_signals(self):
        for sig, previous in self.saved_signals.items():
            signal.signal(sig, previous)
        reset_state()

    def _main(self, argv):
        old = os.environ.copy()
        os.environ.clear()
        os.environ.update(self.repo.env)
        try:
            try:
                return call_main(argv)
            except Exception as exc:
                self.fail("main raised %s: %s" % (type(exc).__name__, exc))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_help_and_bare_arguments(self):
        """source: help is ordinary output, and a bare command is a usage error."""
        code, out, err = self._main(["--help"])
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        for word in ("commit", "swap", "all", "--keep", "--repo", "--expect", "--timeout", "--link", "--max-mb", "--find", "--replace", "--only", "--keep-copy", "--stale-only"):
            self.assertIn(word, out)
        code, out, err = self._main(["-h"])
        self.assertEqual(code, 0)
        self.assertIn("commit", out)
        self.assertEqual(err, "")
        code, out, err = self._main([])
        self.assertEqual(code, 2)
        self.assertIn("commit", err)
        self.assertIn("swap", err)
        self.assertIn("all", err)
        self.assertEqual(out, "")

    def test_explanations_use_stderr(self):
        """source: a refusal and a bad list are errors, and a verdict stays ordinary output."""
        code, out, err = self._main(["commit"])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("usage:"))
        self.assertNotIn("usage:", out)
        code, out, err = self._main(["all", "--repo", self.repo.repo])
        self.assertEqual(code, 2)
        self.assertIn("could not:", err)
        self.assertNotIn("could not:", out)
        path = self.repo.write("bad.json", json.dumps({
            "bugs": [{
                "id": "a", "guards": "g", "test": "true", "expect": "e",
                "file": "app.py", "find": "A", "replace": "A",
            }],
        }))
        code, out, err = self._main(["all", path, "--repo", self.repo.repo])
        self.assertEqual(code, 2)
        self.assertIn("BAD LIST:", err)
        self.assertNotIn("BAD LIST:", out)
        self.assertIn("could not:", err)

    def test_oserror_and_unexpected_return(self):
        """source: an operating-system error or any other error is exit two, without a traceback."""
        real = tool.dispatch

        def deny(argv):
            folder = tempfile.mkdtemp(prefix="put-the-bug-back-")
            deny.folder = folder
            tool.STATE.copy_dir = folder
            tool.STATE.keep = True
            err = OSError(13, "Permission denied")
            err.filename = "secret.txt"
            raise err

        tool.dispatch = deny
        try:
            code, out, err = self._main(["run"])
        finally:
            tool.dispatch = real
        self.assertEqual(code, 2, err)
        self.assertEqual(err, "could not: secret.txt: Permission denied\n")
        self.assertNotIn("Traceback", err + out)
        self.assertFalse(os.path.exists(deny.folder))

        def bare(argv):
            folder = tempfile.mkdtemp(prefix="put-the-bug-back-")
            bare.folder = folder
            tool.STATE.copy_dir = folder
            tool.STATE.keep = True
            raise OSError(13, "Permission denied")

        tool.dispatch = bare
        try:
            code, out, err = self._main(["run"])
        finally:
            tool.dispatch = real
        self.assertEqual(code, 2)
        self.assertEqual(err, "could not: Permission denied\n")
        self.assertFalse(os.path.exists(bare.folder))

        def boom(argv):
            folder = tempfile.mkdtemp(prefix="put-the-bug-back-")
            boom.folder = folder
            tool.STATE.copy_dir = folder
            tool.STATE.keep = True
            raise RuntimeError("boom")

        tool.dispatch = boom
        try:
            code, out, err = self._main(["run"])
        finally:
            tool.dispatch = real
        self.assertEqual(code, 2, err)
        self.assertEqual(err, "could not: unexpected error: RuntimeError: boom\n")
        self.assertNotIn("Traceback", out + err)
        self.assertFalse(os.path.exists(boom.folder))

    def test_closed_pipe_keeps_going(self):
        """source: a closed output pipe does not change the exit code or leave the copy."""
        saved_fd = os.dup(1)
        saved_out = sys.stdout
        saved_err = sys.stderr

        def restore_fd():
            os.dup2(saved_fd, 1)
            os.close(saved_fd)
            sys.stdout = saved_out
            sys.stderr = saved_err

        self.addCleanup(restore_fd)
        folder = tempfile.mkdtemp(prefix="put-the-bug-back-")
        self.addCleanup(shutil.rmtree, folder, True)
        reset_state()

        class Closed(object):
            def write(self, text):
                raise BrokenPipeError(32, "Broken pipe")

            def flush(self):
                pass

        real = tool.dispatch

        def plant(argv):
            tool.STATE.copy_dir = folder
            tool.STATE.keep = True
            return real(argv)

        err_buf = io.StringIO()
        sys.stderr = err_buf
        sys.stdout = Closed()
        tool.dispatch = plant
        try:
            try:
                code = tool.main(["--help"])
            except Exception as exc:
                self.fail("main raised %s: %s" % (type(exc).__name__, exc))
        finally:
            tool.dispatch = real
        err = err_buf.getvalue()
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(folder))

    def test_handlers_return_on_every_way_out(self):
        """source: handlers for terminate and hang-up are put back however the run ends."""

        def on_term(signum, frame):
            pass

        def on_hup(signum, frame):
            pass

        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGHUP, on_hup)
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        code, out, err = self._main([
            "swap", "app.py", "--repo", self.repo.repo,
            "--find", "VALUE = 2", "--replace", "VALUE = 1", "--", "true",
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("SURVIVED:", out)
        self.assertIs(signal.getsignal(signal.SIGTERM), on_term)
        self.assertIs(signal.getsignal(signal.SIGHUP), on_hup)
        code, out, err = self._main(["commit"])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("usage:"))
        self.assertIs(signal.getsignal(signal.SIGTERM), on_term)
        self.assertIs(signal.getsignal(signal.SIGHUP), on_hup)
        code, out, err = self._main(["all", "--repo", self.repo.repo])
        self.assertEqual(code, 2)
        self.assertIn("could not:", err)
        self.assertIs(signal.getsignal(signal.SIGTERM), on_term)
        self.assertIs(signal.getsignal(signal.SIGHUP), on_hup)
        real = tool.dispatch

        def interrupt(argv):
            raise KeyboardInterrupt()

        tool.dispatch = interrupt
        try:
            code, out, err = self._main(["run"])
        finally:
            tool.dispatch = real
        self.assertEqual(code, 130, err)
        self.assertIn("stopped", err)
        self.assertIs(signal.getsignal(signal.SIGTERM), on_term)
        self.assertIs(signal.getsignal(signal.SIGHUP), on_hup)

    def test_stop_line_is_the_only_error(self):
        """source: a stop writes one line and nothing else on the error stream."""
        reset_state()
        folder = tempfile.mkdtemp(prefix="put-the-bug-back-")
        self.addCleanup(shutil.rmtree, folder, True)
        tool.STATE.copy_dir = folder
        tool.STATE.keep = True
        old_err = sys.stderr
        buf = io.StringIO()
        sys.stderr = buf
        try:
            tool.perform_stop(signal.SIGTERM)
        finally:
            sys.stderr = old_err
        self.assertEqual(buf.getvalue(), "stopped\n")
        self.assertFalse(os.path.exists(folder))

    def test_further_stops_are_held(self):
        """source: a second stop during cleanup cannot interrupt removal of the copy."""
        previous = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        self.addCleanup(lambda: signal.pthread_sigmask(signal.SIG_SETMASK, previous))
        signal.pthread_sigmask(signal.SIG_UNBLOCK, set(HANDLED))
        folder = tempfile.mkdtemp(prefix="put-the-bug-back-")
        self.addCleanup(shutil.rmtree, folder, True)
        reset_state()
        tool.STATE.copy_dir = folder
        tool.STATE.keep = True
        seen = {}
        real = tool.shutil.rmtree

        def spy(path, ignore_errors=False):
            if tool.STATE.stopped:
                seen["mask"] = signal.pthread_sigmask(signal.SIG_BLOCK, set())
            return real(path, ignore_errors)

        tool.shutil.rmtree = spy
        old_err = sys.stderr
        sys.stderr = io.StringIO()
        try:
            tool.perform_stop(signal.SIGTERM)
        finally:
            sys.stderr = old_err
            tool.shutil.rmtree = real
        self.assertIn(signal.SIGTERM, seen.get("mask", set()))
        self.assertIn(signal.SIGHUP, seen.get("mask", set()))
        self.assertFalse(os.path.exists(folder))

    def test_restore_is_checked(self):
        """source: a restore that leaves the bug in place is an error, not a success."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        real = tool.Editor.write
        calls = {"n": 0}

        def fake(editor, rel, data, mode):
            calls["n"] += 1
            if calls["n"] >= 2:
                return
            return real(editor, rel, data, mode)

        tool.Editor.write = fake
        try:
            code, out, err = self._main([
                "swap", "app.py", "--repo", self.repo.repo,
                "--find", "VALUE = 2", "--replace", "VALUE = 1",
                "--expect", "value is 1", "--", PY, "-c",
                "import sys\n"
                "body = open('app.py').read()\n"
                "raise SystemExit(0 if 'VALUE = 2' in body else 1)\n",
            ])
        finally:
            tool.Editor.write = real
        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(code, 2, out + err)
        self.assertIn("could not: the copy did not restore after", err)
        self.assertNotIn("Traceback", err)

    def test_timeout_rejects_non_finite_numbers(self):
        """source: a timeout that is not a finite number of seconds is refused on the command and in a list."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        for text in ("nan", "inf", "1e999"):
            code, out, err = self._main([
                "swap", "app.py", "--repo", self.repo.repo,
                "--find", "VALUE = 2", "--replace", "VALUE = 1",
                "--timeout", text, "--", "true",
            ])
            self.assertEqual(code, 2, err)
            self.assertIn("usage: timeout must be a number of seconds", err)
            self.assertNotIn("Traceback", err + out)
        for raw in ("NaN", "Infinity", "1e999"):
            path = self.repo.write("odd.json", (
                '{"timeout": %s, "bugs": [{"id": "a", "guards": "g", "test": "true", '
                '"expect": "e", "file": "app.py", "find": "VALUE = 2", "replace": "VALUE = 1"}]}'
            ) % raw)
            code, out, err = self._main(["all", path, "--repo", self.repo.repo])
            self.assertEqual(code, 2, err)
            self.assertIn("could not: timeout is not a number of seconds", err)
            self.assertNotIn("Traceback", err + out)

    def test_max_mb_rejects_a_superscript(self):
        """source: a size limit must be written with ascii digits."""
        code, out, err = self._main([
            "swap", "f.py", "--find", "a", "--replace", "b",
            "--max-mb", "2\u00b2", "--", "true",
        ])
        self.assertEqual(code, 2, err)
        self.assertIn("usage: max-mb must be a whole number", err)
        self.assertNotIn("Traceback", err + out)
