"""Stage the change as it stood at an earlier checkpoint commit."""

import subprocess
from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def stage_checkpoint(
    worktree_name: Annotated[str, CliOption(positional=True)],
    checkpoint: Annotated[str, CliOption(positional=True)],
) -> int:
    """Stage the change as it stood at ``<checkpoint>``, leaving everything since unstaged.

    The checkpoint is a commit ``wt commit`` made earlier, which a later ``sync`` folded back into
    the uncommitted change. Its own diff (checkpoint parent to checkpoint) is staged onto the
    change's start commit, so ``git diff --cached`` shows the checkpoint and ``git diff`` shows
    only the work done after it. When master moved since the checkpoint, the patch applies only
    if master did not touch the same lines; otherwise nothing is staged and the conflict is named.
    ``stage-moves`` puts the review layout back. Nothing is committed.

    :param worktree_name: worktree path or bare name
    :param checkpoint: the checkpoint commit, e.g. ``606ba97d``
    """
    path, branch, base = worktree.resolve_worktree(worktree_name)
    resolved = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--verify", "--quiet", f"{checkpoint}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0:
        raise SystemExit(f"{checkpoint!r} is not a commit in {path}")
    commit = resolved.stdout.strip()
    worktree.uncommit_to_start(path, branch, base)
    patch = worktree.git(
        path, "diff", "-M", "-U0", "--no-color", "--src-prefix=a/", "--dst-prefix=b/", f"{commit}^", commit
    )
    # git() strips the output; the patch's last line needs its newline back for `git apply`.
    worktree.stage_patch(path, branch, patch + "\n", f"checkpoint {commit[:8]}")
    print(f"{branch}: staged checkpoint {commit[:8]}; `git diff` shows only the work since it")
    return 0
