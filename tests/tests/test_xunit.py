"""Tests for the XUnit report feature."""

import xml.etree.ElementTree as ET

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import TestDriver as Driver
from e3.testsuite.result import TestStatus as Status

from .utils import create_testsuite, run_testsuite


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
        run_testsuite(
            Mysuite, ["--xunit-output", xunit_file], expect_failure=True
        )

        # For now, just check that this produces a valid XML file
        ET.parse(xunit_file)


class TestXFail:
    """Check that XFAIL tests are reported as skipped."""

    class MyDriver(Driver):
        def add_test(self, dag):
            self.add_fragment(dag, "run")

        def run(self, prev, slot):
            self.result.set_status(Status.XFAIL)
            self.push_result()

    def test(self, tmp_path):
        xunit_file = str(tmp_path / "xunit.xml")
        run_testsuite(
            create_testsuite(["mytest"], self.MyDriver),
            ["--xunit-output", xunit_file],
        )

        ts = ET.parse(xunit_file).getroot()
        assert ts.attrib["errors"] == "0"
        assert ts.attrib["failures"] == "0"
        assert ts.attrib["skipped"] == "1"
        assert ts.attrib["tests"] == "1"


class TestTime:
    """Check that testsuite and testcase durations are properly reported."""

    class MyDriver(Driver):
        def add_test(self, dag):
            self.add_fragment(dag, "run")

        def run(self, prev, slot):
            self.result.time = 1.2345
            self.result.set_status(Status.PASS)
            self.push_result()

    def test(self, tmp_path):
        xunit_file = str(tmp_path / "xunit.xml")
        run_testsuite(
            create_testsuite(["mytest"], self.MyDriver),
            ["--xunit-output", xunit_file],
        )

        testsuites = ET.parse(xunit_file).getroot()
        testsuite = testsuites[0]
        testcase = testsuite[0]

        # Sanity checks
        assert testsuites.tag == "testsuites"
        assert testsuite.tag == "testsuite"
        assert testcase.tag == "testcase"
        assert testcase.get("name") == "mytest"

        # Check that we have time attributes for both the <testsuites> and
        # <testsuite> tags. Since we do not control the time it takes to
        # actually run it, we can just check for the presence of these
        # attributes, not their actual values.
        assert isinstance(testsuites.get("time"), str)
        assert testsuites.get("time") == testsuite.get("time")

        # We do control the value for the testcase
        assert testcase.get("time") == "1.234"
