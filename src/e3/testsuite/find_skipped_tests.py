import argparse
from typing import List, Optional, Set

from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import TestStatus


args_parser = argparse.ArgumentParser(
    description="Look for testcases that are always skipped in a set of"
    " testsuite reports."
)
args_parser.add_argument(
    "reports",
    metavar="RESULT_DIR",
    nargs="+",
    help="Directory that contains the report to load.",
)


def always_skipped_tests(reports: List[ReportIndex]) -> Set[str]:
    """Return the set of test names in ``reports`` that are always skipped."""
    skipped_once = set()
    not_skipped_once = set()
    for r in reports:
        for e in r.entries.values():
            if e.status == TestStatus.SKIP:
                skipped_once.add(e.test_name)
            else:
                not_skipped_once.add(e.test_name)
    return skipped_once - not_skipped_once


def main(argv: Optional[List[str]] = None) -> None:
    args = args_parser.parse_args(argv)
    tests = always_skipped_tests([ReportIndex.read(d) for d in args.reports])
    if tests:
        print("The following tests are never executed:")
        for t in sorted(tests):
            print("  {}".format(t))
    else:
        print("All testcases are executed at least once.")


if __name__ == "__main__":  # interactive-only
    main()
