"""
Tests for the code e3.testsuite framework.

This checks the behavior of the Testsuite, TestDriver and BasicTestDriver
classes.
"""

import glob
import logging
import os

import yaml

from e3.testsuite import TestAbort as E3TestAbort
from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.result import TestResult as Result, TestStatus as Status


def run_testsuite(cls, args=[], expect_failure=False):
    """Instantiate a Testsuite subclass and run it."""
    suite = cls()
    status = suite.testsuite_main(args)
    if expect_failure:
        assert status != 0
    else:
        assert status == 0
    return suite


def testsuite_logs(caplog):
    """Helper to extract messages of testsuite log records."""
    return {r.getMessage() for r in caplog.records if r.name == "testsuite"}


def check_results_dir(new={}, old={}):
    """Check the content of a testsuite results directory.

    ``new`` must be a dictionnary that maps test names to expected test
    statuses for the "new" results subdirectory. ``old`` is the same, but for
    the "old" results subdirectory.
    """
    expected_data = {"new": new, "old": old}
    actual_data = {"new": {}, "old": {}}

    for filename in glob.glob(os.path.join("out", "*", "*.yaml")):
        with open(filename, "r") as f:
            result = yaml.safe_load(f)
        directory = os.path.basename(os.path.dirname(filename))
        actual_data[directory][result.test_name] = result.status
    assert expected_data == actual_data


def test_basic():
    """Basic driver with all tests passing."""

    class MyDriver(BasicDriver):
        return_status = Status.PASS

        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(self.return_status)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    result1 = {"test1": Status.PASS, "test2": Status.PASS}
    result2 = {"test1": Status.FAIL, "test2": Status.FAIL}
    result3 = {"test1": Status.SKIP, "test2": Status.SKIP}

    # Do a first testsuite run, checking the results
    suite = run_testsuite(Mysuite)
    assert suite.results == {"test1": Status.PASS, "test2": Status.PASS}
    check_results_dir(new=result1)

    # Then do a second one. We expect the previous "new" directory to move to
    # the "old" one.
    MyDriver.return_status = Status.FAIL
    suite = run_testsuite(Mysuite)
    check_results_dir(new=result2, old=result1)

    # Do a third run. We expect the "old" directory to just disappear, and the
    # "new" one to take its place.
    MyDriver.return_status = Status.SKIP
    suite = run_testsuite(Mysuite)
    check_results_dir(new=result3, old=result2)


def test_outer_testcase():
    """Check that we can run tests from another directory."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "empty-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    outer_test_dir = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "simple-tests"
    )
    suite = run_testsuite(Mysuite, args=[outer_test_dir])
    assert suite.results == {
        "simple-tests__test1": Status.PASS,
        "simple-tests__test2": Status.PASS,
    }


def test_invalid_filter_pattern(caplog):
    """Check the proper detection of invalid tests on the command line."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite, args=["("], expect_failure=True)
    assert any(
        message.startswith("Invalid test pattern, skipping: ")
        for message in testsuite_logs(caplog)
    )


def test_dump_environ():
    """Check that --dump-environ works (at least does not crash)."""

    class MyDriver(BasicDriver):
        return_status = Status.PASS

        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(self.return_status)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite, args=["--dump-environ"])


def test_no_testcase(caplog):
    """Testsuite run with no testcase."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS, "ok!")
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "no-test"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite)
    logs = testsuite_logs(caplog)
    assert suite.results == {}
    assert any("<no test result>" in message for message in logs)


def test_abort():
    """Check for if TestAbort work."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            raise E3TestAbort
            return "INVALID"

        def analyze(self, prev, slot):
            if prev["run"] is None:
                self.result.set_status(Status.PASS, "ok!")
            else:
                self.result.set_status(Status.FAIL, "unexpected return value")

            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    suite = run_testsuite(Mysuite)
    assert suite.results == {"test1": Status.PASS, "test2": Status.PASS}


def test_exception_in_driver():
    """Check handling of exception in test driver."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            raise AttributeError("expected exception")

        def analyze(self, prev, slot):
            prev_value = prev["run"]
            logging.debug(prev_value)
            if isinstance(prev_value, Exception):
                self.result.set_status(Status.PASS, "ok!")
            else:
                self.result.set_status(Status.FAIL, "unexpected return value")
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    suite = run_testsuite(Mysuite)

    results = dict(suite.results)

    # Expect PASS for both tests
    assert results.pop("test1") == Status.PASS
    assert results.pop("test2") == Status.PASS

    # Expect two extra ERROR results for errors in MyDriver.run. Their names
    # depend on a counter we don't control, hence the involved checking code.
    assert len(results) == 2

    keys = sorted(results)
    assert keys[0].startswith("test1.run__except")
    assert keys[1].startswith("test2.run__except")
    assert set(results.values()) == {Status.ERROR}


def test_not_existing_temp_dir(caplog):
    """Check the detection of missing requested temporary directory."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            return True

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    # Check that the testsuite aborted and that we have the expected error
    # message.
    run_testsuite(Mysuite, ["--temp-dir=tmp"], expect_failure=True)
    logs = testsuite_logs(caplog)
    assert "temp dir 'tmp' does not exist" in logs


