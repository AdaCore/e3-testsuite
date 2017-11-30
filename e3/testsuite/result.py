from __future__ import absolute_import, division, print_function

import logging
from enum import Enum


class TestStatus(Enum):
    PASS = 0
    FAIL = 1
    UNSUPPORTED = 2
    XFAIL = 3
    XPASS = 4
    ERROR = 5
    UNRESOLVED = 6
    UNTESTED = 7


class TestResult(object):
    """Represent a result for a given test."""

    def __init__(self, name, env=None, status=None, msg=''):
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

    def set_status(self, status, msg=''):
        """Update the test status.

        :param status: new status. Note that only test results with status
            set to UNRESOLVED can be changed.
        :type status: TestStatus
        :param msg: short message associated with the test result
        :type msg: str
        """
        if self.status != TestStatus.UNRESOLVED:
            logging.error('cannot set test %s status twice', self.test_name)
            return
        self.status = status
        self.msg = msg

    def __str__(self):
        return '%-24s %-12s %s' % (self.test_name, self.status, self.msg)
