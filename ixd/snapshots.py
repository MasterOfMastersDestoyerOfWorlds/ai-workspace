"""Snapshots of a worktree's uncommitted state, taken before every tool call that may change it.

An agent's work in a worktree stays uncommitted, so git alone cannot bring back code an agent
wrote and later deleted. The ``snapshot_edit`` hook calls :func:`take` before each Edit, Write
or Bash call that reaches into a worktree. A snapshot is a commit object built through a temporary
index: the worktree's files as they stand, new files included and ignored ones (``tmp/``,
``target/``) left out, with the branch's HEAD as parent. A ref ``refs/snapshots/<branch>/<n>``
keeps it alive. The working files, the real index, HEAD and the branch are never touched, and a
snapshot is skipped when nothing changed since the last one.

``ixd wt snapshots`` lists them and ``ixd wt restore`` copies a file or directory back out.
The refs live in the shared repository, so they outlive the worktree and its branch.

Standard library only: the hook imports this module on every call.
"""

import datetime
import os
import re
import subprocess
import tempfile
from pathlib import Path

REF_ROOT = "refs/snapshots"
# Characters of a Bash command kept in a snapshot's message.
SUMMARY_WIDTH = 100
WORKTREE_IN_TEXT = re.compile(r"[/\\]\.claude[/\\]worktrees[/\\]([a-z0-9][a-z0-9._-]*)", re.IGNORECASE)
DRIVE_PATH = re.compile(r"^/([a-zA-Z])/")


def run_git(cwd, *args, env=None):
    """Runs git in ``cwd`` and returns (exit code, stripped stdout)."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout.strip()


def native_path(text):
    """Turns a Git Bash path such as ``/c/Code/x`` into ``C:/Code/x`` on Windows."""
    if os.name == "nt":
        match = DRIVE_PATH.match(text)
        if match:
            return f"{match.group(1).upper()}:/{text[match.end():]}"
    return text


def worktree_root(path):
    """The ``<repo>/.claude/worktrees/<name>`` directory holding ``path``, or None.

    :param path: any path, existing or not
    :return: the worktree's root when it is a live linked worktree
    """
    parts = Path(native_path(str(path))).absolute().parts
    for index in range(len(parts) - 2):
        if parts[index] == ".claude" and parts[index + 1] == "worktrees":
            root = Path(*parts[: index + 3])
            return root if (root / ".git").is_file() else None
    return None


def worktrees_named_in(command, repo_home):
    """Every live worktree a shell command names, by path or by its ``.claude/worktrees`` slot.

    :param command: the Bash command text
    :param repo_home: the directory holding every repository
    :return: worktree roots, without duplicates
    """
    found = []
    for match in WORKTREE_IN_TEXT.finditer(command):
        start = command.rfind(" ", 0, match.start()) + 1
        prefix = command[start : match.end()].strip("'\"=")
        root = worktree_root(prefix) if prefix.startswith(("/", "~")) or ":" in prefix[:3] else None
        if root is None:
            name = match.group(1)
            for repo in sorted(Path(repo_home).iterdir()) if Path(repo_home).is_dir() else []:
                candidate = repo / ".claude" / "worktrees" / name
                if (candidate / ".git").is_file():
                    root = candidate
                    break
        if root is not None and root not in found:
            found.append(root)
    return found


def branch_of(worktree):
    """The branch checked out in a worktree, or None for a detached HEAD."""
    code, branch = run_git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
    return branch if code == 0 and branch else None


def snapshot_refs(worktree, branch):
    """The snapshots of a branch, oldest first, as (number, commit, unix time, message)."""
    code, listing = run_git(
        worktree,
        "for-each-ref",
        "--format=%(refname)%09%(objectname)%09%(committerdate:unix)%09%(contents:subject)",
        f"{REF_ROOT}/{branch}/",
    )
    snapshots = []
    for line in listing.splitlines() if code == 0 else []:
        ref, commit, when, message = (line.split("\t", 3) + ["", "", ""])[:4]
        number = ref.rsplit("/", 1)[-1]
        if number.isdigit():
            snapshots.append((int(number), commit, int(when or 0), message))
    return sorted(snapshots)


def tree_of(worktree):
    """Writes the worktree's current files, ignored ones left out, as a tree; returns its id."""
    code, index_path = run_git(worktree, "rev-parse", "--git-path", "index")
    real_index = Path(index_path) if Path(index_path).is_absolute() else Path(worktree) / index_path
    handle, temporary = tempfile.mkstemp(prefix="ixd-snapshot-", suffix=".index")
    os.close(handle)
    try:
        # Starting from a copy of the real index lets `git add` skip every file whose stat matches.
        if code == 0 and real_index.is_file():
            Path(temporary).write_bytes(real_index.read_bytes())
        else:
            os.unlink(temporary)
        env = dict(os.environ, GIT_INDEX_FILE=temporary)
        added, _ = run_git(worktree, "add", "-A", env=env)
        if added != 0:
            return None
        written, tree = run_git(worktree, "write-tree", env=env)
        return tree if written == 0 and tree else None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def take(worktree, message):
    """Snapshots a worktree unless nothing changed since its last snapshot.

    :param worktree: the worktree root
    :param message: what is about to run, kept as the snapshot's subject
    :return: the new snapshot's number, or None when none was taken
    """
    branch = branch_of(worktree)
    if branch is None:
        return None
    tree = tree_of(worktree)
    if tree is None:
        return None
    existing = snapshot_refs(worktree, branch)
    if existing:
        code, last_tree = run_git(worktree, "rev-parse", f"{existing[-1][1]}^{{tree}}")
        if code == 0 and last_tree == tree:
            return None
    code, head = run_git(worktree, "rev-parse", "--verify", "--quiet", "HEAD")
    parents = ["-p", head] if code == 0 and head else []
    code, commit = run_git(worktree, "commit-tree", tree, *parents, "-m", message)
    if code != 0 or not commit:
        return None
    number = existing[-1][0] + 1 if existing else 1
    code, _ = run_git(worktree, "update-ref", f"{REF_ROOT}/{branch}/{number}", commit, "")
    return number if code == 0 else None


