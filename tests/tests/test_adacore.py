"""Tests for the "test.opt" handling."""

import os
import shutil
import tempfile

from e3.testsuite import Testsuite as Suite
import e3.testsuite.control as control
from e3.testsuite.driver.adacore import AdaCoreLegacyTestDriver as ACDriver
import e3.testsuite.testcase_finder as testcase_finder
from e3.testsuite.result import TestStatus as Status

from .utils import (
    MultiSchedulingSuite,
    extract_results,
    run_testsuite,
    suite_logs,
)


def test_adacore():
    """Check that AdaCore legacy support works as expected."""

    class Mysuite1(Suite):
        tests_subdir = "adacore-tests"

        def set_up(self):
            super(Mysuite1, self).set_up()
            self.env.discs = ["foo"]
            self.env.test_environ = dict(os.environ)

        test_finders = [testcase_finder.AdaCoreLegacyTestFinder(ACDriver)]

    suite = run_testsuite(Mysuite1, ["-E"], expect_failure=True)
    assert extract_results(suite) == {
        # Check that test.sh are picked up
        "0000-097": Status.PASS,
        # Check that test.sh aren't converted from cmd to Bourne syntax
        "3807-001": Status.PASS,
        # Check that test.cmd_suffix tests are converted
        "DB15-019": Status.PASS,
        # Regular test execution, exercize output refiners
        "T415-993": Status.PASS,
        # Missing non-default baseline
        "T415-994": Status.ERROR,
        # Missing test script
        "T415-995": Status.ERROR,
        # test.opt's SKIP yields a XFAIL without trying to execute the test
        "T415-996": Status.XFAIL,
        # test.opt says DEAD when there is a "foo" discriminant
        "T415-997": Status.SKIP,
        # Regular test execution and failing diff comparison (test.out absent)
        "T415-998": Status.FAIL,
        # Regular test execution and successful diff comparison
        "T415-999": Status.PASS,
        # Regular test execution and successful diff comparison
        "TA23-999": Status.PASS,
        # Regular test execution and failing diff comparison (test.out present)
        "Z999-999": Status.XFAIL,
    }

    class Mysuite2(Suite):
        tests_subdir = "adacore-support-tests"

        def set_up(self):
            super(Mysuite2, self).set_up()
            self.env.discs = ["FORCE_SH"]
            os.environ["TEST_SUPPORT_DIR"] = os.path.join(
                os.path.abspath(os.path.dirname(__file__)),
                "adacore-support-tests",
                "support",
            )
            self.env.test_environ = dict(os.environ)

        def tear_down(self):
            os.environ["TEST_SUPPORT_DIR"] = ""
            super(Mysuite2, self).tear_down()

        test_finders = [testcase_finder.AdaCoreLegacyTestFinder(ACDriver)]

    suite = run_testsuite(Mysuite2)
    assert extract_results(suite) == {"T415-999": Status.PASS}


def test_optfile(caplog):
    """Check that OptfileTestControlCreator works as expected."""

    class Mydriver(ACDriver):
        test_control_creator = control.AdaCoreLegacyTestControlCreator(["foo"])

    class Mysuite(MultiSchedulingSuite):
        tests_subdir = "adacore-tests"
        test_driver_map = {"adacore": Mydriver}
        default_driver = "adacore"

        def set_up(self):
            super().set_up()
            self.env.discs = []
            self.env.test_environ = dict(os.environ)

    suite = run_testsuite(Mysuite)
    assert extract_results(suite) == {
        "just-cmd": Status.PASS,
        "just-py": Status.PASS,
        "both-cmd-py": Status.PASS,
        "extra-control": Status.PASS,
    }

    message = (
        'extra-control: "control" entry found in test.yaml whereas only'
        " test.opt files are considered"
    )
    assert message in suite_logs(caplog)


