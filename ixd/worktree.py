"""Git actions that are safe inside a linked worktree, and nothing else.

This is what the `ixd wt` subcommands are built from. The Claude permission deny list blocks
`git add`, `git commit`, `git merge` and friends everywhere so agents can never touch the main
branch, and these functions are the one allow-listed door. They act only on a *linked* worktree,
never the main checkout, whose HEAD is a branch other than the main branch, and they only ever move
that branch.

The model: the worktree's uncommitted diff IS the proposed change, the "PR". The branch pointer sits
on the main branch, so `git diff` in the worktree shows exactly what would land.

`sync` never loses work. The change is parked in a temporary commit, replayed onto the main branch
with `git rebase`, and unpacked back into the working tree. A conflicted replay leaves the rebase in
progress with the conflicting files listed, for `continue` or `abort`. Nothing here checks out,
pushes, or writes to the main branch, and tmp/ is never staged or committed.

Works on Linux, macOS and Windows.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .paths import repo_home

TMP_EXCLUDE = ":(exclude)tmp"
PARK_MESSAGE = "ixd wt: parked working tree (temporary)"
CODE_ROOT = repo_home()
TICKET_REPO = CODE_ROOT / "ixdar-tickets"
TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
WORKTREE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
LAUNCH_VM_ARGS = (
    "-enableassertions -Dsun.awt.noerasebackground=true "
    "-Dorg.lwjgl.util.DebugLoader=true -XX:ErrorFile=target/hs_err_pid%p.log"
)
LAUNCH_MAIN_CLASS = "ixdar.canvas.IxdarWindow"
SCREENSHOT_SUFFIXES = (".png", ".jpg", ".jpeg")
MIN_TRANSCRIPT_AGE = 120
# Fewer tool calls into a worktree than this is incidental: one `wt status` reaches that far.
MIN_WORKTREE_CALLS = 5
SUBAGENT_DIR = "subagents"
# The model name Claude Code puts on its own interruption notices, which are not the agent talking.
SYNTHETIC_MODEL = "<synthetic>"
# Tools that change a file. Writing into a worktree is what only the agent working there does.
WRITING_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
NOTE_LINES = 8
NOTE_WIDTH = 160
BUILD_COMMAND = ["mvn", "-q", "compile", "-pl", "annotations,ixdar-app"]


def git(cwd, *args, check=True):
    result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {cwd}:\n{result.stderr.strip()}")
    return result.stdout.strip()


def current_checkout():
    """(toplevel, main checkout) of the repository containing the current directory, or None.

    Inside a linked worktree the main checkout is the directory holding the shared .git; in the
    main checkout the two are the same."""
    toplevel = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if toplevel.returncode != 0 or common.returncode != 0:
        return None
    top = Path(toplevel.stdout.strip()).resolve()
    common_dir = Path(common.stdout.strip())
    common_dir = (Path.cwd() / common_dir).resolve() if not common_dir.is_absolute() else common_dir.resolve()
    return top, common_dir.parent


def locate_worktree(name_or_path):
    """A bare name like ``craw-27`` resolves to ``<repo>/.claude/worktrees/<name>`` of the
    repository containing the current directory (its main checkout, even when the current
    directory is inside another worktree), falling back to REPO_HOME/Ixdar; a path is used as
    is; no argument means the worktree containing the current directory."""
    checkout = current_checkout()
    if not name_or_path:
        if checkout is None:
            raise SystemExit("not inside a git worktree; name the worktree or run from inside it")
        return checkout[0]
    given = Path(name_or_path)
    if given.is_dir():
        return given.resolve()
    roots = []
    if checkout is not None:
        toplevel, main_checkout = checkout
        if toplevel.name == name_or_path and toplevel != main_checkout:
            return toplevel
        roots.append(main_checkout)
    roots.append(CODE_ROOT / "Ixdar")
    for root in roots:
        candidate = root / ".claude" / "worktrees" / name_or_path
        if candidate.is_dir():
            return candidate.resolve()
    raise SystemExit(
        f"no worktree named {name_or_path!r} under "
        + " or ".join(str(r / ".claude/worktrees") for r in roots)
    )


def resolve_worktree(path, allow_rebase=False):
    """Return (worktree_path, branch, main_branch) or exit with a reason."""
    worktree = locate_worktree(path)
    if not worktree.is_dir():
        raise SystemExit(f"{worktree} is not a directory")
    inside = git(worktree, "rev-parse", "--is-inside-work-tree", check=False)
    if inside != "true":
        raise SystemExit(f"{worktree} is not inside a git work tree")
    toplevel = Path(git(worktree, "rev-parse", "--show-toplevel")).resolve()
    if toplevel != worktree:
        if not (worktree / ".git").exists():
            raise SystemExit(
                f"{worktree} is a leftover directory, not a worktree: git no longer knows it, so it "
                f"was landed or removed and the editor recreated its output. Delete it."
            )
        raise SystemExit(f"{worktree} is not a worktree root (root is {toplevel})")
    git_dir = Path(git(worktree, "rev-parse", "--absolute-git-dir")).resolve()
    common_dir = Path(git(worktree, "rev-parse", "--git-common-dir"))
    common_dir = (worktree / common_dir).resolve() if not common_dir.is_absolute() else common_dir.resolve()
    if git_dir == common_dir:
        raise SystemExit(
            f"{worktree} is the main checkout, refusing; this tool only acts on linked worktrees"
        )
    rebasing = (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()
    if rebasing:
        if not allow_rebase:
            raise SystemExit(f"{worktree} has a sync in progress; run `continue` or `abort` first")
        head_name = None
        for state_dir in ("rebase-merge", "rebase-apply"):
            candidate = git_dir / state_dir / "head-name"
            if candidate.exists():
                head_name = candidate.read_text(encoding="utf-8").strip()
        if not head_name:
            raise SystemExit(f"{worktree}: cannot read the branch of the sync in progress")
        branch = head_name.removeprefix("refs/heads/")
    else:
        branch = git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if not branch:
            raise SystemExit(f"{worktree} has a detached HEAD, refusing")
    main_branch = main_branch_of(worktree)
    if branch == main_branch:
        raise SystemExit(f"{worktree} has the main branch {main_branch!r} checked out, refusing")
    return worktree, branch, main_branch


def main_branch_of(worktree):
    """The branch checked out in the main (first) worktree of this repository."""
    listing = git(worktree, "worktree", "list", "--porcelain")
    for line in listing.splitlines():
        if line.startswith("branch "):
            return line[len("branch ") :].removeprefix("refs/heads/")
        if line == "":
            break
    raise SystemExit("cannot determine the main branch: the main worktree has a detached HEAD")


def changed_files(worktree):
    status = git(worktree, "status", "--porcelain", "--", ".", TMP_EXCLUDE)
    return [line for line in status.splitlines() if line.strip()]


def stage_all(worktree):
    git(worktree, "add", "-A", "--", ".", TMP_EXCLUDE)
    return bool(git(worktree, "diff", "--cached", "--name-only"))


def ahead_behind(worktree, branch, main_branch):
    ahead = int(git(worktree, "rev-list", "--count", f"{main_branch}..{branch}"))
    behind = int(git(worktree, "rev-list", "--count", f"{branch}..{main_branch}"))
    return ahead, behind


def print_resume_note(worktree):
    """The last thing an agent said about this worktree, so a relaunch does not rebuild it by hand."""
    note = last_agent_note(worktree)
    if not note:
        print("resume:   no finished agent transcript mentions this worktree yet")
        return
    path, when, text = note
    print(f"resume:   last agent note ({when}, {path.name}):")
    lines = [line for line in text.strip().splitlines() if line.strip()]
    for line in lines[:NOTE_LINES]:
        print(f"  | {line[:NOTE_WIDTH]}" + (" ..." if len(line) > NOTE_WIDTH else ""))
    if len(lines) > NOTE_LINES:
        print(f"  | ... {len(lines) - NOTE_LINES} more lines in {path}")


def last_agent_note(worktree, file_limit=200, min_age_seconds=MIN_TRANSCRIPT_AGE):
    """(transcript path, local timestamp, text) of the newest finished transcript of an agent that
    worked in this worktree.

    Claude Code writes one JSONL per session under ~/.claude/projects/, and subagent transcripts
    below it. Naming the worktree is not enough: one `git worktree list` prints every worktree path
    and a tool-review agent quotes them hundreds of times, which used to give every worktree the
    same note. Only tool calls aimed at the worktree count, and the agent that wrote files there
    outranks one that merely ran commands against it (copying a fix out of another worktree, say).
    A subagent's transcript, which is an agent's own note, outranks a session transcript, which is
    the user's. A transcript still being written is the caller's own session, whose half-formed
    last line is not a resume note, so anything touched in the last couple of minutes is skipped."""
    if not TRANSCRIPT_ROOT.is_dir():
        return None
    now = datetime.datetime.now().timestamp()
    transcripts = [
        path
        for path in TRANSCRIPT_ROOT.rglob("*.jsonl")
        if path.is_file() and now - path.stat().st_mtime >= min_age_seconds
    ]
    transcripts.sort(key=lambda path: (is_subagent_transcript(path), path.stat().st_mtime), reverse=True)
    fallback = None
    for path in transcripts[:file_limit]:
        writes, calls = worktree_activity(path, worktree)
        if not writes and (calls < MIN_WORKTREE_CALLS or fallback is not None):
            continue
        note = dated_note(path)
        if note is None:
            continue
        if writes:
            return note
        fallback = note
    return fallback


def dated_note(path):
    """(path, local timestamp, closing prose) of a transcript, or None when it says nothing."""
    text = last_assistant_text(path)
    if not text:
        return None
    when = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return path, when, text


def is_subagent_transcript(path):
    """Whether a transcript is a subagent's own, rather than a session the user drove."""
    return SUBAGENT_DIR in path.parts


