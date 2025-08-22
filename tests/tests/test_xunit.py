"""Tests for the XUnit report feature."""

import os.path
import xml.etree.ElementTree as ET

import yaml

from e3.fs import mkdir
from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import TestDriver as Driver
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.report.xunit import (
    XUnitImporter,
    XUnitImporterApp,
    convert_main,
)
from e3.testsuite.result import TestStatus as Status

from .utils import create_testsuite, run_testsuite


def write_xfails_yaml(filename, xfails):
    """Write a XFAILs YAML file."""
    with open(filename, "w") as f:
        yaml.dump(xfails, f)


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


def test_import(tmp_path, capsys):
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

                    <!-- Test handling of classname. -->
                    <testcase name="test_name" classname="MyClass">
                    </testcase>

                    <!-- Test handling of multiline messages. -->
                    <testcase name="test-failure-multiline-message">
                        <failure message="Some multi&#10;
line&#10;
message...">\
Some failure logging</failure>
                    </testcase>

                    <!-- Test handling of too long messages. -->
                    <testcase name="test-failure-too-long-message">
                        <failure message="Some extremely very ultra long
message. Viewers may not like it, so we are going to strip it to ~200 colons.
The imported report will include only a small prefix of this too long message.
They will not see the complete message. This is okay, as in known cases where
messages are too long, their content is actually also present in the log, which
is not capped, so no content is lost in practice.
">Some failure logging</failure>
                    </testcase>

                    <!-- Test handling of too long multi-line messages. -->
                    <testcase name="test-failure-too-long-multiline-message">
                        <failure message="
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&#10;
BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB&#10;
CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC&#10;
DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD&#10;
">Some failure logging</failure>
                    </testcase>

                    <!-- Test handling of the system-out and system-err
                         elements. -->
                    <testcase name="test-system-elts">
                        <system-out><![CDATA[
Some content for system-out.
]]></system-out>
                        <system-err><![CDATA[
Some content for system-err.
]]></system-err>
                    </testcase>

                    <!-- Test handling of invalid status tags. -->
                    <testcase name="test-invalid-status-tags">
                        <unknown/>
                        <failure message="failure message">Failure log.
</failure>
                        <skipped message="skip message">Skip log.
