"""Verify a worktree's work and hand it to the user."""

from typing import Annotated

from ... import diagnostics, worktree
from ...registry import CliOption, cli_command


@cli_command
def done(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
) -> int:
    """Sync, refuse leftover diagnostics, build, run the launch entry, check tmp/, mark REVIEW.

    Log lines, public counters, describe/dump helpers, sample limits and ``*Probe.java`` files
    the diff adds are refused unless the ticket's definition of done names them: strip them, or
    name them there when they are meant to land. Every step must pass. A failure stops with the reason and nothing is marked, because a ticket in
    REVIEW is a claim that the user can verify the work with F5. The launch entry is run exactly as
    F5 runs it, only headless, so a crash on that path is caught here and never at the user's
    keyboard; there is no way to skip it.

    After the build, each module's Maven classes are copied over the IDE's ``target-ide/``
    output, which is what F5 actually runs: VS Code's Java extension may not have rebuilt after
    the agent's edits, and would otherwise launch stale classes without a word.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    print(f"== done {branch}: sync, build, run the launch entry, check screenshots, mark REVIEW")
    worktree.sync(path, branch, main_branch)
    require_no_leftover_diagnostics(path, branch)
    build(path)
    refreshed = worktree.refresh_ide_classes(path)
    if refreshed:
        print(
            f"== IDE classes: {', '.join(module.name for module in refreshed)} target-ide/ now hold the build"
        )
    entry = require_launch_entry(path, branch)
    print(f"== launch entry: {entry.get('name')} (scene {entry.get('args')})")
    shot = path / "tmp" / f"{branch}-launch.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    worktree.run_step("launch run", worktree.launch_command(path, entry, shot), path)
    require_screenshot(path, branch)
    mark_review(branch)
    return 0


def require_no_leftover_diagnostics(path, branch):
    """Refuse when the diff adds debugging scaffolding the ticket's definition of done never names.

    :param path: the worktree directory
    :param branch: its branch, whose upper-cased name is the ticket id
    """
    ticket = worktree.ticket_for(branch) or {}
    findings = diagnostics.scan(path)
    left = diagnostics.unaccounted(findings, ticket.get("definition-of-done", ""))
    if not left:
        print(f"== diagnostics: {len(findings)} added, all named in the definition of done")
        return
    listing = "\n".join(f"  {finding.describe()}" for finding in left)
    ticket_id = ticket.get("id", branch.upper())
    raise SystemExit(
        f"the diff adds {len(left)} diagnostic(s) the definition of done of {ticket_id} does not "
        f"name; nothing marked.\n{listing}\nStrip each one (ask the running scene through an "
        f"ixdar-cli probe instead of committing a log line), or, when it is meant to land, name "
        f"it in the DoD: generate_board.py update {ticket_id} --append-definition-of-done "
        f'"Keeps <identifier>: <why>."'
    )


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
