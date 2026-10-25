#!/usr/bin/env python3
"""UserPromptSubmit hook: tells the session what the user landed or archived since its last prompt.

``ixd land`` and ``ixd wt archive`` run in the user's terminal, where no session can hear them, so
a session kept working from a stale picture (an agent left unsynced, a ticket still offered as
ready). They append to the workspace event log (``ixd/events.py``); this hook keeps a read offset
per session and adds the unseen lines to the prompt as context. A session's first prompt only
records where the log ends, so a new session is not handed the whole history.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_common import read_event  # noqa: E402
from ixd import events  # noqa: E402


def main():
    """Prints the unseen events as additional context and moves the session's offset to the end."""
    session = str(read_event().get("session_id") or "")
    log = events.log_path()
    if not session or not log.exists():
        return 0
    offsets = log.parent / "events-seen"
    offsets.mkdir(exist_ok=True)
    marker = offsets / session
    end = log.stat().st_size
    start = int(marker.read_text() or 0) if marker.exists() else end
    marker.write_text(str(end))
    if start >= end:
        return 0
    with log.open("rb") as stream:
        stream.seek(start)
        unseen = stream.read(end - start).decode("utf-8", errors="replace")
    lines = [described for described in map(events.describe, unseen.splitlines()) if described]
    if not lines:
        return 0
    context = "Since your last message the user ran (ixd event log):\n" + "\n".join(
        f"- {line}" for line in lines
    )
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
