#!/usr/bin/env python3
"""PreToolUse hook on Bash: refuses to let tracked source be edited through the shell.

Shell edits fail quietly. A drifted anchor in a `sed -i` or a python heredoc rewrites nothing
and still reports success, and the change never reaches the diff the user reviews; the
2026-09-08 tool review counted 137 heredoc edits across four agents, 102 of 148 without an
`assert old in s`. Published numbers agree: bash-only editing scored 28 percent on SWE-bench
Pro against 51 percent with a string-replace tool.

The Edit and Write tools fail loudly instead, so this hook sends the model to them. Writing to
a tmp or scratchpad path through the shell stays allowed.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hook_common import (  # noqa: E402
    PROTECTED,
    UNKNOWN,
    block,
    classify_path,
    command_of,
    looks_like_source,
    program_name,
    read_event,
    split_segments,
    strip_heredoc_bodies,
    strip_quoted_spans,
    tokenize,
    working_directory,
)

# Redirections that create or truncate a file, ignoring `2>&1` and `>&2`.
REDIRECTION = re.compile(r"(?<![0-9<>&])(?:[0-9]*&?>>?|>\|)\s*(?P<target>[^\s;|&<>()]+)")

# Python fragments that write a file. A bare `.write(` is left out: it also matches stdout.
PYTHON_WRITE_PATTERNS = (
    re.compile(r"\bopen\s*\([^)]*,\s*['\"][^'\"]*[wax]"),
    re.compile(r"\.open\s*\(\s*['\"][^'\"]*[wax]"),
    re.compile(r"\.write_text\s*\("),
    re.compile(r"\.write_bytes\s*\("),
    re.compile(r"\.writelines\s*\("),
    re.compile(r"\bfileinput\.[a-z_]*\([^)]*inplace"),
    re.compile(r"\bshutil\.(?:copy|copyfile|copy2|move)\s*\("),
    re.compile(r"\bos\.(?:rename|replace)\s*\("),
    re.compile(r"\bjson\.dump\s*\("),
)

PYTHON_PROGRAMS = ("python", "python3", "python2")

IN_PLACE_SED = re.compile(r"-[a-zA-Z]*i[a-zA-Z.]*|--in-place(=.*)?")

QUOTED_LITERAL = re.compile(r"['\"]([^'\"\n]{2,})['\"]")

# Reading many files in one Bash call overflows the harness output file; the review counted
# twenty such overflows. At or above this many operands the call belongs to Read.
CAT_ARGUMENT_LIMIT = 4

EDIT_ADVICE = (
    "Use the Edit tool for an exact string replacement, or Write for a whole file. Both appear "
    "in the diff the user reviews and both fail loudly when the anchor has drifted, which a "
    "shell edit does not: it reports success and changes nothing. Shell writes under a tmp or "
    "scratchpad path are still fine."
)

READ_ADVICE = (
    "Use the Read tool, one call per file. Reading many files through Bash in one call "
    "overflows the harness output file and loses the content you asked for."
)


def arguments_after_program(tokens):
    """Returns the tokens that follow the program name, skipping env, sudo and uv run."""
    program = program_name(tokens)
    for index, token in enumerate(tokens):
        if os.path.basename(token) == program:
            return tokens[index + 1:]
    return tokens[1:]


def operand_files(arguments, script_options, script_is_positional=True):
    """Picks the file operands out of an editor invocation's arguments.

    The first positional argument is the editing script unless a script option supplied it.
    """
    files = []
    script_taken = not script_is_positional
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token.startswith("-") and token != "-":
            if token in script_options:
                script_taken = True
                index += 2
                continue
            index += 1
            continue
        if not script_taken:
            script_taken = True
            index += 1
            continue
        files.append(token)
        index += 1
    return files


def in_place_editor_targets(tokens):
    """Returns the files an in-place editor rewrites, or None when this is not one.

    An empty list means the invocation edits in place but the hook could not name its targets.
    """
    program = program_name(tokens)
    arguments = arguments_after_program(tokens)
    if program in ("sed", "gsed"):
        if not any(IN_PLACE_SED.fullmatch(token) for token in arguments):
            return None
        return operand_files(arguments, ("-e", "-f", "--expression", "--file"))
    if program == "perl":
        if not any(re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z.]*", token) for token in arguments):
            return None
        return operand_files(arguments, ("-e", "-E"), script_is_positional=False)
    if program in ("awk", "gawk", "mawk"):
        if "inplace" not in " ".join(arguments):
            return None
        return operand_files(arguments, ("-f", "-v", "-i"))
    return None


def redirection_targets(command):
    """Returns every path a redirection in this command writes to."""
    masked = strip_quoted_spans(command)
    targets = []
    for match in REDIRECTION.finditer(masked):
        start, end = match.span("target")
        targets.append(command[start:end])
    return targets


def tee_targets(tokens):
    """Returns the files a tee invocation writes to, or None when this is not tee."""
    if program_name(tokens) != "tee":
        return None
    return [token for token in arguments_after_program(tokens) if not token.startswith("-")]


def python_script_texts(command, bodies):
    """Collects the python source a command runs inline, from heredocs and from -c arguments."""
    scripts = []
    for opening_line, body in bodies:
        if any(program in opening_line for program in PYTHON_PROGRAMS):
            scripts.append(body)
    for segment in split_segments(command):
        tokens = tokenize(segment)
        if program_name(tokens) not in PYTHON_PROGRAMS:
            continue
        for index, token in enumerate(tokens):
            if token == "-c" and index + 1 < len(tokens):
                scripts.append(tokens[index + 1])
    return scripts


def script_writes_files(script):
    """Says whether an inline python script writes to the filesystem."""
    return any(pattern.search(script) for pattern in PYTHON_WRITE_PATTERNS)


def script_path_literals(script):
    """Returns the quoted strings in a script that look like paths."""
    return [literal for literal in QUOTED_LITERAL.findall(script)
            if "/" in literal or looks_like_source(literal)]


def find_violation(command, cwd):
    """Returns a reason and the advice to print, or None when the command may run."""
    stripped, bodies = strip_heredoc_bodies(command)

    for script in python_script_texts(stripped, bodies):
        if not script_writes_files(script):
            continue
        literals = script_path_literals(script)
        if not literals:
            return ("an inline python script writes files through the shell, and the hook cannot "
                    "see which ones", EDIT_ADVICE)
        offenders = [literal for literal in literals
                     if classify_path(literal, cwd) in (PROTECTED, UNKNOWN)]
        if offenders:
            return (f"an inline python script writes {offenders[0]} through the shell", EDIT_ADVICE)

    for segment in split_segments(stripped):
        tokens = tokenize(segment)
        if not tokens:
            continue
        program = program_name(tokens)

        targets = in_place_editor_targets(tokens)
        if targets is not None:
            if not targets:
                return (f"{program} edits in place and the hook cannot name its targets",
                        EDIT_ADVICE)
            offenders = [target for target in targets
                         if classify_path(target, cwd) in (PROTECTED, UNKNOWN)]
            if offenders:
                return (f"{program} edits {offenders[0]} in place", EDIT_ADVICE)

        piped = tee_targets(tokens)
        if piped:
            offenders = [target for target in piped
                         if classify_path(target, cwd) == PROTECTED and looks_like_source(target)]
            if offenders:
                return (f"tee writes {offenders[0]}, a tracked source file", EDIT_ADVICE)

        if program == "cat" and ">" not in segment:
            operands = [token for token in arguments_after_program(tokens)
                        if not token.startswith("-")]
            protected = [token for token in operands if classify_path(token, cwd) == PROTECTED]
            if len(operands) >= CAT_ARGUMENT_LIMIT and len(protected) >= 2:
                return (f"cat reads {len(operands)} files in one call", READ_ADVICE)

    for target in redirection_targets(stripped):
        if classify_path(target, cwd) == PROTECTED and looks_like_source(target):
            return (f"a shell redirection writes {target}, a tracked source file", EDIT_ADVICE)

    return None


def main():
    """Reads the Bash event and blocks the call when it edits source through the shell."""
    event = read_event()
    command = command_of(event)
    if not command:
        return 0
    violation = find_violation(command, working_directory(event))
    if violation is None:
        return 0
    reason, advice = violation
    block(f"Blocked by the ai-workspace shell_edit_guard hook: {reason}.\n\n{advice}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
