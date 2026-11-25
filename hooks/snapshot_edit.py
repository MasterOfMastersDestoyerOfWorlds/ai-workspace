#!/usr/bin/env python3
"""PreToolUse hook: snapshot a worktree before any tool call that may change it.

Runs before Edit, Write, MultiEdit, NotebookEdit and Bash. When the call reaches into a linked
worktree under ``<repo>/.claude/worktrees/`` (the file it edits, a worktree path in the shell
command, or the directory the command runs in), the worktree's uncommitted state is saved as
``refs/snapshots/<branch>/<n>`` by ``ixd/snapshots.py``, unless nothing changed since the last
snapshot. ``ixd wt snapshots`` and ``ixd wt restore`` bring the work back.

The hook never blocks: any failure leaves the call to run unsnapshotted.
"""

import os
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from hook_common import read_event, working_directory  # noqa: E402
from ixd import snapshots  # noqa: E402

FILE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def repo_home():
    """The directory holding every repository, as ``ixd/paths.py`` resolves it."""
    configured = os.environ.get("REPO_HOME")
    return Path(configured) if configured else WORKSPACE_ROOT.parent


def targets(event):
    """The worktrees this tool call may change."""
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    found = []
    if tool in FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        root = snapshots.worktree_root(path) if isinstance(path, str) and path else None
        if root is not None:
            found.append(root)
    elif tool == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str):
            found.extend(snapshots.worktrees_named_in(command, repo_home()))
        root = snapshots.worktree_root(working_directory(event))
        if root is not None and root not in found:
            found.append(root)
    return found


def main():
    event = read_event()
    try:
        message = snapshots.summary(event.get("tool_name", ""), event.get("tool_input") or {})
        for worktree in targets(event):
            snapshots.take(worktree, message)
    except Exception:  # noqa: BLE001 - a snapshot failure must never stop the tool call
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
