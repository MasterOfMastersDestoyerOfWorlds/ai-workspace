"""Open a ticket for review: its page in the browser and its worktree in VS Code."""

import json
import shutil
import webbrowser
from pathlib import Path
from typing import Annotated

from ... import editor, worktree
from . import _desktop as desktop
from . import _menu as menu
from . import _page as review_page
from ...registry import CliOption, cli_command

DESCRIPTION_WIDTH = 160


CLOSED = ("DONE", "ARCHIVED")


def status_of(ticket):
    """The ticket's status, upper-cased."""
    return str(ticket.get("status", "")).upper()


def live_tickets():
    """Every ticket under ``content/``, as {id: ticket JSON}."""
    found = {}
    for path in sorted((worktree.TICKET_REPO / "content").glob("*/*.json")):
        try:
            ticket = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(ticket, dict):
            found[str(ticket.get("id", path.stem)).upper()] = ticket
    return found


def dependents(tickets):
    """Each ticket's open dependents, direct or through a chain, as {id: set of ids}.

    A link counts from either side (``blocks`` on the blocker, ``blocked-by`` on the blocked), and
    only tickets that are not DONE or ARCHIVED count as dependents.
    """
    direct = {ticket_id: set() for ticket_id in tickets}
    for ticket_id, ticket in tickets.items():
        for blocked in ticket.get("blocks") or []:
            direct.setdefault(ticket_id, set()).add(str(blocked).upper())
        for blocker in ticket.get("blocked-by") or []:
            direct.setdefault(str(blocker).upper(), set()).add(ticket_id)
    open_ids = {ticket_id for ticket_id, ticket in tickets.items() if status_of(ticket) not in CLOSED}
    found = {}
    for ticket_id in tickets:
        seen, stack = set(), list(direct.get(ticket_id, ()))
        while stack:
            other = stack.pop()
            if other in seen or other == ticket_id:
                continue
            seen.add(other)
            stack += direct.get(other, ())
        found[ticket_id] = seen & open_ids
    return found


def review_tickets():
    """Every live ticket in the REVIEW state, as (id, ticket JSON, score), highest score first.

    The score is how many open tickets depend on the ticket, directly or through a chain; ties go
    by id.
    """
    tickets = live_tickets()
    scores = {ticket_id: len(ids) for ticket_id, ids in dependents(tickets).items()}
    found = [
        (ticket_id, ticket, scores[ticket_id])
        for ticket_id, ticket in tickets.items()
        if status_of(ticket) == "REVIEW"
    ]
    return sorted(found, key=lambda item: (-item[2], item[0]))


def worktree_of(ticket_id, ticket):
    """The ticket's worktree under its repo's ``.claude/worktrees`` (or Ixdar's), or None.

    A directory without a ``.git`` entry is what an editor leaves after ``land`` removed the
    worktree, so it does not count.
    """
    repos = [ticket.get("repo") or "Ixdar", "Ixdar"]
    for repo in repos:
        candidate = worktree.CODE_ROOT / repo / ".claude" / "worktrees" / ticket_id.lower()
        if (candidate / ".git").exists():
            return candidate
    return None