def worktree_activity(path, worktree, minimum=MIN_WORKTREE_CALLS):
    """(writes, calls) this transcript aimed at the worktree, counted no further than it takes.

    A write is an Edit or a Write of a file under the worktree, which only its own agent does. A
    call is any tool call that names it, including a shell command. Prose and tool output never
    count: quoting a path is not working in it. The name must end at a boundary, so ``craw-2`` does
    not match ``craw-22``.
    """
    if not file_contains(path, str(worktree).encode("utf-8")):
        return 0, 0
    inside = re.compile(re.escape(str(worktree)) + r"(?![A-Za-z0-9._-])")
    writes = calls = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"tool_use"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                found, written = calls_into(event, worktree, inside)
                calls += found
                writes += written
                if writes:
                    return writes, max(calls, minimum)
    except OSError:
        return 0, 0
    return writes, calls


def calls_into(event, worktree, inside):
    """(tool calls, of them writes) that one transcript event aimed at this worktree."""
    content = (event.get("message") or {}).get("content")
    if not isinstance(content, list):
        return 0, 0
    found = 0
    written = 0
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        arguments = block.get("input")
        if not isinstance(arguments, dict):
            continue
        target = str(arguments.get("file_path") or arguments.get("notebook_path") or "")
        if (
            target == str(worktree)
            or target.startswith(str(worktree) + os.sep)
            or target.startswith(str(worktree) + "/")
        ):
            found += 1
            written += block.get("name") in WRITING_TOOLS
        elif inside.search(str(arguments.get("command") or "")):
            found += 1
    return found, written


