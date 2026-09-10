"""Where the user's repositories live on this machine.

Every tool and hook in this repo reaches the other repositories (Ixdar, ixdar-tickets, autofix,
obsidian) through ``repo_home()`` instead of a literal path, so one checkout of ai-workspace works
on every machine and operating system.

Resolution order:

1. ``REPO_HOME`` environment variable, when set and non-empty (``setup`` writes it).
2. The directory containing this ai-workspace checkout. The repositories are siblings, which
   ``.claude/settings.json`` already assumes through its ``../Ixdar`` style directory entries.
"""
import os
from pathlib import Path

REPO_HOME_VARIABLE = "REPO_HOME"

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

MANIFEST = WORKSPACE_ROOT / "repos.json"


def repo_home():
    """The directory that holds every repository, as an absolute path."""
    configured = os.environ.get(REPO_HOME_VARIABLE, "").strip()
    if configured:
        return Path(os.path.expanduser(configured)).resolve()
    return WORKSPACE_ROOT.parent


def repo_path(name):
    """The checkout of one repository by its manifest name, whether or not it exists yet."""
    return repo_home() / name
