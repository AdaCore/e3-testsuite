"""Helpers to automatically rewrite test baseline."""

from __future__ import annotations

import abc
import dataclasses
import glob
import os.path
import sys

from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import FailureReason, TestStatus
from e3.testsuite.utils import ColorConfig


class RewritingError(Exception):
    """Raised by BaseBaselineRewriter.rewrite in case of fatal error."""

    pass


@dataclasses.dataclass
class RewritingSummary:
    """Summary of rewritten baselines."""

    errors: set[str]
    """
    Set of test names whose result was an error (baseline not updated).
    """

    updated_baselines: set[str]
    """Set of baselines that were updated.

    These are the baselines that changed, but that were not created nor
    deleted: they existed before the rewriting, they exist after and their
    contents are different.
    """

    new_baselines: set[str]
    """Set of test names whose baseline was created."""

    deleted_baselines: set[str]
    """Set of test names whose baseline file was removed."""


class BaseBaselineRewriter(abc.ABC):
    """Base class to rewrite test baselines from testsuite results."""

    def __init__(self, colors: ColorConfig, default_encoding: str = "utf-8"):
        """Baseline rewriter constructor.

        :param colors: Color configuration for messages printed to sys.stderr.
        :param default_encoding: Default encoding to use in order to write
            baseline files.
        """
        self.colors = colors
        self.default_encoding = default_encoding

    @abc.abstractmethod
    def baseline_filename(self, test_name: str) -> str:
        """
        Return the filename that contains the baseline for the given test.

        :param test_name: Name of the test for which we want the baseline
            filename.
        """
        ...

    def postprocess_baseline(self, baseline: bytes) -> bytes:
        """Refine a baseline to rewrite.

        By default, this returns the argument unchanged. Subclasses can
        override this if they need to refine baselines.
        """
        return baseline

    def rewrite(self, results_dir: str) -> RewritingSummary:
        """Rewrite baselines from a testsuite report.

        :param results_dir: Name of the directory in which to read the test
            results used to update baselines. That directory can contain either
            a native e3-testsuite report index, or a GAIA report.
        :return: A summary of tests that were processed.
        """
        summary = RewritingSummary(set(), set(), set(), set())

        # Try to detect the report format present in the results dir...

        # Try to read a "native" e3-testsuite report index
        if os.path.exists(
            os.path.join(results_dir, ReportIndex.INDEX_FILENAME)
        ):
            self.rewrite_from_index(summary, ReportIndex.read(results_dir))
            return summary

        # Try to read results from a GAIA report
        gaia_results = glob.glob(os.path.join(results_dir, "*.result"))
        if gaia_results:
            self.rewrite_from_gaia(summary, gaia_results)
            return summary

        raise RewritingError(
            f"could not find testsuite results in {results_dir}"
        )

    def rewrite_from_index(
        self, summary: RewritingSummary, index: ReportIndex
    ) -> None:
        """Rewrite baselines from a native e3-testsuite report index."""
        for test_name, entry in index.entries.items():
            # Only rewrite the output of (not expected) failed tests, and which
            # failed because of a DIFF
            if entry.status == TestStatus.FAIL:
                if entry.failure_reasons != {FailureReason.DIFF}:
                    self.handle_test_error(
                        summary,
                        test_name,
                        "test failed for another reason than a diff",
                    )
                    continue

                result = entry.load()

                # In case the output is a string, we need its encoding to write
                # it down to a file.
                assert result.env is not None
                encoding = result.env.get("encoding", self.default_encoding)

                if result.out is None:
                    self.handle_test_error(
                        summary,
                        test_name,
                        "no output associated to test result",
                    )
                    continue
                assert isinstance(result.out, (bytes, str))
                self.handle_test_diff(summary, test_name, result.out, encoding)

            elif entry.status == TestStatus.ERROR:
                self.handle_test_error(
                    summary, test_name, "test aborted because of an error"
                )

    def rewrite_from_gaia(
        self, summary: RewritingSummary, results: list[str]
    ) -> None:
        """Rewrite baselines from a GAIA report."""
        for filename in results:
            test_name = os.path.splitext(os.path.basename(filename))[0]

            with open(filename) as result_fp:
                # According to the GAIA format documentation, this file should
                # contain "TEST_STATUS:COMMENT", but in practice it contains
                # only a single letter for the status. Tolerate both.
                serialized_result = result_fp.read().strip()
                if len(serialized_result) == 1:
                    status = {
                        "O": "OK",
                        "I": "FAIL",
                        "X": "XFAIL",
                        "U": "UOK",
                        "T": "VERIFY",
                        "N": "DEAD",
                        "n": "NOT-APPLICABLE",
                        "C": "PROBLEM",  # Could also be CRASH/TIMEOUT
                        "D": "DIFF",
                    }[serialized_result]
                else:
                    status = serialized_result.split(":", 1)[0]

            # Consider that there is a diff if we get a DIFF ("D")
            if status == "DIFF":
                # Fetch the new baseline: look for an X.out file in the same
                # directory as "filename" (X.result). If not found, consider
                # that the new baseline is empty.
                new_baseline = b""
                out_file = os.path.join(
                    os.path.dirname(filename), f"{test_name}.out"
                )
                if os.path.exists(out_file):
                    with open(out_file, "rb") as baseline_fp:
                        new_baseline = baseline_fp.read()

                self.handle_test_diff(
                    summary, test_name, new_baseline, self.default_encoding
                )

            # Consider that the test aborted because of a fatal error if we get
            # a CRASH/PROBLEM/TIMEOUT ('C') or a simple FAIL.
            elif status == "PROBLEM":
                self.handle_test_error(
                    summary, test_name, "test status is CRASH/PROBLEM/TIMEOUT"
                )

    def handle_test_error(
        self, summary: RewritingSummary, test_name: str, reason: str
    ) -> None:
        """Notify users that a test result is an error."""
        summary.errors.add(test_name)
        self.print_warning(f"cannot update baseline for {test_name}: {reason}")

    def handle_test_diff(
        self,
        summary: RewritingSummary,
        test_name: str,
        new_baseline: bytes | str,
        encoding: str,
    ) -> None:
        """Rewrite the baseline of a single test."""
        filename = self.baseline_filename(test_name)
        baseline_exists = os.path.exists(filename)

        baseline_bytes = self.postprocess_baseline(
            new_baseline
            if isinstance(new_baseline, bytes)
            else new_baseline.encode(encoding)
        )
        if baseline_bytes:
            if baseline_exists:
                summary.updated_baselines.add(test_name)
            else:
                self.print_info(
                    f"no baseline file for {test_name}, creating it"
                )
                summary.new_baselines.add(test_name)
            with open(filename, "wb") as f:
                f.write(baseline_bytes)

        else:
            if baseline_exists:
                self.print_info(
                    f"baseline file found for {test_name}, deleting it"
                )
                summary.deleted_baselines.add(test_name)
                os.unlink(filename)

    def print_stderr(self, message: str, prefix: str, style: str = "") -> None:
        print(
            f"{style}{prefix}{self.colors.Style.RESET_ALL}: {message}",
            file=sys.stderr,
        )

    def print_info(self, message: str) -> None:
        self.print_stderr(message, "INFO")

    def print_warning(self, message: str) -> None:
        self.print_stderr(message, "WARNING", self.colors.Fore.YELLOW)

    def print_error(self, message: str) -> None:
        self.print_stderr(
            message,
            "ERROR",
            self.colors.Fore.RED + self.colors.Style.BRIGHT,
        )
