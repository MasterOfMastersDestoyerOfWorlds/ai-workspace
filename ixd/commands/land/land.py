"""Land a worktree's proposed change on the main branch and clean up after it.

FOR THE USER ONLY. Every spelling of this command is on the Claude permission deny list; agents use
``ixd wt``, which never touches the main branch.
"""

import subprocess
from typing import Annotated, Literal

from ... import editor, worktree
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
    Remove every .vscode/launch.json entry named after a ticket (``PATCH-117: quad-layout``), the
    F5 verification aids ``wt launch-add`` writes, while other launch.json changes, such as a new
    scene's entry, land. Squash the diff into one commit. Fast-forward the main checkout. Remove
    the worktree and its branch. Mark the branch's ticket DONE, which happens after the removal so
    the ticket CLI's unmerged-worktree guard sees the landed state.

    Before the removal, a VS Code window that shows the worktree is switched to the main checkout
    with ``code -r``, so its Java extension stops writing into the directory being deleted; this
    waits until the very end when land itself runs in that window's terminal, which the switch
    would close. ``code -r`` is used only when it will reach that window (the only window, or the
    last active one); otherwise the output says which window to switch. Whatever the extension
    wrote back meanwhile is cleared once more after the rebuild.

    Run on a folder git no longer has a worktree for (already landed, but an editor kept writing
    into it, or the shell still sits in the deleted directory), it only finishes the cleanup:
    VS Code off it, folder deleted.

    A sync that stopped on conflicts is finished here when the markers are gone, so resolving the
    files and running this one command is the whole recovery; it refuses, naming the files, while
    any marker remains.

    The main checkout is then recompiled: the VS Code Java extension does not notice files git
    changed underneath it, so the next F5 would otherwise run pre-merge classes and answer HTTP 404
    for routes that now exist.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param message: override the commit message entirely, instead of building it from the ticket
    :param body: commit body: the subject alone, the ticket's changes-made bullets, or its description
    :param keep_launch: keep the ticket-named launch.json entries instead of removing them
    :param keep_worktree: merge but leave the worktree and branch in place
    :param no_build: skip recompiling the main checkout after the merge
    :param no_mark: leave the ticket's status alone instead of marking it DONE
    """
    leftover = worktree.leftover_directory(worktree_name)
    if leftover is not None:
        clean_up_leftover(*leftover)
        return 0
    path, branch, main_branch = worktree.resolve_worktree(worktree_name, allow_rebase=True)
    subject = message.strip() or default_message(branch, body)
    print(f"== landing {branch} as: {subject.splitlines()[0]}")
    main_checkout = worktree.main_checkout_of(path)
    head = worktree.git(main_checkout, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if head != main_branch:
        raise SystemExit(f"main checkout {main_checkout} is on {head!r}, not {main_branch!r}; refusing")

    finish_interrupted_sync(path, branch, main_branch)
    print(f"== sync {branch} onto {main_branch}")
    worktree.sync(path, branch, main_branch)

    if not keep_launch:
        removed = worktree.strip_ticket_launch_entries(path)
        if removed:
            print(f"== removed ticket launch entries: {', '.join(removed)}")

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

    switch_last = keep_worktree or editor.running_inside(path)
    if not switch_last:
        editor.return_to_main_checkout(path, main_checkout)
    if keep_worktree:
        print(f"== kept worktree {path} and branch {branch}")
    else:
        print(f"== remove worktree {path} and branch {branch}")
        worktree.git(main_checkout, "worktree", "remove", "--force", str(path))
        worktree.git(main_checkout, "branch", "-d", branch)
        worktree.remove_leftovers(path)

    if not no_mark:
        mark_ticket_done(branch)
    try:
        if not no_build:
            rebuild_main_checkout(main_checkout)
    finally:
        if not keep_worktree:
            if switch_last:
                editor.return_to_main_checkout(path, main_checkout)
            worktree.remove_leftovers(path)
    print("done")
    return 0


def clean_up_leftover(slot, main_checkout):
    """Finish the cleanup of a worktree git no longer has: editor off it, folder gone.

    Landing or removing a worktree an editor still shows leaves a folder the editor keeps writing
    into, and a shell whose current directory was deleted. Nothing is merged or marked here.

    :param slot: the ``.claude/worktrees/<name>`` directory
    :param main_checkout: the repository's main checkout
    """
    branch = worktree.git(main_checkout, "show-ref", "--verify", f"refs/heads/{slot.name}", check=False)
    state = f"branch {slot.name} still exists" if branch else f"branch {slot.name} is gone"
    print(f"== {slot.name}: git has no worktree there ({state}); cleaning up what is left")
    editor.return_to_main_checkout(slot, main_checkout)
    worktree.remove_leftovers(slot)
    if worktree.enclosing_worktree_slot(worktree.shell_directory()) == slot:
        print(f"your shell is still in the deleted folder: cd {main_checkout}")
    print("done")


def finish_interrupted_sync(path, branch, main_branch):
    """Complete a sync that stopped on conflicts, once the working tree no longer holds markers.

    This is `ixd wt continue` run on the user's behalf: the resolved files are staged, the rebase
    step is committed, and the change is unpacked as an uncommitted diff again, so the land can go
    on as if the sync had never stopped. Markers still present are a refusal, not a prompt.

    :param path: the worktree directory
    :param branch: its branch
    :param main_branch: the branch being landed onto
    """
    if not worktree.rebase_in_progress(path):
        return
    markers = worktree.conflict_markers(path)
    if markers:
        raise SystemExit(
            f"{branch}: a sync is in progress and conflict markers remain in:\n{markers}\n"
            f"resolve them and run land again, or run `ixd wt abort {branch}` to drop the sync"
        )
    print(f"== finishing the interrupted sync of {branch} (conflicts resolved)")
    worktree.continue_rebase(path, branch, main_branch)


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
    worktree.ticket_command("mark", "done", ticket["id"], after="the merge itself is done")


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
