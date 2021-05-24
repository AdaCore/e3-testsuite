"""Helpers for testcases."""

import glob
import os.path
import yaml

from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import Log, TestResult as Result


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
        for filename in glob.glob(os.path.join(dirs[d], "*.yaml")):
            if os.path.basename(filename) == ReportIndex.INDEX_FILENAME:
                continue
            with open(filename, "r") as f:
                result = yaml.safe_load(f)
            actual_data[d][result.test_name] = result.status
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


def extract_results(testsuite):
    """Extract synthetic test results from a testsuite run."""
    return {
        e.test_name: e.status for e in testsuite.report_index.entries.values()
    }


def run_testsuite_status(cls, args=None):
    """Instantiate a Testsuite subclass, run it and return it and its sttus."""
    args = args if args is not None else []
    suite = cls()
    return (suite, suite.testsuite_main(args))


def run_testsuite(cls, args=None, expect_failure=False):
    """Instantiate a Testsuite subclass and run it."""
    args = args if args is not None else []
    suite, status = run_testsuite_status(cls, args)
    if expect_failure:
        assert status != 0
    else:
        assert status == 0
    return suite


def testsuite_logs(caplog):
    """Helper to extract messages of testsuite log records."""
    return {r.getMessage() for r in caplog.records if r.name == "testsuite"}


def create_report(results, tmp_path):
    """Create a report index in "tmp_path" for the given results."""
    index = ReportIndex(tmp_path)
    for r in results:
        index.add_result(r)
    index.write()
    return index


def create_result(
    name,
    status,
    msg="",
    log="",
    diff=None,
    time=None,
    failure_reasons=None,
):
    """Create a TestResult instance."""
    result = Result(name, status=status, msg=msg)
    result.log += log
    if diff is not None:
        result.diff = Log(diff)
    result.time = time
    if failure_reasons:
        result.failure_reasons.update(failure_reasons)
    return result
