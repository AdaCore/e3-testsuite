"""Tests for the XUnit report feature."""

import xml.etree.ElementTree as ET

import yaml

from e3.fs import mkdir
from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import TestDriver as Driver
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.report.xunit import convert_main
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


class TestControlChars:
    """Check XUnit reports with control characters.

    Check that XUnit reports are valid when control chars are present in test
    outputs.
    """

    class MyDriver(Driver):
        def add_test(self, dag):
            self.add_fragment(dag, "run")

        def run(self, prev, slot):
            self.result.log += "Control character: \x01\nDone.\n"
            self.result.set_status(Status.FAIL, "Another control char: \x02")
            self.push_result()

    def test(self, tmp_path):
        xunit_file = str(tmp_path / "xunit.xml")
        run_testsuite(
            create_testsuite(["mytest"], self.MyDriver),
            ["--xunit-output", xunit_file],
            expect_failure=True,
        )
        testsuites = ET.parse(xunit_file).getroot()
        testsuite = testsuites[0]
        testcase = testsuite[0]
        failure = testcase[0]

        # Sanity checks
        assert testsuites.tag == "testsuites"
        assert testsuite.tag == "testsuite"
        assert testcase.tag == "testcase"
        assert testcase.get("name") == "mytest"
        assert failure.tag == "failure"

        assert failure.get("message") == "Another control char: \\x02"
        assert failure.text == "Control character: \\x01\nDone.\n"


