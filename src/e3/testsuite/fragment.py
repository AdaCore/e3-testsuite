from __future__ import annotations

"""
Test fragments handling.

Test drivers can split the execution of their test in multiple test fragments.
Each fragment is an atomic task, which can be dispatched to a separate worker.
"""

from dataclasses import dataclass
import traceback
from typing import (
    Any,
    Callable,
    Dict,
    Protocol,
    TYPE_CHECKING,
    Type,
)

from e3.job import Job
from e3.testsuite.driver import TestDriver
from e3.testsuite.result import TestResult, TestStatus


if TYPE_CHECKING:
    from e3.testsuite.running_status import RunningStatus
    from e3.testsuite.result import ResultQueue


class FragmentCallback(Protocol):
    def __call__(self, previous_values: Dict[str, Any], slot: int) -> None:
        ...


@dataclass(frozen=True)
class FragmentData:
    """Data for a job unit in the testsuite.

    Each ``FragmentData`` instance is recorded in the testsuite global DAG to
    control the order of execution of all fragments with the requested level of
    parallelism.

    Note that the job scheduler turns ``FragmentData`` instances into
    ``TestFragment`` ones during the execution (see ``Testsuite.job_factory``
    callback).
    """

    uid: str
    driver: TestDriver
    name: str
    callback: FragmentCallback

    def matches(self, driver_cls: Type[TestDriver], name: str) -> bool:
        """Return whether this fragment matches the given name/test driver.

        If ``name`` is left to None, just check the driver type.
        """
        return isinstance(self.driver, driver_cls) and (
            name is None or self.name == name
        )


class TestFragment(Job):
    """Job used in a testsuite.

    :ivar driver: A TestDriver instance.
    """

    def __init__(
        self,
        uid: str,
        driver: TestDriver,
        callback: FragmentCallback,
        previous_values: Dict[str, Any],
        notify_end: Callable[[str], None],
        running_status: RunningStatus,
    ) -> None:
        """Initialize a TestFragment.

        :param uid: UID of the test fragment (should be unique).
        :param driver: A TestDriver instance.
        :param callback: Callable to be executed by the job.
        :param notify_end: Internal parameter. See e3.job.
        :param running_status: RunningStatus instance to signal when job
            starts/completes.
        """
        super().__init__(uid, callback, notify_end)
        self.driver = driver
        self.previous_values = previous_values
        self.running_status = running_status

        self.result_queue: ResultQueue = driver.result_queue
        """
        List of test results that this fragments plans to integrate to the
        testsuite report.
        """

    def push_error_result(self, exc: Exception) -> None:
        """Generate a test result to log the exception and traceback.

        This helper method is meant to be used when the execution of the test
        fragments aborts because of an uncaught exception. We must report a
        test error, and we provide exception information for post-mortem
        investigation.
        """
        # The name is based on the test fragment name with an additional random
        # part to avoid conflicts at the testsuite report level.
        result = TestResult(
            "{}__except{}".format(self.uid, self.index),
            env=self.driver.test_env,
            status=TestStatus.ERROR,
        )
        result.log += traceback.format_exc()
        self.driver.push_result(result)

    def run(self) -> None:
        """Run the test fragment."""
        from e3.testsuite import TestAbort

        self.running_status.start(self)
        self.return_value = None
        try:
            self.return_value = self.data(self.previous_values, self.slot)
        except TestAbort:
            pass
        except Exception as e:
            self.push_error_result(e)
            self.return_value = e
        self.running_status.complete(self)
