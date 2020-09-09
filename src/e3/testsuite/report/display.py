import argparse
import os.path
from typing import Optional, List

from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import TestResult, TestStatus
from e3.testsuite.utils import ColorConfig


args_parser = argparse.ArgumentParser(
    description="Display the results of a testsuite.")
args_parser.add_argument(
    "--all", "-a", action="store_true",
    help="Show all tests, even if successful."
)
args_parser.add_argument(
    "--show-error-output", "-E", action="store_true", dest="show_error_output",
    default=True,
    help="Display the log of test failures. Enabled by default."
)
args_parser.add_argument(
    "--no-error-output", action="store_false", dest="show_error_output",
    help="Do not display test output logs."
)
args_parser.add_argument(
    "--show-time-info", action="store_true",
    help="Display time information for test results, if available."
)
args_parser.add_argument(
    "report", metavar="RESULT_DIR", nargs="?",
    default=os.path.join("out", "new"),
    help="Directory that contains the report to load. By default, use"
         " 'out/new' from the current directory."
)


def summary_line(result: TestResult,
                 colors: ColorConfig,
                 show_time_info: bool) -> str:
    """Format a summary line to describe the ``result`` test result.

    :param colors: Proxy to introduce (or not) colors in the result.
    :param show_time_info: Whether to include timing information in the result.
    """
    if show_time_info and result.time is not None:
        seconds = int(result.time)
        time_info = '{:>02}m{:>02}s'.format(seconds // 60,
                                            seconds % 60)
    else:
        time_info = ''

    line = '{}{:<8}{} {}{:>6}{} {}{}{}'.format(
        result.status.color(colors),
        result.status.name,
        colors.Style.RESET_ALL,

        colors.Style.DIM,
        time_info,
        colors.Style.RESET_ALL,

        colors.Style.BRIGHT,
        result.test_name,
        colors.Style.RESET_ALL)
    if result.msg:
        line += ': {}{}{}'.format(colors.Style.DIM, result.msg,
                                  colors.Style.RESET_ALL)
    return line


def main(argv: Optional[List[str]] = None) -> None:
    args = args_parser.parse_args(argv)
    report = ReportIndex.read(args.report)
    colors = ColorConfig()

    status_to_display = {TestStatus.FAIL, TestStatus.VERIFY,
                         TestStatus.NOT_APPLICABLE, TestStatus.ERROR}

    for _, entry in sorted(report.entries.items()):
        if not args.all and entry.status not in status_to_display:
            continue

        result = entry.load()
        log_line = summary_line(result, colors, args.show_time_info)

        if args.show_error_output:
            log = str(result.diff if result.diff else result.log)
            log_line += "\n"
            log_line += '\n'.join(
                "    {}".format(line) for line in log.splitlines()
            )
            log_line += colors.Style.RESET_ALL

        print(log_line)


if __name__ == '__main__':  # interactive-only
    main()
