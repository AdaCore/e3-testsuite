"""Tests for the "test.opt" handling."""

import os

from e3.testsuite import Testsuite as Suite
import e3.testsuite.control as control
from e3.testsuite.driver.adacore import AdaCoreLegacyTestDriver as ACDriver
import e3.testsuite.testcase_finder as testcase_finder
from e3.testsuite.result import TestStatus as Status

from .test_basics import run_testsuite, testsuite_logs


def test_adacore():
    """Check that AdaCore legacy support works as expected."""

    class Mysuite1(Suite):
        tests_subdir = "adacore-tests"

        def set_up(self):
            super(Mysuite1, self).set_up()
            self.env.discs = ["foo"]
            self.env.test_environ = dict(os.environ)

        test_finders = [testcase_finder.AdaCoreLegacyTestFinder(ACDriver)]

    suite = run_testsuite(Mysuite1)
    assert suite.results == {
        # Missing non-default baseline
        "T415-994": Status.ERROR,
        # Missing test script
        "T415-995": Status.ERROR,
        # test.opt's SKIP yields a XFAIL without trying to execute the test
        "T415-996": Status.XFAIL,
        # test.opt says DEAD when there is a "foo" discriminant
        "T415-997": Status.UNSUPPORTED,
        # Regular test execution and failing diff comparison (test.out absent)
        "T415-998": Status.FAIL,
        # Regular test execution and successful diff comparison
        "T415-999": Status.PASS,
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

    suite = run_testsuite(Mysuite2, args=["-Ed/tmp/bar"])
    assert suite.results == {"T415-999": Status.PASS}


def test_optfile(caplog):
    """Check that OptfileTestControlCreator works as expected."""

    class Mydriver(ACDriver):
        test_control_creator = control.OptfileTestControlCreator(["foo"])

    class Mysuite(Suite):
        tests_subdir = "adacore-tests"
        test_driver_map = {"adacore": Mydriver}
        default_driver = "adacore"

        def set_up(self):
            super(Mysuite, self).set_up()
            self.env.test_environ = {}

    suite = run_testsuite(Mysuite)
    assert suite.results == {
        "just-cmd": Status.PASS,
        "just-py": Status.PASS,
        "both-cmd-py": Status.PASS,
        "extra-control": Status.PASS,
    }

    message = (
        'extra-control: "control" entry found in test.yaml whereas only'
        " test.opt files are considered"
    )
    assert message in testsuite_logs(caplog)
