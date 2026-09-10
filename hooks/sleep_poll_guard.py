#!/usr/bin/env python3
"""PreToolUse hook on Bash: refuses hand-written sleep polling and task-output polling.

The 2026-09-08 tool review counted 34 backgrounded commands, 14 hand-written waiters and 21
reads of the harness task-output directory in one agent alone, and one waiter that re-woke its
agent 59 minutes after the command it watched had finished. The Monitor tool already turns a
loop's output into notifications, and Bash with run_in_background already notifies on exit, so
none of that wall-clock is necessary.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_common import (  # noqa: E402
    block,
    command_of,
    read_event,
    strip_quoted_spans,
)

LOOP_KEYWORD = re.compile(r"(?:^|[\s;&|(])(until|while|for)(?=[\s(])")

SLEEP_CALL = re.compile(r"(?:^|[\s;&|(])sleep\s")

# A sleep whose result feeds another command: the fixed-wait poll the review kept finding.
SLEEP_CHAIN = re.compile(
    r"(?:^|[\s;&|(])sleep\s+[0-9.]+\s*(?:;|&&|\|\||\|)\s*\S"
    r"|(?:;|&&|\|\|)\s*sleep\s+[0-9.]+"
)

# The harness writes a background command's output under <session>/tasks/<id>.output.
TASK_OUTPUT = re.compile(r"tasks/[^\s'\"]*\.output|claude-[0-9]+/[^\s'\"]*/tasks\b")

MONITOR_ADVICE = (
    "Use the Monitor tool when you want a notification per event; it takes the until-sleep loop "
    "itself and streams each matching line to you. Use Bash with run_in_background for a "
    "command that ends on its own, then wait for its completion notification. Background output "
    "arrives as a notification, so never read the task-output directory: read the log file the "
    "command writes instead."
)


def find_violation(command):
    """Returns the reason this command must be refused, or None when it may run."""
    masked = strip_quoted_spans(command)
    loop = LOOP_KEYWORD.search(masked)
    if loop and SLEEP_CALL.search(masked):
        return f"a {loop.group(1)} loop polls with a fixed sleep"
    if SLEEP_CHAIN.search(masked):
        return "a sleep is chained with another command as a fixed wait"
    if TASK_OUTPUT.search(masked):
        return "the command reads the harness task-output directory"
    return None


def main():
    """Reads the Bash event and blocks the call when it polls instead of waiting on a signal."""
    event = read_event()
    command = command_of(event)
    if not command:
        return 0
    reason = find_violation(command)
    if reason is None:
        return 0
    block(f"Blocked by the ai-workspace sleep_poll_guard hook: {reason}.\n\n{MONITOR_ADVICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
