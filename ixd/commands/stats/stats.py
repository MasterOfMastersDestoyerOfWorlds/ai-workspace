"""Where an agent session's wall time went, read from its transcripts."""

import collections
from typing import Annotated

from ... import transcripts
from ...registry import CliOption, cli_command


@cli_command
def stats(
    transcript: Annotated[list[str], CliOption(positional=True, multiple=True)] = (),
    session: str = "",
    latest: int = 0,
    top: int = 12,
    idle: float = 600.0,
) -> int:
    """Print wall time by activity, thinking pauses, slow calls, errors and repeated command shapes.

    This is the evidence /ix-tool-review reads first: the biggest number in the activity table is
    usually the biggest finding. A session id pulls in that session and every subagent it spawned.

    :param transcript: transcript paths to read, when neither a session nor a recent count is given
    :param session: session id, which also pulls in its subagents
    :param latest: read the N most recent sessions with their subagents
    :param top: rows to print per list
    :param idle: seconds of gap after a result that count as idle rather than activity
    """
    paths = transcripts.resolve(transcript, session, latest)
    if not paths:
        raise SystemExit("no transcripts given: name one, or pass --session or --latest")
    totals, counts = collections.Counter(), collections.Counter()
    for path in paths:
        by_category, per_category = transcripts.summarise(path, transcripts.load_calls(path), top, idle)
        totals.update(by_category)
        counts.update(per_category)
    if len(paths) > 1:
        print("\n=== all transcripts, wall time by activity:")
        for category, span in totals.most_common():
            print(f"  {span / 60:6.1f} min  {counts[category]:4d} calls  {category}")
    return 0
