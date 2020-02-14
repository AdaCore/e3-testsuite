from enum import Enum
import subprocess

from e3.fs import sync_tree
from e3.os.process import get_rlimit, quote_arg
from e3.testsuite.driver import TestDriver
from e3.testsuite.result import Log, TestStatus


class TestSkip(Exception):
    """
    Convenience exception to abort a testcase, considering it must be skipped
    (TestStatus.UNSUPPORTED).
    """
    pass


class TestAbortWithError(Exception):
    """
    Convenience exception to abort a testcase, considering something went wrong
    (TestStatus.ERROR).
    """
    pass


class TestAbortWithFailure(Exception):
    """Convenience exception to abort a testcase, considering it failed."""
    pass


class TestControlKind(Enum):
    """Control how to run (or not!) testcases."""

    NONE = 0
    """Run the test the regular way."""

    SKIP = 1
    """Do not run the testcase, setting it UNSUPPORTED."""

    XFAIL = 2
    """
    Run the test the regular way. If its status is PASS, correct it to
    XPASS. If it succeeds, correct it to XFAIL. Leave its status unchanged in
    other cases.
    """


class TestControl(object):
    """Association of a TestControlKind instance and a message."""
    def __init__(self, kind, message=None):
        self.kind = kind
        self.message = message

    @classmethod
    def interpret(cls, driver, condition_env={}):
        """Interpret the test "control" configuration in ``test_env``.

        Raise a ValueError exception if the configuration is invalid.

        :param TestDriver driver: Test driver for which we must parse the
            "control" configuration.
        :param dict condition_env: Environment to pass to condition evaluation
            in control entries.
        """
        # Read the configuration from the test environment's "control" key, if
        # present.
        default = cls(TestControlKind.NONE, "")
        try:
            control = driver.test_env["control"]
        except KeyError:
            return default

        # Variables available to entry conditions
        condition_env = dict(condition_env)
        condition_env["env"] = driver.env

        # First validate the whole control structure, and only then interpret
        # it, for the same reason an language interpreter checks the syntax
        # before starting the interpretation.
        #
        # We expect control to be a list of lists of strings. The top-level
        # list is a collection of "entries": each entry conditionally selects a
        # test behavior. Each entry (list of strings) have one of the following
        # format:
        #
        #    [kind, condition]
        #    [kind, condition, message]
        #
        # "kind" is the name of any of the TestControlKind values. "condition"
        # is a Python expression that determines whether the entry applies, and
        # the optional "message" is a free form text to track which entry was
        # selected.
        entries = []

        if not isinstance(control, list):
            raise ValueError("list expected at the top level")

        for i, entry in enumerate(control, 1):
            def error(message):
                raise ValueError("entry #{}: {}".format(i, message))

            if (
                not isinstance(entry, list) or
                not len(entry) in (2, 3) or
                any(not isinstance(s, str) for s in entry)
            ):
                error("list of 2 or 3 strings expected")

            # Decode the test control kind
            try:
                kind = TestControlKind[entry[0]]
            except KeyError:
                error("invalid kind: {}".format(entry[0]))

            # Evaluate the condition
            try:
                cond = eval(entry[1], condition_env)
            except Exception as exc:
                error("invalid condition ({}): {}"
                      .format(type(exc).__name__, exc))

            message = entry[2] if len(entry) > 2 else ""

            entries.append((kind, cond, message))

        # Now, select the first entry whose condition is True. By default,
        # fallback to "default".
        for kind, cond, message in entries:
            if cond:
                return TestControl(kind, message)
        return default


