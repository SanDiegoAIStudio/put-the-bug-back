"""source: the hand-run fixture and the demo leave a temp repository and agree with themselves."""
import fcntl
import os
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers


class DemoTests(helpers.Case):
    def _build(self, shell, folder):
        env = self.repo.env.copy()
        proc = subprocess.run(
            [shell, os.path.join(helpers.ROOT, "examples", "make_fixture.sh"), folder],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        return proc

    def _head(self, folder, name="HEAD"):
        proc = subprocess.run(
            ["git", "-C", folder, "rev-parse", name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.repo.env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        return proc.stdout.decode().strip()

    def test_fixture_is_repeatable(self):
        """source: building the made-up repository twice gives the same commits, and an existing folder is refused."""
        one = os.path.join(self.repo.base, "one")
        two = os.path.join(self.repo.base, "two")
        first = self._build("/bin/sh", one)
        self.assertEqual(first.returncode, 0, first.stderr.decode())
        self.assertIn("fixture ready:", first.stdout.decode())
        second = self._build("/bin/sh", two)
        self.assertEqual(second.returncode, 0, second.stderr.decode())
        for name in ("HEAD", "fix-button", "fix-share", "fix-score", "fix-footer"):
            self.assertEqual(self._head(one, name), self._head(two, name), name)
        again = self._build("/bin/sh", one)
        self.assertEqual(again.returncode, 2)
        self.assertIn("already exists", again.stderr.decode())
        if os.path.exists("/bin/dash"):
            three = os.path.join(self.repo.base, "three")
            dashed = self._build("/bin/dash", three)
            self.assertEqual(dashed.returncode, 0, dashed.stderr.decode())
            self.assertEqual(self._head(one), self._head(three))

    def test_demo_script(self):
        """source: the demo prints a caught fix, a survivor, a kept test, a stale fix, and a kept list."""
        proc = subprocess.run(
            ["/bin/sh", os.path.join(helpers.ROOT, "examples", "demo.sh")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.repo.env,
            timeout=240,
        )
        text = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, text + "\n" + err)
        self.assertIn("1. commit fix-button", text)
        self.assertIn("CAUGHT: red with the bug back, green without it", text)
        self.assertIn("2. commit fix-share", text)
        self.assertIn("SURVIVED:", text)
        self.assertIn("3. commit fix-score", text)
        self.assertIn("4. commit fix-footer", text)
        self.assertIn("STALE:", text)
        self.assertIn("5. all", text)
        self.assertIn("caught 1 of 1", text)
        self.assertIn("6. fixture untouched", text)

    def test_demo_terminate_exits_quietly(self):
        """source: a terminate ends the demo with the terminate status and no error line."""
        proc = subprocess.Popen(
            ["/bin/sh", os.path.join(helpers.ROOT, "examples", "demo.sh")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.repo.env,
            start_new_session=True,
            preexec_fn=lambda: signal.signal(signal.SIGTERM, signal.SIG_DFL),
        )
        try:
            flags = fcntl.fcntl(proc.stdout.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(proc.stdout.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
            seen = b""
            deadline = time.time() + 60
            while time.time() < deadline and b"1. commit" not in seen:
                if proc.poll() is not None:
                    break
                try:
                    chunk = os.read(proc.stdout.fileno(), 4096)
                except OSError:
                    chunk = b""
                if chunk:
                    seen += chunk
                else:
                    time.sleep(0.05)
            self.assertIn(b"1. commit", seen)
            os.killpg(proc.pid, signal.SIGTERM)
            out, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.communicate()
        text = (seen + out).decode("utf-8", "replace")
        errors = err.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 143, text + errors)
        self.assertNotIn("missing:", errors)
        self.assertNotIn("exit ", errors)
