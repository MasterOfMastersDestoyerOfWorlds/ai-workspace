"""Move a VS Code window off a worktree that is about to disappear, back to the main checkout.

VS Code's command line cannot address one window by name: ``code -r <folder>`` reuses the last
active window. So the window that shows the worktree is found first, from the window titles
``code --status`` prints (the default title carries the folder's name) and from the last active
window VS Code records in its ``storage.json``, and ``-r`` is used only when it will land on that
window. Otherwise the user is told which window to switch.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

CODE = "code"
CODE_TIMEOUT_SECONDS = 10
WORKSPACE_EXIT_TIMEOUT_SECONDS = 60
POLL_SECONDS = 0.5
WINDOW_LINE = re.compile(r"\bwindow \[\d+\] \((.*)\)\s*$")
APP_SUFFIX = " - Visual Studio Code"


def storage_path():
    """VS Code's global ``storage.json`` for this platform."""
    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Code" / "User" / "globalStorage" / "storage.json"


def run_code(arguments, cwd):
    """Run the ``code`` command line from an existing directory, giving up after a few seconds.

    ``code`` started from a deleted current directory, which is where a shell is left after
    ``land`` removes the worktree it sat in, never returns; so every call names its directory.

    :param arguments: arguments after ``code``
    :param cwd: an existing directory to run it from
    :return: the completed process, or None when it could not start or did not answer in time
    """
    try:
        return subprocess.run(
            [CODE, *arguments], cwd=str(cwd), capture_output=True, text=True, timeout=CODE_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError):
        return None


def window_titles(cwd):
    """The title of every open VS Code window, [] when none is open, None when VS Code did not answer.

    :param cwd: an existing directory to run ``code`` from
    """
    status = run_code(["--status"], cwd)
    if status is None:
        return None
    return [match.group(1) for match in map(WINDOW_LINE.search, status.stdout.splitlines()) if match]


def shows_folder(title, folder):
    """Whether a window title names this folder as its workspace (``... - <name> - Visual Studio Code``)."""
    body = title.removesuffix(APP_SUFFIX)
    return body == folder.name or body.endswith(f" - {folder.name}")


def last_active_folder():
    """The folder of the window VS Code last recorded as active, as a path, or None."""
    try:
        state = json.loads(storage_path().read_text(encoding="utf-8")).get("windowsState", {})
    except (OSError, ValueError):
        return None
    uri = (state.get("lastActiveWindow") or {}).get("folder", "")
    if not uri.startswith("file://"):
        return None
    return Path(uri.removeprefix("file://"))


def plan_return(worktree, cwd):
    """What to do about VS Code windows showing the worktree.

    :param worktree: the worktree directory
    :param cwd: an existing directory to run ``code`` from
    :return: ("none", why) when no window shows it or VS Code is absent, ("reuse", why) when
        ``code -r`` will land on that window, ("manual", why) when it would land elsewhere or
        VS Code did not answer
    """
    if not shutil.which(CODE):
        return "none", f"no `{CODE}` on PATH"
    titles = window_titles(cwd)
    if titles is None:
        return "manual", f"`{CODE} --status` did not answer within {CODE_TIMEOUT_SECONDS}s"
    showing = [title for title in titles if shows_folder(title, worktree)]
    if not showing:
        return "none", f"no VS Code window shows {worktree.name}"
    if len(titles) == 1:
        return "reuse", "the only VS Code window shows it"
    if last_active_folder() == worktree:
        return "reuse", "it is VS Code's last active window"
    return "manual", f"{len(titles)} windows are open and another one was active last"


def workspace_storage_dirs(folder):
    """VS Code's per-workspace storage directories for this folder, from their ``workspace.json``.

    :param folder: the workspace folder
    :return: the storage directories, usually one
    """
    root = storage_path().parent.parent / "workspaceStorage"
    uri = folder.absolute().as_uri()
    found = []
    for record in root.glob("*/workspace.json"):
        try:
            if json.loads(record.read_text(encoding="utf-8")).get("folder") == uri:
                found.append(record.parent)
        except (OSError, ValueError):
            continue
    return found


