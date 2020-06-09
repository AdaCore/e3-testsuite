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

from .test_basics import run_testsuite


class DiffScriptDriver(diff.DiffTestDriver):
    """Driver to check test output with DiffTestDriver."""

    helper_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "classic-tests", "script.py")
    )

    @property
    def output_refiners(self):
        path_substitutions = self.test_env.get("path_substitutions", [])
        return super(DiffScriptDriver, self).output_refiners + [
            diff.ReplacePath(self.working_dir(path), replacement)
            for path, replacement in path_substitutions
        ]

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
    assert suite.results == {
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

        def check_test_out(test, expected_lines):
            with open(os.path.join(tests_copy, test, "test.out")) as f:
                lines = [line.rstrip() for line in f]
            assert lines == expected_lines

        # Make sure we have the expected baselines before running the testsuite
        check_test_out("adacore", ["legacy"])
        check_test_out("plain", ["hello", "world"])
        check_test_out("regexp", ["h.l+o", "world"])
        check_test_out("xfail", ["hello", "world"])

        # Run the testsuite in rewrite mode
        suite = run_testsuite(Mysuite, args=["-r"])
        assert suite.results == {
            "adacore": Status.FAIL,
            "plain": Status.FAIL,
            "regexp": Status.FAIL,
            "xfail": Status.XFAIL,
        }

        # Check that non-regexp baselines were updated, except when a failure
        # is expected.
        check_test_out("adacore", ["adacore", "legacy", "driver"])
        check_test_out("plain", ["helloo", "world", "!"])
        check_test_out("regexp", ["h.l+o", "world"])
        check_test_out("xfail", ["hello", "world"])


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
    assert suite.results == {"test1": Status.FAIL}

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
