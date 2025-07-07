from __future__ import annotations

import os
import re

from pathlib import Path
import traceback
from typing import Any, Dict, IO, List, Optional, TYPE_CHECKING, Union

import e3.collection.dag
from e3.fs import rm, sync_tree
from e3.os.process import DEVNULL, PIPE, Run, STDOUT, quote_arg
from e3.testsuite import CleanupMode
from e3.testsuite.utils import DummyColors
from e3.testsuite.control import (
    TestControl,
    TestControlCreator,
    YAMLTestControlCreator,
)
from e3.testsuite.driver import TestDriver
from e3.testsuite.result import (
    Log,
    TestResult,
    TestStatus,
    binary_repr,
    truncated,
)
from e3.testsuite.utils import indent

from colorama import Fore, Style


if TYPE_CHECKING:
    from e3.os.process import DEVNULL_VALUE, PIPE_VALUE

    import colorama


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


# Regular expressions to match the "timeout" error message from the rlimit
# program.
TIMEOUT_OUTPUT_PATTERN = r"rlimit: Real time limit ([^\n]+) exceeded\n"
TIMEOUT_OUTPUT_STR_RE = re.compile(TIMEOUT_OUTPUT_PATTERN)
TIMEOUT_OUTPUT_BYTES_RE = re.compile(TIMEOUT_OUTPUT_PATTERN.encode("ascii"))


