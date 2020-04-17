import os
import re
import sys

from e3.diff import diff
from e3.os.fs import unixpath
from e3.testsuite.result import Log, binary_repr
from e3.testsuite.driver.classic import ClassicTestDriver, TestAbortWithError


def indent(text, prefix="  "):
    """Prepend ``prefix`` to every line in ``text``.

    :param str text: Text to transform.
    :param str prefix: String to prepend.
    :rtype: str
    """
    # Use .split() rather than .splitlines() because we need to preserve the
    # last line if is empty. "a\n".splitlines() returns ["a"], so we must avoid
    # it.
    return "\n".join((prefix + line) for line in text.split("\n"))


class OutputRefiner(object):
    """
    Interface to refine a test output before baseline and actual comparison.

    Sometimes, the way a library/tool works forces it to have outputs that
    depends on the environment (for instance: the location of the testsuite on
    the filesystem, the current date, etc.). Refiners makes it possible for
    a testsuite to "hide" these discrepancies during the diff computation.

    Note that output refiners might get called bytes strings when the test
    drivers operate in binary mode.
    """

    def refine(self, output):
        """
        Refine a test/baseline output.

        :param str output: Output to refine.
        :rtype: str
        """
        raise NotImplementedError


class RefiningChain(OutputRefiner):
    """Simple wrapper for a sequence of output refiners applied in chain."""

    def __init__(self, refiners):
        """
        Initialize a RefiningChain instance.

        :param list[OutputRefiner] refiners: List of refiners to execute in
            sequence.
        """
        self.refiners = refiners

    def refine(self, output):
        for r in self.refiners:
            output = r.refine(output)
        return output


class Substitute(OutputRefiner):
    """Replace substrings in outputs."""

    def __init__(self, substring, replacement=""):
        """
        Initialize a Substitute instance.

        :param str substring: Substring to replace.
        :param str replacement: Replacement to use for the substitution.
        """
        self.substring = substring
        self.replacement = replacement

    def refine(self, output):
        return output.replace(self.substring, self.replacement)


class ReplacePath(RefiningChain):
    """Return an output refiner to replace the given path."""

    def __init__(self, path, replacement=""):
        # TODO: the path processings below were mostly copied from gnatpython.
        # The exact intend behind them is unknown: we should investigate
        # removing them at some point, and if they are really needed, document
        # here why they are.

        def escape(s):
            return s.replace("\\", "\\\\")

        super(ReplacePath, self).__init__([
            Substitute(substring, replacement)
            for substring in [escape(os.path.abspath(path)),
                              escape(unixpath(path)),
                              escape(path)]
        ])


class PatternSubstitute(OutputRefiner):
    """Replace patterns in outputs."""

    def __init__(self, pattern, replacement=""):
        """
        Initialize a PatternSubstitute instance.

        :param str pattern: Pattern (regular expression) to replace.
        :param str replacement: Replacement to use for the substitution.
        """
        self.regexp = re.compile(pattern)
        self.replacement = replacement

    def refine(self, output):
        return self.regexp.sub(self.replacement, output)


