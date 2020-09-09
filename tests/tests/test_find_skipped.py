"""Tests for the "e3-find-skipped-tests" script."""

from e3.testsuite.find_skipped_tests import main
from e3.testsuite.result import TestStatus as Status

from .utils import create_report, create_result


def run(results_map, tmp_path, capsys):
    argv = []
    for dir_name, results in results_map.items():
        dir_path = tmp_path / dir_name
        dir_path.mkdir()
        create_report(results, dir_path)
        argv.append(str(dir_path))
    main(argv)
    captured = capsys.readouterr()
    assert not captured.err
    return captured.out


def test_no_skipped(tmp_path, capsys):
    assert (
        run(
            {
                "res1": [
                    create_result("foo", Status.SKIP),
                    create_result("bar", Status.PASS),
                ],
                "res2": [
                    create_result("foo", Status.XFAIL),
                    create_result("bar", Status.SKIP),
                ],
            },
            tmp_path,
            capsys,
        )
        == "All testcases are executed at least once.\n"
    )


def test_some_skipped(tmp_path, capsys):
    assert (
        run(
            {
                "res1": [
                    create_result("foo", Status.SKIP),
                    create_result("bar", Status.PASS),
                    create_result("baz", Status.SKIP),
                ],
                "res2": [
                    create_result("foo", Status.XFAIL),
                    create_result("bar", Status.SKIP),
                    create_result("qux", Status.SKIP),
                ],
            },
            tmp_path,
            capsys,
        )
        == "The following tests are never executed:\n  baz\n  qux\n"
    )
