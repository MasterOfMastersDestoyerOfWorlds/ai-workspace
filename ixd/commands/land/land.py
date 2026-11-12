"""Land a worktree's proposed change on the main branch and clean up after it.

FOR THE USER ONLY. Every spelling of this command is on the Claude permission deny list; agents use
``ixd wt``, which never touches the main branch.
"""

import datetime
import subprocess
from pathlib import Path
from typing import Annotated, Literal

from ... import editor, events, worktree
from ...registry import CliOption, cli_command

TICKET_REPO = worktree.TICKET_REPO
# git config key under branch.<name> listing the unlanded bases a --force land takes in.
FOLDED_KEY = "ixdfolded"


@cli_command
def land(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    message: Annotated[str, CliOption(short="-m")] = "",
    body: Literal["none", "changes", "description"] = "none",
    keep_launch: bool = False,
    keep_worktree: bool = False,
    no_build: bool = False,
    no_mark: bool = False,
    force: bool = False,
    folded_into: str = "",
) -> int:
    """Merge a worktree's change into the main branch and clean up after it.

    Once landed, a ``landed`` line goes to the workspace event log (``ixd/events.py``), which the
    ``land_events`` hook shows every Claude session on its next prompt.

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

    If git cannot delete the folder because the editor keeps writing into it, the land goes on:
    git's record of the worktree is dropped, and the branch, the DONE mark and the rebuild still
    happen; the folder is cleared at the end.

    Run on a folder git no longer has a worktree for (already landed, but an editor kept writing
    into it, or the shell still sits in the deleted directory), it finishes the cleanup: a branch
    already in the main branch is deleted, its ticket marked DONE, VS Code moved off, folder deleted.

    A sync that stopped on conflicts is finished here when the markers are gone, so resolving the
    files and running this one command is the whole recovery; it refuses, naming the files, while
    any marker remains.

    The main checkout is then recompiled: the VS Code Java extension does not notice files git
    changed underneath it, so the next F5 would otherwise run pre-merge classes and answer HTTP 404
    for routes that now exist.

    A worktree stacked on branches that have not landed (``wt new --base``) is refused, unless
    ``--force``: then the worktree comes off its stack and lands as one commit holding every
    unlanded base under it, for when the top of a stack already carries all of its bases' work.
    Each base is then tagged ``folded/<name>`` at its tip, its worktree and branch are removed, and
    its ticket is marked DONE with a note naming the ticket it landed inside. It refuses while a
    base's worktree has uncommitted changes, which the land would leave behind.

    ``--folded-into <branch>`` retires a worktree whose work already landed inside another one,
    the same way, without merging anything: for a base a ``--force`` land did not retire.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param message: override the commit message entirely, instead of building it from the ticket
    :param body: commit body: the subject alone, the ticket's changes-made bullets, or its description
    :param keep_launch: keep the ticket-named launch.json entries instead of removing them
    :param keep_worktree: merge but leave the worktree and branch in place
    :param no_build: skip recompiling the main checkout after the merge
    :param no_mark: leave the ticket's status alone instead of marking it DONE
    :param force: land a stacked worktree together with the unlanded bases it sits on
    :param folded_into: the branch this worktree's work already landed inside; retire it, merge nothing
    """
    leftover = worktree.leftover_directory(worktree_name)
    if leftover is not None:
        clean_up_leftover(*leftover)
        return 0
    path, branch, main_branch = worktree.resolve_worktree(worktree_name, allow_rebase=True)
    if folded_into:
        if worktree.changed_files(path):
            raise SystemExit(f"{branch} has uncommitted changes, which retiring it would leave behind")
        print(f"== retiring {branch}: its work landed inside {folded_into}")
        retire_folded_base(
            worktree.main_checkout_of(path), branch, folded_into.strip().lower(), keep_worktree, no_mark
        )
        print("done")
        return 0
    base = worktree.base_branch_of(path, branch)
    if base and not force:
        raise SystemExit(
            f"{branch} is stacked on {base}, which has not landed; land {base} first, or run land "
            f"--force to land {base} inside {branch}"
        )
    # A --force land that stopped (on sync conflicts, say) has already unstacked; the bases it
    # took in are recorded so the land run again still retires them.
    recorded = worktree.git(path, "config", "--get", f"branch.{branch}.{FOLDED_KEY}", check=False)
    folded = unstack(path, branch) if base else recorded.split()
    if folded:
        # resolve_worktree named the base as the branch to land onto; off the stack it is main.
        main_branch = worktree.main_branch_of(path)
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
        remove_worktree_record(main_checkout, path)
        worktree.git(main_checkout, "branch", "-d", branch)
        worktree.remove_leftovers(path)

    if not no_mark:
        mark_ticket_done(branch)
    for base in folded:
        retire_folded_base(main_checkout, base, branch, keep_worktree, no_mark)
    ticket = worktree.ticket_for(branch) or {}
    events.record(
        "landed",
        ticket.get("id", branch),
        commit=worktree.git(main_checkout, "rev-parse", "--short", "HEAD"),
        branch=main_branch,
    )
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


