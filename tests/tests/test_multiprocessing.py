"""Tests for the multiprocessing scheduler for test fragments."""

import sys

from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.result import TestStatus as Status

from .utils import create_testsuite, extract_results, run_testsuite


class TestEnable:
    """Test that automatic enabling of multiprocessing works as expected."""

    ENABLED_MSG = "multiprocessing enabled"
    DISABLED_MSG = "multiprocessing disabled"

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(
                Status.PASS,
                TestEnable.ENABLED_MSG
                if self.env.use_multiprocessing
                else TestEnable.DISABLED_MSG,
            )
            self.push_result()

    def run_testsuite(self, enable_expected, args=None, supported=None):
        """Run a testsuite with a single test with MyDriver."""
        MySuite = create_testsuite(["single_test"], TestEnable.MyDriver)
        if supported is not None:
            MySuite.multiprocessing_supported = supported

        suite = run_testsuite(MySuite, args=args)
        assert len(suite.report_index.entries) == 1
        result = suite.report_index.entries["single_test"]
        assert result.status == Status.PASS
        if enable_expected:
            assert result.msg == self.ENABLED_MSG
        else:
            assert result.msg == self.DISABLED_MSG

    def test_parallel(self):
        """Test that multiprocessing is enabled when support."""
        self.run_testsuite(True, ["-j17"], supported=True)

    def test_not_supported(self):
        """Test that multiprocessing is not enabled when not supported."""
        self.run_testsuite(False, ["-j17"], supported=False)

    def test_too_few_jobs(self):
        """Test that multiprocessing is disabled when parallelism is low."""
        self.run_testsuite(False, ["-j16"], supported=True)

    def test_force(self):
        """Check that --force-multiprocessing have precedence."""
        self.run_testsuite(
            True, ["-j1", "--force-multiprocessing"], supported=False
        )


class TestCollectError:
    """Check issues in result collection are properly handled.

    * check_process_error checks that non-zero subprocess exit codes are
      reported.
    * check_unpicklable checks that corrupted process outputs are reported.
    """

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            method = getattr(self, self.test_name)
            method()

        def process_error(self):
            sys.exit(1)

        def unpicklable(self):
            # Exit "properly" with an empty (and thus invalid) exchange file
            exchange_file = sys.argv[-1]
            with open(exchange_file, "wb"):
                pass
            sys.exit(0)

    def run_testsuite(self, test_name):
        MySuite = create_testsuite([test_name], TestCollectError.MyDriver)
        results = extract_results(
            run_testsuite(
                MySuite,
                args=["--force-multiprocessing", "-E"],
                expect_failure=True,
            )
        )
        keys = sorted(results)
        assert len(keys) == 1
        return keys[0], results[keys[0]]

    def test_process_error(self):
        """Check that non-zero subprocess exit codes are reported."""
        key, result = self.run_testsuite("process_error")
        assert key.startswith("process_error.analyze__internalerror")
        assert result == Status.ERROR

    def test_unpicklable(self):
        key, result = self.run_testsuite("unpicklable")
        assert key.startswith("unpicklable.analyze__except")
        assert result == Status.ERROR
