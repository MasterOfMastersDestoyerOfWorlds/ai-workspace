"""Finish a sync that stopped on conflicts."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command(name="continue")
def continue_sync(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """After the conflict markers are gone, finish the interrupted sync.

    Refuses while any tracked file outside tmp/ still holds a marker, and refuses when a file git
    listed as unmerged has vanished from the working tree.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name, allow_rebase=True)
    worktree.require_sync_in_progress(path, branch)
    worktree.continue_rebase(path, branch, main_branch)
    return 0