def unstack(path, branch):
    """Take a stacked worktree off its stack so its sync replays every unlanded base's commits too.

    The bases are walked down to the lowest one that has not landed. The worktree inherits that
    base's fork, if it has one (its own base already landed), so commits that landed under other
    hashes are not replayed again; otherwise the sync replays everything from the main branch up.

    :param path: the stacked worktree
    :param branch: its branch
    :return: the unlanded bases, nearest first
    """
    chain = []
    base = worktree.base_branch_of(path, branch)
    while base:
        if base in chain or base == branch:
            raise SystemExit(f"the stack under {branch} loops through {base}; refusing")
        chain.append(base)
        base = worktree.base_branch_of(path, base)
    head = worktree.git(path, "rev-parse", "HEAD")
    for base in chain:
        slot = worktree_of_branch(path, base)
        if slot and worktree.changed_files(slot):
            raise SystemExit(
                f"{base} has uncommitted changes in {slot}, which landing {branch} would leave "
                f"behind; commit them on {base} or carry them into {branch} first"
            )
        contained = subprocess.run(["git", "-C", str(path), "merge-base", "--is-ancestor", base, head])
        if contained.returncode != 0:
            print(
                f"== {base}'s commits are not in {branch}'s history; landing assumes {branch}'s "
                f"diff carries them (tag folded/{base} keeps them either way)"
            )
    fork = worktree.stack_fork_of(path, chain[-1])
    worktree.git(path, "config", "--unset", f"branch.{branch}.{worktree.BASE_KEY}", check=False)
    if fork:
        worktree.git(path, "config", f"branch.{branch}.{worktree.FORK_KEY}", fork)
    else:
        worktree.git(path, "config", "--unset", f"branch.{branch}.{worktree.FORK_KEY}", check=False)
    worktree.git(path, "config", f"branch.{branch}.{FOLDED_KEY}", " ".join(chain))
    print(f"== --force: {branch} is off its stack and lands with {', '.join(chain)}")
    return chain


