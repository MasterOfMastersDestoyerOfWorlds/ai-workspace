"""Decorator-driven command registry for the ``ixd`` CLI.

A command is a decorated function. Its module path decides where it sits in the CLI: a module at
``ixd/commands/<group>/<name>.py`` becomes ``ixd <group> <name>``, and a module whose name repeats
its folder (``ixd/commands/land/land.py``) becomes the bare ``ixd <group>``. Nothing is listed
anywhere; dropping a file in adds a command.

The docstring is the only source of help text, in the ``:param name: description`` style. A command
with no docstring, no summary line, or an undocumented parameter fails at import, so the CLI cannot
grow an option that ``--help``, the README and the man page do not describe.
"""

from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Literal, get_args, get_origin

COMMANDS_PACKAGE = "ixd.commands"

PARAM_PATTERN = re.compile(r"^\s*:param\s+(\w+)\s*:\s*(.+?)\s*$")

RETURN_PATTERN = re.compile(r"^\s*:returns?\s*:")

BUILTIN_TYPES = {"bool": bool, "str": str, "int": int, "float": float}


@dataclass(frozen=True)
class CliOption:
    """Argparse metadata a parameter's annotation can carry.

    :param positional: take the value as a positional argument instead of a flag
    :param multiple: accept the flag repeatedly, collecting a list
    :param choices: restrict the value to this set
    :param short: a one-letter alias such as ``-m``, for a flag typed often
    """

    positional: bool = False
    multiple: bool = False
    choices: tuple[Any, ...] | None = None
    short: str = ""


@dataclass(frozen=True)
class CliParameter:
    """One parameter of a command, as argparse needs it.

    :param name: the Python parameter name
    :param annotation: the type argparse converts the raw string with
    :param has_default: whether the parameter is optional
    :param default: the value used when the flag is absent
    :param help_text: the ``:param:`` line from the docstring
    :param flag: the command-line spelling, ``--kebab-case`` unless positional
    :param choices: the permitted values, or None
    :param multiple: whether the flag may repeat
    :param positional: whether the value is positional
    :param short: the one-letter alias, or an empty string
    """

    name: str
    annotation: Any
    has_default: bool
    default: Any
    help_text: str
    flag: str
    choices: tuple[Any, ...] | None = None
    multiple: bool = False
    positional: bool = False
    short: str = ""


@dataclass(frozen=True)
class CliCommand:
    """One registered command.

    :param group: the folder name, which is the first word after ``ixd``
    :param name: the subcommand word, equal to the group for a bare command
    :param function: the implementation, returning an exit code or None
    :param summary: the docstring's first line
    :param detail: the docstring's prose below the summary, without the ``:param:`` lines
    :param params: the command's parameters in declaration order
    :param module: the module the command was defined in
    """

    group: str
    name: str
    function: Callable[..., int | None]
    summary: str
    detail: str
    params: list[CliParameter] = field(default_factory=list)
    module: str = ""

    @property
    def path(self) -> str:
        """The words a user types after ``ixd``."""
        return self.group if self.is_bare else f"{self.group} {self.name}"

    @property
    def is_bare(self) -> bool:
        """Whether the command occupies its whole group, with no subcommand word."""
        return self.name == self.group


_REGISTRY: dict[tuple[str, str], CliCommand] = {}

_IMPORTED = False


def normalise_annotation(annotation: Any, option: CliOption) -> tuple[Any, tuple[Any, ...] | None, bool]:
    """Turn a type annotation into the type, choices and repeatability argparse wants.

    :param annotation: the declared annotation, already stripped of its Annotated metadata
    :param option: the metadata that annotation carried
    :return: the conversion type, the permitted values or None, and whether the flag repeats
    """
    if annotation is inspect.Parameter.empty:
        return str, option.choices, option.multiple
    if isinstance(annotation, str):
        annotation = BUILTIN_TYPES.get(annotation, str)
    origin = get_origin(annotation)
    if origin is Literal:
        choices = tuple(get_args(annotation))
        kinds = {type(choice) for choice in choices}
        return (kinds.pop() if len(kinds) == 1 else str), option.choices or choices, option.multiple
    if origin in {list, tuple}:
        inner = next(iter(get_args(annotation)), str)
        kind, choices, _ = normalise_annotation(inner, option)
        return kind, option.choices or choices, True
    if origin is None:
        return annotation, option.choices, option.multiple
    remaining = [argument for argument in get_args(annotation) if argument is not type(None)]
    if len(remaining) == 1:
        return normalise_annotation(remaining[0], option)
    return str, option.choices, option.multiple


