"""Prepare a machine: clone every repository, install the tools, record REPO_HOME."""

from ... import machine
from ...registry import cli_command


@cli_command
def setup(
    repo_home: str = "",
    dry_run: bool = False,
    no_shell: bool = False,
    no_tools: bool = False,
    no_maven: bool = False,
) -> int:
    """Clone the repositories, install the commands, record REPO_HOME, install the autofix artifact.

    Every step is idempotent, so rerunning after a partial failure is safe. REPO_HOME defaults to the
    directory holding this checkout, because the other repositories are its siblings. It is written to
    .claude/settings.local.json for Claude sessions and to the shell profile for terminals.

    :param repo_home: where the repositories live, defaulting to the parent of this checkout
    :param dry_run: print every step without running it
    :param no_shell: do not touch the shell profile or the user environment
    :param no_tools: skip installing the commands and syncing the environment
    :param no_maven: skip installing the autofix artifact into ~/.m2
    """
    return machine.prepare(
        given_home=repo_home,
        dry_run=dry_run,
        no_shell=no_shell,
        no_tools=no_tools,
        no_maven=no_maven,
    )
