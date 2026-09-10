#!/usr/bin/env python3
"""Land a worktree's proposed change on the main branch and clean the worktree up.

FOR THE USER ONLY. This script is on the Claude permission deny list; agents use
worktree_sync.py, which never touches the main branch.

    worktree_land.py <worktree> -m "message" [--keep-launch]

Steps, each refusing to continue on failure:
  1. sync    rebase the worktree's uncommitted change onto the current main branch
             (worktree_sync.py sync); stops on conflicts so you resolve them and rerun
  2. strip   restore .vscode/launch.json to the main branch's version (agents add
             verification entries there; pass --keep-launch to keep them)
  3. commit  one squashed commit of the whole diff on top of main (worktree_sync.py commit)
  4. merge   fast-forward the main checkout's branch to that commit (git merge --ff-only);
             the main checkout must have no uncommitted changes to the files being landed
  5. clean   git worktree remove <worktree> and git branch -d <branch>
  6. mark    the ticket named like the branch becomes DONE (--no-mark keeps its status)

Works on Linux, macOS and Windows.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from tools import worktree_sync
except ImportError:  # run as a plain script from the tools directory
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import worktree_sync  # noqa: E402

TICKET_REPO = worktree_sync.TICKET_REPO


def ticket_for(branch):
    """The ticket JSON whose id matches the branch name (``craw-27`` -> CRAW-27), or None."""
    return worktree_sync.ticket_for(branch)


def default_message(branch, body):
    """Subject ``CRAW-27: <title>``; body from the ticket's changes-made (what landed) or its
    description (what was asked), per ``body``; falls back to the branch name without a ticket."""
    ticket = ticket_for(branch)
    if not ticket or not ticket.get("title"):
        return branch
    ticket_id = ticket.get("id", branch.upper())
    subject = f"{ticket_id}: {ticket['title']}"
    if body == "changes" and ticket.get("changes-made"):
        return subject + "\n\n" + "\n".join(f"- {entry}" for entry in ticket["changes-made"])
    if body == "description" and ticket.get("description"):
        return subject + "\n\n" + ticket["description"]
    return subject


def main_checkout_of(worktree):
    """Path of the repository's main checkout, from the worktree listing."""
    listing = worktree_sync.git(worktree, "worktree", "list", "--porcelain")
    first = listing.splitlines()[0]
    if not first.startswith("worktree "):
        raise SystemExit("cannot read the main checkout from git worktree list")
    return Path(first[len("worktree "):]).resolve()


