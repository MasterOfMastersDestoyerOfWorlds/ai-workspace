"""Verify a worktree's work and hand it to the user."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def done(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    skip_launch: bool = False,
) -> int:
    """Sync, build, run the launch entry, check tmp/ holds a screenshot, then mark the ticket REVIEW.

    Every step must pass. A failure stops with the reason and nothing is marked, because a ticket in
    REVIEW is a claim that the user can verify the work with F5.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param skip_launch: do not run the launch entry, though the screenshot check still applies
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    print(f"== done {branch}: sync, build, run the launch entry, check screenshots, mark REVIEW")
    worktree.sync(path, branch, main_branch)
    build(path)
    entry = require_launch_entry(path, branch)
    print(f"== launch entry: {entry.get('name')} (scene {entry.get('args')})")
    if skip_launch:
        print("== launch run SKIPPED by request; the entry was not executed this run")
    else:
        shot = path / "tmp" / f"{branch}-launch.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        worktree.run_step("launch run", worktree.launch_command(path, entry, shot), path)
    require_screenshot(path, branch)
    mark_review(branch)
    return 0


def build(path):
    """Compile the worktree, preferring the project's own build command over raw maven.

    :param path: the worktree directory
    """
    if worktree.cli_has_command(path, "build"):
        worktree.run_step("build", ["uv", "run", "ixdar-cli", "build"], path)
    elif (path / "pom.xml").exists():
        worktree.run_step("build", worktree.BUILD_COMMAND, path)
    else:
        print("== build: no pom.xml here, skipped")


def require_launch_entry(path, branch):
    """The launch entry for this ticket, or a refusal naming the entries that do exist.

    :param path: the worktree directory
    :param branch: its branch, whose upper-cased name the entry is expected to carry
    :return: the launch.json entry
    """
    entry = worktree.entry_for_ticket(path, branch)
    if entry is not None:
        return entry
    names = [str(one.get("name", "?")) for one in worktree.launch_entries(path)]
    raise SystemExit(
        f"no .vscode/launch.json entry named {branch.upper()!r} or {branch.upper()}: ...; add one "
        f"with `ixd wt launch-add {branch} --scene <id>` so the user can verify with F5.\n"
        f"entries present: {', '.join(names) or 'none'}"
    )


def require_screenshot(path, branch):
    """Refuse to mark a ticket when nothing under tmp/ shows the change working.

    :param path: the worktree directory
    :param branch: its branch, named in the refusal
    """
    shots = worktree.screenshots_under(path)
    if not shots:
        raise SystemExit(
            f"{branch}: tmp/ holds no screenshot, so nothing verifies the change; the ticket is not "
            f"marked. Capture one (run-scene --screenshot tmp/<name>.png, or the launch entry) and "
            f"run `ixd wt done` again."
        )
    print(f"== screenshots: {len(shots)} under tmp/ (newest {shots[-1].relative_to(path)})")


def mark_review(branch):
    """Move the branch's ticket to REVIEW, so the user knows it is ready to verify and land.

    :param branch: the worktree's branch, whose upper-cased name is the ticket id
    """
    ticket = worktree.ticket_for(branch)
    if not ticket:
        print(f"== ticket: no {branch.upper()} in {worktree.TICKET_REPO}; everything else passed")
        return
    worktree.run_step(
        "mark REVIEW",
        ["uv", "run", "python", "generate_board.py", "mark", "review", ticket["id"]],
        worktree.TICKET_REPO,
    )
    print(f"{ticket['id']} is REVIEW; the user reviews the diff and runs `ixd land {branch}`")