def file_contains(path, needle, chunk_size=1 << 20):
    """Whether the file holds the byte string, read in chunks so a huge transcript stays cheap."""
    try:
        with open(path, "rb") as handle:
            carry = b""
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    return False
                if needle in carry + chunk:
                    return True
                carry = chunk[-len(needle) :]
    except OSError:
        return False


def last_assistant_text(path):
    """The final assistant prose in a transcript: the agent's closing note, tool calls skipped.

    The harness writes its own interruptions ("You've hit your session limit") as assistant events
    marked synthetic. Those are not the agent talking and say nothing about the work, so a killed
    agent's last real words are the note.
    """
    latest = None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"assistant"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                message = event.get("message") or {}
                if message.get("role") != "assistant":
                    continue
                if event.get("isApiErrorMessage") or message.get("model") == SYNTHETIC_MODEL:
                    continue
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                text = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ).strip()
                if text:
                    latest = text
    except OSError:
        return None
    return latest


def ticket_for(branch):
    """The ticket JSON whose id matches the branch name (``craw-27`` -> CRAW-27), or None."""
    path = ticket_path_for(branch)
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ticket_path_for(branch):
    """Path of the ticket JSON named like the branch, under the live ticket store, or None."""
    ticket_id = branch.upper()
    if not TICKET_REPO.is_dir():
        return None
    for folder in ("content", "done"):
        for path in (TICKET_REPO / folder).glob(f"*/{ticket_id}.json"):
            return path
    return None


