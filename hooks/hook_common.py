#!/usr/bin/env python3
"""Shared helpers for the ai-workspace Claude Code hooks.

Every hook reads one JSON event from stdin and either exits 0 in silence or exits 2 with a
message on stderr. Claude Code shows that message to the model: on PreToolUse it blocks the
call, on PostToolUse it arrives as feedback about a call that already ran.

Nothing here imports a third-party package, so a hook process starts in a few milliseconds.
"""

import json
import os
import re
import shlex
import sys

# Exit code that makes Claude Code show stderr to the model (and block, on PreToolUse).
BLOCK_EXIT_CODE = 2

# Directory names whose contents are scratch: writing to them through the shell is fine.
TEMPORARY_DIR_NAMES = frozenset(
    {
        "tmp",
        "temp",
        "target",
        "build",
        "dist",
        "out",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "scratchpad",
        "logs",
    }
)

# Filesystem roots that never hold tracked source.
TEMPORARY_ROOTS = ("/tmp", "/var/tmp", "/dev", "/proc", "/run", "/sys")

# Suffixes that make a path worth protecting from a shell redirection.
SOURCE_SUFFIXES = frozenset(
    {
        ".java",
        ".py",
        ".json",
        ".xml",
        ".md",
        ".toml",
        ".yaml",
        ".yml",
        ".gradle",
        ".kt",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".sh",
        ".dsl",
        ".glsl",
        ".vert",
        ".frag",
        ".properties",
        ".cfg",
        ".ini",
        ".html",
        ".css",
        ".sql",
        ".c",
        ".h",
        ".cpp",
        ".rs",
        ".go",
    }
)

# A path token the hook could not evaluate, because a variable or a glob stands in for it.
UNKNOWN = "unknown"

# A path token that resolves inside a git repository and is not scratch.
PROTECTED = "protected"

# A path token that is scratch, outside every repository, or a device.
EXEMPT = "exempt"

SHELL_OPERATORS = re.compile(r"\|\||&&|[;|\n]")

HEREDOC_START = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

SUBSTITUTION = re.compile(r"[$`*?]")


def read_event(stream=None):
    """Reads the hook event Claude Code writes to stdin.

    A malformed body is treated as an empty event so a hook can never break a session.
    """
    source = stream if stream is not None else sys.stdin
    try:
        return json.loads(source.read() or "{}")
    except (ValueError, OSError):
        return {}


def block(message):
    """Ends the hook with the blocking exit code, showing the message to the model."""
    sys.stderr.write(message.strip() + "\n")
    sys.exit(BLOCK_EXIT_CODE)


def command_of(event):
    """Returns the shell command a Bash tool event carries, or an empty string."""
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def working_directory(event):
    """Returns the directory the tool call runs in, defaulting to the process directory."""
    cwd = event.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else os.getcwd()


def strip_quoted_spans(text):
    """Blanks out quoted stretches, keeping every offset, so operators inside them do not match."""
    characters = list(text)
    quote = None
    index = 0
    while index < len(characters):
        character = characters[index]
        if quote is None:
            if character in "'\"":
                quote = character
                characters[index] = " "
        elif character == quote:
            quote = None
            characters[index] = " "
        elif character == "\n":
            pass
        else:
            characters[index] = " "
        index += 1
    return "".join(characters)


def strip_heredoc_bodies(command):
    """Splits a command into its text without heredoc bodies and the bodies themselves.

    Each body comes back paired with the line that opened it, so a caller can tell a python
    heredoc from a heredoc redirected into a file.
    """
    lines = command.split("\n")
    kept = []
    bodies = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for _, word in HEREDOC_START.findall(line):
            body = []
            while index < len(lines) and lines[index].strip() != word:
                body.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            bodies.append((line, "\n".join(body)))
    return "\n".join(kept), bodies


def split_segments(command):
    """Splits a command on the shell operators that separate one invocation from the next."""
    masked = strip_quoted_spans(command)
    segments = []
    start = 0
    for match in SHELL_OPERATORS.finditer(masked):
        segments.append(command[start : match.start()])
        start = match.end()
    segments.append(command[start:])
    return [segment.strip() for segment in segments if segment.strip()]


def tokenize(segment):
    """Splits one command segment into tokens, falling back to whitespace on unbalanced quotes."""
    try:
        return shlex.split(segment, comments=False, posix=True)
    except ValueError:
        return segment.split()


def program_name(tokens):
    """Returns the program a token list invokes, seeing past env, sudo, uv run and time."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        base = os.path.basename(token)
        if base in ("env", "sudo", "nice", "time", "command", "exec"):
            index += 1
            continue
        if base == "uv" and index + 1 < len(tokens) and tokens[index + 1] == "run":
            index += 2
            continue
        if "=" in token and not token.startswith("-") and "/" not in token.split("=")[0]:
            index += 1
            continue
        return base
    return ""


def resolve_path(token, cwd):
    """Turns a path token into an absolute path without following symlinks."""
    expanded = os.path.expanduser(token)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normpath(expanded)


def find_repository_root(path):
    """Returns the directory holding the .git entry above this path, or None."""
    current = path if os.path.isdir(path) else os.path.dirname(path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def classify_path(token, cwd):
    """Sorts a path token into exempt, protected or unknown.

    A token standing for a name the hook cannot see — a variable, a substitution, a glob — is
    unknown unless it spells out a scratch directory.
    """
    token = token.strip().strip("'\"")
    if not token or token.startswith("&"):
        return EXEMPT
    if SUBSTITUTION.search(token):
        lowered = token.lower()
        if "tmp" in lowered or "scratchpad" in lowered:
            return EXEMPT
        return UNKNOWN
    path = resolve_path(token, cwd)
    if any(path == root or path.startswith(root + "/") for root in TEMPORARY_ROOTS):
        return EXEMPT
    parts = path.split(os.sep)
    if any(part in TEMPORARY_DIR_NAMES for part in parts):
        return EXEMPT
    if ".git" in parts:
        return EXEMPT
    if find_repository_root(path) is None:
        return EXEMPT
    return PROTECTED


def looks_like_source(token):
    """Says whether a path token names a file that belongs in a commit."""
    return os.path.splitext(token.strip().strip("'\""))[1].lower() in SOURCE_SUFFIXES
