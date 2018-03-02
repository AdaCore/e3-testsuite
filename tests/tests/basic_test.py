from __future__ import absolute_import, division, print_function

import logging
import os

from e3.testsuite import TestAbort as E3TestAbort
from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.result import TestStatus as Status


def test_basic():
    """Basic driver with all tests passing."""
    class MyDriver(BasicDriver):
        def run(self, prev):
            pass

        def analyze(self, prev):
            self.result.set_status(Status.PASS, 'ok!')
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = 'sub'
        DRIVERS = {'default': MyDriver}

        @property
        def default_driver(self):
            return 'default'

    suite = Mysuite(os.path.dirname(__file__))
    status = suite.testsuite_main([])
    assert status == 0, 'testsuite failed'
    assert len(suite.results) == 2
    for v in suite.results.values():
        assert v == Status.PASS


def test_abort():
    """Check for if TestAbort work."""
    class MyDriver(BasicDriver):
        def run(self, prev):
            raise E3TestAbort
            return 'INVALID'

        def analyze(self, prev):
            if prev['run'] is None:
                self.result.set_status(Status.PASS, 'ok!')
            else:
                self.result.set_status(Status.FAIL, 'unexpected return value')

            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = 'sub'
        DRIVERS = {'default': MyDriver}

        @property
        def default_driver(self):
            return 'default'

    suite = Mysuite(os.path.dirname(__file__))
    status = suite.testsuite_main([])
    assert status == 0, 'testsuite failed'
    assert len(suite.results) == 2
    for v in suite.results.values():
        assert v == Status.PASS


def test_exception_in_driver():
    """Check handling of exception in test driver."""
    class MyDriver(BasicDriver):
        def run(self, prev):
            raise AttributeError('expected exception')

        def analyze(self, prev):
            prev_value = prev['run']
            logging.debug(prev_value)
            if isinstance(prev_value, Exception):
                self.result.set_status(Status.PASS, 'ok!')
            else:
                self.result.set_status(Status.FAIL, 'unexpected return value')
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = 'sub'
        DRIVERS = {'default': MyDriver}

        @property
        def default_driver(self):
            return 'default'

    suite = Mysuite(os.path.dirname(__file__))
    status = suite.testsuite_main([])
    assert status == 0, 'testsuite failed'
    assert suite.test_counter == 4
    assert suite.test_status_counters[Status.PASS] == 2
    assert suite.test_status_counters[Status.ERROR] == 2