def strip_jsonc(text):
    """The text with comments and trailing commas blanked to spaces so ``json.loads`` reads it.

    Blanking rather than deleting keeps every offset identical to the original, which is what
    lets an edit splice into the real text and leave its comments alone."""
    out = list(text)
    index, length, in_string = 0, len(text), False
    while index < length:
        character = text[index]
        if in_string:
            if character == "\\":
                index += 2
                continue
            if character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            index += 1
            continue
        if character == "/" and index + 1 < length and text[index + 1] in "/*":
            if text[index + 1] == "/":
                end = text.find("\n", index)
                end = length if end < 0 else end
            else:
                end = text.find("*/", index + 2)
                end = length if end < 0 else end + 2
            for position in range(index, end):
                if out[position] != "\n":
                    out[position] = " "
            index = end
            continue
        if character in "}]":
            previous = index - 1
            while previous >= 0 and out[previous].isspace():
                previous -= 1
            if previous >= 0 and out[previous] == ",":
                out[previous] = " "
        index += 1
    return "".join(out)


def parse_jsonc(text):
    """The object a JSONC file describes, reading comments and trailing commas as VS Code does."""
    return json.loads(strip_jsonc(text))


def configurations_close(text):
    """Offset of the ``]`` closing the ``configurations`` array, or -1 when there is no such array."""
    stripped = strip_jsonc(text)
    key = stripped.find('"configurations"')
    if key < 0:
        return -1
    start = stripped.find("[", key)
    if start < 0:
        return -1
    depth, index, in_string = 0, start, False
    while index < len(stripped):
        character = stripped[index]
        if in_string:
            if character == "\\":
                index += 2
                continue
            if character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def insert_launch_entry(text, entry):
    """The launch.json text with one entry appended to ``configurations``, comments untouched.

    The entry is spliced in as text rather than re-serialised from a parse, because a parse
    would drop the file's comments and VS Code's own header lines."""
    close = configurations_close(text)
    if close < 0:
        raise SystemExit("launch.json has no configurations array that this tool can read")
    line_start = text.rfind("\n", 0, close) + 1
    closing_indent = text[line_start:close] if text[line_start:close].isspace() else "  "
    entry_indent = closing_indent + "  "
    block = "\n".join(entry_indent + line for line in json.dumps(entry, indent=2).splitlines())
    last = close
    while last > 0 and text[last - 1].isspace():
        last -= 1
    before, trailing = text[:last], text[last:close] or "\n" + closing_indent
    separator = "" if before.endswith("[") or before.endswith(",") else ","
    return before + separator + "\n" + block + trailing + text[close:]


