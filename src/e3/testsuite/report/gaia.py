import os.path
import yaml

from e3.testsuite.result import TestStatus


STATUS_MAP = {
    TestStatus.PASS: "PASSED",
    TestStatus.FAIL: "FAILED",
    TestStatus.UNSUPPORTED: "DEAD",
    TestStatus.XFAIL: "XFAILED",
    TestStatus.XPASS: "UPASSED",
    TestStatus.ERROR: "CRASH",
    TestStatus.UNRESOLVED: "PROBLEM",
    TestStatus.UNTESTED: "DEAD",
}
"""
Map TestStatus values to GAIA-compatible test statuses.

:type: dict[TestStatus, str]
"""


def dump_gaia_report(testsuite, output_dir):
    """Dump a GAIA-compatible testsuite report.

    :param Testsuite testsuite: Testsuite instance, which have run its
        testcases, for which to generate the report.
    :param str output_dir: Directory in which to emit the report.
    """
    with open(os.path.join(output_dir, "results"), "w") as results_fd:
        for test_name in testsuite.results:
            # Load the result for this testcase
            with open(testsuite.test_result_filename(test_name), "r") as f:
                result = yaml.safe_load(f)

            # Add an entry for it in the "results" index file
            gaia_status = STATUS_MAP[result.status]
            message = result.msg
            results_fd.write(
                "{}:{}:{}\n".format(result.test_name, gaia_status, message)
            )

            # If there are logs, put them in dedicated files
            def write_log(log, file_ext):
                if not log:
                    return
                filename = os.path.join(output_dir, test_name + file_ext)
                with open(filename, "wb") as f:
                    f.write(log)

            write_log(result.out, ".out")
            write_log(result.log, ".log")
