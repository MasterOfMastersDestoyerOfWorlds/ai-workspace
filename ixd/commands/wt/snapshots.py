"""List the snapshots the snapshot hook took of a worktree."""

import datetime
from typing import Annotated

from ... import snapshots as snapshot_store
from ... import worktree
from ...registry import CliOption, cli_command

DEFAULT_LIMIT = 30
FILES_SHOWN = 6


@cli_command
def snapshots(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    path: Annotated[str, CliOption(short="-f")] = "",
    limit: Annotated[int, CliOption(short="-n")] = DEFAULT_LIMIT,
) -> int:
    """List a worktree's snapshots, newest first, with the files each one changed.

    The ``snapshot_edit`` hook saves the worktree's uncommitted state before every Edit, Write or
    Bash call that reaches into it, so code an agent wrote and later deleted is still here. Each
    line shows the snapshot's number, its time, the tool call that ran right after it, and the
    files that differ from the snapshot before. ``ixd wt restore <name> <n> <path>`` copies a file
    or directory back out of snapshot ``<n>``.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param path: show only the snapshots in which this file or directory changed (worktree-relative)
    :param limit: how many snapshots to show
    """
    root, branch, _ = worktree.resolve_worktree(worktree_name)
    taken = snapshot_store.snapshot_refs(root, branch)
    if not taken:
        print(f"{branch}: no snapshots yet")
        return 0
    wanted = path.replace("\\", "/").strip("/")
    shown = 0
    previous = {number: commit for number, commit, _, _ in taken}
    for number, commit, when, message in reversed(taken):
        if shown >= limit:
            break
        older = previous.get(number - 1)
        changed = snapshot_store.changed_paths(root, older, commit) if older else []
        if wanted and not any(item == wanted or item.startswith(wanted + "/") for _, item in changed):
            continue
        stamp = datetime.datetime.fromtimestamp(when).strftime("%m-%d %H:%M:%S")
        print(f"#{number:<4} {stamp}  {message}")
        files = [f"{status} {item}" for status, item in changed]
        for line in files[:FILES_SHOWN]:
            print(f"        {line}")
        if len(files) > FILES_SHOWN:
            print(f"        ... {len(files) - FILES_SHOWN} more")
        if older is None:
            print("        (first snapshot: the whole change as it stood)")
        shown += 1
    print(f"{branch}: {len(taken)} snapshot(s); `ixd wt restore {root.name} <n> <path>` brings a file back")
    return 0
