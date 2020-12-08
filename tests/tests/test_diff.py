"""Tests for the e3.testsuite.driver.diff module."""

import os.path
import shutil
import sys
import tempfile

import yaml

from e3.testsuite import Testsuite as Suite
import e3.testsuite.driver.adacore as adacore
import e3.testsuite.driver.diff as diff
from e3.testsuite.result import TestStatus as Status

from .utils import extract_results, run_testsuite


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

    suite = run_testsuite(Mysuite, args=["-E"])
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
            with open(
                os.path.join(tests_copy, test, "test.out"), encoding=encoding
            ) as f:
                lines = [line.rstrip() for line in f]
            assert lines == expected_lines

        # Make sure we have the expected baselines before running the testsuite
        check_test_out("adacore", ["legacy"])
        check_test_out("plain", ["hello", "world"])
        check_test_out("regexp", ["h.l+o", "world"])
        check_test_out("xfail", ["hello", "world"])
        check_test_out("iso-8859-1", ["héllo"], encoding="utf-8")
        check_test_out("bad-utf-8", ["héllo"], encoding="utf-8")

        # Run the testsuite in rewrite mode
        suite = run_testsuite(Mysuite, args=["-rE"])
        assert extract_results(suite) == {
            "adacore": Status.FAIL,
            "plain": Status.FAIL,
            "regexp": Status.FAIL,
            "xfail": Status.XFAIL,
            "iso-8859-1": Status.FAIL,
            "bad-utf-8": Status.ERROR,
        }

        # Check that non-regexp baselines were updated, except when a failure
        # is expected.
        check_test_out("adacore", ["adacore", "legacy", "driver"])
        check_test_out("plain", ["helloo", "world", "!"])
        check_test_out("regexp", ["h.l+o", "world"])
        check_test_out("xfail", ["hello", "world"])
        check_test_out("iso-8859-1", ["héllo"], encoding="iso-8859-1")
        check_test_out("bad-utf-8", ["héllo"], encoding="utf-8")


def test_double_diff():
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
        test_driver_map = {"default": MyDriver}

    suite = run_testsuite(Mysuite, args=["test1"])
    assert extract_results(suite) == {"test1": Status.FAIL}

    # When multiple diff failures are involved, we expect .expected/.out to be
    # empty, as this formalism assumes that a single output comparison. We
    # expect .diff to contain both diff's though.
    with open(os.path.join("out", "new", "test1.yaml")) as f:
        result = yaml.safe_load(f)
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
        Mysuite, args=["plain-pass", "plain-fail", "--gaia-output"]
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
