"""One ticket rendered as a self-contained HTML page, for `ixd review`.

The page is written to a cache file and opened from ``file://``, so it needs no server: styles are
inline, screenshots are ``file://`` images, and the VS Code buttons are ``vscode://file`` links,
which VS Code registers as a URL scheme when it is installed.

It answers, before any diff is opened, why the change exists (the ticket's ``review-summary``),
what it changes (classes and public signatures, from the worktree diff), where to read (files
ranked by non-mechanical changed lines), and whether anything got slower (the worktree's
``tmp/<ticket>-measurements.json``). The ticket's own text follows, collapsed.
"""

import html
import json
import os
import re
from pathlib import Path

from ... import worktree as wt
from . import _changes as changes

NUMBERED_ITEM = re.compile(r"(?:^|\s)\d+\.\s+")
ABSOLUTE_PATH = re.compile(r"^(/|~/)")
PLAN_PHASE = re.compile(r"\b(?:repo plan )?phase \d[\w.]*(?:, merge [\w.]+)?", re.IGNORECASE)
RULINGS = re.compile(r"^\s*(?:rulings?\b|.*\(user ruling\))", re.IGNORECASE)
MEASUREMENTS_NAME = "{ticket}-measurements.json"
SCREENSHOT_LIMIT = 60
READ_FIRST_COUNT = 6
MECHANICAL_LABELS = {"renamed": "moved", "modified": "imports/comments only", "added": "new"}
READ_FIRST_BADGES = {
    "added": ' <span class="badge">new</span>',
    "renamed": ' <span class="badge">moved</span>',
}

STYLE = """
:root { color-scheme:dark; --bg:#0f1115; --fg:#e6edf3; --muted:#8d96a0; --card:#161a20;
  --line:#2d333b; --accent:#58a6ff; --badge:#21262d; --review:#a371f7; --todo:#8d96a0;
  --done:#3fb950; --progress:#d29922; --warn-bg:#2d2208; --warn-line:#d29922; --bad:#f85149;
  --good:#3fb950; --bad-bg:#3a1416; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:1040px; margin:0 auto; padding:32px 16px 64px; }
header .id { color:var(--muted); font:600 14px ui-monospace, monospace; }
h1 { margin:4px 0 12px; font-size:26px; line-height:1.25; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:0 0 10px; }
h3 { font-size:14px; margin:14px 0 6px; }
section { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 20px; margin:16px 0; overflow-x:auto; }
section.alert { background:var(--warn-bg); border-color:var(--warn-line); }
section.alert h2 { color:var(--warn-line); }
.summary p { font-size:16px; margin:0 0 10px; }
.meta { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:14px; }
.badge { background:var(--badge); border-radius:999px; padding:2px 10px; font-size:13px; }
.status { color:#fff; font-weight:600; }
.buttons { display:flex; flex-wrap:wrap; gap:8px; }
.button { display:inline-block; background:var(--accent); color:#0f1115; text-decoration:none;
  padding:8px 14px; border-radius:8px; font-weight:600; }
.button.secondary { background:var(--badge); color:var(--fg); }
a { color:var(--accent); }
ol, ul { margin:0; padding-left:22px; }
li { margin:4px 0; }
code, pre { font-family:ui-monospace, monospace; font-size:13px; }
pre { white-space:pre-wrap; word-break:break-word; margin:0; }
.muted { color:var(--muted); }
.shots { display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:12px; }
.shots figure { margin:0; }
.shots img { width:100%; border:1px solid var(--line); border-radius:6px; display:block; }
.shots figcaption { font-size:12px; color:var(--muted); margin-top:4px; word-break:break-all; }
dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; margin:0 0 12px; }
dt { color:var(--muted); }
dd { margin:0; word-break:break-word; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; padding:4px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
tr.worse td { background:var(--bad-bg); }
.worse-text { color:var(--bad); font-weight:600; }
.better-text { color:var(--good); }
.add { color:var(--good); }
.del { color:var(--bad); }
details > summary { cursor:pointer; color:var(--muted); }
details.ticket-text { margin:16px 0; }
details.ticket-text > summary { font-size:13px; text-transform:uppercase; letter-spacing:.06em; }
"""

