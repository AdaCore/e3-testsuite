from __future__ import annotations

import argparse
from enum import Enum
import os.path
import sys
from typing import (
    Callable,
    Dict,
    IO,
    Optional,
    List,
    Protocol,
    Set,
    Tuple,
    TypeVar,
)

from e3.testsuite.report.index import ReportIndex, ReportIndexEntry
from e3.testsuite.report.xunit import dump_xunit_report
from e3.testsuite.result import (
    FailureReason,
    TestResult,
    TestResultSummary,
    TestStatus,
)
from e3.testsuite.utils import ColorConfig


args_parser = argparse.ArgumentParser(
    description="Display the results of a testsuite."
)
args_parser.add_argument(
    "--force-colors",
    "-C",
    action="store_true",
    help="Force the use of colors in the output.",
)
args_parser.add_argument(
    "--all-logs",
    "-a",
    action="store_true",
    help="Show logs for all tests, even if successful.",
)
args_parser.add_argument(
    "--xfail-logs", action="store_true", help="Display the log of XFAIL tests."
)
args_parser.add_argument(
    "--show-error-output",
    "-E",
    action="store_true",
    dest="show_error_output",
    default=True,
    help="Display the log of test failures. Enabled by default.",
)
args_parser.add_argument(
    "--no-error-output",
    action="store_false",
    dest="show_error_output",
    help="Do not display test output logs.",
)
args_parser.add_argument(
    "--show-time-info",
    action="store_true",
    help="Display time information for test results, if available.",
)
args_parser.add_argument(
    "--xunit-name",
    dest="xunit_name",
    metavar="NAME",
    default="Untitled testsuite",
    help="Name to use as the XUnit report name.",
)
args_parser.add_argument(
    "--xunit-output",
    dest="xunit_output",
    metavar="FILE",
    help="Output testsuite report to the given file in the standard XUnit XML"
    " format. This is useful to display results in continuous build systems"
    " such as Jenkins.",
)
args_parser.add_argument(
    "--old-result-dir",
    help="Directory that contains the report from a previous testsuite run. If"
    " passed, used to compute the new/already-detected/fixed regressions.",
)
args_parser.add_argument(
    "report",
    metavar="RESULT_DIR",
    nargs="?",
    default=os.path.join("out", "new"),
    help="Directory that contains the report to load. By default, use"
    " 'out/new' from the current directory.",
)
args_parser.add_argument(
    "--failure-exit-code",
    metavar="N",
    type=int,
    default=0,
    help="Exit code to use when at least one test result shows a"
    " failure/error. By default, this is 0. This option is useful when running"
    " this script in a continuous integration setup, as this can make the"
    " testing process stop when there is a regression.",
)


class SupportsLessThan(Protocol):
    def __lt__(self, other: SupportsLessThan) -> bool: ...


KeyType = TypeVar("KeyType")


def sorted_counters(
    counters: Dict[KeyType, int], key: Callable[[KeyType], SupportsLessThan]
) -> List[Tuple[KeyType, int]]:
    """Filter out the set of null counters and sort them."""
    return sorted(
        ((key, count) for key, count in counters.items() if count),
        key=lambda couple: key(couple[0]),
    )


