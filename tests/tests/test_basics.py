"""
Tests for the code e3.testsuite framework: Testsuite, TestDriver and
BasicTestDriver classes.
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
    """Helper to instantiate a Testsuite subclass and run it."""
    suite = cls(os.path.dirname(__file__))
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
    """Helper to check the content of a testsuite results directory.

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

        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(self.return_status)
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    result1 = {"test1": Status.PASS, "test2": Status.PASS}
    result2 = {"test1": Status.FAIL, "test2": Status.FAIL}
    result3 = {"test1": Status.UNSUPPORTED, "test2": Status.UNSUPPORTED}

    # Do a first testsuite run, checking the results
    suite = run_testsuite(Mysuite)
    assert len(suite.results) == 2
    for v in list(suite.results.values()):
        assert v == Status.PASS
    check_results_dir(new=result1)

    # Then do a second one. We expect the previous "new" directory to move to
    # the "old" one.
    MyDriver.return_status = Status.FAIL
    suite = run_testsuite(Mysuite)
    check_results_dir(new=result2, old=result1)

    # Do a third run. We expect the "old" directory to just disappear, and the
    # "new" one to take its place.
    MyDriver.return_status = Status.UNSUPPORTED
    suite = run_testsuite(Mysuite)
    check_results_dir(new=result3, old=result2)


def test_dump_environ():
    """
    Check that the --dump-environ argument works (at least does not crash).
    """

    class MyDriver(BasicDriver):
        return_status = Status.PASS

        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(self.return_status)
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite, args=["--dump-environ"])


def test_no_testcase(caplog):
    """Testsuite run with no testcase"""

    class MyDriver(BasicDriver):
        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(Status.PASS, "ok!")
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = "no-test"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite)
    assert len(suite.results) == 0
    logs = testsuite_logs(caplog)
    assert any("<no test result>" in message for message in logs)


def test_abort():
    """Check for if TestAbort work."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            raise E3TestAbort
            return "INVALID"

        def analyze(self, prev):
            if prev["run"] is None:
                self.result.set_status(Status.PASS, "ok!")
            else:
                self.result.set_status(Status.FAIL, "unexpected return value")

            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    suite = run_testsuite(Mysuite)
    assert len(suite.results) == 2
    for v in list(suite.results.values()):
        assert v == Status.PASS


def test_exception_in_driver():
    """Check handling of exception in test driver."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            raise AttributeError("expected exception")

        def analyze(self, prev):
            prev_value = prev["run"]
            logging.debug(prev_value)
            if isinstance(prev_value, Exception):
                self.result.set_status(Status.PASS, "ok!")
            else:
                self.result.set_status(Status.FAIL, "unexpected return value")
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    suite = run_testsuite(Mysuite)
    assert suite.test_counter == 4
    assert suite.test_status_counters[Status.PASS] == 2
    assert suite.test_status_counters[Status.ERROR] == 2


def test_not_existing_temp_dir(caplog):
    """Check the detection of missing requested temporary directory."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            return True

        def analyze(self, prev):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    # Check that the testsuite aborted and that we have the expected error
    # message.
    run_testsuite(Mysuite, ["--temp-dir=tmp"], expect_failure=True)
    logs = testsuite_logs(caplog)
    assert "temp dir 'tmp' does not exist" in logs


def test_dev_mode():
    """Check the dev mode (--dev-temp) works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            os.mkdir(self.test_env["working_dir"])
            path = os.path.join(self.test_env["working_dir"], "foo.txt")
            with open(path, "w") as f:
                f.write(self.test_env["test_name"])
            return True

        def analyze(self, prev):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite, ["--dev-temp=tmp"])

    # Check testsuite report
    assert suite.test_counter == 2
    assert suite.test_status_counters[Status.PASS] == 2

    # Check the presence and content of working directories
    for test in ["test1", "test2"]:
        path = os.path.join("tmp", test, "foo.txt")
        with open(path, "r") as f:
            content = f.read()
        assert content == test


def test_invalid_yaml(caplog):
    """Check that invalid test.yaml files are properly reported."""
    class MyDriver(BasicDriver):
        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(Status.PASS, "all good")
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "invalid-yaml-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    # The testsuite is supposed to run to completion (valid tests have run),
    # but it ends with an error status code.
    suite = run_testsuite(Mysuite, expect_failure=True)
    assert suite.test_counter == 1
    assert suite.test_status_counters[Status.PASS] == 1

    logs = testsuite_logs(caplog)
    assert "invalid syntax for invalid_syntax/test.yaml" in logs
    assert "invalid format for invalid_structure/test.yaml" in logs
    assert "cannot find driver for invalid_driver/test.yaml" in logs


def test_missing_driver(caplog):
    """Check that missing drivers in test.yaml files are properly reported."""
    class MyDriver(BasicDriver):
        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(Status.PASS, "all good")
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "invalid-yaml-tests"
        DRIVERS = {"my_driver": MyDriver}

    suite = run_testsuite(Mysuite, expect_failure=True)
    assert suite.test_counter == 0
    logs = testsuite_logs(caplog)
    assert "missing driver for valid/test.yaml" in logs


def test_invalid_driver(caplog):
    """Check that faulty driver classes are properly reported."""

    class MyDriver(BasicDriver):
        def __init__(self, *args, **kwargs):
            raise NotImplementedError

    class Mysuite(Suite):
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    run_testsuite(Mysuite, expect_failure=True)
    logs = testsuite_logs(caplog)
    assert any("Traceback:" in message for message in logs)


def test_show_error_output(caplog):
    """Check that --show-error-output works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            self.result.log += "Work is being done..."

        def analyze(self, prev):
            if self.test_env["test_name"] == "test1":
                self.result.set_status(Status.PASS, "all good")
            else:
                self.result.set_status(Status.FAIL, "test always fail!")
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite, ["--show-error-output"])
    logs = testsuite_logs(caplog)
    assert any("Work is being done" in message for message in logs)


def test_push_twice():
    """Test error detection when pushing results twice in a driver."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(Status.PASS, "ok!")
            self.push_result()
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    try:
        suite = run_testsuite(Mysuite, args=["simple-tests/test1"])
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
    assert str(r) == "foobar                   TestStatus.UNRESOLVED <message>"


def test_comment_file():
    """Test that the comment file is written as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        TEST_SUBDIR = "simple-tests"
        DRIVERS = {"default": MyDriver}
        default_driver = "default"

        def write_comment_file(self, f):
            f.write(" ".join(sorted(
                "{}:{}".format(status.name, counter)
                for status, counter in self.test_status_counters.items()
                if counter)))

    suite = run_testsuite(Mysuite)
    with open(os.path.join("out", "new", "comment")) as f:
        content = f.read()
    assert content == "PASS:2"
