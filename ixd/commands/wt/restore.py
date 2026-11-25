"""Copy a file or directory back out of a worktree snapshot."""

from pathlib import Path
from typing import Annotated

from ... import snapshots as snapshot_store
from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def restore(
    worktree_name: Annotated[str, CliOption(positional=True)],
    number: Annotated[int, CliOption(positional=True)],
    path: Annotated[str, CliOption(positional=True)],
) -> int:
    """Copy a file or directory as it stood in snapshot ``<number>`` back into the worktree.

    The worktree is snapshotted first, so the restore itself can be undone the same way. Files
    the snapshot holds under ``<path>`` are written over their current versions; files that exist
    now but not in the snapshot are left alone. Nothing is staged or committed. ``ixd wt
    snapshots`` lists the numbers.

    :param worktree_name: worktree path or bare name
    :param number: the snapshot number, as ``ixd wt snapshots`` prints it
    :param path: file or directory to bring back, relative to the worktree root
    """
    root, branch, _ = worktree.resolve_worktree(worktree_name)
    commits = {taken: commit for taken, commit, _, _ in snapshot_store.snapshot_refs(root, branch)}
    if number not in commits:
        raise SystemExit(f"{branch} has no snapshot #{number}; `ixd wt snapshots {root.name}` lists them")
    relative = path.replace("\\", "/").strip("/")
    absolute = Path(path)
    if absolute.is_absolute():
        relative = absolute.resolve().relative_to(root).as_posix()
    listing = worktree.git(root, "ls-tree", "-r", "--name-only", commits[number], "--", relative)
    files = [line for line in listing.splitlines() if line]
    if not files:
        raise SystemExit(f"snapshot #{number} holds nothing at {relative!r}")
    before = snapshot_store.take(root, f"before restore of {relative} from #{number}")
    for item in files:
        content = snapshot_store.blob_bytes(root, commits[number], item)
        target = root / item
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"restored {item}")
    if before is not None:
        print(f"the state before this restore is snapshot #{before}")
    return 0
