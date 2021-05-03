"""Helpers to generate testsuite reports compatible with GAIA.

GAIA is AdaCore's internal Web analyzer.
"""

from __future__ import annotations

import os.path
from typing import TYPE_CHECKING, Union

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
    TestStatus.NOT_APPLICABLE: "NOT-APPLICABLE",
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
    # If there is a list of discriminants (i.e. in legacy AdaCore testsuites:
    # see AdaCoreLegacyTestDriver), include it in the report.
    discs = getattr(testsuite.env, "discs", None)
    if isinstance(discs, list) and all(isinstance(d, str) for d in discs):
        with open(
            os.path.join(output_dir, "discs"), "w", encoding="utf-8"
        ) as discs_fd:
            if discs:
                discs_fd.write(" ".join(discs))
                discs_fd.write("\n")

    with open(
        os.path.join(output_dir, "results"), "w", encoding="utf-8"
    ) as results_fd:
        for entry in testsuite.report_index.entries.values():
            result = entry.load()

            # Add an entry for it in the "results" index file
            message = result.msg or ""
            results_fd.write(
                "{}:{}:{}\n".format(
                    result.test_name, gaia_status(result), message
                )
            )

            # If there are logs, put them in dedicated files
            def write_log(log: Union[str, bytes], file_ext: str) -> None:
                filename = os.path.join(
                    output_dir, result.test_name + file_ext
                )
                if isinstance(log, bytes):
                    with open(filename, "wb") as bytes_f:
                        bytes_f.write(log)
                else:
                    with open(filename, "w", encoding="utf-8") as str_f:
                        str_f.write(log)

            if result.log:
                assert isinstance(result.log, str)
                write_log(result.log, ".log")
            if result.expected is not None:
                assert isinstance(result.expected, (str, bytes))
                write_log(result.expected, ".expected")
            if result.out is not None:
                assert isinstance(result.out, (str, bytes))
                write_log(result.out, ".out")
            if result.diff is not None:
                assert isinstance(result.diff, (str, bytes))
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