def test_rewriting(caplog):
    """Check that ACDriver's baseline rewriting works as expected."""
    # This testcase involves the rewriting of testcase files, so work on a
    # temporary copy.
    with tempfile.TemporaryDirectory(
        prefix="test_adacore_rewriting"
    ) as temp_dir:
        tests_source = os.path.join(
            os.path.dirname(__file__), "adacore-rewriting-tests"
        )
        tests_copy = os.path.join(temp_dir, "tests")
        shutil.copytree(tests_source, tests_copy)

        class Mysuite(Suite):
            tests_subdir = tests_copy
            test_driver_map = {"adacore": ACDriver}
            default_driver = "adacore"

            def add_options(self, parser):
                parser.add_argument("--rewrite", "-r", action="store_true")

            def set_up(self):
                super().set_up()
                self.env.discs = []
                self.env.test_environ = dict(os.environ)
                self.env.rewrite_baselines = self.main.args.rewrite

        def check_baselines(test, expected_desc):
            files = sorted(
                f
                for f in os.listdir(os.path.join(tests_copy, test))
                if f.endswith(".out")
            )
            expected_files = sorted(expected_desc)
            assert files == expected_files

            for filename in files:
                expected_lines = expected_desc[filename]
                with open(os.path.join(tests_copy, test, filename)) as f:
                    lines = [line.rstrip() for line in f]
                assert lines == expected_lines

        # Make sure we have the expected baselines before running the testsuite
        check_baselines("default-nodiff", {"test.out": ["Hello"]})
        check_baselines("default-diff", {"test.out": ["World"]})
        check_baselines("default-empty", {"test.out": ["Hello"]})
        check_baselines("nondefault-nodiff", {"baseline.out": ["Hello"]})
        check_baselines("nondefault-empty", {"baseline.out": ["Hello"]})
        check_baselines("xfail-diff", {"test.out": ["World"]})

        suite = run_testsuite(Mysuite, args=["-r"], expect_failure=True)
        assert extract_results(suite) == {
            "default-nodiff": Status.PASS,
            "default-diff": Status.FAIL,
            "default-empty": Status.FAIL,
            "nondefault-nodiff": Status.PASS,
            "nondefault-empty": Status.FAIL,
            "xfail-diff": Status.XFAIL,
        }

        # Now check that baselines were updated as expected
        check_baselines("default-nodiff", {"test.out": ["Hello"]})
        check_baselines("default-diff", {"test.out": ["Hello"]})
        check_baselines("default-empty", {})
        check_baselines("nondefault-nodiff", {"baseline.out": ["Hello"]})
        check_baselines("nondefault-empty", {"baseline.out": []})
        check_baselines("xfail-diff", {"test.out": ["World"]})


def test_gaia_discs():
    """Check that the GAIA report reports discriminants as expected."""
    discs_filename = os.path.join("out", "new", "discs")

    class BasicSuite(Suite):
        tests_subdir = "simple-tests"

    def run(cls):
        run_testsuite(cls, args=["nosuchtest", "--gaia-output"])

    def test_discs(discs_value, report_discs):
        """Run a testsuite and check the list of discriminants in report.

        Run a testsuite with ``testsuite.env.discs = discs_value``. Check that
        there is no "discs" report file if ``report_discs`` is None, and that
        it is a text file that contains the ``report_discs`` string otherwise.
        """

        class DiscsSuite(Suite):
            def set_up(self):
                super().set_up()
                self.env.discs = discs_value

        run(DiscsSuite)
        if report_discs is None:
            assert not os.path.exists(discs_filename)
        else:
            assert os.path.exists(discs_filename)
            with open(discs_filename) as f:
                assert f.read() == report_discs

    # Check that no "discs" file is created when there is no "env.discs"
    # attribute, or when it does not contain a list of strings.
    run(BasicSuite)
    assert not os.path.exists(discs_filename)

    test_discs(None, None)
    test_discs(1, None)
    test_discs([1], None)

    # Check that this file is created with the expected content when
    # "env.discs" contains a list of strings.
    test_discs([], "")
    test_discs(["foo", "bar"], "foo bar\n")
    test_discs("a,b,c", "a b c\n")


def test_timeout():
    """Check that AdaCore legacy support detects timeouts."""

    class Mysuite(Suite):
        tests_subdir = "adacore-timeout-tests"
        test_driver_map = {"adacore": ACDriver}
        default_driver = "adacore"

        def set_up(self):
            super(Mysuite, self).set_up()
            self.env.discs = []
            self.env.test_environ = dict(os.environ)

    suite = run_testsuite(
        Mysuite, ["--gaia-output", "-E"], expect_failure=True
    )
    assert extract_results(suite) == {
        "pass": Status.PASS,
        "timedout": Status.FAIL,
    }

    with open(os.path.join("out", "new", "results")) as f:
        lines = sorted(f.read().splitlines())
        assert lines == [
            "pass:OK:",
            "timedout:TIMEOUT:unexpected output | test timed out",
        ]


def test_script_encoding():
    """Check that ACDriver correctly manages script encodings."""

    class MyDriver(ACDriver):
        @property
        def default_encoding(self):
            return self.test_env.get("encoding", "binary")

        @property
        def output_refiners(self):
            return []

    class Mysuite(Suite):
        tests_subdir = "adacore-script-encoding-tests"
        test_driver_map = {"mydriver": MyDriver}
        default_driver = "mydriver"

        def set_up(self):
            super(Mysuite, self).set_up()
            self.env.discs = []
            self.env.test_environ = dict(os.environ)

    suite = run_testsuite(Mysuite, ["-E"], expect_failure=True)
    results = extract_results(suite)
    assert results.pop("default") == Status.PASS
    assert results.pop("latin-1") == Status.PASS
    assert results.pop("utf-8") == Status.PASS
    assert len(results) == 1
    test_name, status = list(results.items())[0]
    assert test_name == "bad.run_wrapper"
    assert status == Status.ERROR
