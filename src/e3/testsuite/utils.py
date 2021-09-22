"""Miscellaneous helpers."""

from __future__ import annotations

from enum import Enum, auto
import sys
from typing import AnyStr, Dict, IO, Optional, Type, TypeVar


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

        self.Fore = Fore
        self.Style = Style

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
    return {
        value.name.lower().replace("_", "-"): value
        for value in enum_cls
    }
