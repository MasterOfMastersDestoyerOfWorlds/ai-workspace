"""Stage every hunk like the one at a file and line."""

from pathlib import Path
from typing import Annotated

from ... import clusters as engine
from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def stage_like(
    worktree_name: Annotated[str, CliOption(positional=True)],
    location: Annotated[str, CliOption(positional=True)],
) -> int:
    """Stage every hunk in the cluster of the hunk at ``<file>:<line>``, the line the cursor is on.

    The file is relative to the worktree (an absolute path inside it works too) and the line is
    the working-tree line, as the editor shows it; a pure deletion is found from the line on
    either side of the gap. A hunk in no cluster is staged alone. Staging works as in
    ``stage-cluster``: the index becomes the start commit plus those hunks, ``git diff --cached``
    shows only them, and ``stage-moves`` puts the review layout back. Nothing is committed.

    :param worktree_name: worktree path or bare name
    :param location: ``path/to/File.java:123``
    """
    path, branch, base = worktree.resolve_worktree(worktree_name)
    file_part, _, line_part = location.rpartition(":")
    if not file_part or not line_part.isdigit():
        raise SystemExit(f"{location!r} is not <file>:<line>")
    given = Path(file_part)
    if given.is_absolute():
        try:
            given = given.resolve().relative_to(path)
        except ValueError:
            raise SystemExit(f"{file_part} is not inside {path}") from None
    worktree.uncommit_to_start(path, branch, base)
    result, _ = engine.of_worktree(path, base)
    hunk = engine.hunk_at(result, given.as_posix(), int(line_part))
    chosen = result.cluster_of(hunk)
    if chosen is None:
        engine.stage_hunks(path, branch, [hunk], f"the unclustered hunk at {location}")
        return 0
    label = f"cluster {chosen.number} ({engine.LEVEL_NAMES[chosen.level]}), the one holding {location}"
    engine.stage_hunks(path, branch, chosen.hunks, label)
    return 0
