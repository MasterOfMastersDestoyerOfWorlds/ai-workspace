"""Create a worktree and branch for a ticket."""

from typing import Annotated, Literal

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def new(
    ticket: Annotated[str, CliOption(positional=True)],
    repo: Literal["Ixdar", "ixdar-tickets", "ai-workspace"] = "Ixdar",
) -> int:
    """Create the worktree and branch off the main branch, seed it, and print the agent brief.

    The branch takes the ticket's name, which is how `ixd wt done` and `ixd land` find the ticket to
    mark. The virtualenv is created up front so an agent's first command is not a cold install. The
    brief that is printed is everything an agent needs to start: the paths, the ticket file, the
    verbs, and what is denied.

    :param ticket: worktree and branch name, usually the ticket id such as craw-27
    :param repo: repository under REPO_HOME that gets the worktree
    """
    name = ticket.strip().lower()
    if not worktree.WORKTREE_NAME.match(name):
        raise SystemExit(f"{ticket!r} is not a usable worktree name (use letters, digits, - . _)")
    repository = worktree.CODE_ROOT / repo
    if not (repository / ".git").exists():
        raise SystemExit(f"{repository} is not a git repository")
    main_branch = worktree.main_branch_of(repository)
    path = repository / ".claude" / "worktrees" / name
    if path.exists():
        raise SystemExit(f"{path} already exists; pick another name or work in the one that is there")
    existing = worktree.git(repository, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False)
    if existing:
        raise SystemExit(f"branch {name!r} already exists ({existing[:8]}); pick another name")
    path.parent.mkdir(parents=True, exist_ok=True)
    worktree.git(repository, "worktree", "add", "-b", name, str(path), main_branch)
    worktree.seed_environment(path)
    print(worktree.brief_text(path, name, main_branch))
    return 0
