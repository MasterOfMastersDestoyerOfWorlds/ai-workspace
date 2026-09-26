"""Find the debugging scaffolding a worktree's diff adds, so it never lands by accident.

Agents chasing a bug add log lines, public counters, ``describe``/``dump`` helpers, sample limits
and throwaway ``*Probe.java`` classes, and then leave them in the change they hand over. Each one
found here must either be stripped or be named in the ticket's definition of done, which makes
keeping it a decision the user sees instead of an accident.

Only added lines of ``.java`` files count: a line the diff removes or leaves alone is master's
business, not this change's.
"""

import re
from dataclasses import dataclass

from .worktree import TMP_EXCLUDE, git

LOG_CALL = re.compile(r"\bPlatforms\.log\(|\bSystem\.(?:out|err)\.print|\.printStackTrace\(")
STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
COUNTER_FIELD = re.compile(r"^\s*public\s+(?:int|long|float|double)\s+(\w*(?:Count|Ulps|Gap)|worst\w+)\s*;")
DESCRIBE_METHOD = re.compile(r"\b(?:String|void)\s+((?:describe|dump)\w*)\s*\(")
SAMPLE_LIMIT = re.compile(r"\b(\w*SAMPLE_LIMIT\w*)\s*=")
PROBE_FILE = re.compile(r"(?:^|/)test/benchmark/(\w*Probe)\.java$")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
LITERAL_LOOKAHEAD = 3
IDENTIFIER_WIDTH = 60


@dataclass(frozen=True)
class Finding:
    """One piece of scaffolding: where it is, what kind, and the name the DoD must mention."""

    path: str
    line: int
    kind: str
    identifier: str

    def describe(self):
        return f"{self.path}:{self.line}  {self.kind:<9} {self.identifier}"


def added_java_lines(worktree):
    """Every line the change adds to a ``.java`` file, as {path: [(line number, text), ...]}.

    Tracked files are diffed against HEAD, which ``sync`` keeps on the main branch; untracked
    files count as added in full.

    :param worktree: the worktree directory
    :return: the added lines per repository-relative path
    """
    diff = git(
        worktree,
        "diff",
        "--no-prefix",
        "--no-color",
        "-U0",
        "HEAD",
        "--",
        "*.java",
        TMP_EXCLUDE,
        check=False,
    )
    added = parse_added_lines(diff)
    untracked = git(worktree, "ls-files", "--others", "--exclude-standard", "--", "*.java", TMP_EXCLUDE)
    for relative in untracked.splitlines():
        text = (worktree / relative).read_text(encoding="utf-8", errors="replace")
        added[relative] = list(enumerate(text.splitlines(), start=1))
    return added


def parse_added_lines(diff):
    """The added lines of a ``--no-prefix -U0`` unified diff, per path.

    :param diff: the diff text
    :return: {path: [(new-file line number, text), ...]}
    """
    added = {}
    path = None
    line_number = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[len("+++ ") :]
            path = None if target == "/dev/null" else target
            continue
        header = HUNK_HEADER.match(raw)
        if header:
            line_number = int(header.group(1))
            continue
        if path and raw.startswith("+"):
            added.setdefault(path, []).append((line_number, raw[1:]))
            line_number += 1
    return added


def log_identifier(lines, index):
    """The words a log call prints before its first format specifier, read from its literal.

    The literal often sits on the line after the call, so a few following added lines are read.

    :param lines: the file's added lines
    :param index: position of the line holding the call
    :return: the printed prefix, or the call line itself when no literal is found
    """
    for _, text in lines[index : index + LITERAL_LOOKAHEAD]:
        literal = STRING_LITERAL.search(text)
        if literal:
            prefix = literal.group(1).split("%")[0].rstrip(" :=(,")
            if prefix:
                return prefix[:IDENTIFIER_WIDTH]
    return lines[index][1].strip()[:IDENTIFIER_WIDTH]


def scan(worktree):
    """Every piece of scaffolding the worktree's change adds.

    :param worktree: the worktree directory
    :return: the findings, ordered by path and line
    """
    return scan_added(added_java_lines(worktree))


def scan_added(added):
    """The scaffolding among already-collected added lines.

    :param added: output of :func:`added_java_lines` or :func:`parse_added_lines`
    :return: the findings, ordered by path and line
    """
    findings = []
    for path, lines in sorted(added.items()):
        probe = PROBE_FILE.search(path)
        if probe:
            findings.append(Finding(path, 1, "probe", probe.group(1)))
        for index, (number, text) in enumerate(lines):
            if text.lstrip().startswith(("*", "/*", "//")):
                continue
            if LOG_CALL.search(text):
                findings.append(Finding(path, number, "log", log_identifier(lines, index)))
            for pattern, kind in (
                (COUNTER_FIELD, "counter"),
                (DESCRIBE_METHOD, "describe"),
                (SAMPLE_LIMIT, "sample"),
            ):
                match = pattern.search(text)
                if match:
                    findings.append(Finding(path, number, kind, match.group(1)))
    return findings


def unaccounted(findings, definition_of_done):
    """The findings whose identifier the ticket's definition of done does not mention.

    :param findings: output of :func:`scan`
    :param definition_of_done: the ticket's DoD text, possibly empty
    :return: the findings still to strip or to name in the DoD
    """
    text = (definition_of_done or "").lower()
    return [finding for finding in findings if finding.identifier.lower() not in text]