def test_import(tmp_path):
    """Test that the xUnit importer works as expected."""
    xml_filename = str(tmp_path / "tmp.xml")
    with open(xml_filename, "w") as f:
        f.write(
            """<?xml version="1.0" encoding="utf-8"?>
            <testsuites name="MyTestsuites">
                <testsuite name="Normal">

                    <!-- Elements discarded during the import. -->
                    <properties>
                        <property name="to-ignore"></property>
                    </properties>
                    <system-out>
                        To ignore
                    </system-out>
                    <system-err>
                        To ignore
                    </system-err>

                    <!-- Test import of the time attribute. -->
                    <testcase name="test1" time="0.1"></testcase>

                    <!-- Test slugification. -->
                    <testcase name="Test2-\xe9"></testcase>
                    <testcase name="Test2-#$^"></testcase>

                    <!-- Test de-duplication of test names. -->
                    <testcase name="Test2-e"></testcase>
                    <testcase name="Test2-e"></testcase>

                    <!-- Test the various test statuses. -->
                    <testcase name="test-failure">
                        <failure>Some failure logging</failure>
                    </testcase>

                    <testcase name="test-error">
                        <error>Some error logging</error>
                    </testcase>

                    <testcase name="test-skipped">
                        <skipped>Some skip logging</skipped>
                    </testcase>

                    <!-- Test the import of status message. -->
                    <testcase name="test-failure-message">
                        <failure message="Some failure message">\
Some failure logging</failure>
                    </testcase>

                </testsuite>

                <!-- Test usage of XFAILs. -->
                <testsuite name="XFails">
                    <testcase name="test-ok"></testcase>
                    <testcase name="test-failure">
                        <failure>Some failure logging</failure>
                    </testcase>
                    <testcase name="test-failure-message">
                        <failure message="Some failure message">\
Some failure logging</failure>
                    </testcase>
                    <testcase name="test-error">
                        <error>Some error logging</error>
                    </testcase>
                    <testcase name="test-skipped">
                        <skipped>Some skip logging</skipped>
                    </testcase>
                    <testcase name="pytest-skip">
                        <skipped type="pytest.skip">Some skip logging</skipped>
                    </testcase>
                    <testcase name="pytest-xfail">
                        <skipped
                          type="pytest.xfail"
                          message="Known bug">Some error logging</skipped>
                    </testcase>
                </testsuite>
            </testsuites>"""
        )

    xfails_filename = str(tmp_path / "xfails.yaml")
    xfails = {
        "XFails.test-ok": "",
        "XFails.test-failure": "",
        "XFails.test-error": "",
        "XFails.test-skipped": "",
        "XFails.test-failure-message": "Expected failure message",
    }
    with open(xfails_filename, "w") as f:
        yaml.dump(xfails, f)

    results_dir = str(tmp_path / "results")
    convert_main(
        ["-o", results_dir, "--xfails", xfails_filename, xml_filename]
    )
    index = ReportIndex.read(results_dir)

    assert sorted(index.entries) == [
        "Normal.Test2",
        "Normal.Test2-e",
        "Normal.Test2-e.1",
        "Normal.Test2-e.2",
        "Normal.test-error",
        "Normal.test-failure",
        "Normal.test-failure-message",
        "Normal.test-skipped",
        "Normal.test1",
        "XFails.pytest-skip",
        "XFails.pytest-xfail",
        "XFails.test-error",
        "XFails.test-failure",
        "XFails.test-failure-message",
        "XFails.test-ok",
        "XFails.test-skipped",
    ]

    def check(test_name, status, message=None, time=None):
        e = index.entries[test_name]
        assert e.status == status
        assert e.msg == message
        if time is None:
            assert e.time is None
        else:
            assert str(e.time) == time

    def check_log(test_name, log):
        assert index.entries[test_name].load().log == log

    check("Normal.test1", Status.PASS, time="0.1")
    check("Normal.Test2", Status.PASS)
    check("Normal.Test2-e", Status.PASS)
    check("Normal.Test2-e.1", Status.PASS)
    check("Normal.Test2-e.2", Status.PASS)

    check("Normal.test-failure", Status.FAIL)
    check_log("Normal.test-failure", "Some failure logging")

    check("Normal.test-error", Status.ERROR)
    check_log("Normal.test-error", "Some error logging")

    check("Normal.test-skipped", Status.SKIP)
    check_log("Normal.test-skipped", "Some skip logging")

    check("Normal.test-failure-message", Status.FAIL, "Some failure message")
    check_log("Normal.test-failure-message", "Some failure logging")

    check("XFails.test-ok", Status.XPASS)

    check("XFails.test-failure", Status.XFAIL)
    check_log("XFails.test-failure", "Some failure logging")

    check("XFails.test-error", Status.XFAIL)
    check_log("XFails.test-error", "Some error logging")

    check("XFails.test-skipped", Status.SKIP)
    check_log("XFails.test-skipped", "Some skip logging")

    check(
        "XFails.test-failure-message",
        Status.XFAIL,
        "Some failure message (Expected failure message)",
    )
    check_log("XFails.test-failure-message", "Some failure logging")

    check("XFails.pytest-skip", Status.SKIP)
    check_log("XFails.pytest-skip", "Some skip logging")

    check("XFails.pytest-xfail", Status.XFAIL, "Known bug")
    check_log("XFails.pytest-xfail", "Some error logging")


def test_import_dirs(tmp_path):
    """Test XML reports search in the xUnit conversion script."""

    def write_xml(filename, testsuite_name, *test_names):
        mkdir(str(filename.parent))
        with open(str(filename), "w") as f:
            f.write(
                '<?xml version="1.0" encoding="utf-8"?>'
                '\n<testsuites name="MyTestsuites">'
                f'\n<testsuite name="{testsuite_name}">'
            )
            for n in test_names:
                f.write(f'\n<testcase name="{n}"></testcase>')
            f.write("\n</testsuite>\n</testsuites>")

    write_xml(tmp_path / "xml" / "f1.xml", "f1", "t1", "t2")
    write_xml(tmp_path / "xml" / "sdir" / "f2.xml", "f2", "t1")
    write_xml(tmp_path / "xml" / "sdir" / "ssdir" / "f3.xml", "f3", "t1")
    write_xml(tmp_path / "xml" / "odir" / "f4.xml", "f4", "t1")

    results_dir = str(tmp_path / "results")
    convert_main(
        [
            "-o",
            results_dir,
            str(tmp_path / "xml" / "f1.xml"),
            str(tmp_path / "xml" / "sdir"),
        ]
    )
    index = ReportIndex.read(results_dir)

    assert sorted(index.entries) == ["f1.t1", "f1.t2", "f2.t1", "f3.t1"]
