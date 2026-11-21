#!/usr/bin/env python3
"""PreToolUse hook on Bash: refuses Java Flight Recorder and points at async-profiler.

Ixdar/CLAUDE.md ("Profiling") says to profile with async-profiler's CPU flame graph, kept as HTML.
An agent profiling the repair benchmarks on 2026-11-17 reached for -XX:StartFlightRecording
instead, and JFR's default 20 ms sampling could not resolve the 60 ms cold-start phases it was
chasing, so the investigation stalled on samples too coarse to read.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_common import (  # noqa: E402
    block,
    command_of,
    program_name,
    read_event,
    split_segments,
    tokenize,
)

# Starting a recording from the command line, in any JVM option spelling, quoted or not.
JFR_OPTION = re.compile(r"-XX:(?:StartFlightRecording|[+]?FlightRecorder\w*)")

# Starting or dumping a recording in a running JVM.
JFR_COMMAND = re.compile(r"\bJFR\.\w+")

# Programs whose arguments only mention JFR, so a search for the flag is not a recording.
SEARCH_PROGRAMS = frozenset({"grep", "egrep", "fgrep", "rg", "ag"})

ASYNC_PROFILER_ADVICE = (
    'Profile with async-profiler, as Ixdar/CLAUDE.md ("Profiling") says, and keep the flame '
    "graph as HTML. For a scene: `ixdar-cli run-scene --profile`. For a test or benchmark JVM, "
    "pass the agent through the test JVM flags, e.g. "
    '"-Dixdar.test.heap=-Xmx4g -agentpath:$REPO_HOME/Ixdar/.profiler/libasyncProfiler'
    '=start,event=cpu,interval=100us,file=<scratch dir>/profile.html" (interval sets the '
    "sampling period; 100us resolves phases of a few milliseconds). Read a capture with "
    "`ixdar-cli profile-report profile.html --top 30 [substr ...]`. For warm-up questions, add "
    "-Xlog:jit+compilation=debug:file=<scratch dir>/jit.log to see when each method compiles."
)


def find_violation(command):
    """Returns the reason this command must be refused, or None when it may run."""
    for segment in split_segments(command):
        if program_name(tokenize(segment)) in SEARCH_PROGRAMS:
            continue
        if JFR_OPTION.search(segment):
            return "the command starts a Java Flight Recorder recording"
        if JFR_COMMAND.search(segment):
            return "the command drives Java Flight Recorder through jcmd"
        if program_name(tokenize(segment)) == "jfr":
            return "the command reads a Java Flight Recorder recording"
    return None


def main():
    """Reads the Bash event and blocks the call when it uses Java Flight Recorder."""
    event = read_event()
    command = command_of(event)
    if not command:
        return 0
    reason = find_violation(command)
    if reason is None:
        return 0
    block(f"Blocked by the ai-workspace jfr_guard hook: {reason}.\n\n{ASYNC_PROFILER_ADVICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
