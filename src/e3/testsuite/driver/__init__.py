from __future__ import annotations

import abc
import os.path
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import e3.collection.dag
import e3.env

from e3.testsuite.result import TestResult


class TestDriver(object, metaclass=abc.ABCMeta):
    """Testsuite Driver.

    All drivers declared in a testsuite should inherit from this class
    """

    def __init__(self, env: e3.env.BaseEnv, test_env: dict) -> None:
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
        self.env = env
        self.test_env = test_env
        self.test_name = test_env["test_name"]

        # Initialize test result
        self.result = TestResult(name=self.test_name, env=self.test_env)

        # Queue used to push result to the testsuite. Each queue item is a
        # couple that contains the TestResult instance and a string traceback
        # corresponding to the chain of call that pushed that result. This
        # traceback is useful to debug test drivers that push twice results.
        self.result_queue: List[Tuple[TestResult, List[str]]] = []

    def push_result(self, result: Optional[TestResult] = None) -> None:
        """Push a result to the testsuite.

        This method should be called to push results to the testsuite report.

        :param result: A TestResult object to push. If None push the current
            test result.
        """
        if result is None:
            result = self.result
        self.result_queue.append((result, traceback.format_stack()))

    def add_fragment(
        self,
        dag: e3.collection.dag.DAG,
        name: str,
        fun: Optional[Callable[[Dict[str, Any], int], None]] = None,
        after: Optional[List[str]] = None
    ) -> None:
        """Add a test fragment.

        This function is a helper to define test workflows that do not
        introduce dependencies to other tests. For more complex operation
        use directly add_vertex method from the dag. See add_test method

        :param dag: DAG containing test fragments.
        :param name: Name of the fragment.
        :param fun: Callable that takes two positional arguments: a mapping
            from fragment names to return values for already executed
            fragments, and a slot ID. If None looks for a method inside this
            class called ``name``.
        :param after: List of fragment names that should be executed before
            this one.
        """
        if after is not None:
            after = [self.test_name + "." + k for k in after]

        if fun is None:
            fun = getattr(self, name)

        dag.update_vertex(
            vertex_id=self.test_name + "." + name,
            data=(self, fun),
            predecessors=after,
            enable_checks=False
        )

    def working_dir(self, *args: str) -> str:
        """Build a filename in the test working directory."""
        return os.path.join(self.test_env['working_dir'], *args)

    def test_dir(self, *args: str) -> str:
        """Build a filename in the testcase directory."""
        return os.path.join(self.test_env['test_dir'], *args)

    @abc.abstractmethod
    def add_test(self, dag: e3.collection.dag.DAG) -> None:
        """Create the test workflow.

        Amend a DAG with the test fragments that should be executed along with
        their dependencies. See BasicTestDriver for an example of workflow.
        """
        raise NotImplementedError


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
