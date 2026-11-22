"""A terminal menu picked with the arrow keys or by typing an entry's number.

Stdlib only: the terminal is put in cbreak mode with ``termios`` (on Windows, keys come from
``msvcrt`` and the console is switched to ANSI processing) and the menu is drawn on the
alternate screen, the way ``less`` does, so it leaves nothing in the scrollback. Every line is cut
to the terminal width so none wraps, and a list taller than the terminal scrolls a window over the
entries to keep the highlighted one in view. Off a terminal it falls back to a plain numbered
prompt.
"""

import os
import select
import shutil
import sys

UP = ("\x1b[A", "\x1bOA", "k")
DOWN = ("\x1b[B", "\x1bOB", "j")
ENTER = ("\r", "\n")
QUIT = ("\x1b", "q", "\x03", "\x04")
ESCAPE_WAIT_SECONDS = 0.05
HIGHLIGHT = "\x1b[7m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
ALTERNATE_SCREEN = "\x1b[?1049h"
MAIN_SCREEN = "\x1b[?1049l"

# msvcrt reports an arrow key as a prefix character then a scan code; map those to the ANSI
# sequences the menu already understands.
WINDOWS_KEY_PREFIXES = ("\x00", "\xe0")
WINDOWS_SCAN_CODES = {"H": UP[0], "P": DOWN[0]}
WINDOWS_STD_OUTPUT_HANDLE = -11
WINDOWS_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def fit(text, width):
    """One line cut to the width, with an ellipsis when it was longer."""
    return text if len(text) <= width else text[: max(width - 3, 0)] + "..."


def read_key(fd):
    """One keypress, an escape sequence such as the up arrow read whole."""
    key = os.read(fd, 1).decode(errors="replace")
    if key != "\x1b":
        return key
    while select.select([fd], [], [], ESCAPE_WAIT_SECONDS)[0]:
        key += os.read(fd, 1).decode(errors="replace")
        if key[-1].isalpha() or key[-1] == "~":
            break
    return key


def read_windows_key(msvcrt):
    """One keypress from the Windows console, an arrow key translated to its ANSI sequence."""
    key = msvcrt.getwch()
    if key in WINDOWS_KEY_PREFIXES:
        return WINDOWS_SCAN_CODES.get(msvcrt.getwch(), "")
    return key


def enable_windows_ansi():
    """Turn on ANSI escape handling for this console, so the highlight, the alternate screen and
    the cursor moves draw instead of printing as text; the old console mode is returned so it
    can be put back, or None when the console could not be switched.
    """
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(WINDOWS_STD_OUTPUT_HANDLE)
    mode = ctypes.c_ulong()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return None
    if not kernel32.SetConsoleMode(handle, mode.value | WINDOWS_VIRTUAL_TERMINAL_PROCESSING):
        return None
    return handle, mode.value


def block(entries, index, selected, width):
    """One entry's lines as drawn: headline, dimmed detail lines, then a blank separator."""
    head = fit(f"{'>' if index == selected else ' '}{index + 1:>3}) {entries[index][0]}", width)
    lines = [f"{HIGHLIGHT}{head}{RESET}" if index == selected else head]
    lines += [f"{DIM}{fit('      ' + line, width)}{RESET}" for line in entries[index][1:]]
    return lines + [""]


def draw(entries, selected, typed, first, size):
    """The screen: as many entries as fit, starting at ``first`` but always showing the selected
    one, and the key help at the bottom.

    :param entries: each entry's lines, the first being its headline
    :param selected: index of the highlighted entry
    :param typed: the digits typed so far
    :param first: the entry the last draw started at, so the window only scrolls when it must
    :param size: the terminal size
    :return: the text and the entry it started at
    """
    width, room = size.columns - 1, max(size.lines - 1, 1)
    per_entry = max(len(entry) for entry in entries) + 1
    visible = max(room // per_entry, 1)
    first = min(max(first, selected - visible + 1), selected)
    lines = []
    for index in range(first, min(first + visible, len(entries))):
        lines += block(entries, index, selected, width)
    shown = f"{first + 1}-{min(first + visible, len(entries))} of {len(entries)}"
    help_line = f"{shown}  up/down or a number, enter to open, q to quit{'  > ' + typed if typed else ''}"
    return "\x1b[H\x1b[J" + "\n".join(lines[:room] + [fit(help_line, width)]), first


def pick_plain(entries, prompt):
    """The fallback off a terminal: print the numbered entries and read a number."""
    for index, entry in enumerate(entries):
        print(f"{index + 1:>4}) {entry[0]}")
        for line in entry[1:]:
            print(f"      {line}")
        print()
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not answer.isdigit() or not 1 <= int(answer) <= len(entries):
        return None
    return int(answer) - 1


def pick(entries, prompt="open which? "):
    """Let the user pick one entry, returning its index or None when they quit.

    Up/down (or k/j) move the highlight, digits jump to that entry number (``1`` then ``2``
    reaches 12 when there are that many), enter picks, q or escape quits.

    :param entries: each entry's lines, the first being its headline
    :param prompt: the question the plain fallback asks
    """
    if not entries:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return pick_plain(entries, prompt)
    if sys.platform == "win32":
        return pick_windows(entries, prompt)
    try:
        # Imported here: Windows has neither, and every ixd command imports this module.
        import termios
        import tty
    except ImportError:
        return pick_plain(entries, prompt)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return run_menu(entries, lambda: read_key(fd))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def pick_windows(entries, prompt):
    """The menu on a Windows console (PowerShell, cmd, Windows Terminal): keys from ``msvcrt``,
    drawing through the console's ANSI mode, the plain prompt when that mode cannot be set."""
    import ctypes
    import msvcrt

    saved = enable_windows_ansi()
    if saved is None:
        return pick_plain(entries, prompt)
    try:
        return run_menu(entries, lambda: read_windows_key(msvcrt))
    finally:
        ctypes.windll.kernel32.SetConsoleMode(*saved)


def run_menu(entries, next_key):
    """Draw the menu and act on keys until one is picked or the user quits.

    :param entries: each entry's lines, the first being its headline
    :param next_key: reads one keypress, arrows as their ANSI sequences
    :return: the picked index, or None
    """
    selected, typed, first = 0, "", 0
    try:
        sys.stdout.write(ALTERNATE_SCREEN + "\x1b[?25l")
        while True:
            text, first = draw(entries, selected, typed, first, shutil.get_terminal_size())
            sys.stdout.write(text)
            sys.stdout.flush()
            key = next_key()
            if key in ENTER:
                return selected
            if key in QUIT:
                return None
            if key in UP:
                selected, typed = (selected - 1) % len(entries), ""
            elif key in DOWN:
                selected, typed = (selected + 1) % len(entries), ""
            elif key.isdigit():
                candidate = typed + key
                if not 1 <= int(candidate) <= len(entries):
                    candidate = key
                if 1 <= int(candidate) <= len(entries):
                    typed, selected = candidate, int(candidate) - 1
                else:
                    typed = ""
    except KeyboardInterrupt:
        return None
    finally:
        sys.stdout.write("\x1b[?25h" + MAIN_SCREEN)
        sys.stdout.flush()
