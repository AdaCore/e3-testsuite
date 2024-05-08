"""Tests for the "e3-testsuite-report" script."""

import os.path
import shutil
import xml.etree.ElementTree as ET

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.report.display import generate_report, main
from e3.testsuite.result import FailureReason, TestStatus as Status
from e3.testsuite.utils import ColorConfig

from .utils import create_report, create_result, run_testsuite


def run_status(results, argv, tmp_path, capsys):
    create_report(results, tmp_path)
    status = main(argv)
    captured = capsys.readouterr()
    assert not captured.err
    return status, captured.out


def run(results, argv, tmp_path, capsys, expect_failure=False):
    status, out = run_status(results, argv, tmp_path, capsys)
    if expect_failure:
        assert status != 0
    else:
        assert status == 0
    return out


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

sep_line = "-" * 79


class MyDriver(BasicDriver):
    return_status = Status.PASS

    def run(self, prev, slot):
        pass

    def analyze(self, prev, slot):
        self.result.set_status(Status.PASS)
        self.push_result()


class Mysuite(Suite):
    tests_subdir = "simple-tests"
    test_driver_map = {"default": MyDriver}

    @property
    def default_driver(self):
        return "default"


def test_basic(tmp_path, capsys):
    """Check that the script works fine in basic configurations."""
    assert run(basic_results, [str(tmp_path)], tmp_path, capsys) == (
        "Summary:\n"
        "\n"
        "  Out of 4 results\n"
        "  4 executed (not skipped)\n"
        "  PASS         1\n"
        "  FAIL         2\n"
        "  XFAIL        1\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  2 new failure(s):\n"
        "    div: Unexpected output\n"
        "    mult: Unexpected result\n"
        "\n"
        "  1 expected failure(s):\n"
        "    sub: Unexpected result\n"
        "\n"
        "Result logs:\n"
        "\n"
        f"{sep_line}\n"
        "FAIL            div: Unexpected output\n"
        f"{sep_line}\n"
        "\n"
        "diff\n"
        "-4\n"
        "+5\n"
        "\n"
        f"{sep_line}\n"
        "FAIL            mult: Unexpected result\n"
        f"{sep_line}\n"
        "\n"
        "3 * 2 = 5\n"
        "\n"
    )


def test_empty(tmp_path, capsys):
    """Check the output for empty reports."""
    assert run([], [str(tmp_path)], tmp_path, capsys) == (
        "Summary:\n"
        "\n"
        "  Out of 0 results\n"
        "  0 executed (not skipped)\n"
        "  <no test result>\n"
        "\n"
        "Result logs:\n"
        "\n"
        "No relevant logs to display\n"
    )


def test_all(tmp_path, capsys):
    """Check that the --all option works as expected."""
    assert run(basic_results, [str(tmp_path), "--all"], tmp_path, capsys) == (
        "Summary:\n"
        "\n"
        "  Out of 4 results\n"
        "  4 executed (not skipped)\n"
        "  PASS         1\n"
        "  FAIL         2\n"
        "  XFAIL        1\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  2 new failure(s):\n"
        "    div: Unexpected output\n"
        "    mult: Unexpected result\n"
        "\n"
        "  1 expected failure(s):\n"
        "    sub: Unexpected result\n"
        "\n"
        "Result logs:\n"
        "\n"
        f"{sep_line}\n"
        "FAIL            div: Unexpected output\n"
        f"{sep_line}\n"
        "\n"
        "diff\n"
        "-4\n"
        "+5\n"
        "\n"
        f"{sep_line}\n"
        "FAIL            mult: Unexpected result\n"
        f"{sep_line}\n"
        "\n"
        "3 * 2 = 5\n"
        "\n"
        f"{sep_line}\n"
        "XFAIL           sub: Unexpected result\n"
        f"{sep_line}\n"
        "\n"
        "3 - 2 = 0\n"
        "\n"
        f"{sep_line}\n"
        "PASS            append\n"
        f"{sep_line}\n"
        "\n"
        "<all logs are empty>\n"
        "\n"
    )


def test_time(tmp_path, capsys):
    """Check that the --show-time-info option works as expected."""
    assert run(
        basic_results, [str(tmp_path), "--show-time-info"], tmp_path, capsys
    ) == (
        "Summary:\n"
        "\n"
        "  Out of 4 results\n"
        "  4 executed (not skipped)\n"
        "  PASS         1\n"
        "  FAIL         2\n"
        "  XFAIL        1\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  2 new failure(s):\n"
        "    div: Unexpected output\n"
        "    mult: Unexpected result\n"
        "\n"
        "  1 expected failure(s):\n"
        "    sub: Unexpected result\n"
        "\n"
        "Result logs:\n"
        "\n"
        f"{sep_line}\n"
        "FAIL            div: Unexpected output\n"
        f"{sep_line}\n"
        "\n"
        "diff\n"
        "-4\n"
        "+5\n"
        "\n"
        f"{sep_line}\n"
        "FAIL     02m03s mult: Unexpected result\n"
        f"{sep_line}\n"
        "\n"
        "3 * 2 = 5\n"
        "\n"
    )


def test_no_error_output(tmp_path, capsys):
    """Check that the --no-error-output option works as expected."""
    assert run(
        basic_results, [str(tmp_path), "--no-error-output"], tmp_path, capsys
    ) == (
        "Summary:\n"
        "\n"
        "  Out of 4 results\n"
        "  4 executed (not skipped)\n"
        "  PASS         1\n"
        "  FAIL         2\n"
        "  XFAIL        1\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  2 new failure(s):\n"
        "    div: Unexpected output\n"
        "    mult: Unexpected result\n"
        "\n"
        "  1 expected failure(s):\n"
        "    sub: Unexpected result\n"
        "\n"
        "Result logs:\n"
        "\n"
        "FAIL            div: Unexpected output\n"
        "FAIL            mult: Unexpected result\n"
    )


def test_failure_reasons(tmp_path, capsys):
    """Check that we report stats about failure reasons."""
    results = [
        create_result(
            "crash", Status.FAIL, failure_reasons={FailureReason.CRASH}
        ),
        create_result(
            "diff", Status.FAIL, failure_reasons={FailureReason.DIFF}
        ),
        create_result(
            "diff-memcheck",
            Status.FAIL,
            failure_reasons={FailureReason.DIFF, FailureReason.MEMCHECK},
        ),
    ]

    assert run(
        results,
        [str(tmp_path), "--no-error-output"],
        str(tmp_path),
        capsys,
    ) == (
        "Summary:\n"
        "\n"
        "  Out of 3 results\n"
        "  3 executed (not skipped)\n"
        "  FAIL         3, including:\n"
        "    CRASH        1\n"
        "    MEMCHECK     1\n"
        "    DIFF         2\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  3 new failure(s):\n"
        "    crash\n"
        "    diff\n"
        "    diff-memcheck\n"
        "\n"
        "Result logs:\n"
        "\n"
        "FAIL            crash\n"
        "FAIL            diff\n"
        "FAIL            diff-memcheck\n"
    )


def test_old_result(tmp_path, capsys):
    """Check that --old-result-dir works as expected."""
    old_results = [
        create_result("fail-to-pass", Status.FAIL),
        create_result("fail-to-xfail", Status.FAIL),
        create_result("fail-to-xpass", Status.FAIL),
        create_result("fail-to-fail", Status.FAIL),
        create_result("pass-to-fail", Status.PASS),
        create_result("pass-to-pass", Status.PASS),
        create_result("pass-to-xfail", Status.PASS),
        create_result("pass-to-xpass", Status.PASS),
        create_result("skip-to-skip", Status.SKIP),
        create_result("skip-to-pass", Status.SKIP),
        create_result("skip-to-fail", Status.SKIP),
        create_result("xfail-to-skip", Status.XFAIL),
        create_result("xfail-to-pass", Status.XFAIL),
        create_result("xfail-to-fail", Status.XFAIL),
        create_result("xfail-to-xfail", Status.XFAIL),
        create_result("removed", Status.PASS),
    ]
    new_results = [
        create_result("fail-to-pass", Status.PASS),
        create_result("fail-to-xfail", Status.XFAIL),
        create_result("fail-to-xpass", Status.XPASS),
        create_result("fail-to-fail", Status.FAIL),
        create_result("pass-to-fail", Status.FAIL),
        create_result("pass-to-pass", Status.PASS),
        create_result("pass-to-xfail", Status.XFAIL),
        create_result("pass-to-xpass", Status.XPASS),
        create_result("skip-to-skip", Status.SKIP),
        create_result("skip-to-pass", Status.PASS),
        create_result("skip-to-fail", Status.FAIL),
        create_result("xfail-to-skip", Status.SKIP),
        create_result("xfail-to-pass", Status.PASS),
        create_result("xfail-to-fail", Status.FAIL),
        create_result("xfail-to-xfail", Status.XFAIL),
        create_result("to-verify", Status.VERIFY),
        create_result("not-applicable-test", Status.NOT_APPLICABLE),
        create_result("error", Status.ERROR),
    ]

    # Create a report for old results
    tmp_path = str(tmp_path)
    old_result_dir = os.path.join(tmp_path, "old")
    os.mkdir(old_result_dir)
    create_report(old_results, old_result_dir)

    new_result_dir = os.path.join(tmp_path, "new")
    os.mkdir(new_result_dir)
    assert run(
        new_results,
        [
            new_result_dir,
            "--no-error-output",
            "--old-result-dir",
            old_result_dir,
        ],
        new_result_dir,
        capsys,
    ) == (
        "Summary:\n"
        "\n"
        "  Out of 18 results\n"
        "  16 executed (not skipped)\n"
        "  1 new skipped test(s)\n"
        "  1 removed test(s)\n"
        "\n"
        "  PASS         4\n"
        "  FAIL         4\n"
        "  XFAIL        3\n"
        "  XPASS        2\n"
        "  VERIFY       1\n"
        "  SKIP         2\n"
        "  NOT_APPLICABLE 1\n"
        "  ERROR        1\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  3 new failure(s):\n"
        "    pass-to-fail\n"
        "    skip-to-fail\n"
        "    xfail-to-fail\n"
        "\n"
        "  1 already detected failure(s):\n"
        "    fail-to-fail\n"
        "\n"
        "  1 fixed failure(s):\n"
        "    fail-to-pass\n"
        "\n"
        "  3 expected failure(s):\n"
        "    fail-to-xfail\n"
        "    pass-to-xfail\n"
        "    xfail-to-xfail\n"
        "\n"
        "  2 unexpected passed test(s):\n"
        "    fail-to-xpass\n"
        "    pass-to-xpass\n"
        "\n"
        "  1 test(s) requiring additional verification:\n"
        "    to-verify\n"
        "\n"
        "  1 test(s) aborted due to unknown error:\n"
        "    error\n"
        "\n"
        "Result logs:\n"
        "\n"
        "FAIL            pass-to-fail\n"
        "FAIL            skip-to-fail\n"
        "FAIL            xfail-to-fail\n"
        "FAIL            fail-to-fail\n"
        "VERIFY          to-verify\n"
        "ERROR           error\n"
        "NOT_APPLICABLE        not-applicable-test\n"
    )


def test_generate_text_report(tmp_path):
    """Check TestsuiteCore's --generate-text-report option."""
    tmp_path = str(tmp_path)

    def check_report(expected):
        with open(os.path.join(tmp_path, "new", "report")) as f:
            assert f.read() == expected

    args = [
        "--generate-text-report",
        "--output-dir",
        tmp_path,
        "--rotate-output-dirs",
    ]

    # First run the testsuite with no previous results
    run_testsuite(Mysuite, args=args)
    check_report(
        "Summary:\n"
        "\n"
        "  Out of 2 results\n"
        "  2 executed (not skipped)\n"
        "  PASS         2\n"
        "\n"
        "Result logs:\n"
        "\n"
        "No relevant logs to display\n"
    )

    # Replace the "new" report with other data and then re-run the testsuite in
    # the same result dir, to exercize results comparison in the generated
    # report.
    new_result_dir = os.path.join(tmp_path, "new")
    shutil.rmtree(new_result_dir)
    os.mkdir(new_result_dir)
    create_report(
        [
            create_result("test1", Status.PASS),
            create_result("test2", Status.FAIL),
        ],
        new_result_dir,
    )

    run_testsuite(Mysuite, args=args)
    check_report(
        "Summary:\n"
        "\n"
        "  Out of 2 results\n"
        "  2 executed (not skipped)\n"
        "  0 new skipped test(s)\n"
        "  0 removed test(s)\n"
        "\n"
        "  PASS         2\n"
        "\n"
        "  The following results may need further investigation:\n"
        "  0 new failure(s):\n"
        "\n"
        "  1 fixed failure(s):\n"
        "    test2\n"
        "\n"
        "Result logs:\n"
        "\n"
        "No relevant logs to display\n"
    )


def test_auto_generate(tmp_path):
    """Check TestsuiteCore's auto_generate_text_report property."""

    def check_report(report_expected):
        assert (tmp_path / "new" / "report").exists() == report_expected

    class MyDerivedSuite(Mysuite):
        auto_generate_text_report = True

    args = [f"--output-dir={tmp_path}"]

    # First run the testsuite with no arg: we expect the text report to be
    # automatically generated.
    run_testsuite(MyDerivedSuite, args=args)
    check_report(True)
    shutil.rmtree(str(tmp_path / "new"))

    # Disable its generation on the command line and make sure it's not
    # generated
    run_testsuite(MyDerivedSuite, args=args + ["--no-generate-text-report"])
    check_report(False)


def test_failure_exit_code(tmp_path, capsys):
    """Check that --failure-exit-code works as expected."""

    def check(statuses, expected_exit_code):
        status, _ = run_status(
            [
                create_result(f"t{i}", status)
                for i, status in enumerate(statuses)
            ],
            ["--failure-exit-code=10", str(tmp_path)],
            tmp_path,
            capsys,
        )
        assert status == expected_exit_code

    check([Status.PASS, Status.PASS, Status.XFAIL, Status.SKIP], 0)
    check([Status.PASS, Status.FAIL], 10)
    check([Status.PASS, Status.ERROR], 10)
    check([Status.FAIL, Status.ERROR], 10)


def test_xunit_output(tmp_path, capsys):
    """Check that --xunit-output generates a report."""
    xunit_file = str(tmp_path / "xunit.xml")
    run(
        [create_result("foo", Status.PASS)],
        ["--xunit-output", xunit_file, str(tmp_path)],
        tmp_path,
        capsys,
    )

    # Just check that this produces a valid XML file
    ET.parse(xunit_file)


def test_xunit_name(tmp_path, capsys):
    """Check that --xunit-name has the desired effect."""
    xunit_file = str(tmp_path / "xunit.xml")
    testsuite_name = "mytestsuite"
    run(
        [create_result("foo", Status.PASS)],
        [
            "--xunit-output",
            xunit_file,
            "--xunit-name",
            testsuite_name,
            str(tmp_path),
        ],
        tmp_path,
        capsys,
    )

    xml = ET.parse(xunit_file)
    root = xml.getroot()

    # Check the root node
    assert root.tag == "testsuites"
    assert root.get("name") == testsuite_name

    # Check the invididual testsuites
    testsuites = xml.findall(".//testsuite")
    assert len(testsuites) != 0
    assert all(e.get("name") == testsuite_name for e in testsuites)

    # Check the invidiual tests
    tests = xml.findall(".//testcase")
    assert len(tests) != 0
    assert all(e.get("classname") == testsuite_name for e in tests)


def test_output_file(tmp_path, capsys):
    """Check that nothing is printed on stdout when output is a file."""
    create_report(
        [
            create_result(
                "foo", Status.FAIL, msg="Problem", log="This test failed"
            )
        ],
        tmp_path,
    )
    index = ReportIndex.read(str(tmp_path))
    filename = str(tmp_path / "report.txt")
    with open(filename, "w") as f:
        generate_report(
            output_file=f,
            new_index=index,
            old_index=None,
            colors=ColorConfig(colors_enabled=False),
            show_all_logs=True,
            show_xfail_logs=True,
            show_error_output=True,
            show_time_info=True,
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

    with open(filename) as f:
        assert f.read() == (
            "Summary:\n"
            "\n"
            "  Out of 1 results\n"
            "  1 executed (not skipped)\n"
            "  FAIL         1\n"
            "\n"
            "  The following results may need further investigation:\n"
            "  1 new failure(s):\n"
            "    foo: Problem\n"
            "\n"
            "Result logs:\n"
            "\n"
            "-----------------------------------------------------------------"
            "--------------\n"
            "FAIL            foo: Problem\n"
            "-----------------------------------------------------------------"
            "--------------\n"
            "\n"
            "This test failed\n"
            "\n"
        )