class DiffTestDriver(ClassicTestDriver):
    """Test driver to compute test output against a baseline."""

    @property
    def baseline_file(self):
        """Return the test output baseline file.

        :return: The name of the text file (relative to test directories) that
            contains the expected test output and whether the baseline is a
            regexp.
        :rtype: (str, bool)
        """
        filename = self.test_env.get("baseline_file", "test.out")
        is_regexp = self.test_env.get("baseline_regexp", False)
        return (filename, is_regexp)

    @property
    def baseline(self):
        """Return the test output baseline.

        Subclasses can override this method if they want to provide a baseline
        that does not come from a file, short-circuiting the baseline_file
        property.

        :return: The baseline absolute filename (if any), the baseline content,
            as a string or as a bytes string (depending on the default
            encoding), and whether the baseline is a regexp. The baseline
            filename is used to rewrite test output: leave it to None if
            rewriting does not make sense.
        :rtype: (str|None, str|bytes, bool)
        """
        filename, is_regexp = self.baseline_file
        filename = self.test_dir(filename)
        is_binary = self.default_encoding == "binary"
        mode = "rb" if is_binary else "rt"

        try:
            with open(filename, mode) as f:
                baseline = f.read()
            if not is_binary and sys.version_info.major == 2:  # py2-only
                baseline = baseline.decode(self.default_encoding)
        except Exception as exc:
            raise TestAbortWithError(
                "cannot read baseline file ({}: {})".format(
                    type(exc).__name__, exc
                )
            )
        return (filename, baseline, is_regexp)

    output_refiners = []
    """
    List of refiners for test baselines/outputs.

    :type: list[OutputRefiner]
    """

    diff_ignore_white_chars = False
    """
    Whether the comparison between test output and baseline must ignore
    whitespaces (leading and trailing spaces, tabs and carriage returns on
    lines, and empty lines). Note that if we don't ignore them, we still
    canonicalize line separators (CRLF are replaced by LF before the
    comparison).

    Note that at some point, this mechanism should be unified with the
    ``output_refiners`` machinery. However, this relies on e3.diff's
    ignore_white_chars feature, which is not trivial to reimplement.
    """

    def compute_diff(self, baseline_file, baseline, actual,
                     failure_message="unexpected output",
                     ignore_white_chars=None):
        """Compute the diff between expected and actual outputs.

        Return an empty list if there is no diff, and return a list that
        contains an error message based on ``failure_message`` otherwise.

        :param str|None baseline_file: Absolute filename for the text file that
            contains the expected content (for baseline rewriting, if enabled),
            or None.
        :param str|bytes actual: Actual content to compare.
        :param str failure_message: Failure message to return if there is a
            difference.
        :param None|bool ignore_white_chars: Whether to ignore whitespaces
            during the diff computation. If left to None, use
            ``self.diff_ignore_white_chars``.

        :rtype: list[str]
        """
        if ignore_white_chars is None:
            ignore_white_chars = self.diff_ignore_white_chars

        # Run output refiners
        refiners = RefiningChain(self.output_refiners)
        actual = refiners.refine(actual)
        baseline = refiners.refine(baseline)

        # When running in binary mode, make sure the diff runs on text strings
        if self.default_encoding == "binary":
            actual = binary_repr(actual)
            baseline = binary_repr(baseline)

        # Except in Python2: e3.diff supports only bytes string
        if sys.version_info.major == 2:  # py2-only
            actual = actual.encode("utf-8")
            baseline = baseline.encode("utf-8")

        # Get the two texts to compare as list of lines, with trailing
        # characters preserved (splitlines(keepends=True)).
        expected_lines = baseline.splitlines(True)
        actual_lines = actual.splitlines(True)

        # Compute the diff. If it is empty, return no failure. Otherwise,
        # include the diff in the test log and return the given failure
        # message.
        d = diff(expected_lines, actual_lines,
                 ignore_white_chars=ignore_white_chars)
        if not d:
            return []

        message = failure_message

        diff_lines = []
        for line in d.splitlines():
            # Add colors diff lines
            if line.startswith("-"):
                color = self.Fore.RED
            elif line.startswith("+"):
                color = self.Fore.GREEN
            elif line.startswith("@"):
                color = self.Fore.CYAN
            else:
                color = ""
            diff_lines.append(color + line + self.Style.RESET_ALL)

        # If requested, rewrite the test baseline with the new one
        if (
            baseline_file is not None
            and getattr(self.env, "rewrite_baselines", False)
        ):
            with open(baseline_file, "w") as f:
                for line in actual:
                    f.write(line)
            message = "{} (baseline updated)".format(message)

        # Send the appropriate logging
        self.result.log += message + "\n"
        self.result.log += "\n".join(diff_lines) + "\n"

        return [message]

    def compute_regexp_match(
        self, regexp, actual,
        failure_message="output does not match expected pattern"
    ):
        """Compute whether the actual output matches a regexp.

        Return an empty list if the acutal content matches, and return a list
        that contains an error message based on ``failure_message`` otherwise.

        :param str|bytes|regexp regexp: Regular expression to use.
        :param str|bytes actual: Actual content to match.
        :param str failure_message: Failure message to return if there is a
            difference.

        :rtype: list[str]
        """
        if isinstance(regexp, (str, bytes)):
            regexp = re.compile(regexp)

        match = regexp.match(actual)
        if match:
            return []

        def quote(content):
            if self.default_encoding == "binary":
                content = binary_repr(content)
            return indent(content)

        # Send the appropriate logging
        self.result.log += failure_message + ":\n"
        self.result.log += quote(actual)
        self.result.log += "\nDoes not match the expected pattern:\n"
        self.result.log += quote(regexp.pattern)

        return [failure_message]

    def compute_failures(self):
        """Return a failure if ``self.result.out`` does not match the baseline.

        This computes a diff with the content of the baseline file, unless
        there is a "baseline_regexp" entry in the test environment that
        evaluates to true.

        Subclasses can override this if they need more involved analysis:
        for instance computing multiple diffs.

        :rtype: list[str]
        """
        filename, baseline, is_regexp = self.baseline
        if is_regexp:
            return self.compute_regexp_match(baseline, self.result.out.log)
        else:
            return self.compute_diff(filename, baseline, self.result.out.log)

    def analyze(self):
        # Clear the output log before computing diffs, so that we present only
        # diffs to users.
        self.result.log = Log.create_empty_text()
        super(DiffTestDriver, self).analyze()
