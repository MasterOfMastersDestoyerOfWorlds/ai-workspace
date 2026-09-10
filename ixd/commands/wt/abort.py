"""Abandon a sync that stopped on conflicts."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def abort(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Abandon an interrupted sync and restore the state the worktree was in before it.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, _ = worktree.resolve_worktree(worktree_name, allow_rebase=True)
    worktree.require_sync_in_progress(path, branch)
    worktree.abort(path, branch)
    return 0
