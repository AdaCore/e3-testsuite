import subprocess

from e3.fs import sync_tree
from e3.os.process import get_rlimit, quote_arg
from e3.testsuite import DummyColors
from e3.testsuite.control import YAMLTestControlCreator
from e3.testsuite.driver import TestDriver
from e3.testsuite.result import Log, TestStatus

from colorama import Fore, Style


class TestSkip(Exception):
    """
    Convenience exception to abort a testcase.

    When this exception is raised during test initialization or execution,
    consider that this testcase must be skipped (TestStatus.SKIP).
    """

    pass


class TestAbortWithError(Exception):
    """
    Convenience exception to abort a testcase.

    When this exception is raised during test initialization or execution,
    consider that something went wrong (TestStatus.ERROR).
    """

    pass


class TestAbortWithFailure(Exception):
    """Convenience exception to abort a testcase, considering it failed.

    When this exception is raised during test initialization or execution,
    consider that it failed (TestStatus.FAIL or TestStatus.XFAIL, depending on
    test control).
    """

    pass


class ProcessResult:
    """Record results from a subprocess."""

    def __init__(self, status, out):
        """ProcessResult constructor.

        :param int status: Process exit code.
        :param bytes|str out: Captured process output stream.
        """
        self.status = status
        self.out = out


class ClassicTestDriver(TestDriver):
    """Enhanced test driver base class for common behaviors.

    This test driver provides several facilities to automate tasks that driver
    often duplicate in practice:

    * run subprocesses;
    * intercept subprocess failures and turn them into appropriate test
      statuses;
    * gather subprocess outputs to ``self.result.out``;
    * have support for automatic XFAIL/SKIP test results.
    """

    @property
    def copy_test_directory(self):
        """
        Return whether to automatically copy test directory to working dir.

        If this returns True, the working directory is automatically
        synchronized to the test directory before running the testcase:

        :rtype: bool
        """
        return True

    def run(self):
        """Run the testcase.

        Subclasses must override this.
        """
        raise NotImplementedError

    @property
    def default_process_timeout(self):
        """
        Return the default timeout for processes spawn in the ``shell`` method.

        The result is a number of seconds.

        :rtype: int
        """
        # Return the timeout defined in test.yaml, if present, otherwise return
        # our true default: 5 minutes.
        return self.test_env.get("timeout", 5 * 60)

    @property
    def default_encoding(self):
        """Return the default encoding to decode process outputs.

        If "binary", consider that process outputs are binary, so do not try to
        decode them to text.
        """
        return self.test_env.get("encoding", "utf-8")

    @property
    def test_control_creator(self):
        """Return a test control creator for this test.

        By default, this returns a YAMLTestControlCreator instance tied to this
        driver with an empty condition environment. Subclasses are free to
        override this to suit their needs: for instance returning a
        OptfileCreater to process "test.opt" files.

        :rtype: e3.testsuite.control.TestControlCreator
        """
        return YAMLTestControlCreator({})

    def shell(self, args, cwd=None, env=None, catch_error=True,
              analyze_output=True, timeout=None, encoding=None):
        """Run a subprocess.

        :param str args: Arguments for the subprocess to run.
        :param None|str cwd: Current working directory for the subprocess. By
            default (i.e. if None), use the test working directory.
        :param None|dict[str, str] env: Environment to pass to the subprocess.
        :param bool catch_error: If True, consider that an error status code
            leads to a test failure. In that case, abort the testcase.
        :param bool analyze_output: If True, add the subprocess output to the
            ``self.output`` log.
        :param None|int timeout: Timeout (in seconds) for the subprocess. Use
            ``self.default_timeout`` if left to None.
        :param str|None encoding: Encoding to use when decoding the subprocess'
            output stream. If None, use the default enocding for this test
            (``self.default_encoding``, from the ``encoding`` entry in
            test.yaml). If "binary", leave the output undecoded as a bytes
            string.
        :rtype: ProcessResult
        """
        # By default, run the subprocess in the test working directory
        if cwd is None:
            cwd = self.test_env["working_dir"]

        if timeout is None:
            timeout = self.default_process_timeout

        # Run the subprocess and log it
        def format_header(label, value):
            return "{}{}{}: {}{}\n".format(
                self.Style.RESET_ALL + self.Style.BRIGHT,
                label,
                self.Style.RESET_ALL,
                self.Style.DIM,
                value,
            )
        self.result.log += format_header(
            "Running",
            "{} (cwd={}{}{})".format(
                " ".join(quote_arg(a) for a in args),
                self.Style.RESET_ALL,
                cwd,
                self.Style.DIM
            )
        )

        process_info = {"cmd": args,
                        "cwd": cwd}
        self.result.processes.append(process_info)

        # Python2's subprocess module does not handle timeout, so re-implement
        # e3.os.process's rlimit-based implementation of timeouts.
        if timeout is not None:
            args = [get_rlimit(), str(timeout)] + args

        # We cannot use e3.os.process.Run as this API forces the use of text
        # streams, whereas testsuite sometimes need to deal with binary data
        # (or unknown encodings, which is equivalent).
        subp = subprocess.Popen(
            args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        stdout, _ = subp.communicate()
        encoding = encoding or self.default_encoding
        if encoding != "binary":
            try:
                stdout = stdout.decode(encoding)
            except UnicodeDecodeError as exc:
                raise TestAbortWithError(
                    "cannot decode process output ({}: {})".format(
                        type(exc).__name__, exc
                    )
                )

        p = ProcessResult(subp.returncode, stdout)

        self.result.log += format_header("Status code", p.status)
        process_info["status"] = p.status
        process_info["output"] = Log(stdout)

        self.result.log += format_header(
            "Output", "\n" + str(process_info["output"])
        )

        # If requested, use its output for analysis
        if analyze_output:
            self.output += stdout

        if catch_error and p.status != 0:
            raise TestAbortWithFailure("non-zero status code")

        return p

    def add_test(self, dag):
        self.add_fragment(dag, "run_wrapper")

    def push_success(self):
        """Set status to consider that the test passed."""
        # Given that we skip execution right after the test control evaluation,
        # there should be no way to call push_success in this case.
        assert not self.test_control.skip

        if self.test_control.xfail:
            self.result.set_status(TestStatus.XPASS)
        else:
            self.result.set_status(TestStatus.PASS)
        self.push_result()

    def push_skip(self, message):
        """
        Consider that we skipped the test, set status accordingly.

        :param str message: Label to explain the skipping.
        """
        self.result.set_status(TestStatus.SKIP, message)
        self.push_result()

    def push_error(self, message):
        """
        Set status to consider that something went wrong during test execution.

        :param str message: Message to explain what went wrong.
        """
        self.result.set_status(TestStatus.ERROR, message)
        self.push_result()

    def push_failure(self, message):
        """
        Consider that the test failed and set status according to test control.

        :param str message: Test failure description.
        """
        if self.test_control.xfail:
            status = TestStatus.XFAIL
            if self.test_control.message:
                message = "{} ({})".format(message, self.test_control.message)
        else:
            status = TestStatus.FAIL
        self.result.set_status(status, message)
        self.push_result()

    def set_up(self):
        """Run initialization operations before a test runs.

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
        """Run finalization operations after a test has run.

        Subclasses can override this to run clean-ups after testcase execution.

        See set_up's docstring for the rationale.
        """
        pass

    def run_wrapper(self, prev, slot):
        # Make the slot (unique identifier for active jobs at a specific time)
        # available to the overridable methods.
        self.slot = slot

        # Make colors available for output if enabled testsuite-wide
        if self.env.enable_colors:  # interactive-only
            self.Fore = Fore
            self.Style = Style
        else:
            self.Fore = DummyColors()
            self.Style = DummyColors()

        # Create a test control for this test...
        try:
            self.test_control = self.test_control_creator.create(self)
        except ValueError as exc:
            return self.push_error(
                "Error while interpreting control: {}".format(exc))

        # If test control tells us to skip the test, stop right here. Note that
        # if we have both skip and xfail, we are supposed not to execute the
        # test but still consider it as an expected failure (not just
        # "skipped").
        if self.test_control.skip:
            if self.test_control.xfail:
                return self.push_failure(self.test_control.message)
            else:
                return self.push_skip(self.test_control.message)

        # If requested, prepare the test working directory to initially be a
        # copy of the test directory.
        if self.copy_test_directory:
            sync_tree(self.test_env["test_dir"], self.test_env["working_dir"],
                      delete=True)

        # If the requested encoding is "binary", this actually means we will
        # handle binary data (i.e. no specific encoding). Create a binary log
        # accordingly.
        self.output = (
            Log(b"") if self.default_encoding == "binary" else Log("")
        )

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
