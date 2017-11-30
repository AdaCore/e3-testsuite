from __future__ import absolute_import, division, print_function

import os

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.result import TestStatus as Status


def test_basic():

    class MyDriver(BasicDriver):
        def run(self):
            pass

        def analyze(self):
            self.result.set_status(Status.PASS, 'ok!')
            self.push_result()

    class Mysuite(Suite):
        CROSS_SUPPORT = True
        TEST_SUBDIR = 'sub'
        DRIVERS = {'default': MyDriver}

        @property
        def default_driver(self):
            return 'default'

    status = Mysuite(os.path.dirname(__file__)).testsuite_main([])
    assert status == 0, 'testsuite failed'