def launch_entry(name, scene, properties):
    """A java launch configuration running one scene id, with each ``k=v`` property as ``-Dk=v``."""
    vm_args = LAUNCH_VM_ARGS
    for prop in properties:
        if "=" not in prop:
            raise SystemExit(f"--property {prop!r} is not key=value")
        vm_args += f" -D{prop}"
    return {
        "type": "java",
        "name": name,
        "request": "launch",
        "mainClass": LAUNCH_MAIN_CLASS,
        "args": scene,
        "vmArgs": vm_args,
        "cwd": "${workspaceFolder}/ixdar-app",
    }


def launch_entries(worktree):
    """Every configuration in the worktree's .vscode/launch.json, or exit saying what is wrong."""
    path = worktree / ".vscode" / "launch.json"
    if not path.exists():
        raise SystemExit(f"{path} does not exist; run `launch add` first")
    try:
        document = parse_jsonc(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"{path} does not parse as JSONC: {error}")
    entries = document.get("configurations")
    if not isinstance(entries, list):
        raise SystemExit(f"{path} has no configurations array")
    return entries


def entry_for_ticket(worktree, branch):
    """The launch entry this ticket added: its name starts with the ticket id, or None."""
    prefix = branch.upper()
    for entry in launch_entries(worktree):
        name = str(entry.get("name", ""))
        if name.upper() == prefix or name.upper().startswith(prefix + ":"):
            return entry
    return None


def entry_properties(entry):
    """The ``key=value`` properties an entry adds beyond the standard vmArgs."""
    standard = set(LAUNCH_VM_ARGS.split())
    properties = []
    for token in str(entry.get("vmArgs", "")).split():
        if token.startswith("-D") and token not in standard and "=" in token:
            properties.append(token[2:])
    return properties


def seed_environment(worktree):
    """Create the worktree's Python virtualenv so the first ixdar-cli call is not a cold install."""
    if not (worktree / "pyproject.toml").exists():
        return
    if not shutil.which("uv"):
        print("seed:     uv is not on PATH; skipped the environment seed")
        return
    started = datetime.datetime.now()
    result = subprocess.run(["uv", "sync"], cwd=str(worktree), capture_output=True, text=True)
    seconds = (datetime.datetime.now() - started).total_seconds()
    if result.returncode != 0:
        reason = (result.stderr.strip().splitlines() or ["no output"])[-1]
        print(f"seed:     uv sync failed ({reason}); run it yourself before the first ixdar-cli call")
    else:
        print(f"seed:     uv sync done in {seconds:.0f}s")


def brief_text(worktree, branch, main_branch):
    """The orientation an agent starting in this worktree needs: paths, ticket, and the verbs.

    :param worktree: the worktree directory
    :param branch: its branch, which is also the ticket id lower-cased
    :param main_branch: the branch it was created from
    :return: the brief, ready to print
    """
    ticket_id = branch.upper()
    ticket_path = ticket_path_for(branch)
    ticket_line = str(ticket_path) if ticket_path else f"no ticket {ticket_id} in {TICKET_REPO}"
    lines = [
        "== worktree ready",
        f"worktree: {worktree}",
        f"branch:   {branch}, created from {main_branch}",
        "model:    the uncommitted diff in this worktree IS the proposed change; leave it uncommitted",
        f"ticket:   {ticket_id}  {ticket_line}",
        "git:      add, commit, merge, branch, checkout, reset and stash are denied; ixd wt is the one door",
        f"  ixd wt status {branch}      branch, distance from {main_branch}, changed files, last agent note",
        f"  ixd wt sync {branch}        replay your diff onto the current {main_branch} (run it first, and for newer {main_branch})",
        f"  ixd wt launch-add {branch} --scene <id> [--property k=v]   the .vscode/launch.json entry for the user's F5",
        f"  ixd wt done {branch}        sync, build, run that entry, check tmp/ screenshots, mark the ticket REVIEW",
    ]
    if (worktree / "pom.xml").exists():
        lines += [
            f"build:    cd {worktree} && mvn -q compile -pl annotations,ixdar-app",
            f"scene:    cd {worktree} && uv run ixdar-cli run-scene --scene <id> --screenshot tmp/{branch}.png",
        ]
    lines += [
        f'tickets:  cd {TICKET_REPO} && uv run python generate_board.py update {ticket_id} --add-changes "..."',
        "never:    ixd land (the user alone merges), raw git writes, editing files through the shell",
    ]
    return "\n".join(lines)