def split_annotation(annotation: Any) -> tuple[Any, CliOption]:
    """Separate a parameter's type from any CliOption attached with Annotated.

    :param annotation: the raw annotation on the parameter
    :return: the type on its own, and the CliOption it carried or a default one
    """
    if get_origin(annotation) is not Annotated:
        return annotation, CliOption()
    arguments = get_args(annotation)
    option = next((item for item in arguments[1:] if isinstance(item, CliOption)), CliOption())
    return arguments[0], option


def parse_docstring(function: Callable[..., Any]) -> tuple[str, str, dict[str, str]]:
    """Read a command's summary, prose and parameter help out of its docstring.

    :param function: the decorated command function
    :return: the summary line, the prose below it, and parameter name to help text
    :raises ValueError: when the docstring is missing or its first line is empty
    """
    doc = inspect.getdoc(function) or ""
    lines = doc.splitlines()
    summary = lines[0].strip() if lines else ""
    if not summary:
        raise ValueError(f"command '{function.__name__}' needs a docstring whose first line is a summary")
    help_text = {}
    prose = []
    for line in lines[1:]:
        match = PARAM_PATTERN.match(line)
        if match:
            help_text[match.group(1)] = match.group(2)
        elif not RETURN_PATTERN.match(line):
            prose.append(line.rstrip())
    return summary, "\n".join(prose).strip(), help_text


def describe_parameters(function: Callable[..., Any], help_text: dict[str, str]) -> list[CliParameter]:
    """Build the CliParameter list for a command's signature.

    :param function: the decorated command function
    :param help_text: parameter name to help text, from the docstring
    :return: one CliParameter per parameter, in declaration order
    :raises ValueError: when a parameter has no ``:param:`` line
    """
    described = []
    for parameter in inspect.signature(function).parameters.values():
        annotation, option = split_annotation(parameter.annotation)
        kind, choices, multiple = normalise_annotation(annotation, option)
        if parameter.name not in help_text:
            raise ValueError(
                f"command '{function.__name__}' is missing ':param {parameter.name}:' in its docstring"
            )
        described.append(
            CliParameter(
                name=parameter.name,
                annotation=kind,
                has_default=parameter.default is not inspect.Parameter.empty,
                default=None if parameter.default is inspect.Parameter.empty else parameter.default,
                help_text=help_text[parameter.name],
                flag=parameter.name if option.positional else "--" + parameter.name.replace("_", "-"),
                choices=choices,
                multiple=multiple,
                positional=option.positional,
                short=option.short,
            )
        )
    return described


def placement(function: Callable[..., Any], name: str | None) -> tuple[str, str]:
    """Work out a command's group and subcommand from the module it lives in.

    :param function: the decorated command function
    :param name: an explicit subcommand name, or None to use the module's own name
    :return: the group word and the subcommand word
    :raises ValueError: when the module is not under the commands package
    """
    parts = function.__module__.split(".")
    if len(parts) < 4 or ".".join(parts[:2]) != COMMANDS_PACKAGE:
        raise ValueError(
            f"command '{function.__name__}' must live in {COMMANDS_PACKAGE}/<group>/<name>.py, "
            f"not in {function.__module__}"
        )
    group = parts[2]
    module_name = parts[3].rstrip("_").replace("_", "-")
    return group, (name or module_name)


def cli_command(function: Callable[..., int | None] | None = None, *, name: str | None = None):
    """Register a function as an ``ixd`` command.

    :param function: the command, when the decorator is used without parentheses
    :param name: the subcommand word, defaulting to the module's file name
    :return: the decorator, or the function it registered
    """

    def decorate(wrapped: Callable[..., int | None]) -> Callable[..., int | None]:
        summary, detail, help_text = parse_docstring(wrapped)
        group, command_name = placement(wrapped, name)
        if (group, command_name) in _REGISTRY:
            raise ValueError(f"command 'ixd {group} {command_name}' is already registered")
        _REGISTRY[(group, command_name)] = CliCommand(
            group=group,
            name=command_name,
            function=wrapped,
            summary=summary,
            detail=detail,
            params=describe_parameters(wrapped, help_text),
            module=wrapped.__module__,
        )
        return wrapped

    return decorate(function) if function is not None else decorate


def get_registry() -> dict[tuple[str, str], CliCommand]:
    """Return every command, importing the command package the first time it is asked for.

    :return: a copy of the registry keyed by (group, name)
    """
    global _IMPORTED
    if not _IMPORTED:
        _IMPORTED = True
        importlib.import_module(COMMANDS_PACKAGE).import_all_commands()
    return dict(_REGISTRY)


def groups() -> dict[str, list[CliCommand]]:
    """Return the commands of each group, sorted by name.

    :return: group word to its commands
    """
    found: dict[str, list[CliCommand]] = {}
    for command in get_registry().values():
        found.setdefault(command.group, []).append(command)
    return {group: sorted(commands, key=lambda one: one.name) for group, commands in sorted(found.items())}
