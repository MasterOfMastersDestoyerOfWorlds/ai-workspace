"""Report where a worktree's work stands."""

from typing import Annotated

from ... import diagnostics, worktree
from ...registry import CliOption, cli_command

CHANGED_FILE_LINES = 40


@cli_command
def status(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Show the branch, its refs, the changed files, added diagnostics, and the last agent note.

    This is what a relaunched agent reads instead of a hand-written brief. The note is the closing
    prose of the transcript whose tool calls actually worked in this worktree, so an agent picking
    the work up learns what was built and what was left. Refs are the published and archived
    copies of the branch (``origin/<branch>``, ``archive/<branch>``), so nobody reaches for the
    denied ``git branch`` or ``git tag`` to find them. Diagnostics are the log lines, counters and
    probes ``wt done`` refuses unless the ticket's definition of done names them.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    ahead, behind = worktree.ahead_behind(path, branch, main_branch)
    changed = worktree.changed_files(path)
    print(f"worktree: {path}")
    print(f"branch:   {branch} (commits ahead of {main_branch}: {ahead}, behind: {behind})")
    refs = worktree.git(
        path,
        "for-each-ref",
        "--format=%(refname:short) %(objectname:short)",
        f"refs/remotes/*/{branch}",
        f"refs/tags/archive/{branch}",
        check=False,
    )
    if refs:
        print(f"refs:     {'; '.join(refs.splitlines())}")
    print(f"changed:  {len(changed)} file(s) uncommitted")
    for line in changed[:CHANGED_FILE_LINES]:
        print(f"  {line}")
    if len(changed) > CHANGED_FILE_LINES:
        print(f"  ... {len(changed) - CHANGED_FILE_LINES} more")
    ticket = worktree.ticket_for(branch) or {}
    left = diagnostics.unaccounted(diagnostics.scan(path), ticket.get("definition-of-done", ""))
    if left:
        print(f"diagnostics: {len(left)} added and not named in the DoD (wt done refuses them)")
        for finding in left[:CHANGED_FILE_LINES]:
            print(f"  {finding.describe()}")
    if ahead or behind:
        print("run `ixd wt sync` to put the whole change on top of the current main branch")
    worktree.print_resume_note(path)
    return 0
