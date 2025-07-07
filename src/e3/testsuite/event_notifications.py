from __future__ import annotations

"""
External notifications for events that occur during testsuite execution.

Each time a tracked event occurs during the testsuite execution (see the
``TestNotification`` subclasses below for the kinds of events that are
tracked), a user-provided command is executed with arguments that give details
about the event that occurred.
"""

import abc
import dataclasses
import importlib
import logging
import re
import shlex
import subprocess
from typing import Callable, TYPE_CHECKING

from e3.testsuite.result import TestResultSummary

if TYPE_CHECKING:
    from e3.testsuite import TestsuiteCore


logger = logging.getLogger("testsuite")


@dataclasses.dataclass(frozen=True)
class TestNotification:
    """Notification for a given test."""

    test_name: str
    """
    Name of the test that this notification refers to.
    """

    @abc.abstractmethod
    def to_args(self) -> list[str]:
        raise NotImplementedError


@dataclasses.dataclass(frozen=True)
class TestQueueNotification(TestNotification):
    """Notification to signal that a test was queued."""

    def to_args(self) -> list[str]:
        return ["--queue", self.test_name]


@dataclasses.dataclass(frozen=True)
class TestStartNotification(TestNotification):
    """Notification to signal that the execution of a test has just started."""

    def to_args(self) -> list[str]:
        return ["--start", self.test_name]


@dataclasses.dataclass(frozen=True)
class TestResultNotification(TestNotification):
    """Notification to signal the addition of a new test result."""

    result: TestResultSummary
    """Summary for the added test result."""

    yaml_result_filename: str
    """Absolute filename for the YAML file that stores the test result.

    This YAML file must be loaded through the ``TestResult.load`` static
    method.
    """

    def to_args(self) -> list[str]:
        return ["--result", self.test_name, self.yaml_result_filename]


@dataclasses.dataclass(frozen=True)
class TestEndNotification(TestNotification):
    """Notification to signal that the execution of a test has just ended."""

    def to_args(self) -> list[str]:
        return ["--end", self.test_name]


class InvalidNotifyCommand(Exception):
    pass


class EventNotifier:
    """Abstraction to send notifications."""

    python_cmd_re = re.compile(
        r"(?P<module>[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*)"
        r":"
        r"(?P<callback>[a-zA-Z_][a-zA-Z0-9_]*)"
    )

    def __init__(self, testsuite: TestsuiteCore, notify_cmd: str | None):
        """Initialize an EventNotifier.

        :param testsuite: Testsuite instance for which this event notifier is
            created.
        :param notify_cmd: Base command line arguments for the notification
            command. Notification specifics are added as extra arguments for
            each notification that is sent. If ``None``, notifications are
            discarded.

        This raises an `InvalidNotifyCommand` if `notify_cmd` cannot be
        decoded/loaded.
        """
        self.notify_callback: Callable[[TestNotification], None] | None = None
        self.notify_cmd: list[str] | None = None
        self._parse_notify_cmd(testsuite, notify_cmd)

    def _parse_notify_cmd(
        self,
        testsuite: TestsuiteCore,
        cmd: str | None,
    ) -> None:
        """Decode the given notify command."""
        if cmd is None:
            return

        python_prefix = "python:"
        if cmd.startswith(python_prefix):
            m = self.python_cmd_re.match(cmd[len(python_prefix) :])
            if not m:
                logger.exception(f"Wrong format: {cmd!r}")
                raise InvalidNotifyCommand()

            module_name = m.group("module")
            callback_name = m.group("callback")

            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                logger.exception(f"Cannot load module {module_name!r}")
                raise InvalidNotifyCommand from exc

            try:
                callback = getattr(module, callback_name)
            except AttributeError as exc:
                logger.exception(f"Cannot load callback {callback_name!r}")
                raise InvalidNotifyCommand from exc

            try:
                self.notify_callback = callback(testsuite)
            except Exception as exc:
                logger.exception("Cannot create notification callback")
                raise InvalidNotifyCommand from exc
            return

        self.notify_cmd = shlex.split(cmd)

    def notify(self, notification: TestNotification) -> None:
        """Send a given notification."""
        if self.notify_callback is not None:
            try:
                self.notify_callback(notification)
            except Exception:
                logger.exception(
                    "Error while executing the event notification callback"
                )
        elif self.notify_cmd is not None:
            try:
                subprocess.check_call(
                    self.notify_cmd + notification.to_args(),
                    stdin=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                logger.exception(
                    "Error while running the event notification command"
                )

    def notify_test_queue(self, test_name: str) -> None:
        self.notify(TestQueueNotification(test_name))

    def notify_test_start(self, test_name: str) -> None:
        self.notify(TestStartNotification(test_name))

    def notify_test_result(
        self,
        test_name: str,
        result: TestResultSummary,
        yaml_result_filename: str,
    ) -> None:
        self.notify(
            TestResultNotification(test_name, result, yaml_result_filename)
        )

    def notify_test_end(self, test_name: str) -> None:
        self.notify(TestEndNotification(test_name))
