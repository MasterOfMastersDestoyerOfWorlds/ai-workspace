"""Place windows on Hyprland workspaces, for `ixd review`.

The review page and the VS Code window go on two adjacent empty workspaces to the right of every
workspace in use, so a review never lands on top of whatever is already open. Only Hyprland is
handled (``hyprctl``); everywhere else ``available`` is False and the caller opens things the
plain way.

A window cannot be asked for by the process that made it: the browser hands ``--new-window`` to
its running instance, and ``code`` hands a folder to the running VS Code, so neither new window
belongs to the process started here. So the client list is read before, and the window that
appears afterwards with the expected class is the one moved.
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HYPRCTL = "hyprctl"
POLL_SECONDS = 0.25
BROWSER_WAIT_SECONDS = 10
EDITOR_WAIT_SECONDS = 20
APPLICATION_DIRS = (
    Path.home() / ".local/share/applications",
    Path.home() / ".nix-profile/share/applications",
    Path("/usr/share/applications"),
)
CODE_CLASSES = ("code", "code-oss", "vscodium")


def available():
    """Whether this session runs under Hyprland with ``hyprctl`` on PATH."""
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and shutil.which(HYPRCTL) is not None


def hyprctl(*arguments):
    """Run ``hyprctl``, returning its stdout, or "" when it failed."""
    try:
        result = subprocess.run([HYPRCTL, *arguments], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def clients():
    """Every mapped window, as hyprctl's JSON objects."""
    try:
        return [
            client for client in json.loads(hyprctl("clients", "-j") or "[]") if client.get("mapped", True)
        ]
    except ValueError:
        return []


def free_pair(ignore=()):
    """The two workspace ids right of the rightmost one holding a window.

    :param ignore: addresses of windows about to be moved, whose workspaces do not count as used
    """
    used = [
        client["workspace"]["id"]
        for client in clients()
        if client["address"] not in ignore and client["workspace"]["id"] > 0
    ]
    first = max(used, default=0) + 1
    return first, first + 1


def wait_for_new(before, classes, seconds):
    """The address of a window of one of these classes that was not open before, or None.

    :param before: the addresses open before the launch
    :param classes: window classes to accept, compared lower-case
    :param seconds: how long to wait for it
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for client in clients():
            if client["address"] not in before and client["class"].lower() in classes:
                return client["address"]
        time.sleep(POLL_SECONDS)
    return None


def move(address, workspace):
    """Move a window to a workspace without following it there."""
    hyprctl("dispatch", "movetoworkspacesilent", f"{workspace},address:{address}")


def show(workspace):
    """Switch the view to a workspace."""
    hyprctl("dispatch", "workspace", str(workspace))


def default_browser():
    """The default browser's executable, read from its desktop file's ``Exec=`` line, or None."""
    try:
        desktop = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    for directory in APPLICATION_DIRS:
        path = directory / desktop
        if desktop and path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Exec="):
                    return line.removeprefix("Exec=").split()[0]
    return None


def browser_classes(executable):
    """Window classes the browser's windows may carry: its name, with and without a channel suffix."""
    name = Path(executable).name.lower()
    return {name, name.removesuffix("-stable"), name.removesuffix("-browser"), f"{name}-browser"}


def launch_detached(command):
    """Start a program that outlives this command, its output discarded."""
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def open_page(url, workspace):
    """Open the URL in a new browser window on the workspace, returning whether it got there."""
    executable = default_browser()
    if not executable or not shutil.which(executable):
        return False
    before = {client["address"] for client in clients()}
    launch_detached([executable, "--new-window", url])
    address = wait_for_new(before, browser_classes(executable), BROWSER_WAIT_SECONDS)
    if address is None:
        return False
    move(address, workspace)
    return True


def editor_window(folder, shows_folder):
    """The address of a VS Code window already showing the folder, or None.

    :param folder: the workspace folder
    :param shows_folder: ``editor.shows_folder``, which reads a window title
    """
    for client in clients():
        if client["class"].lower() in CODE_CLASSES and shows_folder(client["title"], folder):
            return client["address"]
    return None


def open_editor(folder, workspace, existing, run_code):
    """Put a VS Code window on the folder onto the workspace, opening one when none exists.

    :param folder: the folder to show
    :param workspace: where the window goes
    :param existing: the address of a window already showing it, or None
    :param run_code: ``editor.run_code``
    :return: "moved" or "opened" on success, or why it failed
    """
    if existing:
        move(existing, workspace)
        return "moved"
    before = {client["address"] for client in clients()}
    result = run_code(["--new-window", str(folder)], folder)
    if result is None or result.returncode != 0:
        return "no answer from code" if result is None else (result.stderr or result.stdout).strip()
    address = wait_for_new(before, CODE_CLASSES, EDITOR_WAIT_SECONDS)
    if address is None:
        return f"no new VS Code window appeared within {EDITOR_WAIT_SECONDS}s"
    move(address, workspace)
    return "opened"
