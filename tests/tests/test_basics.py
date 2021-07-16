"""
Tests for the code e3.testsuite framework.

This checks the behavior of the Testsuite, TestDriver and BasicTestDriver
classes.
"""

import logging
import os
from typing import List
import warnings

from e3.testsuite import TestAbort as E3TestAbort, Testsuite as Suite
from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.fragment import FragmentData
from e3.testsuite.report.index import ReportIndex, ReportIndexEntry
from e3.testsuite.result import TestResult as Result, TestStatus as Status
from e3.testsuite.testcase_finder import TestFinder as Finder, ParsedTest

from .utils import (
    check_result_dirs,
    check_result_from_prefix,
    extract_results,
    run_testsuite,
    run_testsuite_status,
    testsuite_logs,
)


def test_basic():
    """Basic driver with all tests passing."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    # Run the testsuite and check both the in-memory report and the on-disk one
    result = {"test1": Status.PASS, "test2": Status.PASS}
    suite = run_testsuite(Mysuite, args=["-E"])
    assert extract_results(suite) == result
    check_result_dirs(new=result)


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
    assert extract_results(suite) == {
        "simple-tests__test1": Status.PASS,
        "simple-tests__test2": Status.PASS,
    }


def test_invalid_filter_pattern(caplog):
    """Check the proper detection of invalid regexps on the command line."""

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

    run_testsuite(Mysuite, args=["\\h"])
    assert any(
        message.startswith(
            "Test pattern is not a valid regexp, try to match it as-is: "
        )
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
    assert os.path.exists(os.path.join("out", "new", "environ.sh"))


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
    assert extract_results(suite) == {}
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
    assert extract_results(suite) == {
        "test1": Status.PASS,
        "test2": Status.PASS,
    }


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

    results = extract_results(suite)

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
    assert extract_results(suite) == {
        "test1": Status.PASS,
        "test2": Status.PASS,
    }

    # Check the presence and content of working directories
    for test in ["test1", "test2"]:
        path = os.path.join("tmp", test, "foo.txt")
        with open(path, "r") as f:
            content = f.read()
        assert content == test


def test_invalid_yaml():
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
    suite = run_testsuite(Mysuite)
    results = suite.report_index.entries

    assert len(results) == 4
    assert results["valid"].status == Status.PASS

    check_result_from_prefix(
        suite,
        "invalid_syntax__except",
        Status.ERROR,
        "invalid syntax for test.yaml",
    )
    check_result_from_prefix(
        suite,
        "invalid_structure__except",
        Status.ERROR,
        "invalid format for test.yaml",
    )
    check_result_from_prefix(
        suite,
        "invalid_driver__except",
        Status.ERROR,
        "cannot find driver",
    )


def test_missing_driver():
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

    suite = run_testsuite(Mysuite)
    check_result_from_prefix(
        suite,
        "valid__except",
        Status.ERROR,
        "missing test driver",
    )


def test_invalid_driver():
    """Check that faulty driver classes are properly reported."""

    class MyDriver(BasicDriver):
        def __init__(self, *args, **kwargs):
            raise NotImplementedError("__init__ not implemented")

        def analyze(self):
            raise NotImplementedError

        def run(self):
            raise NotImplementedError

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite, args=["-E"])
    check_result_from_prefix(
        suite,
        "test1__except",
        Status.ERROR,
        "__init__ not implemented",
    )


def test_duplicate_name():
    """Check duplicate test names are properly reported."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            self.result.log += "Work is being done..."

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS, "all good")
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

        def test_name(self, test_dir):
            return "foo"

    suite = run_testsuite(Mysuite, args=["-E"])
    assert len(suite.report_index.entries) == 2
    assert suite.report_index.entries["foo"].status == Status.PASS
    check_result_from_prefix(
        suite,
        "foo__except",
        Status.ERROR,
        "duplicate test name: foo",
    )


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


def test_default_comment_file():
    """Test that the comment file is written as expected by default."""

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

    run_testsuite(Mysuite)
    with open(os.path.join("out", "new", "comment")) as f:
        content = f.readlines()
    assert len(content) == 2
    assert content[0] == "Testsuite options:\n"


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
            counters = self.report_index.status_counters
            lines = sorted(
                "{}:{}".format(status.name, counter)
                for status, counter in counters.items()
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

    suite = run_testsuite(Mysuite, args=["test1"])
    result = suite.report_index.entries["test1"].load()
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

    class Mysuite2(Mysuite):
        default_failure_exit_code = 2

    def check(cls, args, expected_status):
        suite, status = run_testsuite_status(cls, args)
        assert extract_results(suite) == {
            "test1": Status.PASS,
            "test2": Status.FAIL,
        }
        assert status == expected_status

    check(Mysuite, [], 0)
    check(Mysuite, ["--failure-exit-code=1"], 1)
    check(Mysuite2, [], 2)
    check(Mysuite2, ["--failure-exit-code=1"], 1)


def test_max_consecutive_failures(caplog):
    """Check that --max-consecutive-failures works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.FAIL)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(
        Mysuite, args=["--max-consecutive-failures=1", "-j1"]
    )
    logs = {r.getMessage() for r in caplog.records}
    assert len(suite.report_index.entries) == 1
    assert "Too many consecutive failures, aborting the testsuite" in logs


def test_show_time_info(caplog):
    """Check that --show-time-info works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.time = 1.0
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}
        default_driver = "default"

    suite = run_testsuite(Mysuite, args=["--show-time-info", "test1"])
    logs = {r.getMessage() for r in caplog.records}
    test_summaries = [line for line in logs if line.startswith("PASS")]
    assert len(suite.report_index.entries) == 1
    assert test_summaries == ["PASS     00m01s test1"]


