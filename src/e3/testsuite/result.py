"""Data structures for testcase execution results."""

import binascii
from enum import Enum
import logging
import sys

import yaml


class TestStatus(Enum):
    """Testcase execution status."""

    PASS = 0
    FAIL = 1
    UNSUPPORTED = 2
    XFAIL = 3
    XPASS = 4
    ERROR = 5
    UNRESOLVED = 6
    UNTESTED = 7

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
            'UNSUPPORTED': Style.DIM,
            'XFAIL': Fore.CYAN,
            'XPASS': Fore.YELLOW,
            'ERROR': Fore.RED + Style.BRIGHT,
            'UNRESOLVED': Style.DIM,
            'UNTESTED': Style.DIM,
        }[self.name]


class Log(yaml.YAMLObject):
    """Object to hold long text or binary logs.

    We ensure that when dump to yaml the result will be human readable.
    """

    yaml_loader = yaml.SafeLoader
    yaml_tag = '!e3.testsuite.result.Log'

    @classmethod
    def create_empty_text(cls):
        """Create a Log instance that holds text.

        Text is str in Python3, unicode in Python2.

        :rtype: Log
        """
        # Create a Python2 unicode object or a Python3 str object. Disable the
        # flake8 diagnostic: yes, unicode() is undefined with Python3.
        if sys.version_info.major == 2:  # py2-only
            return Log(unicode())  # noqa: F821
        else:
            return Log("")

    @classmethod
    def create_empty_binary(cls):
        """Create a Log instance that holds binary data.

        Binary data is bytes in Python3, str in Python2.

        :rtype: Log
        """
        # Create a Python2 str object or a Python3 bytes object
        return Log(b"")

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
        binary_type = (str if sys.version_info.major == 2 else bytes)
        return isinstance(self.log, binary_type)

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
        if sys.version_info.major == 2:  # py2-only
            b = ord(b)
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


class TestResult(yaml.YAMLObject):
    """Represent a result for a given test."""

    yaml_loader = yaml.SafeLoader
    yaml_tag = '!e3.testsuite.result.TestResult'

    def __init__(self, name, env=None, status=None, msg=""):
        """Initialize a test result.

        :param name: the test name
        :type name: str
        :param env: the test environment. Usually a dict that contains
            relevant test information (output, ...). The object should
            be serializable to YAML format.
        :type env: T
        :param status: the test status. If None status is set to UNRESOLVED
        :type status: TestStatus | None
        :param msg: a short message associated with the test result
        :type msg: str
        """
        self.test_name = name
        self.env = env
        if status is None:
            self.status = TestStatus.UNRESOLVED
        else:
            self.status = status
        self.msg = msg
        self.out = Log("")
        self.log = Log("")
        self.processes = []

    def set_status(self, status, msg=""):
        """Update the test status.

        :param status: new status. Note that only test results with status
            set to UNRESOLVED can be changed.
        :type status: TestStatus
        :param msg: short message associated with the test result
        :type msg: str
        """
        if self.status != TestStatus.UNRESOLVED:
            logging.error("cannot set test %s status twice", self.test_name)
            return
        self.status = status
        self.msg = msg

    def __str__(self):
        return "%-24s %-12s %s" % (self.test_name, self.status, self.msg)


# We cannot use yaml.YAMLObject metaclass magic for TestStatus as it derives
# from Enum, which already has a metaclass. So use an alternative YAML API to
# make it serializable.
def test_status_constructor(self, node):
    # Get the numeric value corresponding to the test status, then build a
    # TestStatus instance from it.
    num = int(node.value[0].value)
    status = TestStatus(num)
    yield status


yaml.SafeLoader.add_constructor(None, test_status_constructor)