def worktree_of_branch(path, branch):
    """The worktree that has a branch checked out, or None.

    :param path: any checkout of the repository
    :param branch: the branch name
    :return: the worktree directory, or None when no worktree holds the branch
    """
    slot = None
    for line in worktree.git(path, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            slot = Path(line[len("worktree ") :])
        elif line == f"branch refs/heads/{branch}":
            return slot
    return None


def retire_folded_base(main_checkout, base, branch, keep_worktree, no_mark):
    """Close a base that landed inside the worktree above it: tag it, remove it, mark it DONE.

    :param main_checkout: the repository's main checkout
    :param base: the folded base's branch
    :param branch: the branch it landed inside
    :param keep_worktree: leave the base's worktree and branch in place
    :param no_mark: leave the base's ticket alone
    """
    tag = f"folded/{base}"
    if not worktree.git(main_checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{base}", check=False):
        print(f"== {base} is already gone; nothing to retire")
        return
    if worktree.git(main_checkout, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", check=False):
        print(f"== tag {tag} already exists; left as it is")
    else:
        worktree.git(main_checkout, "tag", "-a", tag, "-m", f"landed inside {branch}", f"refs/heads/{base}")
        print(f"== tagged {tag} at {worktree.git(main_checkout, 'rev-parse', '--short', tag + '^{}')}")
    slot = worktree_of_branch(main_checkout, base)
    if keep_worktree:
        print(f"== kept {base}'s worktree and branch")
    else:
        print(f"== remove {base}'s worktree and branch")
        if slot:
            editor.return_to_main_checkout(slot, main_checkout)
            remove_worktree_record(main_checkout, slot)
        worktree.git(main_checkout, "branch", "-D", base)
        if slot:
            worktree.remove_leftovers(slot)
    ticket = worktree.ticket_for(base)
    if no_mark or not ticket:
        return
    into = (worktree.ticket_for(branch) or {}).get("id", branch)
    note = f"Landed {datetime.date.today().isoformat()} inside {into} (ixd land --force); its branch is tag {tag}"
    done = "the merge itself is done"
    if worktree.ticket_command("update", ticket["id"], "--add-changes", note, after=done):
        worktree.ticket_command("mark", "done", ticket["id"], after=done)


def remove_worktree_record(main_checkout, path):
    """Remove the worktree from git, tolerating a folder an editor keeps writing into.

    Run from the terminal of the VS Code window that shows the worktree, ``land`` switches that
    window away only at the very end, so the Java extension is still writing ``target-ide/`` while
    git deletes the folder: git removes the tracked files and its own record, then fails on the
    final directory removal with "Directory not empty". That folder is cleared at the end of
    ``land``; the branch deletion, the DONE mark and the rebuild must not be skipped over it.

    :param main_checkout: the repository's main checkout
    :param path: the worktree directory
    """
    removal = subprocess.run(
        ["git", "-C", str(main_checkout), "worktree", "remove", "--force", str(path)],
        capture_output=True,
        text=True,
    )
    if removal.returncode == 0:
        return
    worktree.git(main_checkout, "worktree", "prune")
    listing = worktree.git(main_checkout, "worktree", "list", "--porcelain").splitlines()
    if f"worktree {path}" in listing:
        raise SystemExit(f"git worktree remove failed and git still lists {path}:\n{removal.stderr.strip()}")
    print("== git dropped the worktree but not its folder (an editor is writing into it); cleared at the end")


def clean_up_leftover(slot, main_checkout):
    """Finish a land that stopped after the merge: branch gone, ticket DONE, editor off, folder gone.

    Landing or removing a worktree an editor still shows leaves a folder the editor keeps writing
    into, and a shell whose current directory was deleted. A land that stopped there also left its
    branch and an unmarked ticket; when the branch is already in the main branch, both are finished
    here. Nothing is merged here, and an unmerged branch is left alone.

    :param slot: the ``.claude/worktrees/<name>`` directory
    :param main_checkout: the repository's main checkout
    """
    branch = worktree.git(main_checkout, "show-ref", "--verify", f"refs/heads/{slot.name}", check=False)
    state = f"branch {slot.name} still exists" if branch else f"branch {slot.name} is gone"
    print(f"== {slot.name}: git has no worktree there ({state}); cleaning up what is left")
    main_branch = worktree.git(main_checkout, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    merged = not branch or (
        subprocess.run(
            ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", slot.name, main_branch],
            capture_output=True,
        ).returncode
        == 0
    )
    if branch and merged:
        print(f"== {slot.name} is already in {main_branch}; deleting the branch")
        worktree.git(main_checkout, "branch", "-d", slot.name)
    elif branch:
        print(f"== {slot.name} is not in {main_branch}; branch and ticket left alone")
    ticket = worktree.ticket_for(slot.name)
    if merged and ticket and ticket.get("status") != "DONE":
        mark_ticket_done(slot.name)
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
    # The whole reactor: `-pl` would resolve the skipped modules from ~/.m2, which every
    # worktree shares at one version.
    command = ["mvn", "-q", "compile"]
    print(f"== rebuild {main_checkout} ({' '.join(command)})")
    result = subprocess.run(command, cwd=str(main_checkout), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            "rebuild failed (the merge itself is done):\n" + (result.stderr or result.stdout).strip()[-3000:]
        )
    print("rebuilt; restart any running scene to pick up the merge")