def test_dev_mode():
    """Check the dev mode (--dev-temp) works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            os.mkdir(self.test_env["working_dir"])
            path = os.path.join(self.test_env["working_dir"], "foo.txt")
            with open(path, "w") as f:
                f.write(self.test_env["test_name"])
            return True

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite, ["--dev-temp=tmp"])

    # Check testsuite report
    assert suite.results == {"test1": Status.PASS, "test2": Status.PASS}

    # Check the presence and content of working directories
    for test in ["test1", "test2"]:
        path = os.path.join("tmp", test, "foo.txt")
        with open(path, "r") as f:
            content = f.read()
        assert content == test


def test_invalid_yaml(caplog):
    """Check that invalid test.yaml files are properly reported."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS, "all good")
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "invalid-yaml-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    # The testsuite is supposed to run to completion (valid tests have run),
    # but it ends with an error status code.
    suite = run_testsuite(Mysuite, expect_failure=True)
    assert suite.results == {"valid": Status.PASS}

    logs = testsuite_logs(caplog)
    assert "invalid syntax for test.yaml in 'invalid_syntax'" in logs
    assert "invalid format for test.yaml in 'invalid_structure'" in logs
    assert "cannot find driver for test 'invalid_driver'" in logs


def test_missing_driver(caplog):
    """Check that missing drivers in test.yaml files are properly reported."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS, "all good")
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "invalid-yaml-tests"
        test_driver_map = {"my_driver": MyDriver}

    suite = run_testsuite(Mysuite, expect_failure=True)
    logs = testsuite_logs(caplog)
    assert suite.results == {}
    assert "missing driver for test 'valid'" in logs


def test_invalid_driver(caplog):
    """Check that faulty driver classes are properly reported."""

    class MyDriver(BasicDriver):
        def __init__(self, *args, **kwargs):
            raise NotImplementedError

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite, expect_failure=True)
    logs = testsuite_logs(caplog)
    assert any("Traceback:" in message for message in logs)


def test_show_error_output(caplog):
    """Check that --show-error-output works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            self.result.log += "Work is being done..."

        def analyze(self, prev, slot):
            if self.test_env["test_name"] == "test1":
                self.result.set_status(Status.PASS, "all good")
            else:
                self.result.set_status(Status.FAIL, "test always fail!")
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite, ["--show-error-output"])
    logs = testsuite_logs(caplog)
    assert any("Work is being done" in message for message in logs)


def test_push_twice():
    """Test error detection when pushing results twice in a driver."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS, "ok!")
            self.push_result()
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    try:
        run_testsuite(Mysuite, args=["simple-tests/test1"])
    except AssertionError as exc:
        assert "cannot push twice" in str(exc)


def test_result_set_status_twice(caplog):
    """Test that calling TestResult.set_status twice is rejected."""
    r = Result("foobar")
    r.set_status(Status.PASS)
    r.set_status(Status.PASS)

    logs = {r.getMessage() for r in caplog.records}
    assert "cannot set test foobar status twice" in logs


def test_result_str(caplog):
    """Test that calling TestResult.set_status twice is rejected."""
    r = Result("foobar", msg="<message>")
    assert str(r) == "foobar                   TestStatus.ERROR <message>"


def test_comment_file():
    """Test that the comment file is written as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

        def write_comment_file(self, f):
            lines = sorted(
                "{}:{}".format(status.name, counter)
                for status, counter in self.test_status_counters.items()
                if counter
            )
            f.write(" ".join(lines))

    run_testsuite(Mysuite)
    with open(os.path.join("out", "new", "comment")) as f:
        content = f.read()
    assert content == "PASS:2"


def test_path_builders():
    """Check that path building methods in TestDriver work as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            assert self.working_dir("foo.txt") == os.path.join(
                self.test_env["working_dir"], "foo.txt"
            )
            assert self.test_dir("foo.txt") == os.path.join(
                self.test_env["test_dir"], "foo.txt"
            )

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite)


def test_multiline_message():
    """Check that multiline messages are adjusted in test results."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(
                Status.PASS, "   Ugly  \nmultiline\r\n   \tstring  "
            )
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    run_testsuite(Mysuite, args=["test1"])
    with open(os.path.join("out", "new", "test1.yaml")) as f:
        result = yaml.safe_load(f)
    assert result.status == Status.PASS
    assert result.msg == "Ugly multiline string"


def test_failure_exit_code():
    """Check that --failure-exit-code works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(
                Status.PASS if self.test_name == "test1" else Status.FAIL
            )
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite)
    assert suite.results == {"test1": Status.PASS, "test2": Status.FAIL}

    suite = run_testsuite(
        Mysuite, args=["--failure-exit-code=1"], expect_failure=True
    )
    assert suite.results == {"test1": Status.PASS, "test2": Status.FAIL}
