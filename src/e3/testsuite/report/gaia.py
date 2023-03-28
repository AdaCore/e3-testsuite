"""Helpers to generate testsuite reports compatible with GAIA.

GAIA is AdaCore's internal Web analyzer.
"""

from __future__ import annotations

import dataclasses
import os.path
import tempfile
from typing import Dict, List, Optional, Set, TYPE_CHECKING, Union

import e3.env
from e3.testsuite.result import FailureReason, Log, TestResult, TestStatus

# Import TestsuiteCore only for typing, as this creates a circular import
if TYPE_CHECKING:
    from e3.testsuite.report.index import ReportIndex


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


def gaia_status(
    status: TestStatus, failure_reasons: Set[FailureReason]
) -> str:
    """Return the GAIA-compatible status that describes a result the best.

    :param status: Status for the result.
    :param failure_reasons: Set of failure reason for the result.
    """
    # Translate test failure status to the GAIA status that is most appropriate
    # given the failure reasons.
    if status == TestStatus.FAIL and failure_reasons:
        for reason in FailureReason:
            if reason in failure_reasons:
                return FAILURE_REASON_MAP[reason]
    return STATUS_MAP[status]


@dataclasses.dataclass(frozen=True)
class GAIAResultFiles:
    """Filenames for a given result in a GAIA report.

    In a GAIA testsuite report, each result is described as one entry (line) in
    the "results" text file, and several optional files. This object contains
    the names for the files, when present, corresponding to a given result.
    """

    result: Optional[str]
    log: Optional[str]
    expected: Optional[str]
    out: Optional[str]
    diff: Optional[str]
    time: Optional[str]
    info: Optional[str]


def dump_result_logs(result: TestResult, output_dir: str) -> GAIAResultFiles:
    """Write log files to describe a result in a GAIA report.

    :param result: Result to describe in the GAIA report.
    :param output_dir: Directory where to create the various files involved.
    """
    log_file: Optional[str] = None
    expected_file: Optional[str] = None
    out_file: Optional[str] = None
    diff_file: Optional[str] = None
    time_file: Optional[str] = None
    info_file: Optional[str] = None

    def unwrap_log(log: Union[Log, str, bytes]) -> Union[str, bytes]:
        return log.log if isinstance(log, Log) else log

    def write_log(log: Union[str, bytes], file_ext: str) -> str:
        mode: str
        encoding: Optional[str]

        mode, encoding = (
            ("wb", None) if isinstance(log, bytes) else ("w", "utf-8")
        )

        with tempfile.NamedTemporaryFile(
            prefix="gaia-result-",
            suffix=file_ext,
            dir=output_dir,
            mode=mode,
            encoding=encoding,
            delete=False,
        ) as f:
            f.write(log)
            return f.name

    status = gaia_status(result.status, result.failure_reasons)
    comment = result.msg or ""
    result_file = write_log(f"{status}:{comment}\n", ".result")

    if result.log:
        log = unwrap_log(result.log)
        assert isinstance(log, str)
        log_file = write_log(log, ".log")

    if result.expected is not None:
        expected = unwrap_log(result.expected)
        assert isinstance(expected, (str, bytes))
        expected_file = write_log(expected, ".expected")

    if result.out is not None:
        out = unwrap_log(result.out)
        assert isinstance(out, (str, bytes))
        out_file = write_log(out, ".out")

    if result.diff is not None:
        diff = unwrap_log(result.diff)
        assert isinstance(diff, (str, bytes))
        diff_file = write_log(diff, ".diff")

    if result.time is not None:
        # Nanoseconds granularity (9 decimals for seconds) should be
        # enough for any valuable time measurement. Rounding allows
        # predictable floating-point value representation.
        time_file = write_log("{:.9f}".format(result.time), ".time")

    if result.info:
        # Sort entries to have a deterministic output
        info_file = write_log(
            "\n".join(
                "{}:{}".format(key, value)
                for key, value in sorted(result.info.items())
            ),
            ".info",
        )

    return GAIAResultFiles(
        result_file,
        log_file,
        expected_file,
        out_file,
        diff_file,
        time_file,
        info_file,
    )


def dump_result_logs_if_needed(
    env: e3.env.Env,
    result: TestResult,
    output_dir: str,
) -> Optional[GAIAResultFiles]:
    """Shortcut to call dump_result_logs if a GAIA report is requested."""
    return (
        dump_result_logs(result, output_dir)
        if env.options.gaia_output is not None
        else None
    )


def dump_discriminants(discs: object, output_dir: str) -> None:
    """
    Dump discriminants for a GAIA-compatible testsuite report.

    :param discs: List of discriminants to dump.  Just like OptFileParse,
        accept either a string (comma-separated list of discriminant names) or
        a list of strings (list of discriminant names). Do nothing in other
        cases.
    :param output_dir: Directory in which to emit the report.
    """
    # Create the "discs" file if we had a supported type for "discs", even if
    # the list is empty, but don't create this file otherwise.
    discs_list: Optional[List[str]] = None
    if isinstance(discs, str):
        discs_list = discs.split(",")
    elif isinstance(discs, list) and all(isinstance(d, str) for d in discs):
        discs_list = discs
    if discs_list is not None:
        with open(
            os.path.join(output_dir, "discs"), "w", encoding="utf-8"
        ) as f:
            if discs_list:
                f.write(" ".join(discs_list))
                f.write("\n")


def dump_gaia_report(
    report_index: ReportIndex,
    output_dir: str,
    discs: object = None,
    result_files: Optional[Dict[str, GAIAResultFiles]] = None,
) -> None:
    """Dump a GAIA-compatible testsuite report.

    :param report_index: ReportIndex instance for all the test results to
        include in the report.
    :param output_dir: Directory in which to emit the report.
    :param discs: List of discriminants associated to the testsuite report, if
        any. See "dump_discriminants" for the expected format.
    :param result_files: If the log files for each result have already been
        generated, mapping from test names to result file names. None
        otherwise.
    """
    # If the result files are already generated, make sure we have exactly one
    # set of files per test result.
    if result_files is not None:
        assert set(result_files) == set(report_index.entries)

    # If there is a list of discriminants (i.e. in legacy AdaCore testsuites:
    # see AdaCoreLegacyTestDriver), include it in the report.
    dump_discriminants(discs, output_dir)

    with open(
        os.path.join(output_dir, "results"), "w", encoding="utf-8"
    ) as results_fd:
        for entry in report_index.entries.values():
            # Add an entry for it in the "results" index file
            message = entry.msg or ""
            status = gaia_status(entry.status, entry.failure_reasons)
            results_fd.write(f"{entry.test_name}:{status}:{message}\n")

            # Generate result files if they are not generated yet, then move
            # them where expected.
            files = (
                dump_result_logs(entry.load(), output_dir)
                if result_files is None
                else result_files[entry.test_name]
            )
            for ext, filename in dataclasses.asdict(files).items():
                if filename is not None:
                    new_filename = os.path.join(
                        output_dir, f"{entry.test_name}.{ext}"
                    )
                    os.rename(filename, new_filename)
