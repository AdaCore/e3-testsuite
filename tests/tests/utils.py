"""Helpers for testcases."""

from contextlib import contextmanager
import os.path

from e3.testsuite import Testsuite
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import Log, TestResult as Result
from e3.testsuite.testcase_finder import ParsedTest


class MultiSchedulingSuite(Testsuite):
    """Helper to manually select the scheduler when running the testsuite."""

    def add_options(self, parser):
        parser.add_argument("--multiprocessing", action="store_true")

    def compute_use_multiprocessing(self):
        return self.main.args.multiprocessing


def create_testsuite(
    test_names,
    driver_cls,
    ts_cls=Testsuite,
    adjust_dag_deps=None,
):
    """Create a helper testsuite class.

    The point of this function is to provide a simple mean to create a
    testsuite & its tests with no filesystem support.

    :param test_names: List of names for tests to run.
    :param driver_cls: Test driver to use for these tests.
    :param ts_cls: Testsuite base class.
    :param adjust_dag_deps: Optional callback to adjust DAG dependencies.
    """
    tests = [
        ParsedTest(
            test_name=test_name,
            driver_cls=driver_cls,
            test_env={},
            test_dir=".",
            test_matcher=None,
        )
        for test_name in test_names
    ]

    class MySuite(ts_cls):
        def get_test_list(self, sublist):
            return tests

        def adjust_dag_dependencies(self, dag):
            if adjust_dag_deps:
                adjust_dag_deps(self, dag)

    return MySuite


def check_result_dirs(new=None, old=None, new_dir=None, old_dir=None):
    """Check the content of testsuite result directories.

    :param new: Mapping from test names to expected test statuses for
        "new_dir".
    :param old: Likewise, but for "old_dir".
    :param new_dir: Directory that contains new test results. If left to None,
        use "out/new" in the current directory.
    :param old_dir: Likewise, for old test results. If left to None, use
        "out/old" in the current directory.
    """
    new = new if new is not None else {}
    old = old if old is not None else {}
    dirs = {
        "new": new_dir or os.path.join("out", "new"),
        "old": old_dir or os.path.join("out", "old"),
    }
    expected_data = {"new": new, "old": old}
    actual_data = {"new": {}, "old": {}}

    for d in ("new", "old"):
        output_dir = dirs[d]
        if os.path.exists(os.path.join(output_dir, "_index.json")):
            index = ReportIndex.read(dirs[d])
            for e in index.entries.values():
                actual_data[d][e.test_name] = e.status
    assert expected_data == actual_data, f"{expected_data} != {actual_data}"


def check_result_from_prefix(suite, prefix, status, msg):
    """Check the content of a result from its name prefix."""
    matches = []
    for key, value in suite.report_index.entries.items():
        if key.startswith(prefix):
            matches.append(value)
    assert len(matches) == 1, "Exactly one entry matching expected"
    result = matches[0]
    assert result.status == status
    assert result.msg == msg


def check_result(suite, test_name, status, msg):
    """Check the status and message for a test result."""
    result = suite.report_index.entries[test_name]
    assert result.status == status
    assert result.msg == msg


def extract_results(testsuite):
    """Extract synthetic test results from a testsuite run."""
    return {
        e.test_name: e.status for e in testsuite.report_index.entries.values()
    }


def run_testsuite_status(cls, args=None, multiprocessing=False):
    """Instantiate a Testsuite subclass, run it and return it and its sttus."""
    args = list(args) if args is not None else []
    if multiprocessing:
        args.append("--multiprocessing")
    suite = cls()
    return (suite, suite.testsuite_main(args))


def run_testsuite(cls, args=None, multiprocessing=False, expect_failure=False):
    """Instantiate a Testsuite subclass and run it."""
    args = args if args is not None else []
    suite, status = run_testsuite_status(cls, args, multiprocessing)
    if expect_failure:
        assert status != 0
    else:
        assert status == 0
    return suite


def suite_logs(caplog):
    """Extract messages of testsuite log records."""
    return {r.getMessage() for r in caplog.records if r.name == "testsuite"}


def create_report(results, tmp_path):
    """Create a report index in "tmp_path" for the given results."""
    index = ReportIndex(tmp_path)
    for r in results:
        index.add_result(r.summary, r.save(tmp_path))
    index.write()
    return index


def create_result(
    name,
    status,
    msg="",
    log="",
    out=None,
    expected=None,
    diff=None,
    time=None,
    failure_reasons=None,
    encoding=None,
):
    """Create a TestResult instance."""
    result = Result(name, status=status, msg=msg)
    result.env = {}
    result.log += log
    if out is not None:
        result.out = Log(out)
    if expected is not None:
        result.expected = Log(expected)
    if diff is not None:
        result.diff = Log(diff)
    result.time = time
    if failure_reasons:
        result.failure_reasons.update(failure_reasons)

    if encoding:
        result.env["encoding"] = encoding

    return result


@contextmanager
def chdir_ctx(dirname):
    """Reimplementation of contextlib.chdir for Python pre-3.11."""
    old_cwd = os.getcwd()
    try:
        os.chdir(dirname)
        yield
    finally:
        os.chdir(old_cwd)
