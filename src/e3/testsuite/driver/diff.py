from __future__ import annotations

import os
import re
from typing import (
    AnyStr,
    Callable,
    Generic,
    List,
    Optional,
    Pattern,
    Tuple,
    Union,
)

from e3.diff import diff
from e3.os.fs import unixpath
from e3.testsuite.result import FailureReason, Log, binary_repr, truncated
from e3.testsuite.driver.classic import ClassicTestDriver, TestAbortWithError
from e3.testsuite.utils import indent


class OutputRefiner(Generic[AnyStr]):
    """
    Interface to refine a test output before baseline and actual comparison.

    Sometimes, the way a library/tool works forces it to have outputs that
    depends on the environment (for instance: the location of the testsuite on
    the filesystem, the current date, etc.). Refiners makes it possible for
    a testsuite to "hide" these discrepancies during the diff computation.

    Note that output refiners might get called bytes strings when the test
    drivers operate in binary mode.
    """

    def refine(self, output: AnyStr) -> AnyStr:
        """
        Refine a test/baseline output.

        :param output: Output to refine.
        """
        raise NotImplementedError


class RefiningChain(OutputRefiner[AnyStr]):
    """Simple wrapper for a sequence of output refiners applied in chain."""

    def __init__(self, refiners: List[OutputRefiner]):
        """
        Initialize a RefiningChain instance.

        :param refiners: List of refiners to execute in sequence.
        """
        self.refiners = refiners

    def refine(self, output: AnyStr) -> AnyStr:
        for r in self.refiners:
            output = r.refine(output)
        return output


class Substitute(OutputRefiner[AnyStr]):
    """Replace substrings in outputs."""

    def __init__(
        self, substring: AnyStr, replacement: Optional[AnyStr] = None
    ) -> None:
        """
        Initialize a Substitute instance.

        :param substring: Substring to replace.
        :param replacement: Replacement to use for the substitution. If left to
            None, just remove the substring (i.e. use an empty replacement
            string).
        """
        self.substring: AnyStr = substring
        self.replacement: AnyStr = replacement or type(substring)()

    def refine(self, output: AnyStr) -> AnyStr:
        return output.replace(self.substring, self.replacement)


class CanonicalizeLineEndings(OutputRefiner[AnyStr]):
    r"""Replace \r\n with \n in outputs."""

    def refine(self, output: AnyStr) -> AnyStr:
        if isinstance(output, str):
            return output.replace("\r\n", "\n")
        else:
            return output.replace(b"\r\n", b"\n")


class ReplacePath(RefiningChain[str]):
    """Return an output refiner to replace the given path."""

    def __init__(self, path: str, replacement: str = "") -> None:
        # First replace the normalized path, then the Unix-style path (which
        # some tool may output even on Windows) and finally the very path that
        # was given.
        super().__init__(
            [
                Substitute(substring, replacement)
                for substring in [os.path.realpath(path), unixpath(path), path]
            ]
        )


class PatternSubstitute(OutputRefiner, Generic[AnyStr]):
    """Replace patterns in outputs."""

    def __init__(
        self,
        pattern: AnyStr,
        replacement: AnyStr | Callable[[re.Match], AnyStr] | None = None,
    ) -> None:
        """
        Initialize a PatternSubstitute instance.

        :param pattern: Pattern (regular expression) to replace.
        :param replacement: Replacement to use for the substitution. If left to
            None, just remove the substring (i.e. use an empty replacement
            string).
        """
        self.regexp: Pattern[AnyStr] = re.compile(pattern)
        self.replacement: AnyStr | Callable[[re.Match], AnyStr] = (
            replacement or type(pattern)()
        )

    def refine(self, output: AnyStr) -> AnyStr:
        return self.regexp.sub(self.replacement, output)


class LineByLine(OutputRefiner[AnyStr]):
    """Wrapper to apply an output refine line by line."""

    def __init__(self, refiner: OutputRefiner) -> None:
        """
        Initialize a LineByLine instance.

        :param refiner: Refiner to apply on each input line.
        """
        self.refiner = refiner

    def refine(self, output: AnyStr) -> AnyStr:
        if isinstance(output, str):
            return "".join(
                self.refiner.refine(line)
                for line in output.splitlines(keepends=True)
            )
        else:
            return b"".join(
                self.refiner.refine(line)
                for line in output.splitlines(keepends=True)
            )