def cli_has_command(worktree, name):
    """Whether this checkout's ixdar-cli offers the named command (TOOL-1's `launch` may not exist yet)."""
    if not shutil.which("uv") or not (worktree / "pyproject.toml").exists():
        return False
    result = subprocess.run(
        ["uv", "run", "ixdar-cli", name, "--help"], cwd=str(worktree), capture_output=True, text=True
    )
    return result.returncode == 0 and "invalid choice" not in result.stderr


def run_step(label, command, cwd):
    """Run one step of `done`, echoing it, and exit with its output when it fails."""
    print(f"== {label}: {' '.join(command)}")
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise SystemExit(f"{label} failed; nothing marked.\n{output[-3000:]}")
    return result.stdout


def screenshots_under(worktree):
    """Every image below the worktree's gitignored tmp/, oldest first: the verification evidence."""
    tmp = worktree / "tmp"
    if not tmp.is_dir():
        return []
    images = [path for path in tmp.rglob("*") if path.suffix.lower() in SCREENSHOT_SUFFIXES]
    return sorted(images, key=lambda path: path.stat().st_mtime)


def launch_command(worktree, entry, screenshot):
    """The command that runs a launch entry once and leaves its screenshot under tmp/.

    Prefers ``ixdar-cli launch`` (TOOL-1), which runs the entry the way the user's F5 does; until
    that command exists it falls back to ``run-scene`` with the entry's scene and properties,
    which is headless and so does not exercise the desktop path."""
    if cli_has_command(worktree, "launch"):
        return ["uv", "run", "ixdar-cli", "launch", str(entry.get("name")), "--screenshot", str(screenshot)]
    command = ["uv", "run", "ixdar-cli", "run-scene", "--scene", str(entry.get("args"))]
    for prop in entry_properties(entry):
        command += ["--property", prop]
    return command + ["--screenshot", str(screenshot)]


def sync(worktree, branch, main_branch):
    """Replay the worktree's uncommitted change onto the main branch and unpack it again.

    :param worktree: the worktree directory
    :param branch: its branch
    :param main_branch: the branch to replay onto
    """
    ahead, behind = ahead_behind(worktree, branch, main_branch)
    parked = stage_all(worktree)
    if parked:
        git(worktree, "commit", "--quiet", "--no-verify", "-m", PARK_MESSAGE)
    if ahead == 0 and behind == 0:
        if parked:
            git(worktree, "reset", "--quiet", "--mixed", "HEAD~1")
        print(
            f"{branch}: already on top of {main_branch}; {len(changed_files(worktree))} file(s) uncommitted"
        )
        return
    replay = subprocess.run(
        ["git", "-C", str(worktree), "rebase", "--quiet", main_branch], capture_output=True, text=True
    )
    if replay.returncode != 0:
        conflicts = git(worktree, "diff", "--name-only", "--diff-filter=U", check=False)
        if not conflicts and not conflict_markers(worktree):
            # git rerere replayed a resolution recorded by an earlier sync and stopped for review.
            print(f"{branch}: conflict resolved from an earlier sync (git rerere); continuing")
            continue_rebase(worktree, branch, main_branch)
            return
        raise SystemExit(
            f"{branch}: replaying onto {main_branch} stopped on conflicts. The rebase is left in "
            f"progress: fix the conflict markers in the files below, then run `continue`; or run "
            f"`abort` to put everything back as it was.\n"
            f"conflicting files:\n" + "\n".join(f"  {c}" for c in conflicts.splitlines())
        )
    unpack(worktree, branch, main_branch)