def processes_mentioning(markers):
    """Command lines of running processes, other than this one, that contain any marker.

    :param markers: strings to look for, such as a workspace storage directory
    :return: the matching command lines
    """
    try:
        listing = subprocess.run(
            ["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=CODE_TIMEOUT_SECONDS
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    own = {str(os.getpid()), str(os.getppid())}
    matches = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid not in own and any(marker in command for marker in markers):
            matches.append(command)
    return matches


def wait_for_workspace_to_close(folder):
    """Wait until no process still works on the folder's VS Code workspace, such as its Java server.

    The Java language server saves each project's ``.project`` as it shuts down, which happens
    after the window has already switched; deleting the folder before it exits only has it
    written back.

    :param folder: the folder the window showed
    :return: True once nothing uses it, False when something still did at the time limit
    """
    markers = [str(directory) for directory in workspace_storage_dirs(folder)]
    if not markers:
        return True
    deadline = time.monotonic() + WORKSPACE_EXIT_TIMEOUT_SECONDS
    announced = False
    while processes_mentioning(markers):
        if time.monotonic() > deadline:
            print(f"== VS Code: {folder.name}'s language server is still running; its folder may come back")
            return False
        if not announced:
            print(f"== VS Code: waiting for {folder.name}'s language server to exit")
            announced = True
        time.sleep(POLL_SECONDS)
    return True


def running_inside(worktree):
    """Whether this process runs in a VS Code terminal opened in the worktree.

    Switching that window's folder closes its terminals, so the switch has to wait until the
    command has done everything else.

    :param worktree: the worktree directory
    :return: True when the switch must be the last thing done
    """
    if os.environ.get("TERM_PROGRAM") != "vscode":
        return False
    try:
        here = Path.cwd()
    except OSError:
        here = Path(os.environ.get("PWD", "/"))
    try:
        here.absolute().relative_to(worktree.absolute())
    except ValueError:
        return False
    return True


def started_inside(folder):
    """PIDs of VS Code processes whose working directory is the folder or below it (Linux only).

    VS Code started by ``code`` from a shell in a worktree runs from there, and every process it
    spawns later inherits that directory. Once the folder is deleted, a window opened or reloaded
    afterwards gets an extension host that cannot start its extensions: Source Control sits on
    "Scanning folder for Git repositories" for good. Only quitting VS Code fixes it.

    :param folder: the worktree directory, which may already be gone
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    prefix = str(folder.absolute())
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if Path(os.readlink(entry / "exe")).name != CODE:
                continue
            cwd = os.readlink(entry / "cwd").removesuffix(" (deleted)")
        except OSError:
            continue
        if cwd == prefix or cwd.startswith(prefix + "/"):
            found.append(int(entry.name))
    return found


def return_to_main_checkout(worktree, main_checkout):
    """Point the VS Code window that shows the worktree at the main checkout, or say how to.

    :param worktree: the worktree directory, removed or about to be
    :param main_checkout: the repository's main checkout to open instead
    """
    if started_inside(worktree):
        print(
            f"== VS Code: it was started from inside {worktree.name}, so windows it opens once that "
            "folder is gone cannot load extensions (Source Control stays on 'Scanning folder for Git "
            "repositories'). Quit VS Code completely and start it again."
        )
    action, why = plan_return(worktree, main_checkout)
    if action == "none":
        return
    if action == "manual":
        print(f"== VS Code: switch the window on {worktree.name} to {main_checkout} yourself ({why})")
        return
    result = run_code(["--reuse-window", str(main_checkout)], main_checkout)
    if result is None or result.returncode != 0:
        reason = "no answer" if result is None else (result.stderr or result.stdout).strip()
        print(f"== VS Code: `{CODE} -r {main_checkout}` failed: {reason}")
        return
    print(f"== VS Code: switched the {worktree.name} window to {main_checkout} ({why})")
    wait_for_workspace_to_close(worktree)
