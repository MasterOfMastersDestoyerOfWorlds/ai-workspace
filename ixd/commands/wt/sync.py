"""Replay a worktree's proposed change onto the current main branch."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def sync(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Rebase the uncommitted change onto the main branch and leave it uncommitted again.

    Work is never lost: the change is parked in a temporary commit, replayed, then unpacked. A real
    conflict leaves the rebase in progress with the files listed, for `continue` or `abort`.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    worktree.sync(path, branch, main_branch)
    return 0
