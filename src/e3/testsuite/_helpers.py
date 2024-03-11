"""Internal helpers for e3.testsuite."""

import warnings
from typing import Any, Callable, List, TypeVar, cast


F = TypeVar("F", bound=Callable[..., Any])


def deprecated(stacklevel: int = 1) -> Callable[[F], F]:
    """
    Return a decorator to emit deprecation warnings.

    The function that the decorator returns emits the deprecation warning only
    the first time it is called.
    """

    def deprecated(func: F) -> F:
        triggered: List[bool] = []

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not triggered:
                triggered.append(True)
                warnings.warn(
                    "This function is obsolete and will be removed in the"
                    " future",
                    DeprecationWarning,
                    stacklevel=stacklevel + 1,
                )
            return func(*args, **kwargs)

        return cast(F, wrapper)

    return deprecated
