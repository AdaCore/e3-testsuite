"""Tests for the e3.testsuite.driver.classic module."""


import os
import os.path
import sys

from e3.testsuite import Testsuite as Suite
import e3.testsuite.control as crtl
import e3.testsuite.driver.classic as classic
from e3.testsuite.result import TestStatus as Status

from .test_basics import run_testsuite


def test_control_interpret():
    """Check that TestControl.interpret works as expected."""

    # Mock data structures so that we don't have to create full testsuite runs

    class MockEnv:
        pass

    class MockDriver:
        def __init__(self, test_env, env):
            self.test_env = test_env
            self.env = MockEnv()
            for key, value in env.items():
                setattr(self.env, key, value)

    def expect_result(test_env, condition_env={}, env={}):
        driver = MockDriver(test_env, env)
        control = crtl.TestControl.interpret(driver, condition_env)
        return control.skip, control.xfail, control.message

    def expect_error(test_env, condition_env={}, env={}):
        driver = MockDriver(test_env, env)
        try:
            crtl.TestControl.interpret(driver, condition_env)
        except ValueError as exc:
            return str(exc)
        else:
            assert False, "exception expected"

    # No control entry: no test control
    assert expect_result({}) == (False, False, None)

    # Empty control list: no test control
    assert expect_result({"control": []}) == (False, False, None)

    # Invalid control object: error
    assert expect_error({"control": None}) == "list expected at the top level"

    # Invalid control entry: error
    assert (
        expect_error({"control": [[True]]})
        == "entry #1: list of 2 or 3 strings expected"
    )
    assert (
        expect_error({"control": [["SKIP", True]]})
        == "entry #1: list of 2 or 3 strings expected"
    )
    assert (
        expect_error({"control": [["no-such-control", "True"]]})
        == "entry #1: invalid kind: no-such-control"
    )
    assert expect_error({"control": [["SKIP", "foobar"]]}) == (
        "entry #1: invalid condition (NameError):"
        " name 'foobar' is not defined"
    )

    # Precedence to the first control whose condition is true
    assert expect_result(
        {
            "control": [
                ["SKIP", "False", "entry 1"],
                ["XFAIL", "True", "entry 2"],
                ["SKIP", "False", "entry 3"],
                ["SKIP", "True", "entry 4"],
            ]
        }
    ) == (False, True, "entry 2")

    # Use variables from test_env
    assert expect_result(
        {"control": [["SKIP", "foobar"]]}, condition_env={"foobar": True}
    ) == (True, False, None)
    assert expect_result(
        {"control": [["SKIP", "foobar"]]}, condition_env={"foobar": False}
    ) == (False, False, None)

    # Use variables from env
    assert expect_result(
        {"control": [["SKIP", "env.foobar"]]}, env={"foobar": True}
    ) == (True, False, None)
    assert expect_result(
        {"control": [["SKIP", "env.foobar"]]}, env={"foobar": False}
    ) == (False, False, None)


class ScriptDriver(classic.ClassicTestDriver):
    """Driver to run a Python script through ClassicTestDriver.shell."""

    helper_script = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "classic-tests", "script.py")
    )

    def set_up(self):
        super(ScriptDriver, self).set_up()
        self.failures = []

        try:
            self.process_config = self.test_env["process"]
        except KeyError:
            raise classic.TestAbortWithError(
                "Missing 'process' test.yaml entry"
            )

    def run(self):
        if self.test_env.get("force-skip", False):
            raise classic.TestSkip("forcing skip")

        config = self.process_config
        p = self.shell(
            [sys.executable, self.helper_script] + config["args"],
            catch_error=config.get("catch_error", True),
        )
        if p.out:
            self.failures.append("non-empty output")

    def compute_failures(self):
        return self.failures


class DummyDriver(classic.ClassicTestDriver):
    """Simple driver to check compute_failures's default behavior."""

    def run(self):
        pass


def test_classic():
    """Check that ClassicTestDriver works as expected."""

    class Mysuite(Suite):
        TEST_SUBDIR = "classic-tests"
        DRIVERS = {"script-driver": ScriptDriver, "dummy-driver": DummyDriver}

    suite = run_testsuite(Mysuite)
    assert suite.results == {
        "simple": Status.PASS,
        "catch-error-pass": Status.PASS,
        "catch-error-fail": Status.FAIL,
        "skipped": Status.UNSUPPORTED,
        "xfailed": Status.XFAIL,
        "xpassed": Status.XPASS,
        "errored": Status.ERROR,
        "force-skip": Status.UNSUPPORTED,
        "invalid-control": Status.ERROR,
        "dummy": Status.PASS,
        "with-output": Status.FAIL,
        "binary-output": Status.FAIL,
        "invalid-utf8-output": Status.ERROR,
    }
