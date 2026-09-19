"""Close a worktree without landing it: keep the work on a tag, drop the worktree, archive the ticket.

FOR THE USER ONLY, like ``ixd land``: it deletes a worktree and its branch, which is the user's
call. Every spelling is on the Claude permission deny list.
"""

import datetime
from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command

TAG_PREFIX = "archive/"


@cli_command
def archive(
    reason: Annotated[str, CliOption(short="-r")],
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    message: Annotated[str, CliOption(short="-m")] = "",
    keep_worktree: bool = False,
    no_mark: bool = False,
) -> int:
    """Commit a worktree's change, tag it archive/<name>, remove the worktree, mark the ticket ARCHIVED.

    For an experiment that is not going to land: the work stays reachable as one commit on the
    tag, with the reason in the tag message and on the ticket, and nothing of it reaches the main
    branch. The diff is committed where it sits, on whatever main-branch commit the worktree was
    last synced to; there is no rebase, because replaying dead work onto today's main branch is
    conflict resolution for nothing. The launch.json entries stay in the commit as part of the
    record.

    Refuses when the branch has nothing to archive (no diff and no commits of its own) or when the
    tag already exists. Recover the work later with ``git worktree add <path> archive/<name>``.

    :param reason: why the work is being shelved rather than landed; goes on the tag and the ticket
    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param message: override the commit subject, instead of ``<TICKET>: <title> (archived)``
    :param keep_worktree: tag and mark, but leave the worktree and branch in place
    :param no_mark: leave the ticket's status alone instead of marking it ARCHIVED
    """
    if not reason.strip():
        raise SystemExit("--reason must say why the work is shelved")
    path, branch, main_branch = worktree.resolve_worktree(worktree_name)
    main_checkout = worktree.main_checkout_of(path)
    tag = TAG_PREFIX + branch
    if worktree.git(path, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", check=False):
        raise SystemExit(f"tag {tag} already exists; delete it first if this is a second archive of {branch}")

    ticket = worktree.ticket_for(branch)
    subject = message.strip() or default_subject(branch, ticket)
    ahead, _ = worktree.ahead_behind(path, branch, main_branch)
    if worktree.changed_files(path):
        print(f"== commit {branch}: {subject}")
        worktree.stage_all(path)
        worktree.git(path, "commit", "--quiet", "-m", subject + "\n\n" + reason.strip())
    elif ahead == 0:
        raise SystemExit(f"{branch} has no uncommitted change and no commits of its own; nothing to archive")
    else:
        print(f"== {branch} is already committed ({ahead} commit(s) ahead of {main_branch})")

    archived = worktree.git(path, "rev-parse", "--short", "HEAD")
    worktree.git(path, "tag", "-a", tag, "-m", reason.strip(), "HEAD")
    print(f"== tagged {tag} at {archived}")

    if keep_worktree:
        print(f"== kept worktree {path} and branch {branch}")
    else:
        print(f"== remove worktree {path} and branch {branch}")
        worktree.git(main_checkout, "worktree", "remove", "--force", str(path))
        worktree.git(main_checkout, "branch", "-D", branch)
        worktree.remove_leftovers(path)

    if not no_mark:
        mark_ticket_archived(branch, ticket, tag, archived, reason.strip())
    print(f"archived; restore with: git worktree add {path} {tag}")
    return 0


def default_subject(branch, ticket):
    """The commit subject: the ticket's id and title marked archived, or the branch name.

    :param branch: the worktree's branch, such as ``patch-104``
    :param ticket: the ticket JSON named like the branch, or None
    :return: ``PATCH-104: <title> (archived)``, or ``patch-104 (archived)`` without a ticket
    """
    if not ticket or not ticket.get("title"):
        return f"{branch} (archived)"
    return f"{ticket.get('id', branch.upper())}: {ticket['title']} (archived)"


def mark_ticket_archived(branch, ticket, tag, commit, reason):
    """Record the archive on the ticket and mark it ARCHIVED.

    Failures only warn: the tag exists and the worktree is gone, so aborting here would leave a
    worse state than an unmarked ticket.

    :param branch: the worktree's branch
    :param ticket: the ticket JSON named like the branch, or None
    :param tag: the archive tag
    :param commit: the short hash the tag points at
    :param reason: why the work was shelved
    """
    if not ticket:
        print(f"== ticket: no {branch.upper()} in {worktree.TICKET_REPO}; nothing to mark")
        return
    today = datetime.date.today().isoformat()
    note = f"Archived {today} without landing, as tag {tag} at {commit}: {reason}"
    done = "the tag and the removal are done"
    if worktree.ticket_command("update", ticket["id"], "--add-changes", note, after=done):
        worktree.ticket_command("mark", "archived", ticket["id"], after=done)
