"""Add a VS Code launch entry so the user can verify with F5."""

from typing import Annotated

from ... import worktree
from ...registry import CliOption, cli_command

EMPTY_LAUNCH_FILE = '{\n  "version": "0.2.0",\n  "configurations": []\n}\n'


@cli_command(name="launch-add")
def launch_add(
    scene: str,
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    property: Annotated[list[str], CliOption(multiple=True)] = (),
    name: str = "",
) -> int:
    """Add one entry to the worktree's .vscode/launch.json, keeping the file's comments.

    The file is edited as JSONC, so comments a human left survive. The result is parsed before it is
    written, so a broken edit never reaches disk. `ixd land` strips these entries before merging:
    they are verification aids, not part of the change.

    :param scene: scene id passed to IxdarWindow
    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param property: JVM system property written as -DKEY=VALUE, repeatable
    :param name: entry name, defaulting to "TICKET: scene"
    """
    path, branch, _ = worktree.resolve_worktree(worktree_name)
    entry_name = name or f"{branch.upper()}: {scene}"
    launch_file = path / ".vscode" / "launch.json"
    if not launch_file.exists():
        launch_file.parent.mkdir(parents=True, exist_ok=True)
        launch_file.write_text(EMPTY_LAUNCH_FILE, encoding="utf-8")
        print(f"created {launch_file}")
    text = launch_file.read_text(encoding="utf-8")
    for entry in worktree.launch_entries(path):
        if str(entry.get("name")) == entry_name:
            raise SystemExit(f"{launch_file} already has an entry named {entry_name!r}; nothing written")
    updated = worktree.insert_launch_entry(text, worktree.launch_entry(entry_name, scene, list(property)))
    try:
        worktree.parse_jsonc(updated)
    except ValueError as error:
        raise SystemExit(f"refusing to write: the result would not parse ({error})")
    launch_file.write_text(updated, encoding="utf-8")
    print(f"{launch_file}: added {entry_name!r} (scene {scene})")
    print("the user runs it with F5; `ixd land` strips these entries before merging")
    return 0
