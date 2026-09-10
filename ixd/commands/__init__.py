"""Command modules for the ``ixd`` CLI, one folder per command and one file per subcommand.

Every module here is imported at startup so the decorators register themselves. There is no list to
keep in step: a new subcommand is a new file in the right folder.
"""

import importlib
import pkgutil


def import_all_commands() -> None:
    """Import every command module so its decorator runs.

    An import failure is raised rather than swallowed: a command missing from the CLI is worse than
    a traceback that names the file.
    """
    for module in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
        if module.name.rpartition(".")[2].startswith("_"):
            continue
        importlib.import_module(module.name)