class ProcessResult:
    """Record results from a subprocess."""

    def __init__(self, status: int, out: Union[str, bytes]):
        """ProcessResult constructor.

        :param status: Process exit code.
        :param out: Captured process output stream.
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

    Fore: colorama.ansi.AnsiFore | DummyColors
    Style: colorama.ansi.AnsiStyle | DummyColors

    # Depending on the default encoding, this can be either a log of strings or
    # a log of bytes.
    output: Log

    test_control: TestControl

    @property
    def copy_test_directory(self) -> bool:
        """
        Return whether to automatically copy test directory to working dir.

        If this returns True, the working directory is automatically
        synchronized to the test directory before running the testcase:
        """
        return True

    def run(self) -> None:
        """Run the testcase.

        Subclasses must override this.
        """
        raise NotImplementedError

    @property
    def default_process_timeout(self) -> int:
        """
        Return the default timeout for processes spawn in the ``shell`` method.

        The result is a number of seconds.
        """
        # Return the timeout defined in test.yaml, if present, otherwise return
        # our true default: 5 minutes.
        return self.test_env.get("timeout", 5 * 60)

    @property
    def default_encoding(self) -> str:
        """Return the default encoding to decode process outputs.

        If "binary", consider that process outputs are binary, so do not try to
        decode them to text.
        """
        return self.test_env.get("encoding", "utf-8")

    @property
    def test_control_creator(self) -> TestControlCreator:
        """Return a test control creator for this test.

        By default, this returns a YAMLTestControlCreator instance tied to this
        driver with an empty condition environment. Subclasses are free to
        override this to suit their needs: for instance returning a
        OptfileCreater to process "test.opt" files.
        """
        return YAMLTestControlCreator({})

    def shell(
        self,
        args: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        catch_error: bool = True,
        analyze_output: bool = True,
        timeout: Optional[int] = None,
        encoding: Optional[str] = None,
        truncate_logs_threshold: Optional[int] = None,
        ignore_environ: bool = True,
        stdin: (
            DEVNULL_VALUE | PIPE_VALUE | str | bytes | Path | IO | None
        ) = DEVNULL,
    ) -> ProcessResult:
        """Run a subprocess.

        :param args: Arguments for the subprocess to run.
        :param cwd: Current working directory for the subprocess. By default
            (i.e. if None), use the test working directory.
        :param env: Environment to pass to the subprocess.
        :param catch_error: If True, consider that an error status code leads
            to a test failure. In that case, abort the testcase.
        :param analyze_output: If True, add the subprocess output to the
            ``self.output`` log.
        :param timeout: Timeout (in seconds) for the subprocess. Use
            ``self.default_timeout`` if left to None.
        :param encoding: Encoding to use when decoding the subprocess' output
            stream. If None, use the default enocding for this test
            (``self.default_encoding``, from the ``encoding`` entry in
            test.yaml).  If "binary", leave the output undecoded as a bytes
            string.
        :param truncate_logs_threshold: Threshold to truncate the subprocess
            output in ``self.result.log``. See
            ``e3.testsuite.result.truncated``'s ``line_count`` argument. If
            left to None, use the testsuite's ``--truncate-logs`` option.
        :param ignore_environ: Applies only when ``env`` is not None.
            When True (the default), pass exactly environment variables
            in ``env``. When False, pass a copy of ``os.environ`` that is
            augmented with variables in ``env``.
        :param stdin: Forwarded to ``e3.os.process.Run``'s ``input`` argument.
        """
        # By default, run the subprocess in the test working directory
        if cwd is None:
            cwd = self.test_env["working_dir"]

        if timeout is None:
            timeout = self.default_process_timeout

        if truncate_logs_threshold is None:
            truncate_logs_threshold = self.testsuite_options.truncate_logs

        # Run the subprocess and log it
        def format_header(label: str, value: Any) -> str:
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
                self.Style.DIM,
            ),
        )

        process_info = {"cmd": args, "cwd": cwd}
        self.result.processes.append(process_info)

        subp = Run(
            cmds=args,
            cwd=cwd,
            output=PIPE,
            error=STDOUT,
            input=stdin,
            timeout=timeout,
            env=env,
            ignore_environ=ignore_environ,
        )

        # Testsuites sometimes need to deal with binary data (or unknown
        # encodings, which is equivalent), so always use subp.raw_out.
        stdout: Union[str, bytes]
        assert isinstance(subp.raw_out, bytes)
        stdout_bytes = subp.raw_out
        encoding = encoding or self.default_encoding
        if encoding != "binary":
            try:
                stdout = stdout_bytes.decode(encoding)
            except UnicodeDecodeError as exc:
                self.result.log += "Cannot decode subprocess output:\n\n"
                self.result.log += indent(binary_repr(stdout_bytes))
                raise TestAbortWithError(
                    "cannot decode process output ({}: {})".format(
                        type(exc).__name__, exc
                    )
                ) from exc
        else:
            stdout = stdout_bytes

        # We run subprocesses in foreground mode, so by the time Run's
        # constructor has returned, the subprocess is supposed to have
        # completed, and thus we are supposed to have an exit status code.
        assert subp.status is not None
        p = ProcessResult(subp.status, stdout)

        self.result.log += format_header("Status code", p.status)
        process_info["status"] = p.status
        process_info["output"] = Log(stdout)

        self.result.log += format_header(
            "Output",
            "\n"
            + truncated(str(process_info["output"]), truncate_logs_threshold),
        )

        # If requested, use its output for analysis
        if analyze_output:
            self.output += stdout

        if catch_error and p.status != 0:
            raise TestAbortWithFailure("non-zero status code")

        return p

    def add_test(self, dag: e3.collection.dag.DAG) -> None:
        self.add_fragment(dag, "run_wrapper")

    def push_success(self) -> None:
        """Set status to consider that the test passed."""
        # Given that we skip execution right after the test control evaluation,
        # there should be no way to call push_success in this case.
        assert not self.test_control.skip

        if self.test_control.xfail:
            self.result.set_status(TestStatus.XPASS, self.test_control.message)
        else:
            self.result.set_status(TestStatus.PASS)
        self.push_result()

    def push_skip(self, message: Optional[str]) -> None:
        """
        Consider that we skipped the test, set status accordingly.

        :param message: Label to explain the skipping.
        """
        self.result.set_status(TestStatus.SKIP, message)
        self.push_result()

    def push_error(self, message: Optional[str]) -> None:
        """
        Set status to consider that something went wrong during test execution.

        :param message: Message to explain what went wrong.
        """
        self.result.set_status(TestStatus.ERROR, message)
        self.push_result()

    def push_failure(self, message: Optional[str]) -> None:
        """
        Consider that the test failed and set status according to test control.

        :param message: Test failure description.
        """
        if self.test_control.xfail:
            status = TestStatus.XFAIL
            if self.test_control.message:
                message = "{} ({})".format(message, self.test_control.message)
        else:
            status = TestStatus.FAIL
        self.result.set_status(status, message)
        self.push_result()

    def set_up(self) -> None:
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

    def cleanup_working_dir(self) -> None:
        """Remove the working directory tree."""
        try:
            rm(self.working_dir(), True)
        except Exception:  # all: no cover
            # TODO (U222-013) For mysterious reasons, on Windows hosts,
            # sometimes executable files are still visible in the filesystem
            # even after the call to "os.unlink" returned with success. As a
            # result, removing the directory that contains them fails and thus
            # we get an exception.  At first we thought it could be related to
            # the system indexer
            # (https://superuser.com/questions/260375/why-would-system-continue-locking-
            # executable-file-handles-after-the-app-has-exit)
            # but this issue still occurs on systems that have it disabled.
            #
            # As far as we know (because we failed to pinpoint the exact reason
            # for this condition), these issues do not reveal any bug in tests
            # themselves, so silently ignore such errors.
            if self.env.host.os.name == "windows":
                self.result.log += (
                    f"\nError while cleaning up the working directory:"
                    f"\n{traceback.format_exc()}"
                    f"\nHost is running Windows: discarding this error..."
                )
            else:
                raise

    def tear_down(self) -> None:
        """Run finalization operations after a test has run.

        Subclasses can override this to run clean-ups after testcase execution.
        By default, this method removes the working directory (unless
        --disable-cleanup/--dev-temp is passed).

        See set_up's docstring for the rationale behind this API.
        """
        # Do nothing if cleanup is disabled, not requested for this result or
        # disabled for this driver.
        if (
            self.env.cleanup_mode == CleanupMode.NONE
            or (
                self.env.cleanup_mode == CleanupMode.PASSING
                and self.result.status
                in (
                    TestStatus.FAIL,
                    TestStatus.XFAIL,
                    TestStatus.XPASS,
                    TestStatus.ERROR,
                )
            )
            or not self.working_dir_cleanup_enabled
        ):
            return

        # If an error occurs during working dir cleanup, create a dedicated
        # error message and dump the content of the working directory tree
        # to help investigation.
        wd = self.working_dir()
        try:
            self.cleanup_working_dir()
        except Exception:
            result = TestResult(
                f"{self.test_name}__tear_down",
                env=self.test_env,
                status=TestStatus.ERROR,
            )

            result.log += (
                f"Error while removing the working directory {wd}:\n\n"
            )
            result.log += traceback.format_exc()
            result.log += "\nRemaining files:\n"
            for dirpath, _dirnames, filenames in os.walk(wd):
                if dirpath != wd:
                    result.log += f"  {os.path.relpath(dirpath, wd)}\n"
                for f in filenames:
                    fpath = os.path.join(dirpath, f)
                    result.log += f"  {os.path.relpath(fpath, wd)}\n"
            self.push_result(result)

    def run_wrapper(self, prev: Dict[str, Any], slot: int) -> None:
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
                "Error while interpreting control: {}".format(exc)
            )

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
            sync_tree(
                self.test_env["test_dir"],
                self.test_env["working_dir"],
                delete=True,
            )

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

    def process_may_have_timed_out(self, result: ProcessResult) -> bool:
        """
        Return whether the process that yielded ``result`` may have timed out.

        This assumes that ``result`` is the returned value from a call to the
        ``shell`` method. Note that this uses simple heuristics to determine
        whether the process may have timed out, as this information is not
        preserved reliably under the hood: process is wrapped under the rlimit
        program, which just prints a known error message and returns some
        specific exit code in case of timeout.
        """
        if result.status != 2:
            return False

        if isinstance(result.out, str):
            return bool(TIMEOUT_OUTPUT_STR_RE.search(result.out))
        else:
            return bool(TIMEOUT_OUTPUT_BYTES_RE.search(result.out))

    def compute_failures(self) -> List[str]:
        """
        Analyze the testcase result and return the list of reasons for failure.

        This architecture allows to have multiple reasons for failures, for
        instance: unexpected computation result + presence of Valgrind
        diagnostics. The result is a list of short strings that describe the
        failures. This method is expected to write to ``self.result.log`` in
        order to convey more information if needed.

        By default, consider that the testcase succeeded if we reach the
        analysis step. Subclasses may override this to actually perform checks.
        """
        return []

    def analyze(self) -> None:
        """Analyze the testcase result, adjust status accordingly."""
        failures = self.compute_failures()
        if failures:
            self.push_failure(" | ".join(failures))
        else:
            self.push_success()