</skipped>
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
    write_xfails_yaml(
        xfails_filename,
        {
            "XFails.test-ok": "",
            "XFails.test-failure": "",
            "XFails.test-error": "",
            "XFails.test-skipped": "",
            "XFails.test-failure-message": "Expected failure message",
        },
    )

    results_dir = str(tmp_path / "results")
    convert_main(
        ["-o", results_dir, "--xfails", xfails_filename, xml_filename]
    )
    index = ReportIndex.read(results_dir)

    assert sorted(index.entries) == [
        "Normal.MyClass.test_name",
        "Normal.Test2",
        "Normal.Test2-e",
        "Normal.Test2-e.1",
        "Normal.Test2-e.2",
        "Normal.test-error",
        "Normal.test-failure",
        "Normal.test-failure-message",
        "Normal.test-failure-multiline-message",
        "Normal.test-failure-too-long-message",
        "Normal.test-failure-too-long-multiline-message",
        "Normal.test-invalid-status-tags",
        "Normal.test-skipped",
        "Normal.test-system-elts",
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

    check(
        "Normal.test-failure-multiline-message",
        Status.FAIL,
        message="Some multi [...]",
    )
    check_log(
        "Normal.test-failure-multiline-message",
        "Status message was too long:\n\n"
        "Some multi\n line\n message...\n\n"
        "Some failure logging",
    )

    check(
        "Normal.test-failure-too-long-message",
        Status.FAIL,
        message=(
            "Some extremely very ultra long message. Viewers may not like it,"
            " so we are going to strip it to ~200 colons. The imported report"
            " will include only a small prefix of this too long message. They"
            " will no [...]"
        ),
    )
    check_log(
        "Normal.test-failure-too-long-message",
        "Status message was too long:\n"
        "\n"
        "Some extremely very ultra long message. Viewers may not like it, so"
        " we are going to strip it to ~200 colons. The imported report will"
        " include only a small prefix of this too long message. They will not"
        " see the complete message. This is okay, as in known cases where"
        " messages are too long, their content is actually also present in the"
        " log, which is not capped, so no content is lost in practice. \n\n"
        "Some failure logging",
    )

    check(
        "Normal.test-failure-too-long-multiline-message",
        Status.FAIL,
        message="A" * 74 + " [...]",
    )
    check_log(
        "Normal.test-failure-too-long-multiline-message",
        "Status message was too long:\n"
        "\n"
        + " "
        + "A" * 74
        + "\n "
        + "B" * 74
        + "\n "
        + "C" * 74
        + "\n "
        + "D" * 74
        + "\n \n\nSome failure logging",
    )

    check("Normal.test-error", Status.ERROR)
    check_log("Normal.test-error", "Some error logging")

    check("Normal.test-skipped", Status.SKIP)
    check_log("Normal.test-skipped", "Some skip logging")

    check("Normal.test-failure-message", Status.FAIL, "Some failure message")
    check_log("Normal.test-failure-message", "Some failure logging")

    check("Normal.test-system-elts", Status.PASS)
    check_log(
        "Normal.test-system-elts",
        "\n\nsystem-out:\n\n"
        "Some content for system-out.\n"
        "\n\nsystem-err:\n\n"
        "Some content for system-err.\n",
    )

    check(
        "Normal.test-invalid-status-tags",
        Status.ERROR,
        "xUnit report decoding error",
    )
    check_log(
        "Normal.test-invalid-status-tags",
        "Failure log.\n"
        "\n"
        "\n"
        "Errors while decoding the xUnit report for this testcase:\n"
        "\n"
        "  * unexpected tag: unknown\n"
        "  * too many status elements\n"
        "\n"
        "So turning the following into an ERROR result:\n"
        "\n"
        "  SKIP: failure message\n",
    )

    check("Normal.MyClass.test_name", Status.PASS)

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

    captured = capsys.readouterr()
    assert captured.out == ""

    # Ensure that stderr is empty apart from the logs that are
    # activated by the e3 pytest plugin
    assert not [
        line for line in captured.err.splitlines() if "DEBUG" not in line
    ]


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


def test_gaia(tmp_path):
    """Test GAIA-compatible report creation."""
    xml_report = str(tmp_path / "test.xml")
    with open(xml_report, "w") as f:
        f.write(
            """<?xml version="1.0" encoding="utf-8"?>
            <testsuites name="MyTestsuites">
              <testsuite name="MyTestsuite">
                <testcase name="MyTestcase"></testcase>
              </testsuite>
            </testsuites>
            """
        )

    results_dir = tmp_path / "results"
    convert_main(["--gaia-output", "-o", str(results_dir), xml_report])

    with open(str(results_dir / "results"), "r") as f:
        assert f.read() == "MyTestsuite.MyTestcase:OK:\n"


def test_dangling_xfails(tmp_path, capsys):
    """Test emission of warnings for dangling XFAILs."""
    xml_report = str(tmp_path / "test.xml")
    with open(xml_report, "w") as f:
        f.write(
            """<?xml version="1.0" encoding="utf-8"?>
            <testsuites name="MyTestsuites">
              <testsuite name="MyTestsuite">
                <testcase name="MyTestcase"></testcase>
              </testsuite>
            </testsuites>
            """
        )

    xfails_filename = str(tmp_path / "xfails.yaml")
    write_xfails_yaml(xfails_filename, {"foo": "reason", "bar": ""})

    convert_main(
        [
            "-o",
            str(tmp_path / "results"),
            "--xfails",
            xfails_filename,
            xml_report,
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == (
        "warning: the following tests are expected to fail but are not present"
        " in the testsuite results:\n"
        "  bar\n"
        "  foo (reason)\n"
    )
    # Ensure that stderr is empty apart from the logs that are
    # activated by the e3 pytest plugin
    assert not [
        line for line in captured.err.splitlines() if "DEBUG" not in line
    ]


def test_app_override(tmp_path):
    """Test overriding in the XUnitImporterApp class."""
    xml_report = str(tmp_path / "test.xml")
    with open(xml_report, "w") as f:
        f.write(
            """<?xml version="1.0" encoding="utf-8"?>
            <testsuites name="TSList">
              <testsuite name="ts">
                <testcase name="tc1"></testcase>
                <testcase name="tc2">
                  <failure>Some logging</failure>
                </testcase>
              </testsuite>
            </testsuites>
            """
        )

    basic_results = {"ts.tc1": Status.PASS, "ts.tc2": Status.FAIL}

    def check_results(results_dir, expected):
        actual = {
            e.test_name: e.status
            for e in ReportIndex.read(results_dir).entries.values()
        }
        assert actual == expected

    # Check overriding the add_basic_options method/output_dir property.

    class CustomBasic(XUnitImporterApp):
        def add_basic_options(self, parser):
            parser.add_argument("e3-report-dir")

        @property
        def output_dir(self):
            return getattr(self.args, "e3-report-dir")

        def get_xfails(self):
            return {}

        def iter_xunit_files(self):
            yield xml_report

        @property
        def gaia_report_requested(self):
            return False

    CustomBasic().run(["custom-basic"])
    check_results("custom-basic", basic_results)

    # Check overriding the create_output_report_index method

    class CustomIndex(XUnitImporterApp):
        def create_output_report_index(self):
            mkdir("custom-index")
            return ReportIndex("custom-index")

    CustomIndex().run([xml_report])
    check_results("custom-index", basic_results)

    # Check overriding the add_options/get_xfails method

    class CustomXFails(XUnitImporterApp):
        def add_options(self, parser):
            parser.add_argument("--add-xfail", action="append")

        def get_xfails(self):
            result = {}
            for xfail in self.args.add_xfail:
                test_name, msg = xfail.split(":", 1)
                result[test_name] = msg
            return result

    CustomXFails().run(
        [xml_report, "-o", "custom-xfails", "--add-xfail=ts.tc2:foo"]
    )
    check_results(
        "custom-xfails", {"ts.tc1": Status.PASS, "ts.tc2": Status.XFAIL}
    )

    # Check overriding the create_importer method

    class MyXUnitImporter(XUnitImporter):
        def get_test_name(self, ts_name, tc_name, classname):
            return tc_name

    class CustomImporter(XUnitImporterApp):
        def create_importer(self):
            return MyXUnitImporter(self.index, self.xfails)

    CustomImporter().run([xml_report, "-o", "custom-importer"])
    check_results("custom-importer", {"tc1": Status.PASS, "tc2": Status.FAIL})

    # Check overriding the iter_xunit_files method

    class CustomIterXUnitFiles(XUnitImporterApp):
        def iter_xunit_files(self):
            yield xml_report

    CustomIterXUnitFiles().run(["-o", "custom-iter-xunit-files", "foo.xml"])
    check_results("custom-iter-xunit-files", basic_results)

    # Check overriding the gaia_report_requested property

    class CustomGAIA(XUnitImporterApp):
        @property
        def gaia_report_requested(self):
            return True

    CustomGAIA().run(["-o", "custom-gaia", xml_report])
    check_results("custom-gaia", basic_results)
    assert os.path.exists(os.path.join("custom-gaia", "results"))

    # Check overriding the tear_down method

    class CustomTearDown(XUnitImporterApp):
        def tear_down(self):
            with open(os.path.join(self.index.results_dir, "foo.txt"), "w"):
                pass

    CustomTearDown().run(["-o", "custom-tear-down", xml_report])
    check_results("custom-tear-down", basic_results)
    assert os.path.exists(os.path.join("custom-tear-down", "foo.txt"))
