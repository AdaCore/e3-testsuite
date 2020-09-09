"""Tests for the "e3-testsuite-report" script."""

import yaml

from e3.testsuite.report.display import main
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import Log, TestResult as Result, TestStatus as Status


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
    result = Result(name, status=status, msg=msg)
    result.log += log
    if diff is not None:
        result.diff = Log(diff)
    result.time = time
    return result


def run(results, argv, tmp_path, capsys):
    create_report(results, tmp_path)
    main(argv)
    captured = capsys.readouterr()
    assert not captured.err
    return captured.out


basic_results = [
    create_result("append", Status.PASS, time=1.0),
    create_result(
        "sub", Status.XFAIL, msg="Unexpected result", log="3 - 2 = 0"
    ),
    create_result(
        "mult",
        Status.FAIL,
        msg="Unexpected result",
        log="3 * 2 = 5",
        time=123.0,
    ),
    create_result(
        "div",
        Status.FAIL,
        msg="Unexpected output",
        log="Running the div...",
        diff="diff\n-4\n+5",
    ),
]


def test_basic(tmp_path, capsys):
    """Check that the script works fine in basic configurations."""
    assert run(basic_results, [str(tmp_path)], tmp_path, capsys) == (
        "FAIL            div: Unexpected output\n"
        "    diff\n"
        "    -4\n"
        "    +5\n"
        "FAIL            mult: Unexpected result\n"
        "    3 * 2 = 5\n"
    )


def test_all(tmp_path, capsys):
    """Check that the --all option works as expected."""
    assert run(basic_results, [str(tmp_path), "--all"], tmp_path, capsys) == (
        "PASS            append\n"
        "\n"
        "FAIL            div: Unexpected output\n"
        "    diff\n"
        "    -4\n"
        "    +5\n"
        "FAIL            mult: Unexpected result\n"
        "    3 * 2 = 5\n"
        "XFAIL           sub: Unexpected result\n"
        "    3 - 2 = 0\n"
    )


def test_time(tmp_path, capsys):
    """Check that the --show-time-info option works as expected."""
    assert run(
        basic_results, [str(tmp_path), "--show-time-info"], tmp_path, capsys
    ) == (
        "FAIL            div: Unexpected output\n"
        "    diff\n"
        "    -4\n"
        "    +5\n"
        "FAIL     02m03s mult: Unexpected result\n"
        "    3 * 2 = 5\n"
    )


def test_no_error_output(tmp_path, capsys):
    """Check that the --no-error-output option works as expected."""
    assert run(
        basic_results, [str(tmp_path), "--no-error-output"], tmp_path, capsys
    ) == (
        "FAIL            div: Unexpected output\n"
        "FAIL            mult: Unexpected result\n"
    )
