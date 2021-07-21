"""Tests for the XUnit report feature."""

import xml.etree.ElementTree as ET

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import TestDriver as Driver
from e3.testsuite.result import TestStatus as Status

from .utils import run_testsuite


class TestBasic:
    """Check that requesting a XUnit testsuite report works."""

    class MyDriver(Driver):
        def add_test(self, dag):
            self.add_fragment(dag, "run")

        def run(self, prev, slot):
            self.result.log += "Work is being done..."

            if self.test_env["test_name"] == "test1":
                self.result.set_status(Status.PASS, "all good")
            else:
                self.result.set_status(Status.FAIL, "test always fail!")
            self.push_result()

    def test(self):
        class Mysuite(Suite):
            tests_subdir = "simple-tests"
            test_driver_map = {"default": self.MyDriver}
            default_driver = "default"

        xunit_file = "xunit.xml"
        run_testsuite(Mysuite, ["--xunit-output", xunit_file])

        # For now, just check that this produces a valid XML file
        ET.parse(xunit_file)
