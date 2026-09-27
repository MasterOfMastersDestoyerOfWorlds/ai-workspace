"""One ticket rendered as a self-contained HTML page, for `ixd review`.

The page is written to a cache file and opened from ``file://``, so it needs no server: styles are
inline, screenshots are ``file://`` images, and the VS Code buttons are ``vscode://file`` links,
which VS Code registers as a URL scheme when it is installed.
"""

import html
import json
import re
from pathlib import Path

from ... import worktree as wt

NUMBERED_ITEM = re.compile(r"(?:^|\s)\d+\.\s+")
ABSOLUTE_PATH = re.compile(r"^(/|~/)")

STYLE = """
:root { color-scheme:dark; --bg:#0f1115; --fg:#e6edf3; --muted:#8d96a0; --card:#161a20;
  --line:#2d333b; --accent:#58a6ff; --badge:#21262d; --review:#a371f7; --todo:#8d96a0;
  --done:#3fb950; --progress:#d29922; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width:960px; margin:0 auto; padding:32px 16px 64px; }
header .id { color:var(--muted); font:600 14px ui-monospace, monospace; }
h1 { margin:4px 0 12px; font-size:26px; line-height:1.25; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:0 0 10px; }
section { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 20px; margin:16px 0; }
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
.shots { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:12px; }
.shots figure { margin:0; }
.shots img { width:100%; border:1px solid var(--line); border-radius:6px; display:block; }
.shots figcaption { font-size:12px; color:var(--muted); margin-top:4px; word-break:break-all; }
dl { display:grid; grid-template-columns:max-content 1fr; gap:4px 16px; margin:0 0 12px; }
dt { color:var(--muted); }
dd { margin:0; word-break:break-word; }
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


def vscode_link(path):
    """The ``vscode://file`` URL that opens a file or folder in VS Code."""
    return "vscode://file" + Path(path).expanduser().absolute().as_posix()


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
    """A blocked-by / blocks entry with the other ticket's title and status beside its id."""
    other = wt.ticket_for(ticket_id) or {}
    title = other.get("title", "")
    status = other.get("status", "")
    suffix = f" — {e(title)}" if title else ""
    badge = f' <span class="badge">{e(status)}</span>' if status else ""
    return f"<strong>{e(ticket_id)}</strong>{suffix}{badge}"


def section(title, body):
    """One titled card, or nothing when the body is empty."""
    if not body:
        return ""
    return f"<section><h2>{e(title)}</h2>{body}</section>"


def worktree_section(path):
    """Branch, changed files, launch entry, screenshots and the last agent note of a worktree."""
    try:
        path, branch, main_branch = wt.resolve_worktree(str(path))
        ahead, behind = wt.ahead_behind(path, branch, main_branch)
        changed = wt.changed_files(path)
    except SystemExit as error:
        return section("Worktree", f'<p class="muted">{e(error)}</p>')
    try:
        entry = wt.entry_for_ticket(path, branch)
    except SystemExit:
        entry = None
    rows = [
        ("path", f'<a href="{e(vscode_link(path))}"><code>{e(path)}</code></a>'),
        (
            "branch",
            f"<code>{e(branch)}</code> — {ahead} commit(s) ahead of {e(main_branch)}, {behind} behind",
        ),
        ("F5 entry", f"<code>{e(entry['name'])}</code>" if entry else '<span class="muted">none</span>'),
    ]
    body = "<dl>" + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl>"
    if changed:
        body += f"<h2>{len(changed)} changed file(s)</h2><pre>{e(chr(10).join(changed))}</pre>"
    else:
        body += '<p class="muted">No uncommitted changes.</p>'
    shots = wt.screenshots_under(path)
    if shots:
        figures = "".join(
            f'<figure><a href="{e(shot.as_uri())}"><img src="{e(shot.as_uri())}" loading="lazy"></a>'
            f"<figcaption>{e(shot.relative_to(path))}</figcaption></figure>"
            for shot in shots
        )
        body += f'<h2 style="margin-top:16px">Screenshots</h2><div class="shots">{figures}</div>'
    note = wt.last_agent_note(path)
    if note:
        transcript, when, text = note
        body += (
            f'<h2 style="margin-top:16px">Last agent note ({e(when)})</h2>'
            f"<pre>{e(text.strip())}</pre>"
            f'<p class="muted"><code>{e(transcript)}</code></p>'
        )
    return section("Worktree", body)


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
    links = ""
    if ticket.get("blocked-by") or ticket.get("blocks"):
        links = "".join(
            f"<p><strong>{title}</strong></p>" + bullet_list(ticket[key], linked_ticket)
            for key, title in (("blocked-by", "Blocked by"), ("blocks", "Blocks"))
            if ticket.get(key)
        )
    body = [
        f'<header><div class="id">{e(ticket_id)}</div><h1>{e(ticket.get("title", ticket_id))}</h1>'
        f'<div class="meta">{"".join(badges)}</div><div class="buttons">{"".join(buttons)}</div></header>',
        section("Description", paragraphs(ticket.get("description", ""))),
        section("Definition of done", numbered(ticket.get("definition-of-done", ""))),
        section("Testing plan", numbered(ticket.get("testing-plan", ""))),
        (
            worktree_section(worktree_path)
            if worktree_path
            else section("Worktree", '<p class="muted">No worktree for this ticket.</p>')
        ),
        section(
            "Changes made", bullet_list(ticket.get("changes-made", [])) if ticket.get("changes-made") else ""
        ),
        section("Todos", bullet_list(ticket.get("todos", [])) if ticket.get("todos") else ""),
        section("Unknowns", bullet_list(ticket.get("unknowns", [])) if ticket.get("unknowns") else ""),
        section("Dependencies", links),
        section(
            "Related files",
            bullet_list(ticket.get("related-files", []), related_file) if ticket.get("related-files") else "",
        ),
        section(
            "Raw JSON",
            f"<details><summary>show</summary><pre>{e(json.dumps(ticket, indent=2))}</pre></details>",
        ),
    ]
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{e(ticket_id)} {e(ticket.get('title', ''))}</title><style>{STYLE}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )
