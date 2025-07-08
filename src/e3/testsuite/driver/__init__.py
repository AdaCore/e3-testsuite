from __future__ import annotations

import abc
import argparse
from dataclasses import dataclass
import os.path
import traceback
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import e3.collection.dag
import e3.env

from e3.testsuite.report.gaia import (
    GAIAResultFiles,
    dump_result_logs_if_needed,
)
from e3.testsuite.result import TestResult, TestResultSummary
from e3.testsuite.utils import CleanupMode

if TYPE_CHECKING:
    from e3.testsuite.fragment import FragmentCallback


@dataclass(frozen=True)
class ResultQueueItem:
    """Information to integrate a test result in a testsuite report.

    Test drivers create test results. They travel from there to the testsuite
    final report through various queues. This class gathers all the information
    needed for the various stages of this pipeline.
    """

    test_name: str
    """Name of the test that created this test result."""

    result: TestResultSummary
    """Summary for this test result."""

    filename: str
    """Name of the file that contains test result data."""

    traceback: List[str]
    """Stack trace for this result's push time.

    This stack trace corresponds to the code that led the TestResult instance
    to be included in the testsuite report.
    """

    gaia_results: Optional[GAIAResultFiles]
    """GAIA files for this result.

    This is None if no GAIA report is requested.
    """


ResultQueue = List[ResultQueueItem]


class TestDriver(object, metaclass=abc.ABCMeta):
    """Testsuite Driver.

    All drivers declared in a testsuite should inherit from this class
    """

    Fore: Any
    Style: Any

    test_env_filename: str

    def __init__(self, env: e3.env.Env, test_env: Dict[str, Any]) -> None:
        """Initialize a TestDriver instance.

        :param env: The testsuite environment. This mirrors the
            ``Testsuite.env`` attribute.
        :param test_env: The testcase environment. By the time it is passed to
            this constructor, a TestFinder subclass has populated it, and the
            testsuite added the following entries:

            * ``test_dir``: The absolute name of the directory that contains
              the testcase.
            * ``test_name``: The name that the testsuite assigned to this
              testcase.
            * ``working_dir``: The absolute name of the temporary directory
              that this test driver is free to create (if needed) in order to
              run the testcase.
        """
        self.env: e3.env.Env = env
        assert isinstance(env.options, argparse.Namespace)
        self.testsuite_options: argparse.Namespace = env.options

        self.test_env: Dict[str, Any] = test_env
        self.test_name: str = test_env["test_name"]

        # Initialize test result
        self.result: TestResult = TestResult(
            name=self.test_name, env=self.test_env
        )

        self.result_queue: ResultQueue = []
        """
        Queue of test results that this driver plans to integrate to the
        testsuite report.
        """

        self.execution_started: bool = False
        """
        Whether the execution of at least one fragment for this test driver has
        started.
        """

        self.pending_fragments: set[str] = set()
        """
        Set of UIDs for fragments whose execution has not yet completed for
        this test driver.
        """

    def push_result(self, result: Optional[TestResult] = None) -> None:
        """Push a result to the testsuite.

        This method should be called to push results to the testsuite report.

        :param result: A TestResult object to push. If None push the current
            test result.
        """
        if result is None:
            result = self.result

        # Write the result as a new file in the output directory and let the
        # testsuite main know about this result.
        output_dir = self.env.output_dir
        assert isinstance(output_dir, str)

        self.result_queue.append(
            ResultQueueItem(
                self.test_name,
                result.summary,
                result.save(self.env.output_dir),
                traceback.format_stack(),
                dump_result_logs_if_needed(self.env, result, output_dir),
            )
        )

    def add_fragment(
        self,
        dag: e3.collection.dag.DAG,
        name: str,
        fun: Optional[FragmentCallback] = None,
        after: Optional[List[str]] = None,
    ) -> None:
        """Add a test fragment.

        This function is a helper to define test workflows that do not
        introduce dependencies to other tests. For more complex operation use
        directly add_vertex method from the dag. See add_test method.

        :param dag: DAG containing test fragments.
        :param name: Name of the fragment.
        :param fun: Callable that takes two positional arguments: a mapping
            from fragment names to return values for already executed
            fragments, and a slot ID. If None looks for a method inside this
            class called ``name``.
        :param after: List of fragment names that should be executed before
            this one.
        """
        from e3.testsuite.fragment import FragmentData

        callback_by_name = False

        if after is not None:
            after = [self.test_name + "." + k for k in after]

        if fun is None:
            fun = getattr(self, name)
            callback_by_name = True

        fragment = FragmentData(
            uid=f"{self.test_name}.{name}",
            driver=self,
            name=name,
            callback=fun,
            callback_by_name=callback_by_name,
        )

        self.pending_fragments.add(fragment.uid)
        dag.update_vertex(
            vertex_id=fragment.uid,
            data=fragment,
            predecessors=after,
            enable_checks=False,
        )

    def working_dir(self, *args: str) -> str:
        """Build a filename in the test working directory."""
        return os.path.join(self.test_env["working_dir"], *args)

    def test_dir(self, *args: str) -> str:
        """Build a filename in the testcase directory."""
        return os.path.join(self.test_env["test_dir"], *args)

    @abc.abstractmethod
    def add_test(self, dag: e3.collection.dag.DAG) -> None:
        """Create the test workflow.

        Amend a DAG with the test fragments that should be executed along with
        their dependencies. See BasicTestDriver for an example of workflow.
        """
        raise NotImplementedError

    @property
    def working_dir_cleanup_enabled(self) -> bool:
        """
        Return whether test drivers should cleanup their working directory.

        Unless this returns False, test drivers should delete their working
        directory when the test has completed, so that temporaries for the
        whole testsuite are removed incrementally. This is necessary to avoid
        creating huge temporary directories when executing big testsuites.
        """
        return self.env.cleanup_mode != CleanupMode.NONE


class BasicTestDriver(TestDriver, metaclass=abc.ABCMeta):
    def add_test(self, dag: e3.collection.dag.DAG) -> None:
        """Create a standard test workflow.

        set up -> run -> analyze -> tear_down in which set up and tear_down
        are optional.
        """
        self.add_fragment(dag, "set_up")
        self.add_fragment(dag, "run", after=["set_up"])
        self.add_fragment(dag, "analyze", after=["run"])
        self.add_fragment(dag, "tear_down", after=["analyze"])

    def set_up(self, prev: Dict[str, Any], slot: int) -> None:
        """Execute operations before executing a test."""
        return self.tear_up(prev, slot)

    def tear_up(self, prev: Dict[str, Any], slot: int) -> None:
        """Backwards-compatible name for the "set_up" method."""
        pass

    def tear_down(self, prev: Dict[str, Any], slot: int) -> None:
        """Execute operations once a test is finished."""
        pass

    @abc.abstractmethod
    def run(self, prev: Dict[str, Any], slot: int) -> None:
        """Execute a test."""
        raise NotImplementedError

    @abc.abstractmethod
    def analyze(self, prev: Dict[str, Any], slot: int) -> None:
        """Compute the test result."""
        raise NotImplementedError