STATUS_COLOURS = {
    "REVIEW": "var(--review)",
    "TODO": "var(--todo)",
    "DONE": "var(--done)",
    "IN_PROGRESS": "var(--progress)",
}


def e(value):
    """HTML-escape any value."""
    return html.escape(str(value))


def vscode_link(path, line=None):
    """The ``vscode://file`` URL that opens a file or folder in VS Code, at a line when given."""
    url = "vscode://file" + Path(path).expanduser().absolute().as_posix()
    return f"{url}:{line}" if line else url


def page_path(ticket_id):
    """Where a ticket's page is written: ``$XDG_CACHE_HOME/ixd/review/<ID>.html``."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "ixd" / "review" / f"{ticket_id.upper()}.html"


def measurements_path(worktree, ticket_id):
    """The measurements file a ticket's agent writes: ``tmp/<ticket-lowercase>-measurements.json``."""
    return Path(worktree) / "tmp" / MEASUREMENTS_NAME.format(ticket=ticket_id.lower())


def paragraphs(text):
    """Blank-line separated paragraphs of plain text."""
    return "".join(f"<p>{e(chunk.strip())}</p>" for chunk in re.split(r"\n\s*\n", text) if chunk.strip())


def numbered(text):
    """A ``1. ... 2. ...`` string as an ordered list, or plain paragraphs when it is not numbered."""
    items = [item.strip() for item in NUMBERED_ITEM.split(text) if item.strip()]
    if len(items) < 2 or not NUMBERED_ITEM.match(text.strip()):
        return paragraphs(text)
    return "<ol>" + "".join(f"<li>{e(item)}</li>" for item in items) + "</ol>"


def bullet_list(items, render=e):
    """A list of strings as a bullet list."""
    return "<ul>" + "".join(f"<li>{render(item)}</li>" for item in items) + "</ul>"


def related_file(entry):
    """A related-files entry, linked into VS Code when it is an absolute path."""
    if ABSOLUTE_PATH.match(entry):
        return f'<a href="{e(vscode_link(entry))}"><code>{e(entry)}</code></a>'
    return f"<code>{e(entry)}</code>"


def linked_ticket(ticket_id):
    """A ticket id linked to its review page, with its title and status beside it."""
    other = wt.ticket_for(ticket_id) or {}
    title = other.get("title", "")
    status = other.get("status", "")
    suffix = f" — {e(title)}" if title else ""
    badge = f' <span class="badge">{e(status)}</span>' if status else ""
    page = page_path(ticket_id)
    marker = "" if page.exists() else ' <span class="muted">(page not rendered yet)</span>'
    return f'<a href="{e(page.as_uri())}"><strong>{e(ticket_id.upper())}</strong></a>{suffix}{badge}{marker}'


def section(title, body, css=""):
    """One titled card, or nothing when the body is empty."""
    if not body:
        return ""
    klass = f' class="{css}"' if css else ""
    return f"<section{klass}><h2>{e(title)}</h2>{body}</section>"


def collapsed(title, body):
    """Ticket text folded away under a summary line, or nothing when the body is empty."""
    if not body:
        return ""
    return f'<details class="ticket-text"><summary>{e(title)}</summary><section>{body}</section></details>'


def open_decisions(ticket):
    """The highlighted box of the ticket's unresolved unknowns, or nothing when there are none."""
    unknowns = ticket.get("unknowns") or []
    if not unknowns:
        return ""
    body = bullet_list(unknowns) + (
        '<p class="muted">From the ticket\'s <code>unknowns</code>; resolve one with '
        "<code>generate_board.py update ID --resolve-unknown N</code>.</p>"
    )
    return section(f"Open decisions ({len(unknowns)})", body, "alert")


def stack_of(ticket_id, repo):
    """(branch this one is stacked on or None, open tickets whose worktree is stacked on this one)."""
    branch = ticket_id.lower()
    base = None
    if repo is not None and (repo / ".git").exists():
        base = wt.base_branch_of(repo, branch)
        listing = wt.git(repo, "config", "--get-regexp", rf"^branch\..*\.{wt.BASE_KEY}$", check=False)
    else:
        listing = ""
    above = []
    for line in listing.splitlines():
        key, _, value = line.partition(" ")
        if value.strip() != branch:
            continue
        other = key.removeprefix("branch.").removesuffix(f".{wt.BASE_KEY}")
        status = str((wt.ticket_for(other) or {}).get("status", "")).upper()
        if status and status not in ("DONE", "ARCHIVED"):
            above.append(other)
    return base, sorted(above)


