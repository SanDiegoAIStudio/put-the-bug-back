"""source: the tool reads the repository, works in a copy, and removes that copy."""
import os
import signal
import stat
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers

PY = helpers.PY


def alive(pid):
    proc = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    text = proc.stdout.decode().strip()
    return bool(text) and not text.startswith("Z")


class SafetyTests(helpers.Case):
    def test_uncommitted_untracked_and_ignored(self):
        """source: the copy uses today's edits and new files, and leaves ignored files out."""
        self.repo.write("app.py", "VALUE = 1\n")
        self.repo.write(".gitignore", "secret.txt\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("secret.txt", "hidden\n")
        self.repo.write("test_new.py", (
            "import os, sys, app\n"
            "if os.path.exists('secret.txt'):\n"
            "    sys.stderr.write('secret was copied\\n')\n"
            "    raise SystemExit(1)\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "value is 1", "--", PY, "test_new.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)
        self.assertNotIn("secret was copied", out)

    def test_link_is_the_real_folder(self):
        """source: an ignored dependency folder is visible in the copy only through --link."""
        self.repo.write(".gitignore", "vendor/\n")
        self.repo.write("vendor/helper.py", "MARK = 'linked'\n")
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("test_app.py", (
            "import sys\n"
            "sys.path.insert(0, 'vendor')\n"
            "import helper, app\n"
            "if helper.MARK != 'linked':\n"
            "    raise SystemExit(1)\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        args = ["swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
                "--expect", "value is 1", "--", PY, "test_app.py"]
        code, out, err = self.repo.run(args)
        self.assertEqual(code, 1, out + err)
        self.assertIn("NOT GREEN: the test fails before any bug is put back", out)
        code, out, err = self.repo.run(args[:2] + ["--link", "vendor"] + args[2:])
        self.assertEqual(code, 0, out + err)
        self.assertIn("CAUGHT: red with the bug back, green without it", out)

    def test_direct_arguments_are_not_a_shell(self):
        """source: the test command after -- is executed as given, with its arguments intact."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("check.py", "import sys\nraise SystemExit(0 if sys.argv[1] == 'one two' else 1)\n")
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "check.py", "one two",
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("SURVIVED:", out)

    def test_timeout_kills_the_child(self):
        """source: the time limit kills the test and the child process it started."""
        self.repo.write("app.py", "MODE = 'FAST'\n")
        child_path = os.path.join(self.repo.base, "child.pid")
        parent_path = os.path.join(self.repo.base, "parent.pid")
        self.repo.write("sleep.py", (
            "import os, sys, time\n"
            "if 'SLOW' not in open('app.py').read():\n"
            "    raise SystemExit(0)\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    open(sys.argv[1], 'w').write(str(os.getpid()))\n"
            "    time.sleep(30)\n"
            "    os._exit(0)\n"
            "open(sys.argv[2], 'w').write(str(os.getpid()))\n"
            "time.sleep(30)\n"
        ))
        self.repo.commit("start")
        try:
            code, out, err = self.repo.run([
                "swap", "app.py", "--find", "FAST", "--replace", "SLOW", "--timeout", "1",
                "--", PY, "sleep.py", child_path, parent_path,
            ], timeout=30)
            self.assertEqual(code, 1, out + err)
            self.assertIn("WRONG REASON: the test went red, but not for the bug: timed out after 1 s", out)
            self.assertIn("bug gone  PASS", out)
            for path in (child_path, parent_path):
                with open(path, "r") as handle:
                    pid = int(handle.read().strip())
                self.assertFalse(alive(pid), pid)
        finally:
            for path in (child_path, parent_path):
                if os.path.exists(path):
                    pid = int(open(path).read().strip() or "0")
                    if pid and alive(pid):
                        os.kill(pid, 9)

    def test_keep_copy_and_max_mb(self):
        """source: --keep-copy leaves the copy and prints its path."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("run.sh", "#!/bin/sh\nexit 0\n", mode=0o755)
        os.symlink("app.py", os.path.join(self.repo.repo, "alias.py"))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--keep-copy", "--", "true",
        ])
        self.assertEqual(code, 1, out + err)
        self.assertIn("SURVIVED:", out)
        self.assertIn("copy kept:", out)
        kept = out.split("copy kept: ", 1)[1].splitlines()[0]
        self.assertTrue(os.path.isdir(kept))
        self.assertTrue(
            os.path.realpath(kept).startswith(os.path.realpath(self.repo.tmp) + os.sep)
        )
        self.assertTrue(os.path.islink(os.path.join(kept, "alias.py")))
        self.assertEqual(os.readlink(os.path.join(kept, "alias.py")), "app.py")
        mode = os.stat(os.path.join(kept, "run.sh")).st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        os.chmod(kept, 0o700)
        subprocess.run(["/bin/rm", "-rf", kept], check=False)

    def test_bytecode_and_mtime(self):
        """source: the test sees PYTHONDONTWRITEBYTECODE, and file times only move forward."""
        self.repo.write("app.py", "VALUE = 2\n")
        record = os.path.join(self.repo.base, "seen.txt")
        self.repo.write("check.py", (
            "import os, sys\n"
            "body = open('app.py').read()\n"
            "open(sys.argv[1], 'a').write('%s %s\\n' % (os.environ.get('PYTHONDONTWRITEBYTECODE', 'missing'), os.path.getmtime('app.py')))\n"
            "if 'VALUE = 2' not in body:\n"
            "    sys.stderr.write('value moved\\n')\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", self.repo.env)
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "value moved", "--", PY, "check.py", record,
        ])
        self.assertEqual(code, 0, out + err)
        rows = open(record).read().splitlines()
        self.assertEqual(len(rows), 3)
        for row in rows:
            flag, _stamp = row.split()
            self.assertEqual(flag, "1")

    def test_copy_is_removed_after_pass_failure_and_signal(self):
        """source: the temp copy is gone after a pass, after a failure, and after an interrupt."""
        self.repo.write("app.py", "MODE = 'FAST'\n")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.MODE != 'FAST':\n"
            "    sys.stderr.write('mode changed\\n')\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "FAST", "--replace", "SLOW",
            "--expect", "mode changed", "--", PY, "test_app.py",
        ])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.repo.copies(), [])
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "FAST", "--replace", "SLOW", "--", "true",
        ])
        self.assertEqual(code, 1)
        self.assertIn("SURVIVED:", out)
        self.assertEqual(self.repo.copies(), [])
        pid_path = os.path.join(self.repo.base, "sleep.pid")
        self.repo.write("sleep.py", (
            "import os, sys, time\n"
            "if open('app.py').read().strip() != \"MODE = 'SLOW'\":\n"
            "    raise SystemExit(0)\n"
            "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
            "time.sleep(30)\n"
        ))
        shot = self.repo.snapshot()
        proc = subprocess.Popen(
            [PY, helpers.TOOL, "swap", "app.py", "--repo", self.repo.repo,
             "--find", "FAST", "--replace", "SLOW", "--keep-copy",
             "--", PY, "sleep.py", pid_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.repo.env, cwd=self.repo.repo,
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
        )
        try:
            deadline = time.time() + 15
            while time.time() < deadline and not os.path.exists(pid_path):
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertTrue(os.path.exists(pid_path), proc.stdout.read() if proc.poll() is not None else "no pid")
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
            if os.path.exists(pid_path):
                pid = int(open(pid_path).read().strip() or "0")
                if pid and alive(pid):
                    os.kill(pid, 9)
        self.assertEqual(proc.returncode, 130, out.decode("utf-8", "replace") + err.decode("utf-8", "replace"))
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_repository_untouched_for_each_kind(self):
        """source: commit, swap, a list, a stale result, and a refusal all leave the repository as it was."""
        self.repo.write("app.py", "VALUE = 1\n\nNOTE = 'old'\n")
        self.repo.commit("start")
        self.repo.write("app.py", "VALUE = 2\n\nNOTE = 'old'\n")
        fix = self.repo.commit("fix the value")
        self.repo.write("test_app.py", (
            "import app, sys\n"
            "if app.VALUE != 2:\n"
            "    sys.stderr.write('value is %s\\n' % app.VALUE)\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.write("bugs.json", (
            '{"bugs":[{"id":"value","guards":"the value stays two","test":"%s test_app.py",'
            '"expect":"value is 1","file":"app.py","find":"VALUE = 2","replace":"VALUE = 1"},'
            '{"id":"twice","guards":"the note is one word","test":"%s test_app.py",'
            '"expect":"value is 1","file":"app.py","find":"NOTE","replace":"NAME"}]}\n'
        ) % (PY, PY))
        self.repo.commit("guard it")
        runs = [
            ["commit", fix, "--expect", "value is 1", "--", PY, "test_app.py"],
            ["swap", "app.py", "--find", "NOTE = 'old'", "--replace", "NOTE = 'new'", "--", PY, "test_app.py"],
            ["all", os.path.join(self.repo.repo, "bugs.json")],
            ["swap", "app.py", "--find", "NOTE", "--replace", "NAME", "--", "true"],
            ["commit", "no-such-commit-name", "--", "true"],
        ]
        for args in runs:
            shot = self.repo.snapshot()
            code, out, err = self.repo.run(args)
            self.assertIn(code, (0, 1, 2), out + err)
            self.assertEqual(self.repo.copies(), [])
            self.repo.assert_same(self, shot)

    def test_max_mb_refuses(self):
        """source: a copy over the size limit is refused before it is made."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        shot = self.repo.snapshot()
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--max-mb", "0", "--keep-copy", "--", "true",
        ])
        self.assertEqual(code, 2, out + err)
        self.assertIn("could not: the copy would be 1 MB (limit 0 MB); raise it with --max-mb", err)
        self.assertEqual(self.repo.copies(), [])
        self.repo.assert_same(self, shot)

    def test_mtime_moves_forward(self):
        """source: a changed file's time moves forward by a whole second."""
        self.repo.write("app.py", "VALUE = 2\n")
        record = os.path.join(self.repo.base, "seen.txt")
        self.repo.write("check.py", (
            "import os, sys\n"
            "open(sys.argv[1], 'a').write('%s\\n' % os.path.getmtime('app.py'))\n"
            "if 'VALUE = 2' not in open('app.py').read():\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--expect", "no", "--", PY, "check.py", record,
        ])
        self.assertEqual(code, 1, out + err)
        with open(record, "r") as handle:
            stamps = [float(line) for line in handle.read().splitlines()]
        self.assertEqual(len(stamps), 3)
        self.assertGreaterEqual(stamps[1] - stamps[0], 1)
        self.assertGreaterEqual(stamps[2] - stamps[1], 1)

    def test_copy_keeps_file_times(self):
        """source: the copy keeps a tracked file's modification time to the whole second."""
        path = self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        old = float(int(time.time() - 3600))
        os.utime(path, (old, old))
        record = os.path.join(self.repo.base, "mtime.txt")
        self.repo.write("check.py", (
            "import os, sys\n"
            "open(sys.argv[1], 'w').write('%r\\n' % os.stat('app.py').st_mtime)\n"
            "raise SystemExit(1)\n"
        ))
        self.repo.commit("guard")
        code, out, err = self.repo.run(["swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1", "--", PY, "check.py", record])
        self.assertEqual(code, 1, out + err)
        with open(record, "r") as handle:
            recorded = float(handle.read().strip())
        self.assertEqual(int(recorded), int(os.stat(path).st_mtime))

    def _expect_stop(self, sig, code):
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.commit("start")
        pid_path = os.path.join(self.repo.base, "nap.pid")

        def child(signum=sig):
            signal.signal(signum, signal.SIG_DFL)

        proc = subprocess.Popen(
            [PY, helpers.TOOL, "swap", "app.py", "--repo", self.repo.repo,
             "--find", "VALUE = 2", "--replace", "VALUE = 1", "--keep-copy",
             "--", PY, "-c",
             "import os,sys,time; open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(47)",
             pid_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.repo.env, cwd=self.repo.repo,
            preexec_fn=child, start_new_session=True,
        )
        recorded = 0
        try:
            deadline = time.time() + 15
            while time.time() < deadline and not os.path.exists(pid_path):
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
            self.assertTrue(os.path.exists(pid_path), "the test did not record its process")
            with open(pid_path, "r") as handle:
                recorded = int(handle.read().strip() or "0")
            proc.send_signal(sig)
            out, err = proc.communicate(timeout=15)
            text = out.decode("utf-8", "replace")
            errors = err.decode("utf-8", "replace")
            self.assertEqual(proc.returncode, code, text + errors)
            self.assertEqual(errors, "stopped\n")
            self.assertNotIn("Traceback", text + errors)
            self.assertEqual(self.repo.copies(), [])
            deadline = time.time() + 5
            while time.time() < deadline and alive(recorded):
                time.sleep(0.05)
            self.assertFalse(alive(recorded))
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.communicate()
            if recorded and alive(recorded):
                try:
                    os.kill(recorded, signal.SIGKILL)
                except OSError:
                    pass

    def test_interrupt_stops_the_command(self):
        """source: an interrupt kills the test, removes the copy, and exits with the interrupt status."""
        self._expect_stop(signal.SIGINT, 130)

    def test_terminate_stops_the_command(self):
        """source: a terminate kills the test, removes the copy, and exits with the terminate status."""
        self._expect_stop(signal.SIGTERM, 143)

    def test_hangup_stops_the_command(self):
        """source: a hang-up kills the test, removes the copy, and exits with the hang-up status."""
        self._expect_stop(signal.SIGHUP, 129)

    def test_ignored_hangup_stays_ignored(self):
        """source: a hang-up that is ignored when the tool starts stays ignored for the test."""
        self.repo.write("app.py", "VALUE = 2\n")
        flag = os.path.join(self.repo.base, "hup.txt")
        self.repo.write("check.py", (
            "import signal, sys\n"
            "text = 'ignored' if signal.getsignal(signal.SIGHUP) == signal.SIG_IGN else 'default'\n"
            "open(sys.argv[1], 'w').write(text)\n"
            "raise SystemExit(1)\n"
        ))
        self.repo.commit("start")

        def child():
            signal.signal(signal.SIGHUP, signal.SIG_IGN)

        proc = subprocess.Popen(
            [PY, helpers.TOOL, "swap", "app.py", "--repo", self.repo.repo,
             "--find", "VALUE = 2", "--replace", "VALUE = 1",
             "--", PY, "check.py", flag],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.repo.env, cwd=self.repo.repo, preexec_fn=child,
        )
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 1, out.decode("utf-8", "replace") + err.decode("utf-8", "replace"))
        with open(flag, "r") as handle:
            self.assertEqual(handle.read(), "ignored")

    def test_git_variables_do_not_reach_the_test(self):
        """source: the test command does not inherit the git variables of the caller."""
        self.repo.write("app.py", "VALUE = 2\n")
        record = os.path.join(self.repo.base, "gitvars.txt")
        self.repo.write("check.py", (
            "import os, sys\n"
            "names = sorted(key for key in os.environ if key.startswith('GIT_'))\n"
            "open(sys.argv[1], 'w').write('\\n'.join(names))\n"
            "raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        git_dir = os.path.join(self.repo.repo, ".git")
        env = self.repo.env.copy()
        env["GIT_DIR"] = git_dir
        env["GIT_WORK_TREE"] = self.repo.repo
        env["GIT_INDEX_FILE"] = os.path.join(git_dir, "index")
        env["GIT_OBJECT_DIRECTORY"] = os.path.join(git_dir, "objects")
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.path.join(git_dir, "objects")
        env["GIT_COMMON_DIR"] = git_dir
        env["GIT_PREFIX"] = ""
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "check.py", record,
        ], env=env)
        self.assertEqual(code, 1, out + err)
        with open(record, "r") as handle:
            names = handle.read().splitlines()
        for name in helpers.GIT_VARS:
            self.assertNotIn(name, names)

    def test_stdin_is_empty(self):
        """source: the test command does not read the tool's input."""
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("check.py", (
            "import sys\n"
            "data = sys.stdin.read()\n"
            "if data:\n"
            "    sys.stderr.write('saw stdin\\n')\n"
            "else:\n"
            "    sys.stderr.write('stdin empty\\n')\n"
            "raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        code, out, err = self.repo.run([
            "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
            "--", PY, "check.py",
        ], input=b"secret-from-parent\n")
        self.assertEqual(code, 1, out + err)
        self.assertIn("stdin empty", out)
        self.assertNotIn("saw stdin", out)

    def _holder(self, stay):
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("hold.py", (
            "import os, subprocess, sys, time\n"
            "pidfile = sys.argv[1]\n"
            "stay = sys.argv[2]\n"
            "subprocess.Popen(\n"
            "    [sys.executable, '-c',\n"
            "     'import os,sys,time; open(sys.argv[1],\"w\").write(str(os.getpid())); time.sleep(47)',\n"
            "     pidfile],\n"
            "    start_new_session=True,\n"
            ")\n"
            "if stay == 'yes':\n"
            "    time.sleep(30)\n"
            "raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        pid = os.path.join(self.repo.base, "holder.pid")
        started = time.time()
        try:
            code, out, err = self.repo.run([
                "swap", "app.py", "--find", "VALUE = 2", "--replace", "VALUE = 1",
                "--timeout", "2", "--", PY, "hold.py", pid, stay,
            ], timeout=70)
            elapsed = time.time() - started
            self.assertLess(elapsed, 10, out + err)
            self.assertEqual(code, 1, out + err)
        finally:
            if os.path.exists(pid):
                try:
                    recorded = int(open(pid).read().strip() or "0")
                except ValueError:
                    recorded = 0
                if recorded and alive(recorded):
                    try:
                        os.kill(recorded, signal.SIGKILL)
                    except OSError:
                        pass

    def test_timeout_does_not_wait_on_a_holder(self):
        """source: at the time limit the tool stops waiting on a process that kept the output open."""
        self._holder("yes")

    def test_finished_command_does_not_wait_on_a_holder(self):
        """source: once the test command has ended, a process in its own session does not hold the run open."""
        self._holder("no")

    def test_hook_can_commit_in_its_own_repository(self):
        """source: a hook can run the tool, and the test can commit in a repository of its own."""
        marker = os.path.join(self.repo.base, "inner.txt")
        self.repo.write("app.py", "VALUE = 2\n")
        self.repo.write("check.py", (
            "import os, shutil, subprocess, sys, tempfile\n"
            "base = tempfile.mkdtemp(prefix='ptbb-inner-')\n"
            "try:\n"
            "    repo = os.path.join(base, 'repo')\n"
            "    os.makedirs(repo)\n"
            "    env = os.environ.copy()\n"
            "    subprocess.check_call(['git', '-C', repo, 'init', '-q'], env=env)\n"
            "    top = subprocess.check_output(['git', '-C', repo, 'rev-parse', '--show-toplevel'], env=env)\n"
            "    if os.path.realpath(top.decode().strip()) != os.path.realpath(repo):\n"
            "        sys.stderr.write('toplevel drifted\\n')\n"
            "        raise SystemExit(2)\n"
            "    open(os.path.join(repo, 'f.txt'), 'w').write('x\\n')\n"
            "    subprocess.check_call(['git', '-C', repo, 'add', '-A'], env=env)\n"
            "    subprocess.check_call([\n"
            "        'git', '-C', repo, '-c', 'user.name=test',\n"
            "        '-c', 'user.email=test@example.com', '-c', 'commit.gpgsign=false',\n"
            "        'commit', '-q', '-m', 'inner',\n"
            "    ], env=env)\n"
            "    count = subprocess.check_output(['git', '-C', repo, 'rev-list', '--count', 'HEAD'], env=env)\n"
            "    fsck = subprocess.call(['git', '-C', repo, 'fsck'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)\n"
            "    if count.decode().strip() != '1' or fsck != 0:\n"
            "        sys.stderr.write('inner repository was not sound\\n')\n"
            "        raise SystemExit(2)\n"
            "    open(sys.argv[1], 'a').write('committed\\n')\n"
            "finally:\n"
            "    shutil.rmtree(base, ignore_errors=True)\n"
            "if 'VALUE = 2' not in open('app.py').read():\n"
            "    sys.stderr.write('value moved\\n')\n"
            "    raise SystemExit(1)\n"
        ))
        self.repo.commit("start")
        verdict = os.path.join(self.repo.base, "verdict.txt")
        hook_err = os.path.join(self.repo.base, "hook.err")
        hook = os.path.join(self.repo.repo, ".git", "hooks", "pre-commit")
        with open(hook, "w") as handle:
            handle.write("\n".join([
                "#!/bin/sh",
                "set -e",
                '"%s" "%s" swap app.py --repo "%s" --find "VALUE = 2" --replace "VALUE = 1" --expect "value moved" -- "%s" check.py "%s" > "%s" 2> "%s"' % (
                    PY, helpers.TOOL, self.repo.repo, PY, marker, verdict, hook_err,
                ),
                "exit $?",
                "",
            ]))
        os.chmod(hook, 0o755)
        self.repo.write("note.txt", "n\n")
        added = self.repo.git("add", "-A")
        self.assertEqual(added.returncode, 0, added.stderr.decode())
        proc = self.repo.git(
            "-c", "user.name=test",
            "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", "with the hook",
        )
        verdict_text = ""
        if os.path.exists(verdict):
            with open(verdict, "r") as handle:
                verdict_text = handle.read()
        hook_text = ""
        if os.path.exists(hook_err):
            with open(hook_err, "r") as handle:
                hook_text = handle.read()
        self.assertEqual(proc.returncode, 0, proc.stderr.decode() + verdict_text + hook_text)
        self.assertIn("CAUGHT:", verdict_text)
        self.assertEqual(self.repo.git("status", "--porcelain").stdout, b"")
        count = self.repo.git("rev-list", "--count", "HEAD").stdout.decode().strip()
        self.assertEqual(count, "2")
        fsck = self.repo.git("fsck")
        self.assertEqual(fsck.returncode, 0, fsck.stderr.decode() + fsck.stdout.decode())
