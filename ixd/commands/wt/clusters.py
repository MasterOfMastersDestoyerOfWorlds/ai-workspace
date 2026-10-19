"""List a worktree's hunks grouped by edit pattern."""

from typing import Annotated, Literal

from ... import clusters as engine
from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def clusters(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    every_hunk: bool = False,
    commit: str = "",
    repo: Literal["Ixdar", "ixdar-tickets", "ai-workspace"] = "Ixdar",
) -> int:
    """List the change's hunks grouped by the edit they make, with the rest as unclustered.

    The diff is the one ``stage-moves`` and ``ixd review`` read: from the change's start (the stack
    fork, or the merge base with its base) to the working tree, untracked files included, without
    the mechanical hunks ``stage-moves`` stages. Each hunk joins the hunks that make the same edit,
    at the first level that joins them:

    - identical: the same removed and added lines, whitespace collapsed, blank lines dropped.
    - token rewrite: the same rewrite once differing tokens are abstracted. A token run both sides
      share becomes ``$1``, a local name ``$v1``, a constant or literal ``$k1``; a removed
      declaration of a local the added side never names, and a repeat of the same statement, do
      not count.
    - syntax tree: the same edit on the syntax tree (tree-sitter through ast-grep, for Java,
      Python, JavaScript and TypeScript): each hunk widened to the whole statements it touches, so
      rewrapping and comments do not matter, plus hunks that do part of an established pattern's
      edit because the diff cut it into two hunks.

    Each cluster prints its number (what ``stage-cluster`` takes), level, hunk and file counts,
    pattern, files and one representative hunk; the unclustered hunks, the ones to read, follow
    as ``path:line``. Nothing is staged or changed.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param every_hunk: print every hunk of each cluster, not just one
    :param commit: cluster this commit's diff against its parent instead of a worktree (read only)
    :param repo: repository under REPO_HOME holding ``--commit``
    """
    if commit:
        path = worktree.CODE_ROOT / repo
        result, _ = engine.of_commit(path, commit)
        label = f"{repo} {commit}"
    else:
        path, branch, base = worktree.resolve_worktree(worktree_name)
        result, _ = engine.of_worktree(path, base)
        label = f"{branch} against {base}"
    print("\n".join(engine.report(result, label, show_hunks=every_hunk)))
    return 0