def test_deprecated():
    """Test deprecated methods."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    def check_warning(warn_list):
        assert len(warn_list) == 1
        w = warn_list[0]
        assert issubclass(w.category, DeprecationWarning)
        assert "obsolete" in str(w.message)

    suite = run_testsuite(Mysuite)

    with warnings.catch_warnings(record=True) as w:
        assert suite.test_counter == 2
        check_warning(w)

    with warnings.catch_warnings(record=True) as w:
        expected = {s: 0 for s in Status}
        expected[Status.PASS] = 2
        assert suite.test_status_counters == expected
        check_warning(w)

    with warnings.catch_warnings(record=True) as w:
        assert suite.results == {
            "test1": Status.PASS,
            "test2": Status.PASS,
        }
        check_warning(w)


def test_read_report_index():
    """Check that reading a report index works as expected."""

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "simple-tests"
        test_driver_map = {"default": MyDriver}

        @property
        def default_driver(self):
            return "default"

    run_testsuite(Mysuite)
    index = ReportIndex.read(os.path.join("out", "new"))
    assert index.entries == {
        "test1": ReportIndexEntry(index, "test1", Status.PASS, None),
        "test2": ReportIndexEntry(index, "test2", Status.PASS, None),
    }


def test_multiple_tests_per_dir():
    """Test a test finder that returns multiple tests per directory."""

    class CustomTestFinder(Finder):
        test_dedicated_directory = False

        def probe(self, testsuite, dirpath, dirnames, filenames):
            result = []
            for f in filenames:
                if not f.endswith(".txt"):
                    continue

                # Strip the "*.txt" extension for the test name, but preserve
                # it for the matcher.
                test_name = testsuite.test_name(os.path.join(dirpath, f[:-4]))
                test_matcher = os.path.join(dirpath, f)

                result.append(
                    ParsedTest(
                        test_name=test_name,
                        driver_cls=MyDriver,
                        test_env={},
                        test_dir=dirpath,
                        test_matcher=test_matcher,
                    )
                )
            return result

    class MyDriver(BasicDriver):
        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            self.result.set_status(Status.PASS)
            self.push_result()

    class Mysuite(Suite):
        tests_subdir = "txt-tests"
        test_driver_map = {"default": MyDriver}

        test_finders = [CustomTestFinder()]

        @property
        def default_driver(self):
            return "default"

    # Check a full testsuite run
    suite = run_testsuite(Mysuite)
    assert extract_results(suite) == {
        "bar__x": Status.PASS,
        "bar__y": Status.PASS,
        "foo__a": Status.PASS,
        "foo__b": Status.PASS,
        "foo__c": Status.PASS,
    }

    # Check filtering
    suite = run_testsuite(Mysuite, args=["a.txt"])
    assert extract_results(suite) == {"foo__a": Status.PASS}


def test_inter_test_deps():
    """Check we can run a testsuite with inter-tests dependencies."""
    # Run a testsuite with two kind of drivers: UnitDriver ones, which just
    # "compute a number" and SumDriver ones, which compute the sum of all
    # numbers from UnitDriver tests. SumDriver tests depend on the UnitDriver:
    # they must run after them and access their data.

    class UnitDriver(BasicDriver):
        def run(self, prev, slot):
            return int(self.test_name.split("_")[-1])

        def analyze(self, prev, slot):
            assert isinstance(prev["run"], int)
            self.result.set_status(Status.PASS)
            self.push_result()

    class SumDriver(BasicDriver):
        unit_fragments: List[FragmentData]

        def run(self, prev, slot):
            self.sum_result = sum(
                prev[f"{d.uid}"] for d in self.unit_fragments
            )

        def analyze(self, prev, slot):
            self.result.set_status(
                Status.PASS if self.sum_result == 10 else Status.FAIL
            )
            self.push_result()

    def parsed_test(driver_cls, test_name):
        return ParsedTest(test_name, driver_cls, {}, ".")

    class Mysuite(Suite):
        tests_subdir = "."

        def get_test_list(self, sublist):
            return [
                parsed_test(SumDriver, "sum"),
                parsed_test(UnitDriver, "unit_0"),
                parsed_test(UnitDriver, "unit_1"),
                parsed_test(UnitDriver, "unit_2"),
                parsed_test(UnitDriver, "unit_3"),
                parsed_test(UnitDriver, "unit_4"),
            ]

        def adjust_dag_dependencies(self, dag):
            # Get the list of all fragments for...

            # ... UnitDriver.run
            unit_fragments = []

            # ... SumDriver.run
            sum_fragments = []

            for fg in dag.vertex_data.values():
                if fg.matches(UnitDriver, "run"):
                    unit_fragments.append(fg)
                elif fg.matches(SumDriver, "run"):
                    sum_fragments.append(fg)

            # Pass the list of UnitDriver.run fragments to all SumDriver
            # instances and make sure SumDriver fragments run after all
            # UnitDriver.run ones.
            unit_uids = [fg.uid for fg in unit_fragments]
            for fg in sum_fragments:
                fg.driver.unit_fragments = unit_fragments
                dag.update_vertex(vertex_id=fg.uid, predecessors=unit_uids)

    suite = run_testsuite(Mysuite, args=["-E"])
    assert extract_results(suite) == {
        "unit_0": Status.PASS,
        "unit_1": Status.PASS,
        "unit_2": Status.PASS,
        "unit_3": Status.PASS,
        "unit_4": Status.PASS,
        "sum": Status.PASS,
    }