def one_line(text, width=DESCRIPTION_WIDTH):
    """Text squashed onto one line and cut at a word boundary."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= width else flat[:width].rsplit(" ", 1)[0] + " ..."


def choose():
    """Show the REVIEW tickets as a menu and return the id picked, or None."""
    tickets = review_tickets()
    if not tickets:
        print("no tickets are in REVIEW")
        return None
    entries = []
    for ticket_id, ticket, score in tickets:
        marker = "" if worktree_of(ticket_id, ticket) else "  (no worktree)"
        entry = [f"[{score:>2}] {ticket_id:<11} {ticket.get('title', '')}{marker}"]
        if ticket.get("description"):
            entry.append(one_line(ticket["description"]))
        entries.append(entry)
    index = menu.pick(entries)
    return None if index is None else tickets[index][0]


def focus_editor(path):
    """Bring up the VS Code window on the worktree, opening one when none shows it.

    ``code <folder>`` already does both: it focuses the window that has the folder open and opens
    a new window otherwise. The titles are read first only to say which of the two happened.
    """
    if not shutil.which(editor.CODE):
        print(f"== VS Code: no `{editor.CODE}` on PATH")
        return
    # From home, never the worktree: see editor.started_inside.
    titles = editor.window_titles(Path.home()) or []
    already = any(editor.shows_folder(title, path) for title in titles)
    result = editor.run_code([str(path)], Path.home())
    if result is None or result.returncode != 0:
        reason = "no answer" if result is None else (result.stderr or result.stdout).strip()
        print(f"== VS Code: `{editor.CODE} {path}` failed: {reason}")
        return
    print(f"== VS Code: {'focused the window on' if already else 'opened a new window on'} {path.name}")


def arrange(page, path):
    """On Hyprland, put the page and the VS Code window on two adjacent free workspaces.

    The page goes on the first workspace right of every one in use and VS Code on the next, and
    the view switches to the page. A VS Code window already showing the worktree is moved there
    rather than duplicated, and the workspace it leaves does not count as in use.

    :param page: the page file
    :param path: the worktree to show in VS Code, or None for the page alone
    """
    existing = desktop.editor_window(path, editor.shows_folder) if path else None
    page_workspace, editor_workspace = desktop.free_pair(ignore={existing} if existing else ())
    placed = desktop.open_page(page.as_uri(), page_workspace)
    if placed == "placed":
        print(f"== page: on workspace {page_workspace}")
    elif placed == "stayed":
        print(f"== page: opened, but its window would not move to workspace {page_workspace}")
    else:
        webbrowser.open(page.as_uri())
        print("== page: opened in the browser (no new window appeared to move)")
    if path is not None:
        outcome = desktop.open_editor(path, editor_workspace, existing, editor.run_code)
        if outcome in ("moved", "opened"):
            print(f"== VS Code: {outcome} the window on {path.name} to workspace {editor_workspace}")
        else:
            print(f"== VS Code: {outcome}")
    desktop.show(page_workspace)


@cli_command
def review(
    ticket: Annotated[str, CliOption(positional=True)] = "", no_editor: bool = False, page_only: bool = False
) -> int:
    """Open a ticket's page in the browser and its worktree in VS Code, or pick one in REVIEW.

    The page answers why, what, where and how fast before any diff is opened, in this order:

    - Open decisions: the ticket's unresolved ``unknowns``, in a highlighted box.
    - Context: the ticket's ``review-summary`` (what changed and why it is needed, at most 50
      words in 3 sentences, which ``generate_board.py`` enforces; set with ``generate_board.py update ID
      --review-summary @FILE``; a highlighted box says so when it is missing), the repo-plan phase
      the description names, the branch this worktree is stacked on and the open tickets stacked
      on it (links to their review pages), blocked-by / blocks, and the rulings paragraph.
    - Boundaries that changed: .java classes added, deleted and moved (old -> new package), and
      public/protected declarations the diff adds or removes. The diff runs from the change's
      start (the stack fork, or the merge base with its base branch) to the working tree,
      untracked files included, as ``stage-moves`` reads it.
    - Repeated edits: the clusters ``ixd wt clusters`` lists (hunks making the same edit, matched
      as identical lines, the same token rewrite, or the same syntax-tree edit), each with its
      pattern, hunk count, files and a representative hunk linked into VS Code.
    - Files to read first: ranked by changed lines that are neither mechanical (``stage-moves``'
      rules: renames, imports naming a moved class, comment-only Java files) nor in a cluster,
      each a VS Code link opening the file at its first such hunk; files whose changes are all
      repeated edits, mechanical-only and deleted files are listed apart.
    - Measurements: ``tmp/<ticket-lowercase>-measurements.json`` in the worktree, as a
      before/after table with percent change, regressions highlighted. The schema::

          {"measurements": [{"suite": "quad-suite", "item": "buddha", "metric": "seamless",
                             "unit": "ms", "before": 3520, "after": 3384,
                             "lower_is_better": true, "note": "median of 4"}],
           "tests": {"command": "mvn test", "run": 538, "failed": 0},
           "tolerance_percent": 0, "notes": "how and where it was measured"}

      ``before``/``after`` are numbers, or strings (fingerprints) compared for equality;
      ``lower_is_better`` is true, false, or null for a value with no better direction; a
      change the wrong way by more than ``tolerance_percent`` is a regression. ``tests`` may be
      a list. A bare list is read as ``measurements``.
    - Verification: the F5 launch entry, the test counts from the measurements file and the
      screenshots under ``tmp/`` as thumbnails.
    - Definition of done and todos; then, collapsed, the worktree (branch, uncommitted files, last
      agent note), changes made, the raw description, testing plan, related files and the JSON.

    A ticket with no worktree still renders, without the sections read from the diff and tmp/.
    The page is written to ``~/.cache/ixd/review/<ID>.html`` and carries buttons that open the
    worktree and the ticket JSON in VS Code. The worktree is opened with ``code <folder>``, which
    focuses the window already showing it and opens a new one otherwise.

    Under Hyprland the page opens in a browser window of its own on the first empty workspace
    right of every workspace in use, VS Code goes on the one after it (a window already showing
    the worktree is moved there, not duplicated), and the view switches to the page.

    With no ticket, every ticket in the REVIEW state is listed with its description and a score in
    brackets, the number of open tickets that depend on it directly or through a chain, highest
    score first; move with
    the up and down arrows (or k and j) or type an entry's number, then press enter to open it.

    :param ticket: ticket id such as ``craw-29``; omit it to choose from the tickets in REVIEW
    :param no_editor: open only the page, leaving VS Code alone
    :param page_only: write the page and print its path; open no browser or editor, move no window
    """
    ticket_id = ticket or choose()
    if not ticket_id:
        return 0
    ticket_id = ticket_id.strip().upper()
    ticket_path = worktree.ticket_path_for(ticket_id)
    if ticket_path is None:
        raise SystemExit(f"no ticket {ticket_id} under {worktree.TICKET_REPO}/content or done")
    data = json.loads(ticket_path.read_text(encoding="utf-8"))
    path = worktree_of(ticket_id, data)
    page = review_page.page_path(ticket_id)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(review_page.render(data, ticket_path, path), encoding="utf-8")
    print(f"== page: {page}")
    if page_only:
        return 0
    if path is None:
        print(f"== VS Code: {ticket_id} has no worktree")
    if desktop.available():
        arrange(page, None if no_editor else path)
        return 0
    webbrowser.open(page.as_uri())
    if path is not None and not no_editor:
        focus_editor(path)
    return 0
