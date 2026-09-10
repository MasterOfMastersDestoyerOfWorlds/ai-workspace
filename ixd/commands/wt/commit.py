"""Squash a worktree's change into one commit on top of main."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def commit(
    message: Annotated[str, CliOption(short="-m")],
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
) -> int:
    """Make one squashed commit of the whole diff on top of the main branch.

    Requires a fresh sync, so the result is a single commit the user can fast-forward: no merge
    commits and no history to read.

    :param message: the commit message
    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    worktree.commit(path, branch, main_branch, message)
    return 0