def save(worktree, message):
    """The number of a snapshot holding the worktree exactly as it stands now.

    Takes one unless the last snapshot already matches, then confirms the match.

    :param worktree: the worktree root
    :param message: the snapshot's subject when one is taken
    :return: the snapshot number, or None when the state could not be saved
    """
    taken = take(worktree, message)
    if taken is not None:
        return taken
    branch = branch_of(worktree)
    tree = tree_of(worktree)
    existing = snapshot_refs(worktree, branch) if branch else []
    if not existing or tree is None:
        return None
    code, last_tree = run_git(worktree, "rev-parse", f"{existing[-1][1]}^{{tree}}")
    return existing[-1][0] if code == 0 and last_tree == tree else None


def summary(tool, tool_input):
    """A one-line description of a tool call for a snapshot's subject."""
    if tool == "Bash":
        command = " ".join(str(tool_input.get("command", "")).split())
        text = command if len(command) <= SUMMARY_WIDTH else command[: SUMMARY_WIDTH - 3] + "..."
    else:
        text = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    return f"before {tool} {stamp}: {text}"


def blob_bytes(worktree, commit, path):
    """The bytes of one file in a snapshot, as a checkout would write them (line endings included)."""
    result = subprocess.run(
        ["git", "-C", str(worktree), "cat-file", "--filters", f"{commit}:{path}"], capture_output=True
    )
    if result.returncode != 0:
        raise SystemExit(
            f"cannot read {path} from {commit[:8]}: {result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def changed_paths(worktree, older, newer):
    """The (status, path) pairs that differ between two commits, or from an empty tree."""
    base = older or "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    code, listing = run_git(worktree, "diff", "--name-status", "--no-renames", base, newer)
    pairs = []
    for line in listing.splitlines() if code == 0 else []:
        status, _, path = line.partition("\t")
        pairs.append((status, path))
    return pairs
