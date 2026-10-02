"""Replay a worktree's proposed change onto the current main branch."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def sync(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Rebase the uncommitted change onto the main branch and leave it uncommitted again.

    Work is never lost: the change is parked in a temporary commit, replayed, then unpacked. A real
    conflict leaves the rebase in progress with the files listed, for `continue` or `abort`.

    When the tree moved, it is compiled and Maven's classes are copied over the IDE's
    ``target-ide/``: VS Code compiles the annotation registries Maven generates rather than
    generating its own, so without this F5 runs registries missing whatever master added. A failed
    build leaves the sync in place and exits 1.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    if worktree.sync(path, branch, main_branch) and not worktree.rebuild_for_ide(path):
        return 1
    return 0
