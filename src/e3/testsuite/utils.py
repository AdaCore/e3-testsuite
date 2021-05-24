"""Miscellaneous helpers."""

import sys
from typing import AnyStr, IO, Optional


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