class ClassicTestDriver(TestDriver):
    """Enhanced test driver base class for common behaviors.

    This test driver provides several facilities to automate tasks that driver
    often duplicate in practice:

    * run subprocesses;
    * intercept subprocess failures and turn them into appropriate test
      statuses;
    * gather subprocess outputs to ``self.result.out``;
    * have support for automatic XFAIL/UNSUPPORTED test results.
    """

    copy_test_directory = True
    """
    Whether to copy the test directory to the working directory before running
    the testcase.
    """

    def run(self):
        """Subclasses must override this."""
        raise NotImplementedError

    @property
    def default_process_timeout(self):
        """
        Return the default timeout (number of seconds) for processes spawn in
        the ``shell`` method.
        """
        # Return the timeout defined in test.yaml, if present, otherwise return
        # our true default: 5 minutes.
        return self.test_env.get("timeout", 5 * 60)

    @property
    def control_condition_env(self):
        """Return the environment to evaluate control conditions."""
        return {}

    def shell(self, args, cwd=None, env=None, catch_error=True,
              analyze_output=True, timeout=None, parse_shebang=False):
        """Run a subprocess.

        :param str args: Arguments for the subprocess to run.
        :param None|str cwd: Current working directory for the subprocess. By
            default (i.e. if None), use the test working directory.
        :param None|dict[str, str] env: Environment to pass to the subprocess.
        :param bool catch_error: If True, consider that an error status code
            leads to a test failure. In that case, abort the testcase.
        :param bool analyze_output: If True, add the subprocess output to
            ``self.result.out``.
        :param None|int timeout: Timeout (in seconds) for the subprocess. Use
            ``self.default_timeout`` if left to None.
        :param bool parse_shebang: See e3.os.process.Run's constructor.
        :return e3.os.process.Run: The process object.
        """
        # By default, run the subprocess in the test working directory
        if cwd is None:
            cwd = self.test_env["working_dir"]

        if timeout is None:
            timeout = self.default_process_timeout

        # Run the subprocess and log it
        self.result.log += "Running: {} (cwd={})\n".format(
            " ".join(quote_arg(a) for a in args),
            cwd)

        process_info = {"cmd": args,
                        "cwd": cwd}
        self.result.processes.append(process_info)

        class ProcessResult:
            pass

        # Python2's subprocess module does not handle timeout, so re-implement
        # e3.os.process's rlimit-based implementation of timeouts.
        if timeout is not None:
            args = [get_rlimit(), str(timeout)] + args

        # We cannot use e3.os.process.Run as this API forces the use of text
        # streams, whereas testsuite sometimes need to deal with binary data
        # (or unknown encodings, which is equivalent).
        subp = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        stdout, _ = subp.communicate()
        stdout = stdout.decode("utf-8")

        p = ProcessResult()
        p.out = stdout
        p.status = subp.returncode

        self.result.log += "Status code: {}\n".format(p.status)
        process_info["status"] = p.status
        self.result.log += "Output:\n"
        self.result.log += stdout
        process_info["output"] = Log(stdout)

        # If requested, use its output for analysis
        if analyze_output:
            self.result.out += stdout

        if catch_error and p.status != 0:
            raise TestAbortWithFailure("non-zero status code")

        return p

    def add_test(self, dag):
        self.add_fragment(dag, "run_wrapper")

    def push_success(self):
        """
        Consider that the test passed and set status according to test control.
        """
        kind = self.test_control.kind

        # Given that we skip execution right after the test control evaluation
        # (assuming it returns SKIP), there should be no way to call
        # push_failure in this case.
        assert kind != TestControlKind.SKIP

        if kind == TestControlKind.NONE:
            self.result.set_status(TestStatus.PASS)
        elif kind == TestControlKind.XFAIL:
            self.result.set_status(TestStatus.XPASS)
        self.push_result()

    def push_skip(self, message):
        """
        Consider that we skipped the test, set status accordingly.

        :param str message: Label to explain the skipping.
        """
        self.result.set_status(TestStatus.UNSUPPORTED, message)
        self.push_result()

    def push_error(self, message):
        """
        Consider that something went wrong while processing this test, set
        status accordingly.

        :param str message: Message to explain what went wrong.
        """
        self.result.set_status(TestStatus.ERROR, message)
        self.push_result()

    def push_failure(self, message):
        """
        Consider that the test failed and set status according to test control.

        :param str message: Test failure description.
        """
        kind = self.test_control.kind

        # See similar assertion in push_success
        assert kind != TestControlKind.SKIP

        if kind == TestControlKind.NONE:
            status = TestStatus.FAIL
        elif kind == TestControlKind.XFAIL:
            status = TestStatus.XFAIL
            if self.test_control.message:
                message = "{} ({})".format(message, self.test_control.message)
        self.result.set_status(status, message)
        self.push_result()

    def set_up(self):
        """
        Subclasses can override this to prepare testcase execution.

        Having a callback separate from "run" is useful when dealing with
        inheritance: overriding the "set_up" method in subclasses allows to
        append setup actions before the testcase execution actually takes place
        (in the "run" method).

        If everything happened in "run" method, that would not be possible
        unless re-implementing the "run" method in each subclass, with obvious
        code duplication issues.
        """
        pass

    def tear_down(self):
        """
        Subclasses can override this to run clean ups after testcase execution.

        See set_up's docstring for the rationale.
        """
        pass

    def run_wrapper(self, prev):
        # Interpret the "control" test configuration
        try:
            self.test_control = TestControl.interpret(
                self, condition_env=self.control_condition_env)
        except ValueError as exc:
            return self.push_error(
                "Error while interpreting control: {}".format(exc))

        # If test control tells us to skip the test, stop right here
        if self.test_control.kind == TestControlKind.SKIP:
            return self.push_skip(self.test_control.message)

        # If requested, prepare the test working directory to initially be a
        # copy of the test directory.
        if self.copy_test_directory:
            sync_tree(self.test_env["test_dir"], self.test_env["working_dir"],
                      delete=True)

        # Execute the subclass' "run" method and handle convenience test
        # aborting exception.
        try:
            self.set_up()
            self.run()
            self.analyze()
        except TestSkip as exc:
            return self.push_skip(str(exc))
        except TestAbortWithError as exc:
            return self.push_error(str(exc))
        except TestAbortWithFailure as exc:
            return self.push_failure(str(exc))
        finally:
            self.tear_down()

    def compute_failures(self):
        """
        Analyze the testcase result and return the list of reasons for failure.

        This architecture allows to have multiple reasons for failures, for
        instance: unexpected computation result + presence of Valgrind
        diagnostics. The result is a list of short strings that describe the
        failures. This method is expected to write to ``self.result.log`` in
        order to convey more information if needed.

        By default, consider that the testcase succeeded if we reach the
        analysis step. Subclasses may override this to actually perform checks.

        :rtype: list[str]
        """
        return []

    def analyze(self):
        """Analyze the testcase result, adjust status accordingly."""
        failures = self.compute_failures()
        if failures:
            self.push_failure(" | ".join(failures))
        else:
            self.push_success()
