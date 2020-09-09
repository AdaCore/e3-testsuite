"""Helpers for testcases."""

import yaml

from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import Log, TestResult as Result


def extract_results(testsuite):
    """Extract synthetic test results from a testsuite run."""
    return {
        e.test_name: e.status for e in testsuite.report_index.entries.values()
    }


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


def create_report(results, tmp_path):
    """Create a report index in "tmp_path" for the given results."""
    index = ReportIndex(tmp_path)
    for r in results:
        yaml_filename = tmp_path / "{}.yaml".format(r.test_name)
        with open(yaml_filename, "w") as f:
            yaml.dump(r, f)
        index.add_result(r)
    index.write()
    return index


def create_result(name, status, msg="", log="", diff=None, time=None):
    """Create a TestResult instance."""
    result = Result(name, status=status, msg=msg)
    result.log += log
    if diff is not None:
        result.diff = Log(diff)
    result.time = time
    return result
