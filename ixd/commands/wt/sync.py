"""Replay a worktree's proposed change onto the current main branch."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def sync(worktree_name: Annotated[str, CliOption(positional=True)] = "", base: str = "") -> int:
    """Rebase the uncommitted change onto the main branch and leave it uncommitted again.

    Work is never lost: the change is parked in a temporary commit, replayed, then unpacked. A real
    conflict leaves the rebase in progress with the files listed, for `continue` or `abort`.

    A worktree stacked with ``wt new --base`` replays onto its base branch instead. ``--base``
    stacks an existing worktree the same way: only its own change moves onto the base's tip, and
    later syncs keep it there until the base lands. ``--base`` naming the main branch takes the
    worktree off its stack: only its own change moves onto the main branch, and it can land at once.

    Afterwards the tree is compiled and Maven's classes are copied over the IDE's ``target-ide/``,
    also when it was already on top of the main branch: VS Code compiles the annotation registries
    Maven generates rather than generating its own, and its own build can lag the latest edits, so
    without this F5 runs registries missing whatever master added, or classes older than the
    source. A failed build leaves the sync in place and exits 1.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param base: stack this worktree on that worktree branch from now on, or the main branch to unstack it
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    if base:
        base = base.strip().lower()
        if base == branch or not worktree.git(
            path, "rev-parse", "--verify", "--quiet", f"refs/heads/{base}", check=False
        ):
            raise SystemExit(f"{base!r} is not another existing branch")
        fork = worktree.stack_fork_of(path, branch) or worktree.git(path, "merge-base", branch, main_branch)
        worktree.git(path, "config", f"branch.{branch}.{worktree.FORK_KEY}", fork)
        if base == worktree.main_branch_of(path):
            # Unstacked: the fork stays, so only this change moves, exactly as after a base lands.
            worktree.git(path, "config", "--unset", f"branch.{branch}.{worktree.BASE_KEY}", check=False)
        else:
            worktree.git(path, "config", f"branch.{branch}.{worktree.BASE_KEY}", base)
        main_branch = base
    worktree.sync(path, branch, main_branch)
    return 0 if worktree.rebuild_for_ide(path) else 1