def run_tool(action, worktree, *extra):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "worktree_sync.py"), action, str(worktree), *extra],
        capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        raise SystemExit(f"{action} failed:\n{result.stderr.strip() or result.stdout.strip()}")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("worktree", nargs="?", default="", help=worktree_sync.WORKTREE_HELP)
    parser.add_argument("-m", "--message", default="",
                        help="override the commit message entirely (default: built from the ticket named like the branch)")
    parser.add_argument("--body", choices=("none", "changes", "description"), default="none",
                        help="commit body: none (default, subject only), changes (the ticket's "
                             "changes-made bullets), or description (the ticket's spec)")
    parser.add_argument("--keep-launch", action="store_true",
                        help="keep the worktree's .vscode/launch.json changes instead of restoring main's")
    parser.add_argument("--keep-worktree", action="store_true",
                        help="merge but leave the worktree and branch in place")
    parser.add_argument("--no-build", action="store_true",
                        help="skip rebuilding the main checkout after the merge")
    parser.add_argument("--no-mark", action="store_true",
                        help="leave the ticket's status alone instead of marking it DONE")
    args = parser.parse_args(argv)

    worktree, branch, main_branch = worktree_sync.resolve_worktree(args.worktree)
    message = args.message.strip() or default_message(branch, args.body)
    print(f"== landing {branch} as: {message.splitlines()[0]}")
    main_checkout = main_checkout_of(worktree)
    main_head_branch = worktree_sync.git(main_checkout, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if main_head_branch != main_branch:
        raise SystemExit(f"main checkout {main_checkout} is on {main_head_branch!r}, not {main_branch!r}; refusing")

    print(f"== sync {branch} onto {main_branch}")
    run_tool("sync", worktree)

    launch = worktree / ".vscode" / "launch.json"
    if not args.keep_launch and launch.exists():
        changed = worktree_sync.git(worktree, "diff", "--name-only", "--", ".vscode/launch.json")
        if changed:
            worktree_sync.git(worktree, "checkout", main_branch, "--", ".vscode/launch.json")
            print("== stripped .vscode/launch.json changes (verification entries)")

    if worktree_sync.changed_files(worktree):
        print(f"== squash-commit {branch}")
        run_tool("commit", worktree, "-m", message)
        landed = worktree_sync.git(worktree, "rev-parse", "--short", "HEAD")
        print(f"== fast-forward {main_branch} in {main_checkout}")
        merge = subprocess.run(["git", "-C", str(main_checkout), "merge", "--ff-only", branch],
                               capture_output=True, text=True)
        if merge.returncode != 0:
            raise SystemExit(f"fast-forward failed; the commit {landed} is on {branch}, nothing removed:\n"
                             f"{merge.stderr.strip()}")
        print(f"{main_branch} is now at {worktree_sync.git(main_checkout, 'rev-parse', '--short', 'HEAD')}")
    else:
        # Nothing left to land: the branch was already merged by hand. Only clean up, and only if
        # every commit on it is reachable from main so nothing is lost.
        ancestor = subprocess.run(
            ["git", "-C", str(main_checkout), "merge-base", "--is-ancestor", branch, main_branch],
            capture_output=True, text=True)
        if ancestor.returncode != 0:
            raise SystemExit(f"{branch} has no uncommitted change but is not merged into {main_branch}; refusing")
        print(f"== {branch} already merged into {main_branch}; cleaning up only")

    if args.keep_worktree:
        print(f"== kept worktree {worktree} and branch {branch}")
    else:
        print(f"== remove worktree {worktree} and branch {branch}")
        worktree_sync.git(main_checkout, "worktree", "remove", "--force", str(worktree))
        worktree_sync.git(main_checkout, "branch", "-d", branch)
        remove_leftovers(worktree)

    if not args.no_mark:
        mark_ticket_done(branch)
    if not args.no_build:
        rebuild_main_checkout(main_checkout)
    print("done")


def remove_leftovers(worktree):
    """Delete what git left behind when the worktree directory survived its removal.

    The VS Code Java extension keeps writing into an open worktree (``bin/``, ``target-ide/``,
    ``.project``), so ``git worktree remove`` deletes the tracked files and the directory stays.
    Anything still holding a ``.git`` entry is a live worktree and is left alone.
    """
    if not worktree.is_dir():
        return
    if (worktree / ".git").exists():
        print(f"== {worktree} still has a .git entry; left in place")
        return
    leftovers = sorted(path.name for path in worktree.iterdir())
    shutil.rmtree(worktree, ignore_errors=True)
    if worktree.is_dir():
        print(f"== could not remove {worktree}; close the editor holding it and delete it by hand")
        return
    print(f"== removed the leftover directory ({', '.join(leftovers)})")


def mark_ticket_done(branch):
    """Mark the branch's ticket DONE, now that its change is on the main branch.

    This runs after the worktree is gone, so the ticket CLI's guard against marking a ticket whose
    worktree still holds unmerged work sees the landed state. A branch with no ticket is fine.
    """
    ticket = ticket_for(branch)
    if not ticket:
        print(f"== ticket: no {branch.upper()} in {TICKET_REPO}; nothing to mark")
        return
    result = subprocess.run(["uv", "run", "python", "generate_board.py", "mark", "done", ticket["id"]],
                            cwd=str(TICKET_REPO), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"== ticket: {ticket['id']} not marked (the merge itself is done):\n"
              + (result.stderr or result.stdout).strip()[-1000:])
        return
    print(result.stdout.strip())


def rebuild_main_checkout(main_checkout):
    """Recompile the main checkout so running scenes launched from it pick up the merge.

    The VS Code Java extension does not notice files git changed underneath it, so a scene
    started with F5 after a land would otherwise run the pre-merge classes (missing routes answer
    HTTP 404, old behaviour persists). Maven projects get ``mvn -q compile``; other repos are left
    alone.
    """
    if not (main_checkout / "pom.xml").exists():
        return
    modules = "annotations,ixdar-app" if (main_checkout / "ixdar-app").is_dir() else None
    command = ["mvn", "-q", "compile"] + (["-pl", modules] if modules else [])
    print(f"== rebuild {main_checkout} ({' '.join(command)})")
    result = subprocess.run(command, cwd=str(main_checkout), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("rebuild failed (the merge itself is done):\n" + (result.stderr or result.stdout).strip()[-3000:])
    print("rebuilt; restart any running scene to pick up the merge")


def cli():
    """Console-script entry point (`land`)."""
    main(sys.argv[1:])


if __name__ == "__main__":
    cli()
