from __future__ import annotations

import os.path
import re
import sys
import time
from typing import Dict, List, Optional, Pattern, Tuple

from e3.fs import cp, sync_tree
from e3.testsuite.driver.classic import ProcessResult, TestAbortWithError
from e3.testsuite.driver.diff import (
    DiffTestDriver,
    LineByLine,
    OutputRefiner,
    PatternSubstitute,
)
from e3.testsuite.control import AdaCoreLegacyTestControlCreator
from e3.testsuite.result import FailureReason


class AdaCoreLegacyTestDriver(DiffTestDriver):
    """Test driver for legacy AdaCore testsuites.

    This test driver expects a "test.cmd", "test.sh" or "test.py" script in its
    directory, runs it, and succeeds iff its output matches the content of the
    "test.out" file (or is empty, if that file is missing). Execution of tests
    is controlled by "test.opt" files.

    This driver assumes that the list of discriminants for the "test.opt" file
    is available as "self.env.discs" (i.e. it is a list of strings), and that
    the environ for subprocesses is available as "self.env.test_environ".

    If the TEST_SUPPORT_DIR environment variable is defined, consider that it
    contains the name of a directory that contains a "support.sh" script, that
    is sourced at the beginning of every CMD/Shell test script.
    """

    # We have special procedures to copy test material
    copy_test_directory = False

    # Work on raw bytes: some tests work with ISO-8859-1, others UTF-8, others
    # JIS, ... and we don't have the metadata to know which.
    default_encoding = "binary"

    # By default, ignore white characters in outputs
    diff_ignore_white_chars = True

    argv: List[str]
    test_environ: Dict[str, str]

    test_process: Optional[ProcessResult]

    @property
    def test_control_creator(self) -> AdaCoreLegacyTestControlCreator:
        assert isinstance(self.env.discs, list)
        return AdaCoreLegacyTestControlCreator(self.env.discs)

    @property
    def baseline_file(self) -> Tuple[str, bool]:
        # the "_baseline_file" attribute is defined during the "set_up" stage,
        # and our baseline is never a regexp.
        return (self._baseline_file, False)

    def set_up(self) -> None:
        super().set_up()
        assert self.test_control.opt_results is not None

        # If we have a non-standard output baseline file, make sure it is
        # present.
        baseline = self.test_control.opt_results["OUT"]
        self._original_baseline_file = self.test_dir(baseline)
        if not baseline.endswith("test.out") and not os.path.isfile(
            self._original_baseline_file
        ):
            raise TestAbortWithError(
                "cannot find output file {}".format(baseline)
            )

        # Copy test material to $working_dir/src and make sure we have a
        # baseline file.
        sync_tree(self.test_dir(), self.working_dir("src"), delete=True)
        self._baseline_file = self.working_dir("src", baseline)
        if not os.path.isfile(self._baseline_file):
            with open(self._baseline_file, "w"):
                pass

        # Prepare the test script execution
        self.timeout = int(self.test_control.opt_results["RLIMIT"])
        assert isinstance(self.env.test_environ, dict)
        self.test_environ = dict(self.env.test_environ)
        self.argv = self.get_script_command_line()
        self.test_process = None

    default_substitutions: List[Tuple[Pattern[str], str]] = [
        # Remove ".exe" suffix for output files. This will for instance turn
        # "gcc -o main.exe main.adb" into "gcc -o main main.adb".
        (re.compile(r"-o(.*).exe"), r"-o \1"),
        # Convert references to environment variables: "%VAR%" -> "$VAR"
        (re.compile(r"%([^ ]*)%"), r'"$\1"'),
        # TODO??? Imported as-is from gnatpython.testdriver. It's not clear
        # what this tries to do given that escape characters are interpreted
        # literally ('r' string prefix).
        (re.compile(r"(\032|\015)"), r""),
        # Replace environment variable definitions:
        # "set FOO = BAR" -> 'FOO="BAR"; export FOO'.
        (re.compile(r"set *([^ =]+) *= *([^ ]*)"), r'\1="\2"; export \1'),
    ]

    @property
    def cmd_substitutions(self) -> List[Tuple[Pattern[str], str]]:
        """
        List of substitutions to apply to scripts.

        This returns a list of patterns/replacements couples for substitutions
        to apply to scripts in order to convert them from "cmd" syntax to
        Bourne shell.
        """
        return list(self.default_substitutions)

    @property
    def script_encoding(self) -> str:
        """Return the encoding to decode shell scripts.

        By default, this is the same as the ``default_encoding`` property,
        except in one case: when it returns ``binary``: assume UTF-8 in that
        case.
        """
        result = self.default_encoding
        return "utf-8" if result == "binary" else result

    def get_script_command_line(self) -> List[str]:
        """Return the command line to run the test script."""
        # Command line computation depends on the kind of script (Python or
        # shell).
        assert isinstance(self.env.discs, list)

        # Make sure the test script is present in the working directory
        assert self.test_control.opt_results is not None
        script_filename = self.test_control.opt_results["CMD"]
        self.script_file = self.working_dir("src", script_filename)
        if not os.path.isfile(self.script_file):
            raise TestAbortWithError(
                "cannot find script file {}".format(script_filename)
            )

        _, ext = os.path.splitext(self.script_file)

        # Some tests have a _suffix in their extension. Using .startwith
        # ensures we don't treat ".cmd_x86" as ".sh".
        is_cmd = ext.startswith(".cmd")
        must_convert = is_cmd and (
            self.env.host.os.name != "windows" or "FORCE_SH" in self.env.discs
        )

        if ext == ".py":
            return [sys.executable, self.script_file]

        elif not is_cmd or must_convert:
            # If running a Bourne shell script, not running on Windows, or if
            # specifically asked to use a Bourne shell, create a shell script
            # to run instead of the given test script.
            new_script = []

            # First, make sure the current directory is in the PATH, to ease
            # running just-built programs in test scripts.
            new_script.append("PATH=.:$PATH; export PATH")

            # TODO: filesize_limit handling

            # If "self.env.support_dir" designates a directory that contains a
            # "support.sh" file, make the test script source it.
            support_dir = os.environ.get("TEST_SUPPORT_DIR", "")
            support_script = os.path.join(support_dir, "support.sh")
            if support_dir and os.path.isfile(support_script):
                new_script.append(". $TEST_SUPPORT_DIR/support.sh")

            # Read all lines in the original test script
            script_encoding = self.script_encoding
            with open(self.script_file, encoding=script_encoding) as f:
                # Get rid of potential whitespaces and CR at the end of
                # each line.
                for line in f:
                    line = line.rstrip()
                    if must_convert:
                        # convert the "cmd" syntax to Bourne shell
                        for pattern, replacement in self.cmd_substitutions:
                            line = pattern.sub(replacement, line)
                    new_script.append(line)

            # Write the shell script and schedule its execution with "bash". On
            # Windows, Python interpreters may automatically add CR bytes
            # before LR ones: open the file in binary mode to avoid this
            # behavior, as "bash" would complain about CR bytes.
            new_script_filename = self.working_dir("__test.sh")
            with open(new_script_filename, "wb") as f:
                for line in new_script:
                    f.write(line.encode(script_encoding))
                    f.write(b"\n")
            return ["bash", new_script_filename]

        else:  # os-specific
            # We are running on Windows, so we can use "cmd" to run the
            # original script. Just make sure it has the correct extension.
            script_file = self.script_file
            if not script_file.endswith(".cmd"):
                script_file = self.working_dir("test__.cmd")
                cp(self.script_file, script_file)
            return ["cmd.exe", "/q", "/c", script_file]

    @property
    def output_refiners(self) -> List[OutputRefiner[bytes]]:
        return [
            # Remove platform specificities in relative filenames
            PatternSubstitute(rb"\\", rb"/"),
            # Remove ".exe" extension and CR characters anywhere in outputs.
            # TODO: same question as in the TODO in "cmd_substitutions".
            PatternSubstitute(rb"(\.exe\b|\015)", rb""),
            # Remove occurences of the "src" working dir subdirectory
            LineByLine(
                PatternSubstitute(
                    rb"[^ '\"]*"
                    + os.path.basename(self.working_dir()).encode("ascii")
                    + rb"/src/",
                    rb"",
                )
            ),
        ]

    def run(self) -> None:
        # Run the test script and record execution time. Note that the
        # status code is not significant (catch_error=False).
        start_time = time.time()
        self.test_process = self.shell(
            args=self.argv,
            cwd=self.working_dir("src"),
            env=self.test_environ,
            timeout=self.timeout,
            catch_error=False,
        )
        self.result.time = time.time() - start_time

    def compute_failures(self) -> List[str]:
        # First, do compute the failures and let the baseline rewriting
        # machinery do its magic on the baseline it is given (i.e. the copy in
        # the working directory: see set_up).
        result = super().compute_failures()

        # Now, make sure we propagate the new baseline to the test directory
        if not self.test_control.xfail and getattr(
            self.env, "rewrite_baselines", False
        ):
            with open(self._baseline_file, "rb") as f:
                content = f.read()

            # Materialize empty baselines as missing baseline file, but only
            # for the default baseline file.
            default_baseline_file = self.test_dir("test.out")
            if (
                content
                or self._original_baseline_file != default_baseline_file
            ):
                with open(self._original_baseline_file, "wb") as f:
                    f.write(content)
            elif os.path.exists(default_baseline_file):
                os.remove(default_baseline_file)

        if self.test_process is not None and self.process_may_have_timed_out(
            self.test_process
        ):
            self.result.failure_reasons.add(FailureReason.TIMEOUT)
            result.append("test timed out")

        return result
