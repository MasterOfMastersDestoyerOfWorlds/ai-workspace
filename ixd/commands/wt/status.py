"""Report where a worktree's work stands."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command

CHANGED_FILE_LINES = 40


@cli_command
def status(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Show the branch, its distance from main, the changed files, and the last agent note.

    This is what a relaunched agent reads instead of a hand-written brief. The note is the closing
    prose of the transcript whose tool calls actually worked in this worktree, so an agent picking
    the work up learns what was built and what was left.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    ahead, behind = worktree.ahead_behind(path, branch, main_branch)
    changed = worktree.changed_files(path)
    print(f"worktree: {path}")
    print(f"branch:   {branch} (commits ahead of {main_branch}: {ahead}, behind: {behind})")
    print(f"changed:  {len(changed)} file(s) uncommitted")
    for line in changed[:CHANGED_FILE_LINES]:
        print(f"  {line}")
    if len(changed) > CHANGED_FILE_LINES:
        print(f"  ... {len(changed) - CHANGED_FILE_LINES} more")
    if ahead or behind:
        print("run `ixd wt sync` to put the whole change on top of the current main branch")
    worktree.print_resume_note(path)
    return 0
