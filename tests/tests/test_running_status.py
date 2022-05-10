"""Tests for the "status" file."""

import os

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import TestDriver as Driver
from e3.testsuite.result import TestResult as Result, TestStatus as Status

from .utils import run_testsuite


class TestBasic:
    """Check that the test status at each step with no parallelism."""

    fragments = [
        ("frag_a", Status.PASS),
        ("frag_b", Status.FAIL),
        ("frag_c", Status.XFAIL),
        ("frag_d", Status.PASS),
    ]

    expected_statuses = {
        "frag_a": (
            "Test fragments: 0 / 4 completed"
            "\nCurrently running:"
            "\n  test1.frag_a"
            "\nPartial results:"
            "\n  <none>"
        ),
        "frag_b": (
            "Test fragments: 1 / 4 completed"
            "\nCurrently running:"
            "\n  test1.frag_b"
            "\nPartial results:"
            "\n  PASS         1"
        ),
        "frag_c": (
            "Test fragments: 2 / 4 completed"
            "\nCurrently running:"
            "\n  test1.frag_c"
            "\nPartial results:"
            "\n  PASS         1"
            "\n  FAIL         1"
        ),
        "frag_d": (
            "Test fragments: 3 / 4 completed"
            "\nCurrently running:"
            "\n  test1.frag_d"
            "\nPartial results:"
            "\n  PASS         1"
            "\n  FAIL         1"
            "\n  XFAIL        1"
        ),
        "final": (
            "Test fragments: 4 / 4 completed"
            "\nCurrently running:"
            "\n  <none>"
            "\nPartial results:"
            "\n  PASS         2"
            "\n  FAIL         1"
            "\n  XFAIL        1"
        ),
    }

    @staticmethod
    def check_status(label):
        with open(os.path.join("out", "new", "status")) as f:
            actual = f.read()
        assert (
            actual == TestBasic.expected_statuses[label]
        ), f"Unexpected status file at {label}: {actual}"

    class MyDriver(Driver):
        def add_test(self, dag):
            # Only for "test1", create a chain of fragments that just push some
            # result.
            if self.test_name == "test1":
                prev = None
                for name, _ in TestBasic.fragments:
                    self.add_fragment(
                        dag,
                        name,
                        None,
                        after=[prev] if prev else [],
                    )
                    prev = name

        def frag_a(self, prev, slot):
            self.run("frag_a", prev, slot)

        def frag_b(self, prev, slot):
            self.run("frag_b", prev, slot)

        def frag_c(self, prev, slot):
            self.run("frag_c", prev, slot)

        def frag_d(self, prev, slot):
            self.run("frag_d", prev, slot)

        def run(self, name, prev, slot):
            TestBasic.check_status(name)

            result = Result(name, self.test_env)
            for fragment_name, status in TestBasic.fragments:
                if fragment_name == name:
                    result.set_status(status)
                    break
            else:
                raise AssertionError(f"invalid fragment name: {name}")
            self.push_result(result)

    def test(self):
        class Mysuite(Suite):
            tests_subdir = "simple-tests"
            test_driver_map = {"default": self.MyDriver}
            default_driver = "default"

        run_testsuite(
            Mysuite,
            args=["-j1", "--show-error-output", "--status-update-interval=0"],
            expect_failure=True,
        )
        self.check_status("final")
