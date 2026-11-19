#!/usr/bin/env python3
"""Put a fixed bug back and see whether its test goes red."""
import fnmatch
import json
import math
import os
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time


GIT_COMMANDS = set([
    "rev-parse", "ls-files", "diff", "cat-file", "show", "merge-file",
])
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
STOP_CODES = {
    signal.SIGINT: 130,
    signal.SIGTERM: 143,
    signal.SIGHUP: 129,
}
GIT_ENV_DROP = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)
DRAIN_SECONDS = 2
BUG_FIELDS = set([
    "id", "guards", "test", "expect", "fix", "keep", "file", "find", "replace",
])
TOP_FIELDS = set(["bugs", "timeout", "link"])
NEEDS_VALUE = {
    "--keep": "keep",
    "--repo": "repo",
    "--expect": "expect",
    "--timeout": "timeout",
    "--link": "link",
    "--max-mb": "max_mb",
    "--find": "find",
    "--replace": "replace",
    "--only": "only",
}


class CouldNot(Exception):
    pass


class Usage(Exception):
    pass


class State(object):
    def __init__(self):
        self.copy_dir = None
        self.keep = False
        self.child = None
        self.temps = []
        self.stopped = False
        self.stdout_silenced = False
        self.force_remove = False


class Outcome(object):
    def __init__(self):
        self.code = 1
        self.out = ""
        self.timed_out = False
        self.signal = None
        self.start_error = False
        self.reason = ""


STATE = State()


def cleanup():
    for path in list(STATE.temps):
        shutil.rmtree(path, ignore_errors=True)
    del STATE.temps[:]
    remove_copy = STATE.stopped or STATE.force_remove or not STATE.keep
    if STATE.copy_dir and remove_copy:
        shutil.rmtree(STATE.copy_dir, ignore_errors=True)
        STATE.copy_dir = None


def kill_group(pid):
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


def hold_stop_signals():
    signal.pthread_sigmask(signal.SIG_BLOCK, set(STOP_SIGNALS))


def perform_stop(signum):
    if STATE.stopped:
        return
    STATE.stopped = True
    hold_stop_signals()
    if STATE.child:
        kill_group(STATE.child)
        STATE.child = None
    cleanup()
    complain("stopped")


def on_stop(signum, frame):
    perform_stop(signum)
    raise SystemExit(STOP_CODES[signum])


def install_one(sig):
    previous = signal.getsignal(sig)
    if previous == signal.SIG_IGN:
        return {}
    signal.signal(sig, on_stop)
    return {sig: previous}


def install_stop_handlers():
    saved = {}
    saved.update(install_one(signal.SIGINT))
    saved.update(install_one(signal.SIGTERM))
    saved.update(install_one(signal.SIGHUP))
    return saved


def restore_handlers(saved):
    for sig, previous in saved.items():
        signal.signal(sig, previous)


def silence_stdout():
    if STATE.stdout_silenced:
        return
    STATE.stdout_silenced = True
    STATE.force_remove = True
    try:
        null_fd = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(null_fd, 1)
    finally:
        os.close(null_fd)
    try:
        sys.stdout = open(os.devnull, "w")
    except OSError:
        pass


def write_out(text):
    if STATE.stdout_silenced:
        return
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except OSError:
        silence_stdout()


def say(line):
    write_out(line + "\n")


def complain(line):
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except OSError:
        pass


def help_text():
    lines = [
        "python3 put_the_bug_back.py commit FIX [--keep GLOB]... [options] -- TEST COMMAND...",
        "python3 put_the_bug_back.py swap FILE --find OLD --replace NEW [options] -- TEST COMMAND...",
        "python3 put_the_bug_back.py all [LIST] [--only ID] [--stale-only] [options]",
        "--keep GLOB       keep a file the fix changed",
        "--repo PATH       repository to read",
        "--expect TEXT     words the failure must contain",
        "--timeout N       seconds for one test run",
        "--link PATH       place a link to a file or folder in the copy",
        "--max-mb N        largest copy, in megabytes",
        "--find TEXT       text as it stands today",
        "--replace TEXT    buggy text to put back",
        "--only ID         run one bug from the list",
        "--keep-copy       leave the copy and print its path",
        "--stale-only      report stale bugs and run no test",
        "-h, --help        print this help",
    ]
    return "\n".join(lines) + "\n"


def report_oserror(err):
    reason = err.strerror
    if not reason:
        reason = str(err)
    name = err.filename
    if name:
        complain("could not: %s: %s" % (name, reason))
    else:
        complain("could not: %s" % reason)
    return 2


def outside_message(path):
    return "%s is outside the repository" % path


def not_a_commit(name):
    return "%s is not a commit" % name


def restore_message(name):
    return "the copy did not restore after %s" % name


