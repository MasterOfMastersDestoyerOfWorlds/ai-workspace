"""Save a worktree's change as a snapshot, then put the worktree back to its starting commit."""

from typing import Annotated

from ... import snapshots as snapshot_store
from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def reset(worktree_name: Annotated[str, CliOption(positional=True)]) -> int:
    """Snapshot the whole uncommitted change, then reset the worktree to the commit it sits on.

    For starting a ticket over from a clean tree without losing anything: the change, new files
    included, is saved as a snapshot first, and the reset only runs once that snapshot is
    confirmed to hold exactly the current files. Then tracked files go back to the branch's
    commit (master, for a worktree that has not committed) and untracked files are removed.
    Ignored files (``tmp/``, ``target/``) stay, so diagnostics and logs survive.
    ``ixd wt restore <name> <n> <path>`` brings back any file or directory from the printed
    snapshot.

    Refuses when the branch has commits of its own (their work is not in the uncommitted change,
    and a reset would not take the tree to master) or when a sync is in progress.

    :param worktree_name: worktree path or bare name
    """
    root, branch, base = worktree.resolve_worktree(worktree_name)
    ahead, _ = worktree.ahead_behind(root, branch, base)
    if ahead:
        raise SystemExit(
            f"{branch} has {ahead} commit(s) of its own on top of {base}; reset only discards the "
            f"uncommitted change, so it would not give a clean {base} tree. Nothing was changed."
        )
    if not worktree.changed_files(root):
        print(f"{branch}: nothing uncommitted; the tree already matches its commit")
        return 0
    number = snapshot_store.save(root, f"before wt reset of {branch}")
    if number is None:
        raise SystemExit(f"{branch}: could not save the change as a snapshot; nothing was reset")
    worktree.git(root, "reset", "--hard", "--quiet", "HEAD")
    worktree.git(root, "clean", "-fd", "--quiet")
    print(f"{branch}: change saved as snapshot #{number}; the tree is back at {base}")
    print(f"`ixd wt restore {root.name} {number} <path>` brings back a file or directory")
    return 0
