from __future__ import annotations

"""
Test fragments handling.

Test drivers can split the execution of their test in multiple test fragments.
Each fragment is an atomic task, which can be dispatched to a separate worker.
"""

import abc
import argparse
from dataclasses import dataclass
import pickle
import sys
import tempfile
import traceback
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    TYPE_CHECKING,
    Type,
)

import e3.env
from e3.fs import rm
import e3.job
from e3.os.process import DEVNULL, PIPE, Run, STDOUT
from e3.testsuite.driver import ResultQueue, TestDriver
import e3.testsuite.multiprocess_scheduler
from e3.testsuite.result import TestResult, TestStatus


if TYPE_CHECKING:
    from e3.testsuite.running_status import RunningStatus


class FragmentCallback(Protocol):
    def __call__(self, previous_values: Dict[str, Any], slot: int) -> None:
        ...


@dataclass
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

    callback_by_name: bool
    """Whether ``callback`` is just the ``name`` method of ``driver``."""

    def matches(self, driver_cls: Type[TestDriver], name: str) -> bool:
        """Return whether this fragment matches the given name/test driver.

        If ``name`` is left to None, just check the driver type.
        """
        return isinstance(self.driver, driver_cls) and (
            name is None or self.name == name
        )

    def clear_driver_data(self) -> None:
        """Remove references to ``TestDriver`` instances and related data.

        Doing this is necessary after each fragment is complete to keep memory
        consumption under control for big testsuites: test driver instances may
        contain a lot of data.
        """
        joker: Any = None
        self.driver = joker
        self.callback = joker


class TestFragment:
    """Base class for testcase scheduling units."""

    uid: str
    """Unique string identifier for this test fragment."""

    index: int
    """Unique integer identifier for this test fragment."""

    driver: TestDriver
    """Test driver that is responsible for this test fragment."""

    running_status: RunningStatus
    """RunningStatus instance to signal when job starts/completes."""

    result_queue: ResultQueue
    """
    List of test results that this fragments plans to integrate to the
    testsuite report.
    """

    @staticmethod
    def static_push_error_result(
        uid: str, index: int, driver: TestDriver
    ) -> None:
        """Generate a test result to log the exception and traceback.

        This helper method is meant to be used when the execution of the test
        fragments aborts because of an uncaught exception. We must report a
        test error, and we provide exception information for post-mortem
        investigation.

        :param uid: UID for the test fragment.
        :param index: Index for the test fragment.
        :param driver: TestDriver for the test fragment.
        """
        # The name is based on the test fragment name with an additional random
        # part to avoid conflicts at the testsuite report level.
        result = TestResult(
            "{}__except{}".format(uid, index),
            env=driver.test_env,
            status=TestStatus.ERROR,
        )
        result.log += traceback.format_exc()
        driver.push_result(result)

    def push_error_result(self, exc: Exception) -> None:
        """Shortcut for static_push_error_result on the current fragment."""
        self.static_push_error_result(self.uid, self.index, self.driver)

    @abc.abstractmethod
    def clear_driver_data(self) -> None:
        """Remove references to ``TestDriver`` instances and related data.

        Doing this is necessary after each fragment is complete to keep memory
        consumption under control for big testsuites: test driver instances may
        contain a lot of data.
        """
        pass


