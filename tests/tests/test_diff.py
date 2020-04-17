"""Tests for the e3.testsuite.driver.diff module."""

import os.path
import shutil
import sys
import tempfile

from e3.testsuite import Testsuite as Suite
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
        return [
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
        "regexp-pass": Status.PASS,
        "regexp-fail": Status.FAIL,
        "regexp-binary-pass": Status.PASS,
        "regexp-binary-fail": Status.FAIL,
        "missing-baseline": Status.ERROR,
        "path-substitution": Status.PASS,
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
            test_driver_map = {"diff-script-driver": DiffScriptDriver}

            def add_options(self):
                self.main.argument_parser.add_argument(
                    "--rewrite", "-r", action="store_true"
                )

            def set_up(self):
                super(Mysuite, self).set_up()
                self.env.rewrite_baselines = self.main.args.rewrite

        def check_test_out(test, expected_lines):
            with open(os.path.join(tests_copy, test, "test.out")) as f:
                lines = [l.rstrip() for l in f]
            assert lines == expected_lines

        # Make sure we have the expected baselines before running the testsuite
        check_test_out("plain", ["hello", "world"])
        check_test_out("regexp", ["h.l+o", "world"])

        # Run the testsuite in rewrite mode
        suite = run_testsuite(Mysuite, args=["-r"])
        assert suite.results == {"plain": Status.FAIL, "regexp": Status.FAIL}

        # Check that non-regexp baselines were updated
        check_test_out("plain", ["helloo", "world", "!"])
        check_test_out("regexp", ["h.l+o", "world"])
