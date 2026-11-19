"""Temp repositories for the put-the-bug-back tests.

Every git command runs inside a folder this process created. The tool is always
pointed at that folder with --repo.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "put_the_bug_back.py")
PY = sys.executable
GIT_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


class Repo(object):
    def __init__(self, base):
        self.base = base
        self.home = os.path.join(self.base, "home")
        self.tmp = os.path.join(self.base, "tmp")
        self.repo = os.path.join(self.base, "repo")
        os.makedirs(self.home)
        os.makedirs(self.tmp)
        os.makedirs(self.repo)
        self.env = os.environ.copy()
        self.env["HOME"] = self.home
        self.env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        self.env["GIT_CONFIG_SYSTEM"] = "/dev/null"
        self.env["TMPDIR"] = self.tmp
        self.env.pop("PYTHONDONTWRITEBYTECODE", None)
        for name in GIT_VARS:
            self.env.pop(name, None)
        self.git("init", "-q")
        top = self.git("rev-parse", "--show-toplevel").stdout.decode().strip()
        # Stop if git's toplevel is not this temp folder.
        if os.path.realpath(top) != os.path.realpath(self.repo):
            raise RuntimeError("refusing to write git data outside the temp repository")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", self.repo] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )

    def write(self, rel, text, mode=None):
        path = os.path.join(self.repo, rel)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        with open(path, "wb") as handle:
            handle.write(data)
        if mode is not None:
            os.chmod(path, mode)
        return path

    def commit(self, message):
        added = self.git("add", "-A")
        if added.returncode != 0:
            raise RuntimeError(added.stderr.decode())
        proc = self.git(
            "-c", "user.name=test",
            "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false",
            "commit", "-q", "-m", message,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode())
        return self.head()

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def branch(self):
        return self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.decode().strip()

    def run(self, args, timeout=90, cwd=None, env=None, input=None):
        cmd = [PY, TOOL, args[0], "--repo", self.repo] + list(args[1:])
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env if env is None else env,
            cwd=self.repo if cwd is None else cwd,
            input=input,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

    def copies(self):
        return [name for name in os.listdir(self.tmp) if name.startswith("put-the-bug-back")]

    def snapshot(self):
        files = {}
        for dirpath, dirnames, filenames in os.walk(self.repo):
            if ".git" in dirnames:
                dirnames.remove(".git")
            for name in filenames:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, self.repo)
                if os.path.islink(path):
                    files[rel] = ("link", os.readlink(path))
                else:
                    with open(path, "rb") as handle:
                        files[rel] = ("file", handle.read())
        return {
            "status": self.git("status", "--porcelain").stdout,
            "head": self.git("rev-parse", "HEAD").stdout,
            "branch": self.git("branch", "--list").stdout,
            "stash": self.git("stash", "list").stdout,
            "worktree": self.git("worktree", "list", "--porcelain").stdout,
            "files": files,
        }

    def assert_same(self, case, shot):
        now = self.snapshot()
        case.assertEqual(now["status"], shot["status"])
        case.assertEqual(now["head"], shot["head"])
        case.assertEqual(now["branch"], shot["branch"])
        case.assertEqual(now["stash"], shot["stash"])
        case.assertEqual(now["worktree"], shot["worktree"])
        case.assertEqual(sorted(now["files"]), sorted(shot["files"]))
        for rel, item in shot["files"].items():
            case.assertEqual(now["files"][rel], item, rel)

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


class Case(unittest.TestCase):
    def setUp(self):
        self.repo = None
        base = tempfile.mkdtemp(prefix="ptbb-test-")
        self.addCleanup(shutil.rmtree, base, True)
        if shutil.which("git") is None:
            self.fail("git is not installed")
        self.repo = Repo(base)

    def tearDown(self):
        if getattr(self, "repo", None) is not None:
            self.repo.close()