def git(repo, args):
    if not args or args[0] not in GIT_COMMANDS:
        raise CouldNot("git is not available for that")
    return subprocess.run(
        ["git", "-C", repo] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def find_repo(explicit):
    if explicit:
        start = explicit
    else:
        start = os.getcwd()
    proc = git(start, ["rev-parse", "--show-toplevel"])
    if proc.returncode != 0:
        raise CouldNot("not inside a git repository")
    return proc.stdout.decode("utf-8", "replace").strip()


def start_dir(repo):
    root = os.path.realpath(repo)
    cwd = os.path.realpath(os.getcwd())
    try:
        if os.path.commonpath([root, cwd]) == root:
            return os.getcwd()
    except ValueError:
        pass
    return repo


def inside(repo, path, from_start=False):
    root = os.path.realpath(repo)
    if os.path.isabs(path):
        joined = path
    elif from_start:
        joined = os.path.join(start_dir(repo), path)
    else:
        joined = os.path.join(root, path)
    real = os.path.realpath(os.path.abspath(joined))
    try:
        if os.path.commonpath([root, real]) != root or real == root:
            return None
    except ValueError:
        return None
    return os.path.relpath(real, root)


def number_text(value):
    if float(value) == int(value):
        return str(int(value))
    return str(value)


def run_line(label, status, extra=None):
    text = label + (" " * (10 - len(label))) + status
    if extra:
        return text + "  " + extra
    return text


def show_tail(text):
    lines = text.splitlines()
    if lines:
        say("\n".join(lines[-15:]))


def take(raw, index, name):
    if index + 1 >= len(raw):
        raise Usage("give a value for %s" % name)
    return raw[index + 1], index + 2


def acceptable_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if not math.isfinite(value):
        return False
    if value <= 0:
        return False
    return True


def parse_timeout(text):
    try:
        value = float(text)
    except ValueError:
        raise Usage("timeout must be a number of seconds")
    if not acceptable_timeout(value):
        raise Usage("timeout must be a number of seconds")
    return value


def ascii_digits(text):
    if not text:
        return False
    for ch in text:
        if ch < "0" or ch > "9":
            return False
    return True


def parse_mb(text):
    if not ascii_digits(text):
        raise Usage("max-mb must be a whole number")
    return int(text)


def parse_args(argv):
    command = argv[0]
    if command not in ("commit", "swap", "all"):
        raise Usage("python3 put_the_bug_back.py commit|swap|all ...")
    raw = list(argv[1:])
    test = None
    if command in ("commit", "swap"):
        if "--" not in raw:
            raise Usage("give the test command after --")
        cut = raw.index("--")
        test = raw[cut + 1:]
        raw = raw[:cut]
        if not test:
            raise Usage("give the test command after --")
    elif "--" in raw:
        raise Usage("all does not take a test command")
    opts = {
        "command": command,
        "test": test,
        "keep": [],
        "repo": None,
        "expect": None,
        "timeout": None,
        "link": [],
        "max_mb": 200,
        "keep_copy": False,
        "find": None,
        "replace": None,
        "saw_find": False,
        "saw_replace": False,
        "only": None,
        "stale_only": False,
        "positionals": [],
    }
    index = 0
    while index < len(raw):
        item = raw[index]
        if item in NEEDS_VALUE:
            value, index = take(raw, index, item)
            key = NEEDS_VALUE[item]
            if key in ("keep", "link"):
                opts[key].append(value)
            elif key == "timeout":
                opts[key] = parse_timeout(value)
            elif key == "max_mb":
                opts[key] = parse_mb(value)
            else:
                opts[key] = value
            opts["saw_find"] = opts["saw_find"] or item == "--find"
            opts["saw_replace"] = opts["saw_replace"] or item == "--replace"
        elif item == "--keep-copy":
            opts["keep_copy"] = True
            index += 1
        elif item == "--stale-only":
            opts["stale_only"] = True
            index += 1
        elif item.startswith("-"):
            raise Usage("unknown option %s" % item)
        else:
            opts["positionals"].append(item)
            index += 1
    check_shape(opts)
    return opts


def check_shape(opts):
    command = opts["command"]
    count = len(opts["positionals"])
    if command == "commit":
        if opts["saw_find"] or opts["saw_replace"] or opts["only"] or opts["stale_only"]:
            raise Usage("commit takes a fix, options, and a test command after --")
        if opts["expect"] == "":
            raise Usage("--expect must not be empty")
        if count != 1:
            raise Usage("commit takes the fix commit before --")
    elif command == "swap":
        if opts["keep"] or opts["only"] or opts["stale_only"]:
            raise Usage("swap takes a file, --find, --replace, and a test command after --")
        if count != 1:
            raise Usage("swap takes the file before --")
        if not opts["saw_find"] or not opts["saw_replace"]:
            raise Usage("swap needs --find and --replace")
        if opts["find"] == "":
            raise Usage("--find must not be empty")
        if opts["expect"] == "":
            raise Usage("--expect must not be empty")
        if opts["find"] == opts["replace"]:
            raise Usage("--find and --replace must differ")
    else:
        if opts["keep"] or opts["saw_find"] or opts["saw_replace"] or opts["expect"] is not None:
            raise Usage("all takes a list, --only, --stale-only, and the shared options")
        if count > 1:
            raise Usage("all takes one list file")


def list_work_files(repo):
    proc = git(repo, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    if proc.returncode != 0:
        raise CouldNot("not inside a git repository")
    rels = []
    total = 0
    for part in proc.stdout.split(b"\0"):
        if not part:
            continue
        rel = part.decode("utf-8", "replace")
        full = os.path.join(repo, rel)
        if not os.path.lexists(full):
            continue
        info = os.lstat(full)
        if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            rels.append(rel)
            total += info.st_size
    return rels, total


def copy_one(repo, copy, rel):
    src = os.path.join(repo, rel)
    dst = os.path.join(copy, rel)
    parent = os.path.dirname(dst)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    info = os.lstat(src)
    if stat.S_ISLNK(info.st_mode):
        os.symlink(os.readlink(src), dst)
        return
    shutil.copyfile(src, dst)
    os.chmod(dst, stat.S_IMODE(info.st_mode))
    os.utime(dst, (info.st_atime, info.st_mtime))


def place_link(repo, copy, link):
    rel = inside(repo, link)
    real_base = os.path.realpath(os.path.join(repo, rel))
    if not os.path.lexists(os.path.join(repo, rel)):
        raise CouldNot("%s does not exist" % link)
    dest = os.path.join(copy, rel)
    parent = os.path.dirname(dest)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if os.path.lexists(dest):
        if os.path.isdir(dest) and not os.path.islink(dest):
            raise CouldNot("%s is already in the copy" % link)
        os.remove(dest)
    os.symlink(real_base, dest)


def make_copy(repo, opts):
    for link in opts["link"]:
        if inside(repo, link) is None:
            raise CouldNot(outside_message(link))
    rels, total = list_work_files(repo)
    limit = opts["max_mb"] * 1024 * 1024
    if total > limit:
        shown = (total + 1024 * 1024 - 1) // (1024 * 1024)
        raise CouldNot(
            "the copy would be %d MB (limit %d MB); raise it with --max-mb"
            % (shown, opts["max_mb"])
        )
    path = tempfile.mkdtemp(prefix="put-the-bug-back-")
    STATE.copy_dir = path
    if STATE.keep:
        say("copy kept: %s" % path)
    for rel in rels:
        copy_one(repo, path, rel)
    for link in opts["link"]:
        place_link(repo, path, link)
    return path


def resolve_commit(repo, name):
    proc = git(repo, ["rev-parse", "--verify", "--quiet", "%s^{commit}" % name])
    if proc.returncode != 0 or not proc.stdout.strip():
        raise CouldNot(not_a_commit(name))
    commit = proc.stdout.strip().decode("utf-8", "replace")
    proc = git(repo, ["cat-file", "-p", commit])
    if proc.returncode != 0:
        raise CouldNot(not_a_commit(name))
    parents = []
    for line in proc.stdout.splitlines():
        if line == b"":
            break
        if line.startswith(b"parent "):
            parents.append(line.split()[1].decode("utf-8", "replace"))
    if not parents:
        raise CouldNot(
            "%s is the first commit; there is no earlier version to go back to" % name
        )
    if len(parents) > 1:
        raise CouldNot(
            "%s is a merge commit; name the commit that holds the fix" % name
        )
    return commit, parents[0]


def blob(repo, rev, rel):
    proc = git(repo, ["cat-file", "blob", "%s:%s" % (rev, rel)])
    if proc.returncode == 0:
        return proc.stdout
    return None


def is_exec(mode):
    return bool(stat.S_IMODE(mode) & 0o111)


def with_exec(mode, executable):
    mode = stat.S_IMODE(mode)
    if executable:
        return mode | 0o111
    return mode & ~0o111


def changed_files(repo, parent, commit):
    proc = git(repo, ["diff", "--raw", "--no-renames", "-z", parent, commit])
    if proc.returncode != 0:
        raise CouldNot("the fix could not be read")
    parts = proc.stdout.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    rows = []
    index = 0
    while index + 1 < len(parts):
        header = parts[index].decode("utf-8", "replace")
        rel = parts[index + 1].decode("utf-8", "replace")
        index += 2
        if not header.startswith(":"):
            continue
        bits = header[1:].split()
        if len(bits) < 5:
            continue
        old_mode = int(bits[0], 8)
        new_mode = int(bits[1], 8)
        status = bits[4][:1]
        rows.append((status, rel, old_mode, new_mode))
    return rows


def path_is_kept(rel, globs):
    for glob in globs:
        if fnmatch.fnmatchcase(rel, glob):
            return True
    return False


def merge_three(repo, current, at_fix, at_parent):
    folder = tempfile.mkdtemp(prefix="put-the-bug-back-merge-")
    STATE.temps.append(folder)
    try:
        paths = []
        for name, data in zip(("current", "fix", "parent"), (current, at_fix, at_parent)):
            path = os.path.join(folder, name)
            write_bytes(path, data)
            paths.append(path)
        proc = git(repo, ["merge-file", "-p", paths[0], paths[1], paths[2]])
        return proc.returncode, proc.stdout
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        if folder in STATE.temps:
            STATE.temps.remove(folder)


def working_mode_problem(path, rel, new_mode):
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    current_mode = stat.S_IMODE(os.lstat(path).st_mode)
    if is_exec(current_mode) != is_exec(new_mode):
        return "%s changed mode since the fix" % rel
    return None


def undo_path(repo, root, commit, parent, status, rel, old_mode, new_mode):
    path = os.path.join(root, rel)
    if status == "A":
        at_fix = blob(repo, commit, rel)
        if at_fix is None or not os.path.lexists(path):
            return ("stale", "%s is missing" % rel)
        problem = working_mode_problem(path, rel, new_mode)
        if problem:
            return ("stale", problem)
        if os.path.islink(path):
            current = os.readlink(path).encode("utf-8")
            same = current == at_fix.rstrip(b"\n")
        elif os.path.isfile(path):
            same = read_bytes(path) == at_fix
        else:
            return ("stale", "%s is missing" % rel)
        if not same:
            return ("stale", "%s changed since the fix added it" % rel)
        return ("ok", ("delete", rel))
    if status == "D":
        if os.path.lexists(path):
            return ("stale", "%s changed since the fix deleted it" % rel)
        data = blob(repo, parent, rel)
        if data is None:
            return ("stale", "%s is missing" % rel)
        return ("ok", ("write", rel, data))
    if status != "M":
        return ("stale", "%s is not a simple text change" % rel)
    if os.path.islink(path) or not os.path.isfile(path):
        return ("stale", "%s is missing" % rel)
    problem = working_mode_problem(path, rel, new_mode)
    if problem:
        return ("stale", problem)
    current = read_bytes(path)
    at_fix = blob(repo, commit, rel)
    at_parent = blob(repo, parent, rel)
    if at_fix is None or at_parent is None:
        return ("stale", "%s is missing" % rel)
    if b"\0" in current or b"\0" in at_fix or b"\0" in at_parent:
        return ("stale", "%s is binary" % rel)
    code, merged = merge_three(repo, current, at_fix, at_parent)
    target = None
    if is_exec(old_mode) != is_exec(new_mode):
        current_mode = stat.S_IMODE(os.lstat(path).st_mode)
        target = with_exec(current_mode, is_exec(old_mode))
    if code == 0:
        return ("ok", ("write", rel, merged, target))
    if 0 < code < 128:
        return ("stale", "conflict in %s" % rel)
    return ("stale", "%s could not be merged" % rel)


def plan_commit(repo, root, user_name, commit, parent, globs):
    rows = changed_files(repo, parent, commit)
    if not rows:
        raise CouldNot("%s changed no file" % user_name)
    kept = []
    actions = []
    problems = []
    for status, rel, old_mode, new_mode in rows:
        if path_is_kept(rel, globs):
            kept.append(rel)
            continue
        item = undo_path(repo, root, commit, parent, status, rel, old_mode, new_mode)
        if item[0] == "stale":
            problems.append(item[1])
        else:
            actions.append(item[1])
    if problems:
        return ("stale", "; ".join(problems))
    if not actions:
        raise CouldNot("every file the fix changed is kept; nothing to put back")
    return ("ok", actions, kept, user_name)


def count_occurrences(data, needle):
    count = 0
    start = 0
    while True:
        found = data.find(needle, start)
        if found < 0:
            return count
        count += 1
        start = found + 1


def plan_swap(root, rel, find, replace):
    path = os.path.join(root, rel)
    if os.path.islink(path) or not os.path.isfile(path):
        return ("stale", "%s is missing" % rel)
    data = read_bytes(path)
    needle = find.encode("utf-8")
    repl = replace.encode("utf-8")
    count = count_occurrences(data, needle)
    if count != 1:
        return (
            "stale",
            "the text occurs %d times in %s; it must occur once" % (count, rel),
        )
    at = data.find(needle)
    updated = data[:at] + repl + data[at + len(needle):]
    return ("ok", [("write", rel, updated)], [], None)


class Editor(object):
    def __init__(self, copy):
        self.copy = copy
        self.saved = {}
        self.mtime = {}

    def full(self, rel):
        return os.path.join(self.copy, rel)

    def remember(self, rel):
        if rel in self.saved:
            return
        path = self.full(rel)
        if not os.path.lexists(path):
            self.saved[rel] = ("missing",)
            self.mtime[rel] = None
            return
        info = os.lstat(path)
        self.mtime[rel] = info.st_mtime
        if stat.S_ISLNK(info.st_mode):
            self.saved[rel] = ("link", os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            self.saved[rel] = ("file", read_bytes(path), stat.S_IMODE(info.st_mode))
        else:
            self.saved[rel] = ("other",)

    def step_stamp(self, rels):
        gap = 1.0
        now = time.time()
        later = int(now) + gap
        if later <= now:
            later = later + gap
        for rel in rels:
            remembered = self.mtime.get(rel)
            if remembered is None:
                remembered = 0
            need = remembered + gap
            whole = int(need)
            if whole < need:
                whole = whole + 1
            if whole > later:
                later = whole
        return later

    def wait_until_passed(self, stamp):
        limit = stamp + 1
        remaining = limit - time.time()
        if remaining > 0:
            time.sleep(remaining)

    def finish_step(self, rels):
        if not rels:
            return
        stamp = self.step_stamp(rels)
        for rel in rels:
            path = self.full(rel)
            if os.path.lexists(path) and not os.path.islink(path):
                os.utime(path, (stamp, stamp))
                self.mtime[rel] = stamp
        self.wait_until_passed(stamp)

    def write(self, rel, data, mode):
        self.remember(rel)
        path = self.full(rel)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        if os.path.lexists(path):
            os.remove(path)
        write_bytes(path, data)
        if mode is None:
            saved = self.saved.get(rel)
            if saved and saved[0] == "file":
                mode = saved[2]
            else:
                mode = 0o644
        os.chmod(path, mode)

    def apply(self, actions):
        written = []
        for action in actions:
            if action[0] == "delete":
                self.remember(action[1])
                path = self.full(action[1])
                if os.path.lexists(path):
                    os.remove(path)
            else:
                mode = action[3] if len(action) > 3 else None
                self.write(action[1], action[2], mode)
                written.append(action[1])
        self.finish_step(written)

    def same(self, rel, saved):
        path = self.full(rel)
        if saved[0] == "missing":
            return not os.path.lexists(path)
        if saved[0] == "link":
            return os.path.islink(path) and os.readlink(path) == saved[1]
        if saved[0] == "file":
            return (
                os.path.isfile(path)
                and not os.path.islink(path)
                and read_bytes(path) == saved[1]
            )
        return False

    def restore(self):
        written = []
        for rel, saved in list(self.saved.items()):
            path = self.full(rel)
            if saved[0] == "missing":
                if os.path.lexists(path):
                    os.remove(path)
            elif saved[0] == "link":
                if os.path.lexists(path):
                    os.remove(path)
                parent = os.path.dirname(path)
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent)
                os.symlink(saved[1], path)
            elif saved[0] == "file":
                self.write(rel, saved[1], saved[2])
                written.append(rel)
            else:
                return False
        self.finish_step(written)
        return all(self.same(rel, saved) for rel, saved in self.saved.items())


def report_commit(user_name, actions, kept):
    put = [item[1] for item in actions]
    say("  put back: %s" % ", ".join(put))
    if kept:
        say("  kept as it is today: %s" % ", ".join(kept))
    for rel in put:
        lower = rel.lower()
        if "test" in lower or "spec" in lower:
            say(
                "  note: %s also changed %s, which looks like a test, so it went back too. "
                "To keep today's version: --keep '%s'"
                % (user_name, rel, rel)
            )


def test_env():
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in GIT_ENV_DROP:
        env.pop(name, None)
    return env


def read_until(fd, chunks, deadline):
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        try:
            ready, _write, _err = select.select([fd], [], [], remaining)
        except InterruptedError:
            continue
        if not ready:
            return
        try:
            data = os.read(fd, 65536)
        except OSError:
            return
        if not data:
            return
        chunks.append(data)


def run_test(cmd, cwd, timeout, shell):
    env = test_env()
    if shell:
        cmd = ["/bin/sh", "-c", cmd]
    outcome = Outcome()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as err:
        outcome.start_error = True
        outcome.code = 127
        outcome.reason = err.strerror or str(err)
        return outcome
    STATE.child = proc.pid
    chunks = []
    fd = proc.stdout.fileno()
    started = time.time()
    child_done = None
    timed_out = False
    try:
        while True:
            if child_done is None and proc.poll() is not None:
                child_done = time.time()
            now = time.time()
            if (
                not timed_out
                and child_done is None
                and timeout is not None
                and now - started >= timeout
            ):
                kill_group(proc.pid)
                timed_out = True
                read_until(fd, chunks, time.time() + DRAIN_SECONDS)
                break
            if child_done is not None and now - child_done >= DRAIN_SECONDS:
                break
            if child_done is not None:
                window = child_done + DRAIN_SECONDS - now
            elif timeout is not None:
                window = started + timeout - now
            else:
                window = 1.0
            if window <= 0:
                continue
            try:
                ready, _write, _err = select.select([fd], [], [], min(window, 0.2))
            except InterruptedError:
                continue
            if not ready:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
        if proc.poll() is None:
            try:
                proc.wait(timeout=DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                kill_group(proc.pid)
                try:
                    proc.wait(timeout=DRAIN_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        STATE.child = None
        try:
            proc.stdout.close()
        except OSError:
            pass
    outcome.timed_out = timed_out
    outcome.out = b"".join(chunks).decode("utf-8", "replace")
    outcome.code = proc.returncode
    if outcome.code is not None and outcome.code < 0:
        outcome.signal = -outcome.code
    return outcome


def passed(outcome):
    return (
        outcome.code == 0
        and not outcome.timed_out
        and not outcome.signal
        and not outcome.start_error
    )


def held(detail):
    return 'the output does not hold "%s"' % detail


def timeout_reason(timeout):
    return "timed out after %s s" % number_text(timeout)


def judge(outcome, expect, timeout):
    if outcome.timed_out:
        return ("wrong", timeout_reason(timeout))
    if outcome.signal:
        return ("wrong", "killed by signal %d" % outcome.signal)
    if outcome.start_error or outcome.code in (126, 127):
        return ("wrong", "the command could not start")
    if outcome.code == 0:
        return ("survived", None)
    if expect is None:
        return ("unchecked", None)
    if expect in outcome.out:
        return ("caught", expect)
    return ("mismatch", expect)


def print_back(verdict, outcome):
    kind, detail = verdict
    if kind == "survived":
        say(run_line("bug back", "PASS"))
    elif kind == "caught":
        say(run_line("bug back", "FAIL", 'the output holds "%s"' % detail))
    else:
        say(run_line("bug back", "FAIL"))
        if kind in ("unchecked", "mismatch") or outcome.timed_out or outcome.signal:
            show_tail(outcome.out)


def finish_verdict(verdict):
    kind, detail = verdict
    if kind == "caught":
        say("CAUGHT: red with the bug back, green without it")
        say("changelog line: put the bug back: red, then green")
        return 0
    if kind == "unchecked":
        say(
            "CAUGHT, REASON NOT CHECKED: red with the bug back, green without it. "
            "Read the failure above: it should name the bug. "
            "Pass --expect with words from it and the tool checks that for you."
        )
        return 0
    if kind == "survived":
        say("SURVIVED: the test passed with the bug back. It checks something else, or nothing.")
        return 1
    if kind == "wrong":
        say("WRONG REASON: the test went red, but not for the bug: %s" % detail)
        return 1
    say("WRONG REASON: the test went red, but not for the bug: %s" % held(detail))
    return 1


def stale_followup(reason):
    parts = [part.strip() for part in reason.split(";")]
    tangled = False
    keepish = True
    for part in parts:
        if part.startswith("conflict in ") or "changed since the fix" in part:
            tangled = True
            keepish = False
        elif part.endswith(" is binary") or "is not a simple text change" in part:
            continue
        else:
            keepish = False
    if tangled:
        return "The fix is tangled with later changes. Next time, commit a fix on its own."
    if keepish:
        return "Keep that file as it is today with --keep, or name the bug with swap."
    return None


def run_single(copy, opts, plan):
    if opts["timeout"] is not None:
        timeout = opts["timeout"]
    else:
        timeout = 300
    before = run_test(opts["test"], copy, timeout, False)
    if before.start_error:
        raise CouldNot("the test command could not start: %s" % before.reason)
    if before.timed_out:
        say(run_line("before", "FAIL"))
        show_tail(before.out)
        say("NOT GREEN: the test %s before any bug was put back" % timeout_reason(timeout))
        return 1
    if passed(before):
        say(run_line("before", "PASS"))
    else:
        say(run_line("before", "FAIL"))
    if not passed(before):
        show_tail(before.out)
        say("NOT GREEN: the test fails before any bug is put back")
        return 1
    if plan[0] == "stale":
        say("STALE: could not put the bug back: %s" % plan[1])
        if opts["command"] == "commit":
            follow = stale_followup(plan[1])
            if follow:
                say(follow)
        return 1
    edit = Editor(copy)
    edit.apply(plan[1])
    if opts["command"] == "commit":
        report_commit(plan[3], plan[1], plan[2])
    back = run_test(opts["test"], copy, timeout, False)
    verdict = judge(back, opts["expect"], timeout)
    print_back(verdict, back)
    if not edit.restore():
        raise CouldNot(restore_message("the bug"))
    gone = run_test(opts["test"], copy, timeout, False)
    if passed(gone):
        say(run_line("bug gone", "PASS"))
    else:
        say(run_line("bug gone", "FAIL"))
    if not passed(gone):
        show_tail(gone.out)
        say("NOT GREEN: the test did not pass again once the bug was gone")
        return 1
    return finish_verdict(verdict)


def text_line(value, allow_empty=False):
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        return False
    if allow_empty:
        return True
    return value != ""


def load_json(path, display):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except OSError:
        if display is None:
            raise CouldNot("no list at %s" % path)
        raise CouldNot("%s could not be read" % display)
    try:
        return json.loads(raw)
    except ValueError:
        raise CouldNot("%s is not valid JSON" % display)


def normalize_links(raw, repo):
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise CouldNot("link must be text or a list of text")
    links = []
    for item in raw:
        if not text_line(item):
            raise CouldNot("link must be text or a list of text")
        if inside(repo, item) is None:
            raise CouldNot(outside_message(item))
        links.append(item)
    return links


def vet_bug(bug, index, seen, repo, parsed):
    problems = []
    if isinstance(bug, dict) and text_line(bug.get("id", "")):
        ident = bug.get("id")
    else:
        ident = "?"

    def bad(message):
        problems.append("BAD LIST: bug %d (%s): %s" % (index, ident, message))

    if not isinstance(bug, dict):
        bad("a bug must be an object")
        return problems
    for key in bug.keys():
        if key not in BUG_FIELDS:
            bad("unknown field %s" % key)
    for field in ("id", "guards", "test", "expect"):
        if field not in bug:
            bad("missing %s" % field)
        elif not text_line(bug.get(field)):
            bad("%s must be one line of text" % field)
    if ident != "?":
        if ident in seen:
            bad("the id %s is used twice" % ident)
        else:
            seen[ident] = index
    has_fix = "fix" in bug
    has_swap = any(key in bug for key in ("file", "find", "replace"))
    if has_fix and has_swap:
        bad("give fix, or file, find and replace, not both")
        return problems
    if not has_fix and not has_swap:
        bad("missing fix or file, find and replace")
        return problems
    if has_fix:
        if not text_line(bug.get("fix")):
            bad("fix must be one line of text")
        keep = []
        if "keep" in bug:
            raw_keep = bug["keep"]
            if not isinstance(raw_keep, list) or not all(text_line(item) for item in raw_keep):
                bad("keep must be a list of text")
            else:
                keep = list(raw_keep)
        if not problems and text_line(bug.get("id", "")):
            parsed.append({
                "id": bug["id"],
                "guards": bug.get("guards", ""),
                "test": bug.get("test", ""),
                "expect": bug.get("expect", ""),
                "fix": bug["fix"],
                "keep": keep,
            })
        return problems
    if "keep" in bug:
        bad("keep is only for a fix commit")
    for field in ("file", "find"):
        if field not in bug:
            bad("missing %s" % field)
        elif not text_line(bug.get(field)):
            bad("%s must be one line of text" % field)
    if "replace" not in bug:
        bad("missing replace")
    elif (
        not isinstance(bug.get("replace"), str)
        or "\n" in bug.get("replace", "")
        or "\r" in bug.get("replace", "")
    ):
        bad("replace must be text")
    elif text_line(bug.get("find", "")) and bug.get("find") == bug.get("replace"):
        bad("find and replace must differ")
    rel = None
    if text_line(bug.get("file", "")):
        rel = inside(repo, bug["file"])
        if rel is None:
            bad(outside_message(bug["file"]))
    if (
        not problems
        and rel
        and text_line(bug.get("find", ""))
        and isinstance(bug.get("replace"), str)
    ):
        parsed.append({
            "id": bug["id"],
            "guards": bug.get("guards", ""),
            "test": bug.get("test", ""),
            "expect": bug.get("expect", ""),
            "file": rel,
            "find": bug["find"],
            "replace": bug["replace"],
        })
    return problems


def check_list(data, repo, display):
    if not isinstance(data, dict) or not isinstance(data.get("bugs"), list):
        raise CouldNot("%s has no bugs field" % display)
    unknown = [key for key in data.keys() if key not in TOP_FIELDS]
    if unknown:
        raise CouldNot("%s has an unknown field %s" % (display, unknown[0]))
    if not data["bugs"]:
        raise CouldNot("%s names no bug, so nothing was checked" % display)
    timeout = data.get("timeout")
    if "timeout" in data and not acceptable_timeout(timeout):
        raise CouldNot("timeout is not a number of seconds")
    if "link" in data:
        links = normalize_links(data["link"], repo)
    else:
        links = []
    problems = []
    parsed = []
    seen = {}
    for index, bug in enumerate(data["bugs"], 1):
        problems.extend(vet_bug(bug, index, seen, repo, parsed))
    if problems:
        for line in problems:
            complain(line)
        raise CouldNot(problem_summary(len(problems)))
    return parsed, links, timeout


def is_singular(count):
    return count == 1


def plural_phrase(count, singular, plural):
    if is_singular(count):
        word = singular
    else:
        word = plural
    return "%d %s" % (count, word)


def problem_summary(count):
    return "the list has %s" % plural_phrase(count, "problem", "problems")


def stale_summary(total, stale):
    if is_singular(total):
        return "1 bug, %d stale" % stale
    return "%d bugs, %d stale" % (total, stale)


def plan_listed(repo, root, bug):
    if "fix" in bug:
        try:
            commit, parent = resolve_commit(repo, bug["fix"])
        except CouldNot as err:
            return ("stale", str(err))
        try:
            return plan_commit(
                repo, root, bug["fix"], commit, parent, bug.get("keep") or [],
            )
        except CouldNot as listed:
            return ("stale", str(listed))
    return plan_swap(root, bug["file"], bug["find"], bug["replace"])


def list_line(bug, outcome, timeout):
    kind, detail = judge(outcome, bug["expect"], timeout)
    if kind in ("caught", "unchecked"):
        return "CAUGHT %s  %s" % (bug["id"], bug["guards"]), True
    if kind == "survived":
        return "SURVIVED %s  %s" % (bug["id"], bug["guards"]), False
    if kind == "wrong":
        return "WRONG REASON %s  %s" % (bug["id"], detail), False
    return "WRONG REASON %s  %s" % (bug["id"], held(detail)), False


def stale_only(repo, bugs):
    stale = 0
    for bug in bugs:
        plan = plan_listed(repo, repo, bug)
        if plan[0] == "stale":
            stale += 1
            say("STALE %s  %s" % (bug["id"], plan[1]))
    say(stale_summary(len(bugs), stale))
    if stale:
        return 1
    return 0


def before_reason(outcome, timeout):
    if outcome.timed_out:
        return "the test %s before any bug was put back" % timeout_reason(timeout)
    if outcome.start_error or outcome.code in (126, 127):
        if outcome.code in (126, 127):
            code = outcome.code
        else:
            code = 127
        return "the test command could not start (exit %d)" % code
    return "the test fails before any bug is put back"


def run_all(repo, opts):
    if opts["positionals"]:
        list_path = opts["positionals"][0]
        display = opts["positionals"][0]
    else:
        list_path = os.path.join(repo, "bugs.json")
        display = None
    bugs, links, list_timeout = check_list(load_json(list_path, display), repo, display)
    if opts["only"]:
        bugs = [bug for bug in bugs if bug["id"] == opts["only"]]
        if not bugs:
            raise CouldNot("no bug has the id %s" % opts["only"])
    if opts["timeout"] is None:
        if list_timeout is not None:
            opts["timeout"] = list_timeout
        else:
            opts["timeout"] = 300
    for link in links:
        if link not in opts["link"]:
            opts["link"].append(link)
    if opts["stale_only"]:
        return stale_only(repo, bugs)
    copy = make_copy(repo, opts)
    plans = [plan_listed(repo, copy, bug) for bug in bugs]
    failed = {}
    seen = set()
    for bug, plan in zip(bugs, plans):
        if plan[0] == "stale" or bug["test"] in seen:
            continue
        seen.add(bug["test"])
        outcome = run_test(bug["test"], copy, opts["timeout"], True)
        if not passed(outcome):
            failed[bug["test"]] = before_reason(outcome, opts["timeout"])
    caught = 0
    for bug, plan in zip(bugs, plans):
        if plan[0] == "stale":
            say("STALE %s  %s" % (bug["id"], plan[1]))
            continue
        if bug["test"] in failed:
            say("NOT GREEN %s  %s" % (bug["id"], failed[bug["test"]]))
            continue
        edit = Editor(copy)
        edit.apply(plan[1])
        outcome = run_test(bug["test"], copy, opts["timeout"], True)
        if not edit.restore():
            raise CouldNot(restore_message(bug["id"]))
        line, was_caught = list_line(bug, outcome, opts["timeout"])
        say(line)
        if was_caught:
            caught += 1
    say("caught %d of %d" % (caught, len(bugs)))
    if caught == len(bugs):
        return 0
    return 1


def single_plan(repo, copy, opts):
    if opts["command"] == "commit":
        name = opts["positionals"][0]
        commit, parent = resolve_commit(repo, name)
        return plan_commit(repo, copy, name, commit, parent, opts["keep"])
    rel = inside(repo, opts["positionals"][0], from_start=True)
    if rel is None:
        raise CouldNot(outside_message(opts["positionals"][0]))
    return plan_swap(copy, rel, opts["find"], opts["replace"])


def bind_cli_links(repo, opts):
    resolved = []
    for link in opts["link"]:
        rel = inside(repo, link, from_start=True)
        if rel is None:
            raise CouldNot(outside_message(link))
        resolved.append(rel)
    opts["link"] = resolved


def execute(opts):
    repo = find_repo(opts["repo"])
    STATE.keep = opts["keep_copy"]
    bind_cli_links(repo, opts)
    if opts["command"] == "all":
        return run_all(repo, opts)
    if opts["command"] == "commit":
        resolve_commit(repo, opts["positionals"][0])
    elif inside(repo, opts["positionals"][0], from_start=True) is None:
        raise CouldNot(outside_message(opts["positionals"][0]))
    copy = make_copy(repo, opts)
    return run_single(copy, opts, single_plan(repo, copy, opts))


def dispatch(argv):
    if not argv:
        sys.stderr.write(help_text())
        return 2
    if argv[0] in ("-h", "--help"):
        write_out(help_text())
        return 0
    try:
        opts = parse_args(argv)
    except Usage as err:
        sys.stderr.write("usage: %s\n" % err)
        return 2
    if shutil.which("git") is None:
        raise CouldNot("git not found")
    return execute(opts)


def main(argv):
    saved = install_stop_handlers()
    code = 2
    try:
        try:
            code = dispatch(argv)
        except KeyboardInterrupt:
            perform_stop(signal.SIGINT)
            code = STOP_CODES[signal.SIGINT]
        except SystemExit as err:
            if isinstance(err.code, int):
                code = err.code
            else:
                code = STOP_CODES[signal.SIGINT]
        except CouldNot as err:
            complain("could not: %s" % err)
            code = 2
        except OSError as err:
            STATE.force_remove = True
            code = report_oserror(err)
        except Exception as err:
            STATE.force_remove = True
            complain("could not: unexpected error: %s: %s" % (type(err).__name__, err))
            code = 2
        return code
    finally:
        cleanup()
        restore_handlers(saved)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
