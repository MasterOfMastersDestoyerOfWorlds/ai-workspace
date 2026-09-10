"""The ``ixd`` entry point: builds argparse from the registry and dispatches.

Every command's help text, flags and defaults come from the decorated function's signature and
docstring, so ``ixd wt sync --help`` and the generated README always agree with the code.
"""

from __future__ import annotations

import argparse
import sys

from .registry import CliCommand, CliParameter, get_registry, groups

PROGRAM = "ixd"

DESCRIPTION = "Workspace commands: worktrees, landing, machine setup and transcript statistics."


def add_argument(parser: argparse.ArgumentParser, parameter: CliParameter) -> None:
    """Add one command parameter to a parser as argparse expects it.

    :param parser: the subcommand's parser
    :param parameter: the parameter to add
    """
    options: dict = {"help": parameter.help_text}
    if parameter.choices is not None:
        options["choices"] = list(parameter.choices)
    if parameter.positional:
        options["type"] = parameter.annotation
        if parameter.multiple:
            options["nargs"] = "*" if parameter.has_default else "+"
        elif parameter.has_default:
            options["nargs"] = "?"
        if parameter.has_default:
            options["default"] = parameter.default
        parser.add_argument(parameter.name, **options)
        return
    if parameter.annotation is bool:
        default = bool(parameter.default) if parameter.has_default else False
        options["default"] = default
        options["action"] = "store_false" if default else "store_true"
    elif parameter.multiple:
        options["action"] = "append"
        options["type"] = parameter.annotation
        options["default"] = parameter.default if parameter.has_default else []
    else:
        options["type"] = parameter.annotation
        if parameter.has_default:
            options["default"] = parameter.default
        else:
            options["required"] = True
    flags = ([parameter.short] if parameter.short else []) + [parameter.flag]
    parser.add_argument(*flags, dest=parameter.name, **options)


def add_command(subparsers: argparse._SubParsersAction, command: CliCommand, word: str) -> None:
    """Give one command its own parser under a subparser action.

    :param subparsers: the parent's subparser action
    :param command: the command to add
    :param word: the word that selects it
    """
    parser = subparsers.add_parser(
        word,
        help=command.summary,
        description=command.summary if not command.detail else f"{command.summary}\n\n{command.detail}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for parameter in command.params:
        add_argument(parser, parameter)
    parser.set_defaults(command=command)


def build_parser() -> argparse.ArgumentParser:
    """Assemble the whole CLI from the registry.

    :return: the top-level parser, with one subparser per group
    """
    parser = argparse.ArgumentParser(
        prog=PROGRAM, description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    top = parser.add_subparsers(dest="group", required=True, metavar="command")
    for group, commands in groups().items():
        bare = next((one for one in commands if one.is_bare), None)
        if bare is not None:
            add_command(top, bare, group)
            continue
        summaries = ", ".join(one.name for one in commands)
        group_parser = top.add_parser(group, help=summaries, description=f"{group}: {summaries}")
        inner = group_parser.add_subparsers(dest="name", required=True, metavar="subcommand")
        for command in commands:
            add_command(inner, command, command.name)
    return parser


def main(argv: list[str]) -> int:
    """Parse arguments and run the selected command.

    :param argv: the arguments after the program name
    :return: the command's exit code
    """
    arguments = build_parser().parse_args(argv)
    command: CliCommand = arguments.command
    values = {parameter.name: getattr(arguments, parameter.name) for parameter in command.params}
    return command.function(**values) or 0


def cli() -> int:
    """Console-script entry point for ``ixd``.

    :return: the command's exit code
    """
    return main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(cli())
