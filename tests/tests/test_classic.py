"""Tests for the e3.testsuite.driver.classic module."""

import os
import os.path
import re
import sys

from e3.testsuite import Testsuite as Suite
import e3.testsuite.control as crtl
import e3.testsuite.driver.classic as classic
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import TestStatus as Status

from .utils import (
    MultiSchedulingSuite,
    extract_results,
    run_testsuite,
    testsuite_logs,
)


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

    def expect_result(test_env, condition_env=None, env=None):
        condition_env = condition_env if condition_env is not None else {}
        env = env if env is not None else {}
        driver = MockDriver(test_env, env)
        control = crtl.YAMLTestControlCreator(condition_env).create(driver)
        return control.skip, control.xfail, control.message

    def expect_error(test_env, condition_env=None, env=None):
        condition_env = condition_env if condition_env is not None else {}
        env = env if env is not None else {}
        driver = MockDriver(test_env, env)
        try:
            crtl.YAMLTestControlCreator(condition_env).create(driver)
        except ValueError as exc:
            return str(exc)
        else:
            raise AssertionError("exception expected")

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
    assert (
        expect_result(
            {
                "control": [
                    ["SKIP", "False", "entry 1"],
                    ["XFAIL", "True", "entry 2"],
                    ["SKIP", "False", "entry 3"],
                    ["SKIP", "True", "entry 4"],
                ]
            }
        )
        == (False, True, "entry 2")
    )

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


class TestClassic:
    """Check that ClassicTestDriver works as expected."""

    class Mysuite(MultiSchedulingSuite):
        tests_subdir = "classic-tests"
        test_driver_map = {
            "script-driver": ScriptDriver,
            "dummy-driver": DummyDriver,
        }

    def run_check(self, caplog, multiprocessing):
        # Look for tests using a relative path to check that test directories
        # are properly converted to absolute paths (see abs-test-dir).
        tests_subdir = os.path.relpath(
            os.path.join(
                os.path.abspath(os.path.dirname(__file__)),
                self.Mysuite.tests_subdir,
            ),
        )

        suite = run_testsuite(
            self.Mysuite,
            args=["--truncate-logs=0", tests_subdir, "-E"],
            multiprocessing=multiprocessing,
        )
        assert extract_results(suite) == {
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

        # Check that XPASS result prints the XFAIL message
        assert suite.report_index.entries["xpassed"].msg == "XFAIL message"

    def test_multithreading(self, caplog):
        self.run_check(caplog, multiprocessing=False)

    # TODO: somehow forward logs emitted in multiprocess test fragments to the
    # testsuite's main logging system.


def test_long_logs(caplog):
    """Check that long logs are truncated as requested."""

    class Mysuite(Suite):
        tests_subdir = "classic-tests"
        test_driver_map = {"script-driver": ScriptDriver}

    suite = run_testsuite(
        Mysuite, args=["--truncate-logs=3", "long-logs", "--gaia-output"]
    )
    assert extract_results(suite) == {"long-logs": Status.FAIL}

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


class TestCleanupFailure:
    """Check that error recovery for working dir cleanup works as expected."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            os.mkdir(self.working_dir("foo"))
            with open(self.working_dir("foo", "bar.txt"), "w"):
                pass

        def cleanup_working_dir(self):
            raise RuntimeError("some cleanup failure")

    class Mysuite(Suite):
        tests_subdir = "simple-tests"

        @property
        def test_driver_map(self):
            return {"default": TestCleanupFailure.MyDriver}

        default_driver = "default"

    def test(self):
        suite = run_testsuite(self.Mysuite)
        assert extract_results(suite) == {
            "test1": Status.PASS,
            "test2": Status.PASS,
            "test1__tear_down": Status.ERROR,
            "test2__tear_down": Status.ERROR,
        }

        index = ReportIndex.read("out/new")
        r = index.entries["test1__tear_down"].load()

        assert re.match(
            "Error while removing the working directory .*test1:\n"
            "\n"
            "Traceback (?:.|\n)*\n"
            "RuntimeError: some cleanup failure\n"
            "\n"
            "Remaining files:\n"
            f"  test.yaml\n"
            f"  foo\n"
            f"  foo{os.path.sep}bar.txt\n",
            r.log,
        )


class TestIgnoreEnv:
    """Check that shell's ignore_env argument works as expected."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            self.shell(
                [sys.executable, self.env.env_printer],
                env={"E3_TESTSUITE_VAR2": "var2-value"},
                **self.env.kwargs,
            )
            self.result.out = self.output

    def run(self, expected_output, **kwargs):
        env_printer = self.env_printer

        class Mysuite(Suite):
            tests_subdir = "simple-tests"
            test_driver_map = {"default": TestIgnoreEnv.MyDriver}
            default_driver = "default"

            def set_up(self):
                self.env.env_printer = env_printer
                self.env.kwargs = kwargs

        suite = run_testsuite(Mysuite, args=["-E", "test1"])
        assert extract_results(suite) == {"test1": Status.PASS}

        index = ReportIndex.read("out/new")
        r = index.entries["test1"].load()
        lines = [line.strip() for line in r.out.splitlines()]
        assert lines == expected_output

    def test(self):
        self.env_printer = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "env_printer.py"
        )
        os.environ["E3_TESTSUITE_VAR1"] = "var1-value"

        self.run(
            ["E3_TESTSUITE_VAR1=var1-value", "E3_TESTSUITE_VAR2=var2-value"],
            ignore_environ=False,
        )
        self.run(["E3_TESTSUITE_VAR2=var2-value"], ignore_environ=True)
        self.run(["E3_TESTSUITE_VAR2=var2-value"])


class TestMayHaveTimedOut:
    """Check the ClassicTestDriver.process_may_have_timed_out method."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            def check(status, output):
                return self.process_may_have_timed_out(
                    classic.ProcessResult(status, output)
                )

            matching_msg = "rlimit: Real time limit (1 s) exceeded\n"

            assert not check(0, "foobar")
            assert not check(2, "foobar")
            assert not check(0, matching_msg)
            assert check(2, matching_msg)

    def test(self):
        class Mysuite(Suite):
            tests_subdir = "simple-tests"
            test_driver_map = {"default": self.MyDriver}
            default_driver = "default"

        suite = run_testsuite(Mysuite, args=["-E", "test1"])
        assert extract_results(suite) == {"test1": Status.PASS}
