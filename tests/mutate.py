"""Plant each kept bug in a copy of this folder and rerun the list.

The tool that runs is the one beside this file. The copy is what the bugs change.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "put_the_bug_back.py")
SKIP_DIRS = set([".git", "__pycache__"])
GIT_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)
RUN_LIMIT = 1800


def copy_tree(repo):
    for dirpath, dirnames, filenames in os.walk(ROOT):
        kept = []
        for name in dirnames:
            if name in SKIP_DIRS or name.startswith("."):
                continue
            src = os.path.join(dirpath, name)
            if os.path.islink(src):
                rel = os.path.relpath(src, ROOT)
                dest = os.path.join(repo, rel)
                parent = os.path.dirname(dest)
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent)
                os.symlink(os.readlink(src), dest)
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            if name != ".gitignore" and (name.startswith(".") or name.endswith(".pyc")):
                continue
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, ROOT)
            dest = os.path.join(repo, rel)
            parent = os.path.dirname(dest)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent)
            if os.path.islink(src):
                os.symlink(os.readlink(src), dest)
            else:
                shutil.copy2(src, dest)


def main():
    bindir = os.path.dirname(sys.executable)
    python3 = os.path.join(bindir, "python3")
    if not (os.path.isfile(python3) and os.access(python3, os.X_OK)):
        sys.stderr.write("python3 is not in %s\n" % bindir)
        return 2
    base = tempfile.mkdtemp(prefix="ptbb-mutate-")
    home = os.path.join(base, "home")
    tmp = os.path.join(base, "tmp")
    repo = os.path.join(base, "repo")
    os.makedirs(home)
    os.makedirs(tmp)
    os.makedirs(repo)
    env = os.environ.copy()
    env["HOME"] = home
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["TMPDIR"] = tmp
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    for name in GIT_VARS:
        env.pop(name, None)
    try:
        copy_tree(repo)
        init = subprocess.run(
            ["git", "-C", repo, "init", "-q"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        if init.returncode != 0:
            sys.stderr.write(init.stderr.decode("utf-8", "replace"))
            return 2
        top = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        if os.path.realpath(top.stdout.decode().strip()) != os.path.realpath(repo):
            sys.stderr.write("refusing to write git data outside the temp repository\n")
            return 2
        proc = subprocess.Popen(
            [sys.executable, TOOL, "all", os.path.join(repo, "bugs.json"), "--repo", repo],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=repo,
            start_new_session=True,
        )
        try:
            out_b, err_b = proc.communicate(timeout=RUN_LIMIT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            sys.stderr.write("the mutation run timed out\n")
            return 1
        text = out_b.decode("utf-8", "replace")
        sys.stdout.write(text)
        err = err_b.decode("utf-8", "replace")
        if err:
            sys.stderr.write(err)
        lines = text.splitlines()
        last = lines[-1] if lines else ""
        match = re.match(r"caught (\d+) of (\d+)$", last)
        if proc.returncode == 0 and match and match.group(1) == match.group(2) and int(match.group(1)) >= 50:
            return 0
        return 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
