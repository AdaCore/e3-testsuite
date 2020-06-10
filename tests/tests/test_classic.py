"""Tests for the e3.testsuite.driver.classic module."""


import os
import os.path
import sys

from e3.testsuite import Testsuite as Suite
import e3.testsuite.control as crtl
import e3.testsuite.driver.classic as classic
from e3.testsuite.result import TestStatus as Status

from .test_basics import run_testsuite, testsuite_logs


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

        def test_dir(self, *args):
            return os.path.join("/nosuchdir", *args)

    def expect_result(test_env, condition_env={}, env={}):
        driver = MockDriver(test_env, env)
        control = crtl.YAMLTestControlCreator(condition_env).create(driver)
        return control.skip, control.xfail, control.message

    def expect_error(test_env, condition_env={}, env={}):
        driver = MockDriver(test_env, env)
        try:
            crtl.YAMLTestControlCreator(condition_env).create(driver)
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

    @property
    def copy_test_directory(self):
        return self.test_env.get("copy_test_directory", True)

    def set_up(self):
        super(ScriptDriver, self).set_up()
        if not self.copy_test_directory:
            os.mkdir(self.working_dir())

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
        args = list(config["args"])
        if config.get("read"):
            args.append("-read={}".format(self.test_dir(config["read"])))
        p = self.shell(
            [sys.executable, self.helper_script] + args,
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


def test_classic(caplog):
    """Check that ClassicTestDriver works as expected."""

    class Mysuite(Suite):
        tests_subdir = "classic-tests"
        test_driver_map = {
            "script-driver": ScriptDriver,
            "dummy-driver": DummyDriver,
        }

    # Look for tests using a relative path to check that test directories are
    # properly converted to absolute paths (see abs-test-dir).
    tests_subdir = os.path.relpath(
        os.path.join(
            os.path.abspath(os.path.dirname(__file__)), Mysuite.tests_subdir
        ),
    )

    suite = run_testsuite(Mysuite, args=["--truncate-logs=0", tests_subdir])
    assert suite.results == {
        "simple": Status.PASS,
        "catch-error-pass": Status.PASS,
        "catch-error-fail": Status.FAIL,
        "skipped": Status.SKIP,
        "xfailed": Status.XFAIL,
        "xpassed": Status.XPASS,
        "errored": Status.ERROR,
        "force-skip": Status.SKIP,
        "invalid-control": Status.ERROR,
        "dummy": Status.PASS,
        "with-output": Status.FAIL,
        "binary-output": Status.FAIL,
        "invalid-utf8-output": Status.ERROR,
        "suspicious-test-opt": Status.PASS,
        "abs-test-dir": Status.PASS,
        "long-logs": Status.FAIL,
    }

    log = (
        'suspicious-test-opt: "test.opt" file found whereas only "control"'
        " entries are considered"
    )
    assert log in testsuite_logs(caplog)


def test_long_logs(caplog):
    """Check that long logs are truncated as requested."""

    class Mysuite(Suite):
        tests_subdir = "classic-tests"
        test_driver_map = {"script-driver": ScriptDriver}

    suite = run_testsuite(
        Mysuite, args=["--truncate-logs=3", "long-logs", "--gaia-output"]
    )
    assert suite.results == {"long-logs": Status.FAIL}

    with open(os.path.join("out", "new", "long-logs.log")) as f:
        content = f.read().splitlines()
    assert content[0].startswith("Running: ")
    assert content[1:] == [
        "Status code: 0",
        "Output: ",
        "a0",
        "a1",
        "a2",
        "",
        "... 8 lines skipped...",
        "",
        "b4",
        "b5",
        "b6",
    ]
