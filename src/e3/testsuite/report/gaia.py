"""Helpers to generate testsuite reports compatible with GAIA.

GAIA is AdaCore's internal Web analyzer.
"""

from __future__ import annotations

import os.path
from typing import AnyStr, TYPE_CHECKING

import yaml

from e3.testsuite.result import FailureReason, TestResult, TestStatus

# Import TestsuiteCore only for typing, as this creates a circular import
if TYPE_CHECKING:  # no cover
    from e3.testsuite import TestsuiteCore


STATUS_MAP = {
    TestStatus.PASS: "OK",
    TestStatus.FAIL: "FAIL",
    TestStatus.XFAIL: "XFAIL",
    TestStatus.XPASS: "UOK",
    TestStatus.VERIFY: "VERIFY",
    TestStatus.SKIP: "DEAD",
    TestStatus.NOT_APPLICABLE: "NOT_APPLICABLE",
    TestStatus.ERROR: "PROBLEM",
}
"""
Map TestStatus values to GAIA-compatible test statuses.
"""

FAILURE_REASON_MAP = {
    FailureReason.CRASH: "CRASH",
    FailureReason.TIMEOUT: "TIMEOUT",
    FailureReason.MEMCHECK: "PROBLEM",
    FailureReason.DIFF: "DIFF",
}
"""
Map FailureReason values to equivalent GAIA-compatible test statuses.
"""


def gaia_status(result: TestResult) -> str:
    """Return the GAIA-compatible status that describes this result the best.

    :param result: Result to analyze.
    """
    assert result.status is not None

    # Translate test failure status to the GAIA status that is most appropriate
    # given the failure reasons.
    if result.status == TestStatus.FAIL and result.failure_reasons:
        for reason in FailureReason:
            if reason in result.failure_reasons:
                return FAILURE_REASON_MAP[reason]
    return STATUS_MAP[result.status]


def dump_gaia_report(testsuite: TestsuiteCore, output_dir: str) -> None:
    """Dump a GAIA-compatible testsuite report.

    :param testsuite: Testsuite instance, which have run its testcases, for
        which to generate the report.
    :param output_dir: Directory in which to emit the report.
    """
    with open(
        os.path.join(output_dir, "results"), "w", encoding="utf-8"
    ) as results_fd:
        for test_name in testsuite.results:
            # Load the result for this testcase
            with open(testsuite.test_result_filename(test_name), "r") as f:
                result = yaml.safe_load(f)

            # Add an entry for it in the "results" index file
            message = result.msg or ""
            results_fd.write(
                "{}:{}:{}\n".format(
                    result.test_name, gaia_status(result), message
                )
            )

            # If there are logs, put them in dedicated files
            def write_log(log: AnyStr, file_ext: str) -> None:
                filename = os.path.join(output_dir, test_name + file_ext)
                with (
                    open(filename, "wb")
                    if isinstance(log, bytes) else
                    open(filename, "w", encoding="utf-8")
                ) as f:
                    f.write(log)

            if result.log:
                write_log(result.log, ".log")
            if result.expected is not None:
                write_log(result.expected, ".expected")
            if result.out is not None:
                write_log(result.out, ".out")
            if result.diff is not None:
                write_log(result.diff, ".diff")
            if result.time is not None:
                # Nanoseconds granularity (9 decimals for seconds) should be
                # enough for any valuable time measurement. Rounding allows
                # predictable floating-point value representation.
                write_log("{:.9f}".format(result.time), ".time")
            if result.info:
                # Sort entries to have a deterministic output
                write_log(
                    "\n".join(
                        "{}:{}".format(key, value)
                        for key, value in sorted(result.info.items())
                    ),
                    ".info"
                )