class DiffTestDriver(ClassicTestDriver):
    """Test driver to compute test output against a baseline."""

    @property
    def rewrite_baseline(self) -> bool:
        """Return whether this driver should rewrite its baseline."""
        # If a failure is expected for this test, consider that the actual
        # output is wrong, and so do not rewrite the baseline.
        return (
            self.baseline_file is not None
            and not self.test_control.xfail
            and getattr(self.env, "rewrite_baselines", False)
        )

    @property
    def baseline_file(self) -> Tuple[str, bool]:
        """Return the test output baseline file.

        :return: The name of the text file (relative to test directories) that
            contains the expected test output and whether the baseline is a
            regexp.
        """
        filename = self.test_env.get("baseline_file", "test.out")
        is_regexp = self.test_env.get("baseline_regexp", False)
        return (filename, is_regexp)

    @property
    def baseline(self) -> Tuple[Optional[str], Union[str, bytes], bool]:
        """Return the test output baseline.

        Subclasses can override this method if they want to provide a baseline
        that does not come from a file, short-circuiting the baseline_file
        property.

        :return: The baseline absolute filename (if any), the baseline content,
            as a string or as a bytes string (depending on the default
            encoding), and whether the baseline is a regexp. The baseline
            filename is used to rewrite test output: leave it to None if
            rewriting does not make sense.
        """
        encoding = self.default_encoding
        is_binary = encoding == "binary"
        filename, is_regexp = self.baseline_file
        filename = self.test_dir(filename)
        baseline: Union[str, bytes]

        # If the baseline should be rewritten, tolerate a missing baseline file
        # and start from an empty baseline: we will create the baseline once
        # the test has run.
        if self.rewrite_baseline and not os.path.isfile(filename):
            return (filename, b"" if is_binary else "", is_regexp)

        try:
            if is_binary:
                with open(filename, "rb") as bin_f:
                    baseline = bin_f.read()
            else:
                with open(filename, "r", encoding=encoding) as text_f:
                    baseline = text_f.read()
        except Exception as exc:
            raise TestAbortWithError(
                "cannot read baseline file ({}: {})".format(
                    type(exc).__name__, exc
                )
            ) from exc
        return (filename, baseline, is_regexp)

    @property
    def output_refiners(self) -> List[OutputRefiner]:
        """
        List of refiners for test baselines/outputs.

        This just returns a refiner to canonicalize line endings unless the
        test environment contains a "strict_line_endings" key associated to
        true.
        """
        return (
            []
            if self.test_env.get("strict_line_endings", False)
            else [CanonicalizeLineEndings()]
        )

    @property
    def refine_baseline(self) -> bool:
        """Whether to apply output refiners to the output baseline."""
        return True

    @property
    def diff_ignore_white_chars(self) -> bool:
        """
        Whether to ignore white characters in diff computations.

        This returns whether the comparison between test output and baseline
        must ignore whitespaces (leading and trailing spaces, tabs and carriage
        returns on lines, and empty lines). Note that if we don't ignore them,
        we still canonicalize line separators (CRLF are replaced by LF before
        the comparison).

        Note that at some point, this mechanism should be unified with the
        ``output_refiners`` machinery. However, this relies on e3.diff's
        ignore_white_chars feature, which is not trivial to reimplement.
        """
        return False

    @property
    def diff_context_size(self) -> int:
        """Positive number of context lines to include in diff computations."""
        return self.test_env.get("diff_context_size", 1)

    def set_up(self) -> None:
        super().set_up()

        # Keep track of the number of non-clean diffs
        self.failing_diff_count = 0

    def compute_diff(
        self,
        baseline_file: Optional[str],
        baseline: AnyStr,
        actual: AnyStr,
        failure_message: str = "unexpected output",
        ignore_white_chars: Optional[bool] = None,
        context_size: Optional[int] = None,
        truncate_logs_threshold: Optional[int] = None,
    ) -> List[str]:
        """Compute the diff between expected and actual outputs.

        Return an empty list if there is no diff, and return a list that
        contains an error message based on ``failure_message`` otherwise.

        :param baseline_file: Absolute filename for the text file that contains
            the expected content (for baseline rewriting, if enabled), or None.
        :param actual: Actual content to compare.
        :param failure_message: Failure message to return if there is a
            difference.
        :param ignore_white_chars: Whether to ignore whitespaces during the
            diff computation. If left to None, use
            ``self.diff_ignore_white_chars``.
        :param context_size: Positive number of context lines to include in
            diff computations. If left to None, use ``self.diff_context_size``.
        :param truncate_logs_threshold: Threshold to truncate the diff message
            in ``self.result.log``. See ``e3.testsuite.result.truncated``'s
            ``line_count`` argument. If left to None, use the testsuite's
            ``--truncate-logs`` option.
        """
        if ignore_white_chars is None:
            ignore_white_chars = self.diff_ignore_white_chars

        if context_size is None:
            context_size = self.diff_context_size

        if truncate_logs_threshold is None:
            truncate_logs_threshold = self.testsuite_options.truncate_logs

        # Run output refiners on the actual output, not on the baseline
        refiners = (
            RefiningChain[str](self.output_refiners)
            if isinstance(actual, str)
            else RefiningChain[bytes](self.output_refiners)
        )
        refined_actual = refiners.refine(actual)
        refined_baseline = (
            refiners.refine(baseline) if self.refine_baseline else baseline
        )

        # When running in binary mode, make sure the diff runs on text strings
        if self.default_encoding == "binary":
            assert isinstance(refined_actual, bytes)
            assert isinstance(refined_baseline, bytes)
            decoded_actual = binary_repr(refined_actual)
            decoded_baseline = binary_repr(refined_baseline)
        else:
            assert isinstance(refined_actual, str)
            assert isinstance(refined_baseline, str)
            decoded_actual = refined_actual
            decoded_baseline = refined_baseline

        # Get the two texts to compare as list of lines, with trailing
        # characters preserved (splitlines(keepends=True)).
        expected_lines = decoded_baseline.splitlines(True)
        actual_lines = decoded_actual.splitlines(True)

        # Compute the diff. If it is empty, return no failure. Otherwise,
        # include the diff in the test log and return the given failure
        # message.
        d = diff(
            expected_lines,
            actual_lines,
            ignore_white_chars=ignore_white_chars,
            context=context_size,
        )
        if not d:
            return []

        self.failing_diff_count += 1
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

        # If requested, rewrite the test baseline with the actual output
        if self.rewrite_baseline:
            assert baseline_file is not None
            if isinstance(refined_actual, str):
                with open(
                    baseline_file, "w", encoding=self.default_encoding
                ) as f:
                    f.write(refined_actual)
            else:
                assert isinstance(refined_actual, bytes)
                with open(baseline_file, "wb") as f:
                    f.write(refined_actual)
            message = "{} (baseline updated)".format(message)

        # Send the appropriate logging. Make sure ".log" has all the
        # information. If there are multiple diff failures for this testcase,
        # do not emit the "expected/out" logs, as they support only one diff.
        diff_log = (
            self.Style.RESET_ALL
            + self.Style.BRIGHT
            + "Diff failure: {}\n".format(message)
            + "\n".join(diff_lines)
            + "\n"
        )
        self.result.log += "\n" + truncated(diff_log, truncate_logs_threshold)
        if self.failing_diff_count == 1:
            self.result.expected = Log(decoded_baseline)
            self.result.out = Log(decoded_actual)
            self.result.diff = Log(diff_log)
        else:
            self.result.expected = None
            self.result.out = None
            assert isinstance(self.result.diff, Log) and isinstance(
                self.result.diff.log, str
            )
            self.result.diff += "\n" + diff_log

        return [message]

    def compute_regexp_match(
        self,
        regexp: Union[Pattern[AnyStr], AnyStr],
        actual: AnyStr,
        failure_message: str = "output does not match expected pattern",
        truncate_logs_threshold: Optional[int] = None,
    ) -> List[str]:
        """Compute whether the actual output matches a regexp.

        Return an empty list if the acutal content matches, and return a list
        that contains an error message based on ``failure_message`` otherwise.

        :param regexp: Regular expression to use.
        :param actual: Actual content to match.
        :param failure_message: Failure message to return if there is a
            difference.
        :param truncate_logs_threshold: Threshold to truncate the diff message
            in ``self.result.log``. See ``e3.testsuite.result.truncated``'s
            ``line_count`` argument. If left to None, use the testsuite's
            ``--truncate-logs`` option.
        """
        if isinstance(regexp, (str, bytes)):
            regexp = re.compile(regexp)

        if truncate_logs_threshold is None:
            truncate_logs_threshold = self.testsuite_options.truncate_logs

        # Run output refiners. Code is more complex than it should be to
        # satisfy Mypy's constraints.
        refiners = (
            RefiningChain[str](self.output_refiners)
            if isinstance(actual, str)
            else RefiningChain[bytes](self.output_refiners)
        )
        refined_actual = refiners.refine(actual)

        match = regexp.fullmatch(refined_actual)
        if match:
            return []

        def quote(content: AnyStr) -> str:
            decoded_content: str
            if self.default_encoding == "binary":
                assert isinstance(content, bytes)
                decoded_content = binary_repr(content)
            else:
                assert isinstance(content, str)
                decoded_content = content
            return indent(decoded_content)

        # Send the appropriate logging
        self.result.log += failure_message + ":\n"
        self.result.log += truncated(
            quote(refined_actual), truncate_logs_threshold
        )
        self.result.log += "\nDoes not match the expected pattern:\n"
        self.result.log += truncated(
            quote(regexp.pattern), truncate_logs_threshold
        )

        return [failure_message]

    def compute_failures(self) -> List[str]:
        """Return a failure if ``self.output.log`` does not match the baseline.

        This computes a diff with the content of the baseline file, unless
        there is a "baseline_regexp" entry in the test environment that
        evaluates to true.

        Subclasses can override this if they need more involved analysis:
        for instance computing multiple diffs.
        """
        # Get the baseline, then check that the actual output matches
        filename, baseline, is_regexp = self.baseline
        if is_regexp:
            result = self.compute_regexp_match(baseline, self.output.log)
        else:
            # Run output refiners. Code is more complex than it should be to
            # satisfy Mypy's constraints.
            if isinstance(baseline, str):
                assert isinstance(self.output.log, str)
                result = self.compute_diff(filename, baseline, self.output.log)
            else:
                assert isinstance(baseline, bytes)
                assert isinstance(self.output.log, bytes)
                result = self.compute_diff(filename, baseline, self.output.log)

        # Adjust the result if there is a mismatch
        if result:
            self.result.failure_reasons.add(FailureReason.DIFF)

        return result
