"""Land a worktree's proposed change on the main branch and clean up after it.

FOR THE USER ONLY. Every spelling of this command is on the Claude permission deny list; agents use
``ixd wt``, which never touches the main branch.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from ... import worktree
from ...registry import CliOption, cli_command

TICKET_REPO = worktree.TICKET_REPO

IXDAR_MODULES = "annotations,ixdar-app"


@cli_command
def land(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    message: Annotated[str, CliOption(short="-m")] = "",
    body: Literal["none", "changes", "description"] = "none",
    keep_launch: bool = False,
    keep_worktree: bool = False,
    no_build: bool = False,
    no_mark: bool = False,
) -> int:
    """Merge a worktree's change into the main branch and clean up after it.

    Six steps, each refusing to continue on failure. Replay the change onto the current main branch.
    Restore the main branch's .vscode/launch.json, because the entries an agent added are
    verification aids rather than part of the change. Squash the diff into one commit. Fast-forward
    the main checkout. Remove the worktree and its branch. Mark the branch's ticket DONE, which
    happens after the removal so the ticket CLI's unmerged-worktree guard sees the landed state.

    The main checkout is then recompiled: the VS Code Java extension does not notice files git
    changed underneath it, so the next F5 would otherwise run pre-merge classes and answer HTTP 404
    for routes that now exist.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param message: override the commit message entirely, instead of building it from the ticket
    :param body: commit body: the subject alone, the ticket's changes-made bullets, or its description
    :param keep_launch: keep the worktree's launch.json changes instead of restoring the main branch's
    :param keep_worktree: merge but leave the worktree and branch in place
    :param no_build: skip recompiling the main checkout after the merge
    :param no_mark: leave the ticket's status alone instead of marking it DONE
    """
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    subject = message.strip() or default_message(branch, body)
    print(f"== landing {branch} as: {subject.splitlines()[0]}")
    main_checkout = main_checkout_of(path)
    head = worktree.git(main_checkout, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if head != main_branch:
        raise SystemExit(f"main checkout {main_checkout} is on {head!r}, not {main_branch!r}; refusing")

    print(f"== sync {branch} onto {main_branch}")
    worktree.sync(path, branch, main_branch)

    if not keep_launch and (path / ".vscode" / "launch.json").exists():
        if worktree.git(path, "diff", "--name-only", "--", ".vscode/launch.json"):
            worktree.git(path, "checkout", main_branch, "--", ".vscode/launch.json")
            print("== stripped .vscode/launch.json changes (verification entries)")

    if worktree.changed_files(path):
        print(f"== squash-commit {branch}")
        worktree.commit(path, branch, main_branch, subject)
        landed = worktree.git(path, "rev-parse", "--short", "HEAD")
        print(f"== fast-forward {main_branch} in {main_checkout}")
        merge = subprocess.run(
            ["git", "-C", str(main_checkout), "merge", "--ff-only", branch], capture_output=True, text=True
        )
        if merge.returncode != 0:
            raise SystemExit(
                f"fast-forward failed; the commit {landed} is on {branch}, nothing removed:\n"
                f"{merge.stderr.strip()}"
            )
        print(f"{main_branch} is now at {worktree.git(main_checkout, 'rev-parse', '--short', 'HEAD')}")
    else:
        require_already_merged(main_checkout, branch, main_branch)

    if keep_worktree:
        print(f"== kept worktree {path} and branch {branch}")
    else:
        print(f"== remove worktree {path} and branch {branch}")
        worktree.git(main_checkout, "worktree", "remove", "--force", str(path))
        worktree.git(main_checkout, "branch", "-d", branch)
        remove_leftovers(path)

    if not no_mark:
        mark_ticket_done(branch)
    if not no_build:
        rebuild_main_checkout(main_checkout)
    print("done")
    return 0


def default_message(branch, body):
    """Build the commit subject, and body, from the ticket named like the branch.

    :param branch: the worktree's branch, such as ``craw-27``
    :param body: which ticket field becomes the commit body, if any
    :return: ``CRAW-27: <title>`` with the chosen body, or the branch name when there is no ticket
    """
    ticket = worktree.ticket_for(branch)
    if not ticket or not ticket.get("title"):
        return branch
    subject = f"{ticket.get('id', branch.upper())}: {ticket['title']}"
    if body == "changes" and ticket.get("changes-made"):
        return subject + "\n\n" + "\n".join(f"- {entry}" for entry in ticket["changes-made"])
    if body == "description" and ticket.get("description"):
        return subject + "\n\n" + ticket["description"]
    return subject


def main_checkout_of(path):
    """The repository's main checkout, read from the worktree listing.

    :param path: any worktree of the repository
    :return: the directory holding the shared .git
    """
    listing = worktree.git(path, "worktree", "list", "--porcelain")
    first = listing.splitlines()[0]
    if not first.startswith("worktree "):
        raise SystemExit("cannot read the main checkout from git worktree list")
    return Path(first[len("worktree ") :]).resolve()


def require_already_merged(main_checkout, branch, main_branch):
    """Refuse to clean up a branch with nothing to land unless the main branch already holds it.

    :param main_checkout: the repository's main checkout
    :param branch: the worktree's branch
    :param main_branch: the branch being landed onto
    """
    ancestor = subprocess.run(
        ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", branch, main_branch],
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise SystemExit(f"{branch} has no uncommitted change but is not merged into {main_branch}; refusing")
    print(f"== {branch} already merged into {main_branch}; cleaning up only")


def remove_leftovers(path):
    """Delete what git left behind when the worktree directory survived its removal.

    The VS Code Java extension keeps writing into an open worktree (``bin/``, ``target-ide/``,
    ``.project``), so ``git worktree remove`` deletes the tracked files and the directory stays.
    Anything still holding a ``.git`` entry is a live worktree and is left alone.

    :param path: the worktree directory git was asked to remove
    """
    if not path.is_dir():
        return
    if (path / ".git").exists():
        print(f"== {path} still has a .git entry; left in place")
        return
    leftovers = sorted(entry.name for entry in path.iterdir())
    shutil.rmtree(path, ignore_errors=True)
    if path.is_dir():
        print(f"== could not remove {path}; close the editor holding it and delete it by hand")
        return
    print(f"== removed the leftover directory ({', '.join(leftovers)})")


def mark_ticket_done(branch):
    """Mark the branch's ticket DONE, now that its change is on the main branch.

    A failure here only warns: the merge has already happened, so aborting would leave a worse state
    than an unmarked ticket. A branch with no ticket is fine.

    :param branch: the worktree's branch, whose upper-cased name is the ticket id
    """
    ticket = worktree.ticket_for(branch)
    if not ticket:
        print(f"== ticket: no {branch.upper()} in {TICKET_REPO}; nothing to mark")
        return
    result = subprocess.run(
        ["uv", "run", "python", "generate_board.py", "mark", "done", ticket["id"]],
        cwd=str(TICKET_REPO),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"== ticket: {ticket['id']} not marked (the merge itself is done):\n"
            + (result.stderr or result.stdout).strip()[-1000:]
        )
        return
    print(result.stdout.strip())


def rebuild_main_checkout(main_checkout):
    """Recompile the main checkout so a scene launched from it picks up the merge.

    :param main_checkout: the repository's main checkout
    """
    if not (main_checkout / "pom.xml").exists():
        return
    modules = IXDAR_MODULES if (main_checkout / "ixdar-app").is_dir() else None
    command = ["mvn", "-q", "compile"] + (["-pl", modules] if modules else [])
    print(f"== rebuild {main_checkout} ({' '.join(command)})")
    result = subprocess.run(command, cwd=str(main_checkout), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            "rebuild failed (the merge itself is done):\n" + (result.stderr or result.stdout).strip()[-3000:]
        )
    print("rebuilt; restart any running scene to pick up the merge")
