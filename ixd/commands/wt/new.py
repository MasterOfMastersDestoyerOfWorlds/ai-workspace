"""Create a worktree and branch for a ticket."""

from typing import Annotated, Literal

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def new(
    ticket: Annotated[str, CliOption(positional=True)],
    repo: Literal["Ixdar", "ixdar-tickets", "ai-workspace"] = "Ixdar",
    base: str = "",
) -> int:
    """Create the worktree and branch off the main branch, seed it, and print the agent brief.

    The branch takes the ticket's name, which is how `ixd wt done` and `ixd land` find the ticket to
    mark. The virtualenv is created up front so an agent's first command is not a cold install. The
    brief that is printed is everything an agent needs to start: the paths, the ticket file, the
    verbs, and what is denied.

    With ``--base`` the worktree is stacked on another worktree's branch instead: it starts from that
    branch's tip, and `sync`, `commit` and `done` replay onto the base rather than the main branch,
    so its diff is only its own change. The base's change must be committed (`ixd wt commit`) for
    the stacked worktree to see it. Once the base lands and its branch is gone, the stacked worktree
    replays onto the main branch again; `ixd land` refuses it while the base is still unlanded.

    :param ticket: worktree and branch name, usually the ticket id such as craw-27
    :param repo: repository under REPO_HOME that gets the worktree
    :param base: stack on this worktree branch instead of the main branch
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
    start = main_branch
    if base:
        start = base.strip().lower()
        if not worktree.git(
            repository, "rev-parse", "--verify", "--quiet", f"refs/heads/{start}", check=False
        ):
            raise SystemExit(f"base branch {start!r} does not exist")
        if start == main_branch:
            raise SystemExit(f"{start!r} is the main branch; leave --base off")
        if worktree.git(repository, "rev-list", "--count", f"{main_branch}..{start}") == "0":
            print(
                f"note: {start} has no commits on top of {main_branch}; commit its change with `ixd wt commit {start}` and run `ixd wt sync {name}` to pick it up"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    worktree.git(repository, "worktree", "add", "-b", name, str(path), start)
    if base:
        worktree.git(repository, "config", f"branch.{name}.{worktree.BASE_KEY}", start)
        worktree.git(
            repository,
            "config",
            f"branch.{name}.{worktree.FORK_KEY}",
            worktree.git(repository, "rev-parse", start),
        )
    worktree.seed_environment(path)
    print(worktree.brief_text(path, name, start))
    return 0
