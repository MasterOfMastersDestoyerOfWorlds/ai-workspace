"""Lay a worktree's change out for review: moves staged, code changes unstaged."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def stage_moves(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Uncommit the change, stage its move hunks, and leave every code hunk unstaged for review.

    A package move touches hundreds of files with nothing but a moved path, a ``package`` line
    and ``import`` lines, which buries the few hunks that change code. This puts the change back
    in the working tree (undoing ``wt commit``, never anything below the worktree's own base) and
    stages exactly the mechanical part: renames, plus hunks whose changed lines are all
    ``package``/``import`` lines or blank and whose imports name a class the change moves, plus
    the whole of every Java file whose changes are only comments, blank lines or such imports. An
    import change that names no moved class belongs to the code beside it, and so does a comment
    change in a file that also changes code. ``git diff --cached`` then shows the mechanical part
    and ``git diff`` (with untracked new files) shows the code to read.

    A worktree stacked on this one keeps working: its history still holds this change's commit,
    and ``sync`` refuses to replay it until this worktree is committed again or landed.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    worktree.stage_moves(path, branch, main_branch)
    return 0
