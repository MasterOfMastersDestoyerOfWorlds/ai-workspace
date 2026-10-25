"""The workspace event log: one JSON line per thing the user did that sessions should hear about.

``ixd land`` and ``ixd wt archive`` append here. The ``land_events`` hook shows each session the
lines it has not seen on the next prompt, and a session coordinating agents can watch the file
with the Monitor tool to hear at once. Only the standard library is imported, so the hook can load
this module in a few milliseconds.
"""

import datetime
import json
import os
from pathlib import Path


def log_path():
    """``$XDG_CACHE_HOME/ixd/events.jsonl``, the one log every checkout and session shares."""
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "ixd" / "events.jsonl"


def record(event, ticket, **fields):
    """Append one event line, stamped with the local time.

    :param event: what happened, such as ``landed`` or ``archived``
    :param ticket: the ticket id it happened to, or the branch name when there is no ticket
    :param fields: anything else worth telling a session, such as the commit
    """
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "event": event, "ticket": ticket}
    line.update(fields)
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def describe(line):
    """One event line as a sentence for a session, or None when the line is not an event.

    :param line: one line of the log
    """
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or "event" not in event:
        return None
    details = ", ".join(
        f"{key} {value}" for key, value in event.items() if key not in ("time", "event", "ticket")
    )
    return f"{event.get('time', '?')}: {event.get('ticket', '?')} {event['event']}" + (
        f" ({details})" if details else ""
    )