class ThreadTestFragment(e3.job.Job, TestFragment):
    """Run a test fragment in a thread."""

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
        :param running_status: See BaseTestFragment.running_status.
        """
        super().__init__(uid, callback, notify_end)
        self.driver = driver
        self.previous_values = previous_values
        self.running_status = running_status
        self.result_queue: ResultQueue = driver.result_queue

    def clear_driver_data(self) -> None:
        joker: Any = None
        self.data = joker
        self.driver = joker

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


class ProcessTestFragment(
    e3.testsuite.multiprocess_scheduler.Worker, TestFragment
):
    """Run a test fragment in a separate process."""

    @dataclass(frozen=True)
    class Input:
        """Subprocess input data."""

        fragment_uid: str
        fragment_index: int

        driver_cls: Type[TestDriver]
        test_env: Dict[str, Any]
        callback_name: str
        slot: int

    @dataclass(frozen=True)
    class Output:
        """Subprocess output data."""

        result_queue: ResultQueue

    exchange_file: str
    """Name of the file to exchange data with the subprocess."""

    def __init__(
        self,
        uid: str,
        driver: TestDriver,
        callback_name: str,
        slot: int,
        running_status: RunningStatus,
        env: e3.env.Env,
    ):
        """Initialize a ProcessTestFragment.

        :param uid: UID of the test fragment (should be unique).
        :param driver: A TestDriver instance.
        :param callback_name: Name of the `driver` method to be executed by the
            job.
        :param slot: Slot ID allocated for the execution of this test fragment.
        :param running_status: See BaseTestFragment.running_status.
        :param env: Testsuite environment.
        """
        self.running_status = running_status
        self.result_queue = []
        super().__init__(uid, driver, callback_name, slot, env)

    def clear_driver_data(self) -> None:
        joker: Any = None
        self.driver = joker

    def start(self) -> Run:
        self.running_status.start(self)

        # Create the exchange file: write the test environment to it
        worker_input = self.Input(
            self.uid,
            self.index,
            type(self.driver),
            self.driver.test_env,
            self.callback_name,
            self.slot,
        )
        with tempfile.NamedTemporaryFile(
            prefix=self.uid + "-",
            dir=self.env.exchange_dir,
            delete=False,
        ) as f:
            self.exchange_file = f.name
            pickle.dump(worker_input, f)

        # Run the worker process, checking that it runs to completion
        # successfully.
        return Run(
            cmds=[
                "e3-run-test-fragment",
                self.env.env_filename,
                f.name,
            ],
            output=PIPE,
            error=STDOUT,
            input=DEVNULL,
            bg=True,
        )

    def collect_result(self) -> None:
        # Let extract_result_queue put results in the driver's result queue,
        # then forward them to this fragment's.
        self.driver.result_queue = []
        self.extract_result_queue()
        self.result_queue = self.driver.result_queue

        # Now cleanup temporary files and declare this fragment as completed
        rm(self.exchange_file)
        self.running_status.complete(self)

    def extract_result_queue(self) -> None:
        """Read the result queue from the exchange file.

        Try to extract the result queue from the exchange file and put results
        in the driver's result queue. If anything goes sour, create an error
        result in the same result queue.
        """
        # Make sure the process exitted with no error
        if self.process.status != 0:
            result = TestResult(
                f"{self.uid}__internalerror",
                env=self.driver.test_env,
                status=TestStatus.ERROR,
                msg="Worker process stopped with an error",
            )
            assert self.process.out is not None
            result.log += self.process.out
            self.driver.push_result(result)
            return

        # Now read the output from the exchange file. If there is anything
        # unexpected, give up decoding the actual results and create an error
        # result instead.
        try:
            with open(self.exchange_file, "rb") as f:
                output = pickle.load(f)
                assert isinstance(output, self.Output)
        except Exception as e:
            self.push_error_result(e)
            return

        self.driver.result_queue.extend(output.result_queue)


# TODO: Investigate why the pytest-cov plugin fails to track coverage in the
# following function (it is supposed to handle subprocesses).


def run_fragment(argv: Optional[List[str]] = None) -> None:  # no cover
    """Run a test fragment.

    This function is meant to be the entry point of a standalone script, to run
    a fragment in a subprocess, separate from the main testsuite process.
    """
    from e3.testsuite import TestAbort

    args_parser = argparse.ArgumentParser(
        description="Internal script for e3-testsuite to run a test fragment"
        " in a subprocess."
    )
    args_parser.add_argument(
        "env-filename", help="Name of the file to load with e3.env.Env.restore"
    )
    args_parser.add_argument(
        "exchange-file",
        help="Name of the file that contains test driver data and in which to"
        " write test results.",
    )
    args = args_parser.parse_args(argv)
    env_filename = getattr(args, "env-filename")
    exchange_file = getattr(args, "exchange-file")

    # Load the testsuite environment
    env = e3.env.Env()
    env.restore(env_filename)

    # Give access to modules that the testsuite main has access to
    sys.path = env.modules_search_path + sys.path

    # Load data needed to run the test fragment
    with open(exchange_file, "rb") as f:
        worker_input = pickle.load(f)
        assert isinstance(worker_input, ProcessTestFragment.Input)

    # Run the test fragment, silently ignoring TestAbort exceptions
    driver = worker_input.driver_cls(env, worker_input.test_env)
    callback = getattr(driver, worker_input.callback_name)
    try:
        callback(prev={}, slot=worker_input.slot)
    except TestAbort:
        pass
    except Exception:
        TestFragment.static_push_error_result(
            worker_input.fragment_uid,
            worker_input.fragment_index,
            driver,
        )

    # Forward test results to the testsuite
    worker_output = ProcessTestFragment.Output(driver.result_queue)
    with open(exchange_file, "wb") as f:
        pickle.dump(worker_output, f)
