from __future__ import absolute_import, division, print_function

import abc

from e3.testsuite.result import TestResult


class TestDriver(object):
    """Testsuite Driver.

    All drivers declared in a testsuite should inherit from this class
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self, env, test_env):
        """Initialize a TestDriver instance.

        :param env: the testsuite environment
        :type env: dict
        :param test_env: the test env dictionary. One entry called
            test_name is at least expected.
        :type test_env: dict
        """
        self.env = env
        self.test_env = test_env
        self.test_name = test_env['test_name']

        # Initialize test result
        self.result = TestResult(name=self.test_name,
                                 env=self.test_env)

        # Queue used to push result to the testsuite
        self.result_queue = []

    def push_result(self, result=None):
        """Push a result to the testsuite.

        This method should be called to push results to the testsuite report.

        :param result: a TestResult object to push. If None push
            the current test result
        :type result: TestResult | None
        """
        if result is None:
            result = self.result
        self.result_queue.append(result)

    def add_fragment(self, dag, name, fun=None, after=None):
        """Add a test fragment.

        This function is a helper to define test workflows that do not
        introduce dependencies to other tests. For more complex operation
        use directly add_vertex method from the dag. See add_test method

        :param dag: a DAG containing test fragments
        :type dag: e3.collection.dag.DAG
        :param name: name of the fragment
        :type name: str
        :param fun: a callable that takes no parameters. If None looks
            for a method inside this class called ``name``.
        :type fun: (, ) -> None | None
        :param after: list of fragment names that should be executed before
        :type after: list[str] | None
        """
        if after is not None:
            after = [self.test_name + '.' + k for k in after]

        if fun is None:
            fun = getattr(self, name)

        dag.add_vertex(self.test_name + '.' + name,
                       (self, fun),
                       predecessors=after)

    @abc.abstractmethod
    def add_test(self, dag):
        """Create the test workflow.

        Amend a DAG with the test fragments that should be executed along with
        their dependencies. See BasicTestDriver for an example of workflow.

        :param dag: the DAG to amend
        :type dag: e3.collection.dag.DAG
        """
        pass


class BasicTestDriver(TestDriver):

    __metaclass__ = abc.ABCMeta

    def add_test(self, dag):
        """Create a standard test workflow.

        set up -> run -> analyze -> tear_down in which set up and tear_down
        are optional.

        :param dag: the DAG to amend
        :type dag: e3.collection.dag.DAG
        """
        self.add_fragment(dag, 'set_up')
        self.add_fragment(dag, 'run', after=['set_up'])
        self.add_fragment(dag, 'analyze', after=['run'])
        self.add_fragment(dag, 'tear_down', after=['analyze'])

    def set_up(self, prev):
        """Execute operations before executing a test."""
        return self.tear_up(prev)

    def tear_up(self, prev):
        """Backwards-compatible name for the "set_up" method."""
        pass

    def tear_down(self, prev):
        """Execute operations once a test is finished."""
        pass

    @abc.abstractmethod
    def run(self, prev):
        """Execute a test."""
        pass

    @abc.abstractmethod
    def analyze(self, prev):
        """Compute the test result."""
        pass