def context_section(ticket, repo):
    """The plain-words summary, then where the ticket sits: plan phase, stack, links, rulings."""
    summary = (ticket.get("review-summary") or "").strip()
    if summary:
        body = f'<div class="summary">{paragraphs(summary)}</div>'
    else:
        body = (
            '<section class="alert"><h2>No review summary</h2><p>This ticket has no '
            "<code>review-summary</code>, so there is no plain-words account of the problem and "
            "the outcome. The finishing agent sets it with "
            f"<code>generate_board.py update {e(ticket.get('id', 'ID'))} --review-summary @FILE</code>."
            "</p></section>"
        )
    description = ticket.get("description", "")
    rows = []
    phase = PLAN_PHASE.search(description)
    if phase:
        rows.append(("plan", e(phase.group(0))))
    base, above = stack_of(str(ticket.get("id", "")), repo)
    if base:
        rows.append(("stacked on", linked_ticket(base)))
    if above:
        rows.append(("stacked on this", "<br>".join(linked_ticket(other) for other in above)))
    for key, label in (("blocked-by", "blocked by"), ("blocks", "blocks")):
        if ticket.get(key):
            rows.append((label, "<br>".join(linked_ticket(other) for other in ticket[key])))
    if rows:
        body += "<dl>" + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl>"
    rulings = [chunk.strip() for chunk in re.split(r"\n\s*\n", description) if RULINGS.match(chunk)]
    if rulings:
        body += "<h3>Rulings that apply</h3>" + "".join(f"<p>{e(chunk)}</p>" for chunk in rulings)
    return section("Context", body)


def class_list(classes):
    """(package, name) pairs as a compact list grouped by package."""
    grouped = {}
    for package, name in classes:
        grouped.setdefault(package, []).append(name)
    return bullet_list(
        [
            f"<code>{e(package)}</code>: {', '.join(e(name) for name in names)}"
            for package, names in grouped.items()
        ],
        render=str,
    )


def boundaries_section(change):
    """Classes added, deleted and moved, and public/protected signatures added or removed."""
    added, deleted, moved, signatures = changes.boundaries(change)
    body = ""
    if deleted:
        body += f'<h3 class="del">Deleted classes ({len(deleted)})</h3>' + class_list(deleted)
    if added:
        body += f'<h3 class="add">New classes ({len(added)})</h3>' + class_list(added)
    if moved:
        count = sum(len(names) for names in moved.values())
        items = [
            f"<code>{e(old)}</code> &rarr; <code>{e(new)}</code>: {', '.join(e(name) for name in names)}"
            for (old, new), names in sorted(moved.items())
        ]
        body += f"<h3>Moved classes ({count})</h3>" + bullet_list(items, render=str)
    if signatures:
        rows = []
        grouped = {}
        for path, gained, lost in sorted(signatures):
            grouped.setdefault((tuple(gained), tuple(lost)), []).append(Path(path).name)
        for (gained, lost), names in grouped.items():
            label = (
                f"<code>{e(names[0])}</code>"
                if len(names) == 1
                else f"{len(names)} files: "
                + ", ".join(f"<code>{e(name.removesuffix('.java'))}</code>" for name in names)
            )
            marked = [("del", "&minus;", text) for text in lost] + [("add", "+", text) for text in gained]
            lines = [f'<div class="{css}">{sign} <code>{e(text)}</code></div>' for css, sign, text in marked]
            methods = [line for line, (_, _, text) in zip(lines, marked) if "(" in text]
            fields = [line for line, (_, _, text) in zip(lines, marked) if "(" not in text]
            cell = "".join(methods)
            if fields:
                cell += (
                    f"<details><summary>{len(fields)} public field(s)</summary>{''.join(fields)}</details>"
                )
            rows.append(f"<tr><td>{label}</td><td>{cell}</td></tr>")
        body += (
            "<h3>Public and protected signatures</h3>"
            '<p class="muted">Declaration lines the diff removes or adds (methods, then fields, '
            "collapsed); a changed signature shows as both.</p>"
            f"<table>{''.join(rows)}</table>"
        )
    if not body:
        body = '<p class="muted">No class added, deleted or moved, and no public or protected signature changed.</p>'
    base = f"<code>{e(change.base)}</code> at <code>{e(change.start[:10])}</code>"
    body += f'<p class="muted">From the diff against {base}, untracked files included.</p>'
    return section("Boundaries that changed", body)


