"""Data structures for testcase execution results."""

import binascii
from enum import Enum, auto
import logging

import yaml


class TestStatus(Enum):
    """Testcase execution status."""

    # The test has run to completion and has succeeded
    PASS = auto()

    # The test has run enough for the testsuite to consider that it failed
    FAIL = auto()

    # The test has run enough for the testsuite to consider that it failed, and
    # that this failure was expected.
    XFAIL = auto()

    # The test has run to completion and has succeeded whereas a failure was
    # expected.
    XPASS = auto()

    # The test has run to completion, but it could not self-verify the test
    # objective (i.e. determine whether it succeeded). This test requires an
    # additional verification action by a human or some external oracle.
    VERIFY = auto()

    # The test was not executed (it has been skipped). This is appropriate when
    # the test does not make sense in the current configuration (for instance
    # it must run on Windows, and the current OS is GNU/Linux).
    #
    # This is equivalent to DejaGnu's UNSUPPORTED, or UNTESTED test outputs.
    SKIP = auto()

    # The test has run and managed to automatically determine it can't work on
    # a given configuration (for instance, a test scenario requires two
    # distinct interrupt priorities, but only one is supported on the current
    # target).
    #
    # The different with SKIP is that here, the test has started when it
    # determined that it would not work. The definition of when a test actually
    # starts is left to the test driver.
    NOT_APPLICABLE = auto()

    # The test could not run to completion because it is misformatted or due to
    # an unknown error. This is very different from FAIL, because here the
    # problem comes more likely from the testcase or the test framework rather
    # than the tested software.
    #
    # This is equivalent to DejaGnu's UNRESOLVED test output.
    ERROR = auto()

    def color(self, testsuite):
        """Return the ANSI color code for this test status.

        This returns an empty string if colors are disabled.

        :param testsuite: TestsuiteCore instance.
        :rtype: str
        """
        Fore = testsuite.Fore
        Style = testsuite.Style
        return {
            'PASS': Fore.GREEN,
            'FAIL': Fore.RED,
            'XFAIL': Fore.CYAN,
            'XPASS': Fore.YELLOW,
            'VERIFY': Fore.YELLOW,
            'SKIP': Style.DIM,
            'NOT_APPLICABLE': Style.DIM,
            'ERROR': Fore.RED + Style.BRIGHT,
        }[self.name]


class FailureReason(Enum):
    """Reason for a test failure."""

    # A process crash was detected. What is a "crash" is not clearly specified:
    # it could be for instance that a "GCC internal compiler error" message is
    # present in the test output.
    CRASH = auto()

    # A process was stopped because it timed out
    TIMEOUT = auto()

    # The tested software triggered an invalid memory access pattern. For
    # instance, Valgrind found a conditional jump that depends on uninitialized
    # data.
    MEMCHECK = auto()

    # Output is not as expected
    DIFF = auto()


class Log(yaml.YAMLObject):
    """Object to hold long text or binary logs.

    We ensure that when dump to yaml the result will be human readable.
    """

    yaml_loader = yaml.SafeLoader
    yaml_tag = '!e3.testsuite.result.Log'

    def __init__(self, content):
        """Initialize log instance.

        :param content: an initial message to log
        :type content: str
        """
        self.log = content

    @property
    def is_binary(self):
        """Return whether this log contains binary data.

        :rtype: bool
        """
        return isinstance(self.log, bytes)

    @property
    def is_text(self):
        """Return whether this log contains text data.

        :rtype: bool
        """
        return not self.is_binary

    def __iadd__(self, content):
        """Add additional content to the log.

        :param content: a message to log
        :type content: str
        """
        self.log += content
        return self

    def __str__(self):
        return self.log if self.is_text else binary_repr(self.log)


def binary_repr(binary):
    r"""Return a human readable representation for the given bytes string.

    This just decodes ASCII printable bytes and newlines to the corresponding
    strings and represents other bytes with the "\xXX" escapes.

    :param bytes binary: Bytes string to represent.
    :rtype: str
    """

    def escape(b):
        if b == ord("\\"):
            return "\\\\"
        elif b == ord("\n") or (b >= ord(" ") and b <= ord("~")):
            return chr(b)
        else:
            return "\\x{:>02x}".format(b)

    return "\n".join(
        "".join(escape(b) for b in line)
        for line in binary.split(b"\n")
    )


