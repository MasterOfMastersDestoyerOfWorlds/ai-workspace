"""Stage one cluster of a worktree's hunks."""

from typing import Annotated

from ... import clusters as engine
from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def stage_cluster(
    worktree_name: Annotated[str, CliOption(positional=True)],
    number: Annotated[int, CliOption(positional=True)],
) -> int:
    """Stage exactly one cluster's hunks, numbered as ``ixd wt clusters`` lists them.

    Like ``stage-moves`` it first puts a committed change back in the working tree (never below
    the worktree's own start), then replaces the index with the start commit plus that cluster's
    hunks through ``git apply --cached``, so ``git diff --cached`` shows only the cluster and
    ``git diff`` the rest. Whatever was staged before, the moves included, is unstaged;
    ``stage-moves`` puts that layout back. A hunk in a renamed file stages the rename with it.
    Nothing is committed.

    :param worktree_name: worktree path or bare name
    :param number: the cluster's number in ``ixd wt clusters``
    """
    path, branch, base = worktree.resolve_worktree(worktree_name)
    worktree.uncommit_to_start(path, branch, base)
    result, _ = engine.of_worktree(path, base)
    if not 1 <= number <= len(result.clusters):
        raise SystemExit(
            f"{branch}: no cluster {number}; `ixd wt clusters {branch}` lists {len(result.clusters)}"
        )
    chosen = result.clusters[number - 1]
    engine.stage_hunks(path, branch, chosen.hunks, f"cluster {number} ({engine.LEVEL_NAMES[chosen.level]})")
    return 0