def read_first_section(change, worktree):
    """Files ranked by non-mechanical changed lines, linked at their first real hunk."""
    real, mechanical = changes.read_first(change)
    body = ""
    if real:

        def table(items):
            rows = "".join(
                f'<tr><td class="num">{item.real_lines}</td><td><a href="'
                f'{e(vscode_link(Path(worktree) / item.new, item.first_real_line))}"><code>{e(item.new)}</code></a>'
                f"{READ_FIRST_BADGES.get(item.kind, '')}</td></tr>"
                for item in items
            )
            return (
                '<table><tr><th class="num">real lines</th><th>file (opens at its first real hunk)</th></tr>'
                f"{rows}</table>"
            )

        first = [item for item in real if not changes.is_supporting(item.new)][:READ_FIRST_COUNT]
        rest = [item for item in real if item not in first]
        body += table(first) if first else '<p class="muted">Only tests and launch entries changed.</p>'
        if rest:
            total = sum(item.real_lines for item in rest)
            body += f"<details><summary>{len(rest)} more file(s), {total} real lines (tests last)</summary>{table(rest)}</details>"
        body += (
            '<p class="muted">Real lines: added and removed lines outside the mechanical hunks '
            "(<code>stage-moves</code>' rules: renames, imports naming a moved class, comment-only Java files).</p>"
        )
    if mechanical:
        items = [
            f'<code>{e(item.new)}</code> <span class="muted">'
            f"({'binary' if item.binary else MECHANICAL_LABELS.get(item.kind, item.kind)}"
            f"{', from ' + e(item.old) if item.kind == 'renamed' else ''})</span>"
            for item in mechanical
        ]
        body += (
            f"<details><summary>{len(mechanical)} mechanical-only file(s): moves, imports of moved "
            f"classes, comment-only changes</summary>{bullet_list(items, render=str)}</details>"
        )
    deleted = [item.old for item in change.files if item.kind == "deleted"]
    if deleted:
        body += (
            f"<details><summary>{len(deleted)} deleted file(s)</summary>"
            f"{bullet_list([f'<code>{e(path)}</code>' for path in deleted], render=str)}</details>"
        )
    if not body:
        body = '<p class="muted">The diff is empty.</p>'
    return section("Files to read first", body)


def number(value):
    """A measurement value printed without a spurious ``.0``."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, (int, float)) else str(value)


def measurement_row(row, tolerance):
    """One ``<tr>`` of the before/after table, and whether it is a regression."""
    before, after = row.get("before"), row.get("after")
    better = row.get("lower_is_better")
    unit = row.get("unit", "")
    worse = False
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (before, after))
    if numeric:
        delta = after - before
        percent = (delta / before * 100) if before else None
        shown = f"{percent:+.1f}%" if percent is not None else f"{delta:+}"
        if better is not None and delta:
            worse = (delta > 0) == bool(better) and (percent is None or abs(percent) > tolerance)
            style = "worse-text" if worse else ("better-text" if (delta < 0) == bool(better) else "")
            shown = f'<span class="{style}">{shown}</span>'
    else:
        shown = "same" if before == after else '<span class="worse-text">differs</span>'
        worse = before != after and better is not None
    cells = [row.get("suite", ""), row.get("item", ""), row.get("metric", "")]
    tail = (
        f'<td class="num">{e(number(before))}</td><td class="num">{e(number(after))}</td>'
        f'<td>{e(unit)}</td><td class="num">{shown}</td><td class="muted">{e(row.get("note", ""))}</td>'
    )
    klass = ' class="worse"' if worse else ""
    return f"<tr{klass}>" + "".join(f"<td>{e(c)}</td>" for c in cells) + tail + "</tr>", worse


def read_measurements(worktree, ticket_id):
    """(path, parsed document or None, error text or None) of the ticket's measurements file."""
    path = measurements_path(worktree, ticket_id)
    if not path.exists():
        return path, None, None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return path, None, str(error)
    if isinstance(document, list):
        document = {"measurements": document}
    if not isinstance(document, dict) or not isinstance(document.get("measurements", []), list):
        return path, None, 'expected {"measurements": [...]} or a bare list'
    return path, document, None


