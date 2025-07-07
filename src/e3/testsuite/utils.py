"""Miscellaneous helpers."""

from __future__ import annotations

from enum import Enum, auto
import os
import sys
from typing import (
    AnyStr,
    Dict,
    IO,
    Iterator,
    Optional,
    Type,
    TypeVar,
    TYPE_CHECKING,
)

from e3.os.fs import unixpath
from e3.os.process import quote_arg

if TYPE_CHECKING:
    from e3.env import Env

    import colorama


def isatty(stream: IO[AnyStr]) -> bool:
    """Return whether stream is a TTY.

    This is a safe predicate: it works if stream is None or if it does not even
    support TTY detection: in these cases, be conservative (consider it's not a
    TTY).
    """
    return bool(stream) and hasattr(stream, "isatty") and stream.isatty()


class DummyColors:
    """Stub to replace colorama's Fore/Style when colors are disabled."""

    def __getattr__(self, name: str) -> str:
        return ""


class ColorConfig:
    """Proxy for color management.

    This embeds colorama's Fore/Style, or DummyColors instances when colors are
    disabled.
    """

    def __init__(self, colors_enabled: Optional[bool] = None):
        """
        Initialize a ColorConfig instance.

        :param colors: Whether to enable colors. If left to None, enable it iff
            the standard output is a TTY.
        """
        from colorama import Fore, Style

        self.Fore: colorama.ansi.AnsiFore | DummyColors = Fore
        self.Style: colorama.ansi.AnsiStyle | DummyColors = Style

        if colors_enabled is None:
            colors_enabled = isatty(sys.stdout)

        if not colors_enabled:
            self.Fore = DummyColors()
            self.Style = DummyColors()


class CleanupMode(Enum):
    """Mode for working space cleanups."""

    NONE = auto()
    PASSING = auto()
    ALL = auto()

    @classmethod
    def default(cls) -> CleanupMode:
        return cls.PASSING

    @classmethod
    def descriptions(cls) -> Dict[CleanupMode, str]:
        return {
            cls.NONE: "Remove nothing.",
            cls.PASSING: "Remove only working spaces for passing tests"
            " (useful for post-mortem investigation with reasonable disk"
            " usage). This is the default.",
            cls.ALL: "Remove all working spaces.",
        }


EnumType = TypeVar("EnumType", bound=Enum)


def enum_to_cmdline_args_map(enum_cls: Type[EnumType]) -> Dict[str, EnumType]:
    """Turn enum alternatives into command-line arguments.

    This helps exposing enums for options on the command-line. This turns
    alternative names into lower case and replaces underscores with dashes.
    """
    return {value.name.lower().replace("_", "-"): value for value in enum_cls}


def dump_environ(filename: str, env: Env) -> None:
    """Dump environment variables into a sourceable file."""
    with open(os.path.join(filename), "w") as f:
        for var_name in sorted(os.environ):
            if (
                # Ignore environment variables whose names will make
                # the "export" commands invalid. Such variables (for
                # instance PROGRAMFILES(X86) on Windows systems) are
                # generally set system-wide, so capturing them here is
                # not useful.
                "(" in var_name
                # Also ignore variables known to be readonly on Cygwin
                # systems. Other users are unlikely to be affected.
                or var_name in ("PROFILEREAD", "SHELLOPTS")
            ):  # all: no cover
                continue

            var_value = os.environ[var_name]

            # For Cygwin tools, turn Windows-style dirnames to
            # Unix-style ones for PATH.
            if (
                var_name == "PATH"
                and env.build.os.name == "windows"
                and os.path.pathsep in var_value
            ):  # windows-only
                var_value = ":".join(
                    unixpath(p) for p in var_value.split(os.path.pathsep)
                )

            f.write(f"export {var_name}={quote_arg(var_value)}\n")


def indent(text: str, prefix: str = "  ") -> str:
    """Prepend ``prefix`` to every line in ``text``.

    :param text: Text to transform.
    :param prefix: String to prepend.
    """
    # Use .split() rather than .splitlines() because we need to preserve the
    # last line if is empty. "a\n".splitlines() returns ["a"], so we must avoid
    # it.
    return "\n".join((prefix + line) for line in text.split("\n"))


def safe_dir_walk(top: str) -> Iterator[tuple[str, list[str], list[str]]]:
    """Traverse a directory hierarchy following symlinks in a safe way.

    This is essentially a wrapper around os.walk() to safely follow symbolic
    links that keeps track of the directories traversed to avoid infinite
    recursion in case of symbolic link loops.
    """
    # Set of realpaths (os.path.realpath) for already visited directories
    visited: set[str] = set()

    def already_visited(f: str) -> bool:
        """Return whether we already visited a directory.

        If ``f`` designates an already visited directory, return False.
        Otherwise, keep track of it as a visited directory and return True.
        """
        f = os.path.realpath(f)
        if f in visited:
            return True
        else:
            visited.add(f)
            return False

    def recurse(top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Recursive wrapper around os.walk()."""
        if already_visited(top):
            return
        for dirpath, dirnames, filenames in os.walk(top):
            yield dirpath, dirnames, filenames

            # For directorise that are actually symlinks, recurse to traverse
            # them too.
            for d in dirnames:
                d = os.path.join(dirpath, d)
                if os.path.islink(d):
                    yield from recurse(d)

    yield from recurse(top)
