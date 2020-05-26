import os.path
import re
import sys
import time

from e3.fs import cp, sync_tree
from e3.testsuite.driver.classic import TestAbortWithError
from e3.testsuite.driver.diff import DiffTestDriver, PatternSubstitute
from e3.testsuite.control import AdaCoreLegacyTestControlCreator


class AdaCoreLegacyTestDriver(DiffTestDriver):
    """Test driver for legacy AdaCore testsuites.

    This test driver expects a "test.cmd", "test.sh" or "test.py" script in its
    directory, runs it, and succeeds iff its output matches the content of the
    "test.out" file (or is empty, if that file is missing). Execution of tests
    is controlled by "test.opt" files.

    This driver assumes that the list of discriminants for the "test.opt" file
    is available as "self.env.discs", and that the environ for subprocesses is
    available as "self.env.test_environ".

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

    @property
    def test_control_creator(self):
        return AdaCoreLegacyTestControlCreator(self.env.discs)

    @property
    def baseline_file(self):
        # the "_baseline_file" attribute is defined during the "set_up" stage,
        # and our baseline is never a regexp.
        return (self._baseline_file, False)

    def set_up(self):
        super().set_up()

        # Make sure the test script is present
        script = self.test_control.opt_results["CMD"]
        script_abs = self.test_dir(script)
        if not os.path.isfile(script_abs):
            raise TestAbortWithError(
                "cannot find script file {}".format(script)
            )

        # If we have a non-standard output baseline file, make sure it is
        # present.
        baseline = self.test_control.opt_results["OUT"]
        baseline_abs = self.test_dir(baseline)
        if (
            not baseline.endswith("test.out")
            and not os.path.isfile(baseline_abs)
        ):
            raise TestAbortWithError(
                "cannot find output file {}".format(script)
            )

        # Copy test material to $working_dir/src and make sure we have a
        # baseline file.
        sync_tree(self.test_dir(), self.working_dir("src"), delete=True)
        self.script_file = self.working_dir("src", script)
        self._baseline_file = self.working_dir("src", baseline)
        if not os.path.isfile(self._baseline_file):
            with open(self._baseline_file, "w"):
                pass

        # Prepare the test script execution
        self.timeout = int(self.test_control.opt_results["RLIMIT"])
        self.test_environ = dict(self.env.test_environ)
        self.argv = self.get_script_command_line()

    default_substitutions = [
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
    def cmd_substitutions(self):
        """
        List of substitutions to apply to scripts.

        This returns a list of patterns/replacements couples for substitutions
        to apply to scripts in order to convert them from "cmd" syntax to
        Bourne shell.

        :rtype: list[(re.regexp, str)]
        """
        return list(self.default_substitutions)

    def get_script_command_line(self):
        """Return the command line to run the test script.

        :rtype: list[str]
        """
        # Command line computation depends on the kind of script (Python or
        # shell).
        _, ext = os.path.splitext(self.script_file)
        if ext == ".py":
            return [sys.executable, self.script_file]

        elif (
            self.env.host.os.name != "windows"
            or "FORCE_SH" in self.env.discs
        ):
            # If not running on Windows, or if specifically asked to use a
            # Bourne shell, create a shell script to run instead of the given
            # test script.
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

            # Read all lines in the original test script. Get rid of potential
            # whitespaces and CR at the end of each line, and convert the "cmd"
            # syntax to Bourne shell.
            with open(self.script_file) as f:
                for line in f:
                    line = line.rstrip()
                    for pattern, replacement in self.cmd_substitutions:
                        line = pattern.sub(replacement, line)
                    new_script.append(line)

            # Write the shell script and schedule its execution with "bash"
            new_script_filename = self.working_dir("__test.sh")
            with open(new_script_filename, "w") as f:
                for line in new_script:
                    f.write(line)
                    f.write("\n")
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
    def output_refiners(self):
        return [
            # Remove platform specificities in relative filenames
            PatternSubstitute(rb"\\", rb"/"),

            # Remove ".exe" extension and CR characters anywhere in outputs.
            # TODO: same question as in the TODO in "cmd_substitutions".
            PatternSubstitute(rb"(\.exe\b|\015)", rb""),

            # Remove occurences of the "src" working dir subdirectory
            PatternSubstitute(
                rb"[^ '\"]*"
                + os.path.basename(self.working_dir()).encode("ascii")
                + rb"/src/",
                rb""
            ),
        ]

    def run(self):
        # Run the test script and record execution time. Note that the
        # status code is not significant (catch_error=False).
        start_time = time.time()
        self.shell(
            args=self.argv,
            cwd=self.working_dir("src"),
            env=self.test_environ,
            timeout=self.timeout,
            catch_error=False
        )
        self.result.execution_time = time.time() - start_time