class TestResult(yaml.YAMLObject):
    """Represent a result for a given test."""

    yaml_loader = yaml.SafeLoader
    yaml_tag = '!e3.testsuite.result.TestResult'

    def __init__(self, name, env=None, status=None, msg=""):
        """Initialize a test result.

        :param str name: Name of the test that this result describes.
        :param dict env: Test environment. Usually a dict that contains
            relevant test information (output, ...). The object should be
            serializable to YAML format.
        :param TestStatus|None status: Test status. If None status is set to
            ERROR.
        :param str msg: Short message associated with the test result.
        """
        self.test_name = name
        self.env = env

        # Use the set_status method to change these once initialization is done
        self.status = TestStatus.ERROR if status is None else status
        self.msg = msg

        # Free-form text, for debugging purposes. Test drivers are invited to
        # write content that will be useful if things go wrong during the test
        # execution. This is what gets printed on the standard output when the
        # test fails and the "--show-error-output" testsuite switch is present.
        self.log = Log("")

        # List of free-form information (but still serializable to YAML)
        # describing the subprocesses that the test driver spawned while runnig
        # the testcase.
        #
        # Note that both e3.testsuite.process.check_call and
        # e3.testsuite.driver.classic.ClassicTestDriver.shell fill this
        # automatically with command-line arguments, exit code, etc.
        self.processes = []

        # When the test failed, optional set of reasons for the failure. This
        # information is used only in advanced viewers, which may highlight
        # specifically some failure reasons. For instance, highlight crashes,
        # that may be more important to investigate than mere unexpected
        # outputs.
        self.failure_reasons = set()

        # Drivers that compare expected and actual output to validate a
        # testcase should initialize these with Log instances to hold the
        # expected test output (self.expected) and the actual test output
        # (self.out). It is assumed that the test fails when there is at least
        # one difference between both.
        #
        # Note that several drivers refine expected/actual outputs before
        # running the comparison (see for instance the
        # e3.testsuite.driver.diff.OutputRefiner mechanism). These logs are
        # supposed to contain the outputs actually passed to the diff
        # computation function, i.e. *after* refining, so that whatever attemps
        # to re-compute the diff (report production, for instance) get the same
        # result.
        #
        # If, for some reason, it is not possible to store expected and actual
        # outputs, self.diff can be assigned a Log instance holding the diff
        # itself. For instance, the output of the `diff -u` command.
        self.expected = None
        self.out = None
        self.diff = None

        # Optional decimal number of seconds (float). Test drivers can use this
        # field to track performance, most likely the time it took to run the
        # test. Advanced results viewer can then plot the evolution of time
        # over software evolution.
        self.time = None

        # Key/value string mapping, for unspecified use. The only restriction
        # is that no string can contain a newline character.
        self.info = {}

    def set_status(self, status, msg=""):
        """Update the test status.

        :param TestStatus status: New status. Note that only test results with
            status set to ERROR can be changed.
        :param None|str msg: Optional short message to describe the result.
            Note that multiline strings are turned into single-line strings.
        """
        if self.status != TestStatus.ERROR:
            logging.error("cannot set test %s status twice", self.test_name)
            return
        self.status = status

        self.msg = (
            " ".join(line.strip() for line in msg.splitlines() if line)
            if msg
            else None
        )

    def __str__(self):
        return "%-24s %-12s %s" % (self.test_name, self.status, self.msg)


# Enforce representation of Log objects when dumped to yaml
def _log_representer(dumper, data):
    return (
        dumper.represent_scalar("tag:yaml.org,2002:str", data.log, style="|")
        if data.is_text else
        dumper.represent_scalar(
            "tag:yaml.org,2002:binary",
            binascii.b2a_base64(data.log).decode('ascii'), style="|")
    )


yaml.add_representer(Log, _log_representer)


_test_status_tag = "!e3.testsuite.result.TestStatus"
_failure_reason_tag = "!e3.testsuite.result.FailureReason"


# We cannot use yaml.YAMLObject metaclass magic for TestStatus as it derives
# from Enum, which already has a metaclass. So use an alternative YAML API to
# make it serializable. Likewise for FailureReason.
def _test_status_constructor(self, node):
    # Get the numeric value corresponding to the test status, then build a
    # TestStatus instance from it.
    num = int(node.value[0])
    status = TestStatus(num)
    yield status


def _test_status_representer(dumper, data):
    return dumper.represent_scalar(
        _test_status_tag, str(data.value), style="|"
    )


def _failure_reason_constructor(self, node):
    # Get the numeric value corresponding to the test status, then build a
    # TestStatus instance from it.
    num = int(node.value[0])
    status = FailureReason(num)
    yield status


def _failure_reason_representer(dumper, data):
    return dumper.represent_scalar(
        _failure_reason_tag, str(data.value), style="|"
    )


yaml.SafeLoader.add_constructor(_test_status_tag, _test_status_constructor)
yaml.add_representer(TestStatus, _test_status_representer)
yaml.SafeLoader.add_constructor(
    _failure_reason_tag, _failure_reason_constructor
)
yaml.add_representer(FailureReason, _failure_reason_representer)