def test_counts(document):
    """The ``tests`` entries of a measurements file, as a list of dicts."""
    tests = (document or {}).get("tests")
    if isinstance(tests, dict):
        return [tests]
    return [entry for entry in tests or [] if isinstance(entry, dict)]


def measurements_section(worktree, ticket_id):
    """The before/after table with percent change, regressions highlighted."""
    path, document, error = read_measurements(worktree, ticket_id)
    if error:
        return section(
            "Measurements", f'<p class="worse-text">{e(path)} does not read: {e(error)}</p>', "alert"
        )
    if document is None:
        return section(
            "Measurements",
            f'<p class="muted">No measurements file (<code>{e(path.relative_to(worktree))}</code>).</p>',
        )
    tolerance = float(document.get("tolerance_percent") or 0)
    rendered = [
        measurement_row(row, tolerance) for row in document.get("measurements", []) if isinstance(row, dict)
    ]
    regressions = sum(worse for _, worse in rendered)
    body = ""
    if regressions:
        body += f'<p class="worse-text">{regressions} measurement(s) moved the wrong way.</p>'
    if rendered:
        body += (
            '<table><tr><th>suite</th><th>item</th><th>metric</th><th class="num">before</th>'
            '<th class="num">after</th><th>unit</th><th class="num">change</th><th>note</th></tr>'
            + "".join(html_row for html_row, _ in rendered)
            + "</table>"
        )
    if document.get("notes"):
        body += f'<p class="muted">{e(document["notes"])}</p>'
    if tolerance:
        body += f'<p class="muted">Changes within {tolerance:g}% are not flagged.</p>'
    body += f'<p class="muted">From <a href="{e(vscode_link(path))}"><code>{e(path.relative_to(worktree))}</code></a>.</p>'
    return section("Measurements", body, "alert" if regressions else "")


def verification_section(path, branch, ticket_id):
    """The F5 entry, the test counts and the screenshots under ``tmp/``, inline."""
    try:
        entry = wt.entry_for_ticket(path, branch)
    except SystemExit:
        entry = None
    rows = [("F5 entry", f"<code>{e(entry['name'])}</code>" if entry else '<span class="muted">none</span>')]
    _, document, _ = read_measurements(path, ticket_id)
    for tests in test_counts(document):
        parts = [f"{tests[key]} {key}" for key in ("run", "passed", "failed", "skipped") if key in tests]
        label = tests.get("command") or tests.get("suite") or "tests"
        rows.append((e(label), e(", ".join(parts) or json.dumps(tests))))
    if len(rows) == 1:
        rows.append(("tests", '<span class="muted">no counts in the measurements file</span>'))
    body = "<dl>" + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl>"
    shots = wt.screenshots_under(path)
    if shots:
        shown = shots[-SCREENSHOT_LIMIT:]
        figures = "".join(
            f'<figure><a href="{e(shot.as_uri())}"><img src="{e(shot.as_uri())}" loading="lazy"></a>'
            f"<figcaption>{e(shot.relative_to(path))}</figcaption></figure>"
            for shot in shown
        )
        more = (
            f'<p class="muted">The newest {SCREENSHOT_LIMIT} of {len(shots)}.</p>'
            if len(shots) > len(shown)
            else ""
        )
        body += f'<h3>Screenshots ({len(shots)})</h3>{more}<div class="shots">{figures}</div>'
    else:
        body += '<p class="muted">No screenshots under tmp/.</p>'
    return section("Verification", body)


