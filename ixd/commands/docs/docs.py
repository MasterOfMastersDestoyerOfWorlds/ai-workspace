"""Regenerate the command reference from the docstrings."""

from pathlib import Path

from ... import docs as render
from ...registry import cli_command

REPO_ROOT = Path(__file__).resolve().parents[3]

README = REPO_ROOT / "README.md"

HELP = REPO_ROOT / "HELP.md"


@cli_command
def docs(check: bool = False) -> int:
    """Write the command reference into README.md and HELP.md from the docstrings.

    README.md gets a table and one section per command, between the generated-region markers, so the
    prose around it survives. HELP.md gets every parser's help exactly as a terminal prints it. Both
    come from the same decorators the CLI itself is built from, so neither can drift.

    :param check: report whether the files are current and change nothing, exiting 1 when they are stale
    """
    wanted = {README: render.reference(), HELP: render.help_document()}
    stale = []
    for path, region in wanted.items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = render.replace_region(current, region) if path is README else region
        if current == updated:
            continue
        stale.append(path.name)
        if not check:
            path.write_text(updated, encoding="utf-8")
    if check:
        print("stale: " + ", ".join(stale) if stale else "README.md and HELP.md are current")
        return 1 if stale else 0
    print("rewrote " + ", ".join(stale) if stale else "README.md and HELP.md were already current")
    return 0