def unpack(worktree, branch, main_branch):
    """Drop the replayed commits back into the working tree as an uncommitted diff on main."""
    git(worktree, "reset", "--quiet", "--mixed", main_branch)
    changed = changed_files(worktree)
    print(
        f"{branch}: now on {main_branch} ({git(worktree, 'rev-parse', '--short', main_branch)}) "
        f"with {len(changed)} file(s) as the uncommitted diff"
    )


def rebase_in_progress(worktree):
    git_dir = Path(git(worktree, "rev-parse", "--absolute-git-dir"))
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def conflict_markers(worktree):
    """The tracked files (outside tmp/) that still hold conflict markers, as git grep lists them."""
    markers = subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "grep",
            "-l",
            "-E",
            "^(<<<<<<<|=======|>>>>>>>)( |$)",
            "--",
            ".",
            TMP_EXCLUDE,
        ],
        capture_output=True,
        text=True,
    )
    return markers.stdout.strip()


def require_sync_in_progress(worktree, branch):
    """Refuse when no rebase is waiting, so `continue` and `abort` cannot act on a clean worktree.

    :param worktree: the worktree directory
    :param branch: its branch, named in the refusal
    """
    if not rebase_in_progress(worktree):
        raise SystemExit(f"{branch}: no sync in progress")


def continue_rebase(worktree, branch, main_branch):
    """Finish an interrupted sync once every conflict is resolved, then unpack the diff again."""
    unresolved = git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).splitlines()
    markers = conflict_markers(worktree)
    if markers:
        raise SystemExit(f"{branch}: conflict markers remain in:\n" + markers)
    for path in unresolved:
        if not (worktree / path).exists():
            raise SystemExit(
                f"{branch}: {path} is unresolved and missing from the working tree; "
                f"recreate it or run `abort`"
            )
    git(worktree, "add", "-A", "--", ".", TMP_EXCLUDE)
    step = subprocess.run(
        ["git", "-C", str(worktree), "-c", "core.editor=true", "rebase", "--continue"],
        capture_output=True,
        text=True,
    )
    if step.returncode != 0:
        conflicts = git(worktree, "diff", "--name-only", "--diff-filter=U", check=False)
        raise SystemExit(
            f"{branch}: next commit conflicted; fix and run `continue` again.\n"
            f"conflicting files:\n" + "\n".join(f"  {c}" for c in conflicts.splitlines())
        )
    unpack(worktree, branch, main_branch)


def abort(worktree, branch):
    """Abandon an interrupted sync and unpark the change it was replaying.

    :param worktree: the worktree directory
    :param branch: its branch
    """
    git(worktree, "rebase", "--abort")
    head_message = git(worktree, "log", "-1", "--format=%s")
    if head_message == PARK_MESSAGE:
        git(worktree, "reset", "--quiet", "--mixed", "HEAD~1")
    print(f"{branch}: sync aborted; the working tree is back to its pre-sync state")


def commit(worktree, branch, main_branch, message):
    """Squash the whole diff into one commit sitting directly on the main branch.

    :param worktree: the worktree directory
    :param branch: its branch
    :param main_branch: the branch the commit must sit on
    :param message: the commit message
    """
    if not message.strip():
        raise SystemExit("commit message must not be empty")
    ahead, behind = ahead_behind(worktree, branch, main_branch)
    if ahead or behind:
        raise SystemExit(
            f"{branch} is {ahead} ahead / {behind} behind {main_branch}; run `sync` first so the "
            f"result is one commit directly on top of {main_branch}"
        )
    if not stage_all(worktree):
        print(f"{branch}: nothing to commit outside tmp/")
        return
    git(worktree, "commit", "--quiet", "-m", message)
    print(
        f"{branch}: one commit {git(worktree, 'rev-parse', '--short', 'HEAD')} on top of {main_branch}; "
        f"fast-forwardable"
    )
