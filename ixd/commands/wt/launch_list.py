"""List a worktree's VS Code launch entries."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command(name="launch-list")
def launch_list(worktree_name: Annotated[str, CliOption(positional=True)] = "") -> int:
    """Print the launch entry names this worktree offers, with their scene arguments.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, _, _ = worktree.resolve_worktree(worktree_name)
    for entry in worktree.launch_entries(path):
        print(f"{entry.get('name', '?')}  (args: {entry.get('args', '')})")
    return 0