def summary_line(
    result: TestResultSummary, colors: ColorConfig, show_time_info: bool
) -> str:
    """Format a summary line to describe the ``result`` test result.

    :param colors: Proxy to introduce (or not) colors in the result.
    :param show_time_info: Whether to include timing information in the result.
    """
    if show_time_info and result.time is not None:
        seconds = int(result.time)
        time_info = "{:>02}m{:>02}s".format(seconds // 60, seconds % 60)
    else:
        time_info = ""

    line = "{}{:<8}{} {}{:>6}{} {}{}{}".format(
        result.status.color(colors),
        result.status.name,
        colors.Style.RESET_ALL,
        colors.Style.DIM,
        time_info,
        colors.Style.NORMAL,
        colors.Style.BRIGHT,
        result.test_name,
        colors.Style.NORMAL,
    )
    if result.msg:
        line += ": {}{}{}".format(
            colors.Style.DIM, result.msg, colors.Style.NORMAL
        )

    return line


def format_result_logs(
    result: TestResult,
    colors: ColorConfig,
    show_error_output: bool,
    show_time_info: bool,
) -> List[str]:
    """Return a human readable description for the ``result`` test result.

    :param colors: Proxy to introduce (or not) colors in the result.
    :param show_error_output: Whether to include the logs themselves: if False,
        only show the test name, status, message and timing info if requested.
    :param show_time_info: Whether to include timing information in the result.
    """
    first_line = summary_line(result.summary, colors, show_time_info)

    # If the caller has not requested logs, just return the summary line
    if not show_error_output:
        return [first_line]

    # To clearly isolate the first line from logs, frame it with horizontal
    # lines, indent the logs and insert empty lines before and after them.
    sep_line = "-" * 79
    lines = [sep_line, first_line, sep_line, ""]

    log = str(result.diff if result.diff else result.log)
    if log:
        lines.append(log)
    else:
        lines.append(f"{colors.Style.DIM}<all logs are empty>")
    lines.append(colors.Style.RESET_ALL)

    return lines


def generate_report(
    output_file: IO[str],
    new_index: ReportIndex,
    old_index: Optional[ReportIndex],
    colors: ColorConfig,
    show_all_logs: bool,
    show_xfail_logs: bool,
    show_error_output: bool,
    show_time_info: bool,
) -> None:
    """Generate a text report for testsuite results.

    :param output_file: Output file for the report.
    :param new_index: Testsuite results to display.
    :param old_index: Results from a previous testsuite run. If present, used
        to compute the new/already-detected/fixed regressions.
    :param colors: Color configuration for the output.
    :param show_all_logs: Whether to display logs for all testcases (successful
        tests are not displayed by default).
    :param show_xfail_logs: Whether to display logs for XFAIL results (hidden
        by default).
    :param show_error_output: Whether to display logs in test results.
    :param show_time_info: Whether to display time information for test
        results, if available.
    """
    # For each test name, list of lines for the results to include in the
    # detailed report (i.e. the part that follows the summary).
    results_display: Dict[str, List[str]] = {}

    # List of test names, in the order in which their results should be
    # displayed (failures first in the summary order, then non-failures if
    # requested).
    ordered_entries: List[str] = []

    count_results = len(new_index.entries)
    count_executed = 0
    count_failure_reasons: Dict[FailureReason, int] = {
        reason: 0 for reason in FailureReason
    }

    # Lists of results of interest (users may want to investigate them
    # further).
    new_failures: List[ReportIndexEntry] = []
    already_detected_failures: List[ReportIndexEntry] = []
    fixed_failures: List[ReportIndexEntry] = []
    xfail: List[ReportIndexEntry] = []
    xpass: List[ReportIndexEntry] = []
    verify: List[ReportIndexEntry] = []
    error: List[ReportIndexEntry] = []

    # Collect information from all entries
    for _, entry in sorted(new_index.entries.items()):
        # Since this is costly, load the TestResult from disk on demand
        result: Optional[TestResult] = None

        if entry.status != TestStatus.SKIP:
            count_executed += 1

        if entry.status == TestStatus.FAIL:
            # Account for entry in failure reason counters
            result = result or entry.load()
            for reason in result.failure_reasons:
                count_failure_reasons[reason] += 1

            # Register entry in the relevant failure category. Note that if
            # there is no old entry, we still consider that the failure is a
            # new one.
            old_entry = (
                old_index.entries.get(entry.test_name) if old_index else None
            )
            if old_entry:
                if old_entry.status == TestStatus.FAIL:
                    already_detected_failures.append(entry)
                else:
                    new_failures.append(entry)
            else:
                new_failures.append(entry)

        elif entry.status == TestStatus.XFAIL:
            xfail.append(entry)
        elif entry.status == TestStatus.XPASS:
            xpass.append(entry)
        elif entry.status == TestStatus.VERIFY:
            verify.append(entry)
        elif entry.status == TestStatus.ERROR:
            error.append(entry)

        # If this is a successful testcase that was failing in the previous
        # run, classify it as a "fixed failure".
        if old_index and entry.status == TestStatus.PASS:
            old_entry = old_index.entries.get(entry.test_name)
            if old_entry and old_entry.status == TestStatus.FAIL:
                fixed_failures.append(entry)

        # Unless they are requested, do not display results for successful
        # tests or XFAILed ones.
        if (
            entry.status
            in (TestStatus.PASS, TestStatus.XPASS, TestStatus.SKIP)
            and not show_all_logs
        ) or (
            entry.status == TestStatus.XFAIL
            and not show_all_logs
            and not show_xfail_logs
        ):
            continue

        result = result or entry.load()
        results_display[entry.test_name] = format_result_logs(
            result, colors, show_error_output, show_time_info
        )

    # Write the summary
    print(
        f"{colors.Style.BRIGHT}Summary:{colors.Style.NORMAL}\n",
        file=output_file,
    )
    print(f"  Out of {count_results} results", file=output_file)
    print(f"  {count_executed} executed (not skipped)", file=output_file)

    # Display test count for each status, but only for status that have
    # at least one test. Sort them by status value, to get consistent
    # order.

    def get_key(enum: Enum) -> SupportsLessThan:
        return enum.value

    stats = sorted_counters(new_index.status_counters, key=get_key)
    failure_reason_stats = sorted_counters(count_failure_reasons, key=get_key)

    if stats:
        # If this information is available, report new skipped tests and
        # removed tests.
        if old_index:

            def skip_entries(index: ReportIndex) -> Set[str]:
                return {
                    test_name
                    for test_name, entry in index.entries.items()
                    if entry.status == TestStatus.SKIP
                }

            new_skipped = len(
                skip_entries(new_index) - skip_entries(old_index)
            )
            removed = len(
                set(old_index.entries.keys()) - set(new_index.entries.keys())
            )

            print(f"  {new_skipped} new skipped test(s)", file=output_file)
            print(f"  {removed} removed test(s)", file=output_file)
            print("", file=output_file)

        # Report the number of results for each status (when the count is not
        # zero).
        for status, count in stats:
            show_reasons = failure_reason_stats and status == TestStatus.FAIL
            suffix = ", including:" if show_reasons else ""
            print(
                f"  {status.color(colors)}{status.name.ljust(12)}"
                f"{colors.Style.RESET_ALL} {count}{suffix}",
                file=output_file,
            )
            if show_reasons:
                for r, c in failure_reason_stats:
                    print(f"    {r.name.ljust(12)} {c}", file=output_file)
        print("", file=output_file)

        # Show the different categories of failures (new, already detected,
        # fixed) and in general results that users may want to inspect more
        # closely.
        if (
            new_failures
            or already_detected_failures
            or fixed_failures
            or xfail
            or xpass
            or verify
            or error
        ):
            print(
                "  The following results may need further investigation:",
                file=output_file,
            )

            def display_failures(
                kind: str,
                color: str,
                failures: List[ReportIndexEntry],
                display_if_empty: bool = False,
            ) -> None:
                if not display_if_empty and not failures:
                    return
                print(
                    f"  {color}{len(failures)} {kind}"
                    f"{colors.Style.RESET_ALL}:",
                    file=output_file,
                )
                for e in failures:
                    label = e.test_name
                    ordered_entries.append(label)
                    if e.msg:
                        label += (
                            f": {colors.Style.DIM}{e.msg}{colors.Style.NORMAL}"
                        )
                    print(f"    {label}", file=output_file)
                print("", file=output_file)

            # Always display the new failures as this is the category that
            # always make sense, even if there is no old index (assuming the
            # baseline is failure free).
            display_failures(
                "new failure(s)",
                colors.Fore.RED + colors.Style.BRIGHT,
                new_failures,
                display_if_empty=True,
            )
            display_failures(
                "already detected failure(s)",
                colors.Fore.RED,
                already_detected_failures,
            )
            display_failures(
                "fixed failure(s)", colors.Fore.GREEN, fixed_failures
            )
            display_failures("expected failure(s)", colors.Fore.CYAN, xfail)
            display_failures(
                "unexpected passed test(s)", colors.Fore.YELLOW, xpass
            )
            display_failures(
                "test(s) requiring additional verification",
                colors.Fore.YELLOW,
                verify,
            )
            display_failures(
                "test(s) aborted due to unknown error",
                colors.Fore.RED + colors.Style.BRIGHT,
                error,
            )

    else:
        print(
            f"  {colors.Style.DIM}<no test result>{colors.Style.NORMAL}\n",
            file=output_file,
        )

    # Display all non-failures at the end of the report
    non_failures = set(results_display) - set(ordered_entries)
    ordered_entries.extend(sorted(non_failures))

    # Finally, display results logs when relevant
    print(
        f"{colors.Style.BRIGHT}Result logs:{colors.Style.NORMAL}\n",
        file=output_file,
    )
    for test_name in ordered_entries:
        lines = results_display.get(test_name)
        if lines:
            for line in lines:
                print(line, file=output_file)
    if not results_display:
        print(
            f"{colors.Style.DIM}No relevant logs to display"
            f"{colors.Style.NORMAL}",
            file=output_file,
        )


def main(argv: Optional[List[str]] = None) -> int:
    args = args_parser.parse_args(argv)
    new_index = ReportIndex.read(args.report)
    old_index = (
        None
        if args.old_result_dir is None
        else ReportIndex.read(args.old_result_dir)
    )

    generate_report(
        output_file=sys.stdout,
        new_index=new_index,
        old_index=old_index,
        colors=ColorConfig(colors_enabled=args.force_colors or None),
        show_all_logs=args.all_logs,
        show_xfail_logs=args.xfail_logs,
        show_error_output=args.show_error_output,
        show_time_info=args.show_time_info,
    )

    if args.xunit_output:
        dump_xunit_report(args.xunit_name, new_index, args.xunit_output)

    # Return the appropriate status code: the failure status code from the
    # --failure-exit-code=N option when there is a least one testcase failure,
    # or 0.
    return args.failure_exit_code if new_index.has_failures else 0


if __name__ == "__main__":  # interactive-only
    main()