def worktree_details(path, branch, main_branch):
    """Branch, distance from its base, the uncommitted files and the last agent note, collapsed."""
    ahead, behind = wt.ahead_behind(path, branch, main_branch)
    changed = wt.changed_files(path)
    rows = [
        ("path", f'<a href="{e(vscode_link(path))}"><code>{e(path)}</code></a>'),
        (
            "branch",
            f"<code>{e(branch)}</code> — {ahead} commit(s) ahead of {e(main_branch)}, {behind} behind",
        ),
        ("uncommitted", f"{len(changed)} file(s)"),
    ]
    body = "<dl>" + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl>"
    note = wt.last_agent_note(path)
    if note:
        transcript, when, text = note
        body += (
            f"<h3>Last agent note ({e(when)})</h3><pre>{e(text.strip())}</pre>"
            f'<p class="muted"><code>{e(transcript)}</code></p>'
        )
    return collapsed("Worktree", body)


def diff_sections(ticket_id, worktree_path):
    """The sections read from the worktree, or one line saying why they are missing."""
    if worktree_path is None:
        return [
            section(
                "Change",
                '<p class="muted">No worktree for this ticket (landed, archived or never started): '
                "boundaries, files to read first, measurements and screenshots are skipped.</p>",
            )
        ]
    try:
        path, branch, base = wt.resolve_worktree(str(worktree_path))
        change = changes.read_change(path, base)
    except (SystemExit, OSError) as error:
        return [section("Change", f'<p class="muted">{e(error)}</p>', "alert")]
    except Exception as error:  # a git failure must not lose the rest of the page
        return [section("Change", f'<p class="muted">reading the diff failed: {e(error)}</p>', "alert")]
    return [
        boundaries_section(change),
        read_first_section(change, path),
        measurements_section(path, ticket_id),
        verification_section(path, branch, ticket_id),
        worktree_details(path, branch, base),
    ]


def render(ticket, ticket_path, worktree_path):
    """The whole page for one ticket.

    :param ticket: the ticket JSON
    :param ticket_path: where the ticket JSON lives
    :param worktree_path: the ticket's worktree, or None when it has none
    :return: the HTML document
    """
    ticket_id = ticket.get("id", ticket_path.stem)
    status = str(ticket.get("status", "")).upper()
    colour = STATUS_COLOURS.get(status, "var(--todo)")
    badges = [f'<span class="badge status" style="background:{colour}">{e(status)}</span>']
    for label in ("epic", "repo", "priority"):
        if ticket.get(label) not in (None, ""):
            badges.append(f'<span class="badge">{label}: {e(ticket[label])}</span>')
    badges += [f'<span class="badge">{e(name)}</span>' for name in ticket.get("subsystem", [])]
    buttons = []
    if worktree_path:
        buttons.append(
            f'<a class="button" href="{e(vscode_link(worktree_path))}">Open worktree in VS Code</a>'
        )
    buttons.append(f'<a class="button secondary" href="{e(vscode_link(ticket_path))}">Open ticket JSON</a>')
    repo = worktree_path or wt.CODE_ROOT / (ticket.get("repo") or "Ixdar")
    body = [
        f'<header><div class="id">{e(ticket_id)}</div><h1>{e(ticket.get("title", ticket_id))}</h1>'
        f'<div class="meta">{"".join(badges)}</div><div class="buttons">{"".join(buttons)}</div></header>',
        open_decisions(ticket),
        context_section(ticket, Path(repo) if Path(repo).is_dir() else None),
        *diff_sections(str(ticket_id), worktree_path),
        section("Definition of done", numbered(ticket.get("definition-of-done", ""))),
        section("Todos", bullet_list(ticket.get("todos", [])) if ticket.get("todos") else ""),
        collapsed(
            "Changes made", bullet_list(ticket.get("changes-made", [])) if ticket.get("changes-made") else ""
        ),
        collapsed("Description", paragraphs(ticket.get("description", ""))),
        collapsed("Testing plan", numbered(ticket.get("testing-plan", ""))),
        collapsed(
            "Related files",
            bullet_list(ticket.get("related-files", []), related_file) if ticket.get("related-files") else "",
        ),
        collapsed("Raw JSON", f"<pre>{e(json.dumps(ticket, indent=2))}</pre>"),
    ]
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{e(ticket_id)} {e(ticket.get('title', ''))}</title><style>{STYLE}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )
