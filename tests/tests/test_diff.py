"""Tests for the e3.testsuite.driver.diff module."""

import os.path
import shutil
import sys
import tempfile

from e3.testsuite import Testsuite as Suite
import e3.testsuite.driver.adacore as adacore
import e3.testsuite.driver.diff as diff
from e3.testsuite.result import TestStatus as Status
from e3.testsuite.testcase_finder import ParsedTest

from .utils import create_testsuite, extract_results, run_testsuite


class DiffScriptDriver(diff.DiffTestDriver):
    """Driver to check test output with DiffTestDriver."""

    helper_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "classic-tests", "script.py")
    )

    @property
    def refine_baseline(self):
        return self.test_env.get("refine_baseline", False)

    @property
    def output_refiners(self):
        result = super().output_refiners

        for path, replacement in self.test_env.get("path_substitutions", []):
            result += [diff.ReplacePath(self.working_dir(path), replacement)]

        if self.refine_baseline:
            result += [
                diff.Substitute("baseline_to_refine", "refined"),
                diff.Substitute("actual_to_refine", "refined"),
            ]

        return result

    def set_up(self):
        super(DiffScriptDriver, self).set_up()
        self.process_args = self.test_env["process_args"]

    def run(self):
        self.shell([sys.executable, self.helper_script] + self.process_args)


def test_diff():
    """Check that DiffTestDriver works as expected."""

    class Mysuite(Suite):
        tests_subdir = "diff-tests"
        test_driver_map = {"diff-script-driver": DiffScriptDriver}

    suite = run_testsuite(Mysuite, args=["-E"], expect_failure=True)
    assert extract_results(suite) == {
        "plain-pass": Status.PASS,
        "plain-fail": Status.FAIL,
        "binary": Status.PASS,
        # Check that binary diffs are based on equally escaped outputs: the
        # b"\\xe9" process output is different from the b"\xe9" baseline.
        "binary-2": Status.FAIL,
        "regexp-pass": Status.PASS,
        "regexp-fail": Status.FAIL,
        "regexp-binary-pass": Status.PASS,
        "regexp-binary-fail": Status.FAIL,
        "missing-baseline": Status.ERROR,
        "path-substitution": Status.PASS,
        "line-endings": Status.PASS,
        "line-endings-binary": Status.PASS,
        "line-endings-strict": Status.FAIL,
        "refine-baseline": Status.PASS,
    }


def test_diff_context_size():
    """Check handling for the diff_context_size setting."""
    baseline = "".join(f"{i}\n" for i in range(100))
    actual = "".join(f"{i}\n" for i in range(100) if i != 20)

    def create_test(name, driver, test_env):
        return ParsedTest(name, driver, test_env, ".", None)

    tests = []

    # Test default behavior and overriding it with the test environment

    class MyDriver(diff.DiffTestDriver):
        def run(self):
            pass

        def compute_failures(self):
            return self.compute_diff("output", baseline, actual)

    tests += [
        create_test("default", MyDriver, {}),
        create_test("test_env", MyDriver, {"diff_context_size": 2}),
    ]

    # Test overriding through the diff_context_size property: it should
    # short-circuit the test environment.

    class MyDriver2(MyDriver):
        @property
        def diff_context_size(self):
            return 2

    tests += [
        create_test("property", MyDriver2, {}),
        create_test("property_test_env", MyDriver2, {"diff_context_size": 5}),
    ]

    # Test direct calls to DiffTestDriver.compute_diff: non-None context_size
    # argument should override the rest.

    class MyDriver3(MyDriver):
        @property
        def diff_context_size(self):
            return 2

        def compute_failures(self):
            return self.compute_diff(
                "output", baseline, actual, context_size=5
            )

    tests += [
        create_test("method", MyDriver3, {}),
        create_test("method_test_env", MyDriver3, {"diff_context_size": 10}),
    ]

    class MySuite(Suite):
        def get_test_list(self, sublist):
            return tests

    suite = run_testsuite(MySuite, args=["-j1"], expect_failure=True)
    assert extract_results(suite) == {
        "default": Status.FAIL,
        "test_env": Status.FAIL,
        "property": Status.FAIL,
        "property_test_env": Status.FAIL,
        "method": Status.FAIL,
        "method_test_env": Status.FAIL,
    }

    def check_diff(test_name, expected):
        assert suite.report_index.entries[test_name].load().diff == expected

    diff_context_1 = (
        "Diff failure: unexpected output\n"
        "--- expected\n"
        "+++ output\n"
        "@@ -20,3 +20,2 @@\n"
        " 19\n"
        "-20\n"
        " 21\n"
    )
    diff_context_2 = (
        "Diff failure: unexpected output\n"
        "--- expected\n"
        "+++ output\n"
        "@@ -19,5 +19,4 @@\n"
        " 18\n"
        " 19\n"
        "-20\n"
        " 21\n"
        " 22\n"
    )
    diff_context_5 = (
        "Diff failure: unexpected output\n"
        "--- expected\n"
        "+++ output\n"
        "@@ -16,11 +16,10 @@\n"
        " 15\n"
        " 16\n"
        " 17\n"
        " 18\n"
        " 19\n"
        "-20\n"
        " 21\n"
        " 22\n"
        " 23\n"
        " 24\n"
        " 25\n"
    )

    check_diff("default", diff_context_1)
    check_diff("test_env", diff_context_2)
    check_diff("property", diff_context_2)
    check_diff("property_test_env", diff_context_2)
    check_diff("method", diff_context_5)
    check_diff("method_test_env", diff_context_5)


def test_regexp_fullmatch():
    """Check that DiffTestDriver does a full match over regexp baselines."""
    # The "abcd" regexp baseline should not be able to match "abcde" (it used
    # to).

    class MyDriver(diff.DiffTestDriver):
        @property
        def baseline(self):
            return (None, "abcd", True)

        def run(self):
            self.output += "abcde"

    suite = run_testsuite(
        create_testsuite(["mytest"], MyDriver), expect_failure=True
    )
    assert extract_results(suite) == {"mytest": Status.FAIL}


def test_diff_rewriting():
    """Check that DiffTestDriver's rewriting feature works as expected."""
    # This testcase involves the rewriting of testcase files, so work on a
    # temporary copy.
    with tempfile.TemporaryDirectory(prefix="test_diff_rewriting") as temp_dir:
        tests_source = os.path.join(
            os.path.dirname(__file__), "diff-rewriting-tests"
        )
        tests_copy = os.path.join(temp_dir, "tests")
        shutil.copytree(tests_source, tests_copy)

        class Mysuite(Suite):
            tests_subdir = tests_copy
            test_driver_map = {
                "diff-script-driver": DiffScriptDriver,
                "adacore-driver": adacore.AdaCoreLegacyTestDriver,
            }

            def add_options(self, parser):
                parser.add_argument("--rewrite", "-r", action="store_true")

            def set_up(self):
                super(Mysuite, self).set_up()
                self.env.rewrite_baselines = self.main.args.rewrite
                self.env.discs = []
                self.env.test_environ = dict(os.environ)

        def check_test_out(test, expected_lines, encoding="utf-8"):
            filename = os.path.join(tests_copy, test, "test.out")
            if expected_lines is None:
                assert not os.path.isfile(filename)
            else:
                with open(filename, encoding=encoding) as f:
                    lines = [line.rstrip() for line in f]
                assert lines == expected_lines

        # Make sure we have the expected baselines before running the testsuite
        check_test_out("adacore", ["legacy"])
        check_test_out("plain", ["hello", "world"])
        check_test_out("regexp", ["h.l+o", "world"])
        check_test_out("xfail", ["hello", "world"])
        check_test_out("iso-8859-1", ["héllo"], encoding="utf-8")
        check_test_out("bad-utf-8", ["héllo"], encoding="utf-8")
        check_test_out("missing-baseline", None)

        # Run the testsuite in rewrite mode
        suite = run_testsuite(Mysuite, args=["-rE"], expect_failure=True)
        assert extract_results(suite) == {
            "adacore": Status.FAIL,
            "plain": Status.FAIL,
            "regexp": Status.FAIL,
            "xfail": Status.XFAIL,
            "iso-8859-1": Status.FAIL,
            "bad-utf-8": Status.ERROR,
            "missing-baseline": Status.FAIL,
        }

        # Check that non-regexp baselines were updated, except when a failure
        # is expected.
        check_test_out("adacore", ["adacore", "legacy", "driver"])
        check_test_out("plain", ["helloo", "world", "!"])
        check_test_out("regexp", ["h.l+o", "world"])
        check_test_out("xfail", ["hello", "world"])
        check_test_out("iso-8859-1", ["héllo"], encoding="iso-8859-1")
        check_test_out("bad-utf-8", ["héllo"], encoding="utf-8")
        check_test_out("missing-baseline", ["helloo", "world", "!"])


class TestDoubleDiff:
    """Check proper result constructions for multiple diff failures."""

    class MyDriver(diff.DiffTestDriver):
        def run(self):
            pass

        def compute_failures(self):
            d1 = self.compute_diff(
                None, "a\nb\nc\n", "a\nc\n", failure_message="first diff"
            )
            d2 = self.compute_diff(
                None, "1\n3\n", "1\n2\n3\n", failure_message="second diff"
            )
            return d1 + d2

    class Mysuite(Suite):
        tests_subdir = "simple-tests"

        @property
        def test_driver_map(self):
            return {"default": TestDoubleDiff.MyDriver}

    def test(self):
        suite = run_testsuite(
            self.Mysuite, args=["test1"], expect_failure=True
        )
        assert extract_results(suite) == {"test1": Status.FAIL}

        # When multiple diff failures are involved, we expect .expected/.out to
        # be empty, as this formalism assumes that a single output comparison.
        # We expect .diff to contain both diff's though.
        result = suite.report_index.entries["test1"].load()
        assert result.expected is None
        assert result.out is None
        assert result.diff is not None
        assert "first diff" in result.diff
        assert "second diff" in result.diff


def test_failure_reason():
    """Check that DiffTestDriver properly sets the DIFF failure reason."""

    class Mysuite(Suite):
        tests_subdir = "diff-tests"
        test_driver_map = {"diff-script-driver": DiffScriptDriver}

    suite = run_testsuite(
        Mysuite,
        args=["plain-pass", "plain-fail", "--gaia-output"],
        expect_failure=True,
    )
    assert extract_results(suite) == {
        "plain-pass": Status.PASS,
        "plain-fail": Status.FAIL,
    }

    with open(os.path.join("out", "new", "results")) as f:
        results = sorted(line.strip().split(":", 2) for line in f)

    assert results == [
        ["plain-fail", "DIFF", "unexpected output"],
        ["plain-pass", "OK", ""],
    ]


def test_line_by_line():
    output = "first line\nssecond line\n"
    subst = diff.PatternSubstitute("[^ ]*second", "some-content")
    lbl_subst = diff.LineByLine(subst)

    assert subst.refine(output) == "first some-content line\n"
    assert lbl_subst.refine(output) == "first line\nsome-content line\n"

    output = b"first line\nssecond line\n"
    subst = diff.PatternSubstitute(b"[^ ]*second", b"some-content")
    lbl_subst = diff.LineByLine(subst)

    assert subst.refine(output) == b"first some-content line\n"
    assert lbl_subst.refine(output) == b"first line\nsome-content line\n"


def test_pattern_substitute_callback():
    """Check that PatternSubstute accept replacement callbacks."""

    def repl(m):
        return m.group(1)

    refiner = diff.PatternSubstitute(r"[a-z]*\((.*)\)", repl)

    assert refiner.refine("foo(1, 2)") == "1, 2"
