"""Helpers to generate testsuite reports using the XUnit XML format."""

from __future__ import annotations

import argparse
import itertools
import os
import re
from typing import Iterable, Optional
import unicodedata
import xml.etree.ElementTree as etree

from e3.fs import mkdir
from e3.testsuite.report.gaia import dump_gaia_report
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import TestResult, TestStatus
import e3.yaml


def add_time_attribute(elt: etree.Element, duration: Optional[float]) -> None:
    """Optionally add a "time" attribute.

    If ``duration`` is a float, add the corresponding "time" attribute to
    ``elt``.
    """
    if duration is not None:
        elt.set("time", "{:0.3f}".format(duration))


def escape_text(text: str) -> str:
    """Escape non-printable characters from a string.

    XML documents cannot contain null or control characters (except newlines).
    """
    result = list(text)
    for i, c in enumerate(result):
        # Replace non-printable characters with their Python escape sequence,
        # but strip quotes.
        if c < " " and c != "\n":
            result[i] = ascii(c)[1:-1]
    return "".join(result)


def dump_xunit_report(name: str, index: ReportIndex, filename: str) -> None:
    """
    Dump a testsuite report to `filename` in the standard XUnit XML format.

    :param name: Name for the teststuite report.
    :param index: Report index for the testsuite results to report.
    :param filename: Name of the text file to write.
    :param duration: Optional number of seconds for the total duration of the
        testsuite run.
    """
    testsuites = etree.Element("testsuites", name=name)
    testsuite = etree.Element("testsuite", name=name)
    testsuites.append(testsuite)

    add_time_attribute(testsuites, index.duration)
    add_time_attribute(testsuite, index.duration)

    # Counters for each category of test in XUnit. We map TestStatus to
    # these.
    counters = {"tests": 0, "errors": 0, "failures": 0, "skipped": 0}
    status_to_counter = {
        TestStatus.PASS: None,
        TestStatus.FAIL: "failures",
        TestStatus.XFAIL: "skipped",
        TestStatus.XPASS: None,
        TestStatus.VERIFY: None,
        TestStatus.SKIP: "skipped",
        TestStatus.NOT_APPLICABLE: "skipped",
        TestStatus.ERROR: "errors",
    }

    # Markup to create inside <testcase> elements for each category of test
    # in XUnit.
    counter_to_markup = {
        "failures": "failure",
        "skipped": "skipped",
        "errors": "error",
    }

    # Now create a <testcase> element for each test
    for test_name, entry in sorted(index.entries.items()):
        result = entry.load()

        # We use the testsuite name for 'classname', as we don't really have
        # something more useful to display anyway.
        testcase = etree.Element("testcase", name=test_name, classname=name)
        testsuite.append(testcase)

        # Get the XUnit-equivalent status for this test and update the
        # corresponding counters.
        counter_key = status_to_counter[result.status]
        if counter_key:
            counters[counter_key] += 1
        counters["tests"] += 1

        # If applicable, create an element to describe the test status. In
        # any case, if we have logs, include them in the report to ease
        # post-mortem debugging. They are included in a standalone
        # "system-out" element in case the test succeeded, or directly in
        # the status element if the test failed.
        markup = counter_key and counter_to_markup.get(counter_key, None)
        if markup:
            status_elt = etree.Element(markup)
            testcase.append(status_elt)
            if counter_key in ("skipped", "errors", "failures") and result.msg:
                status_elt.set("message", escape_text(result.msg))

            if counter_key in ("errors", "failures"):
                status_elt.set("type", "error")

            assert isinstance(result.log, str)
            status_elt.text = escape_text(result.log)

        elif result.log:
            system_out = etree.Element("system-out")
            system_out.text = escape_text(str(result.log))
            testcase.append(system_out)

        add_time_attribute(testcase, result.time)

    # Include counters in <testsuite> and <testsuites> elements
    for key, count in sorted(counters.items()):
        testsuite.set(key, str(count))
        testsuites.set(key, str(count))

    # The report is ready: write it to the requested file
    tree = etree.ElementTree(testsuites)
    tree.write(filename, encoding="utf-8", xml_declaration=True)


class XUnitImporter:
    """Helper class to import results in a xUnit report into a report index."""

    def __init__(
        self,
        index: ReportIndex,
        xfails: dict[str, str] | None = None,
    ):
        """Create a XUnitImporter instance.

        :param index: Report index into which to import xUnit results.
        :param xfails: For each test result that is expected to fail, this dict
            must contain a "test name" to "expected failure message"
            (potentially an empty string) association.
        """
        self.index = index
        self.xfails = xfails or {}

        self.dangling_xfails: set[str] = set()
        """
        Set of tests for which a failure is expected, but that are not present
        in the testsuite report. Computed in the "run" method.
        """

    def warn_dangling_xfails(self) -> None:
        """
        Print warnings for dangling entries in the "xfails" dict.

        This prints warnings on the standard output to mention all tests for
        which a failure is expected, but that are not present in the testsuite
        report.
        """
        if not self.dangling_xfails:
            return
        print(
            "warning: the following tests are expected to fail but are not"
            " present in the testsuite results:"
        )
        for test_name in sorted(self.dangling_xfails):
            reason = self.xfails.get(test_name)
            if reason:
                print(f"  {test_name} ({reason})")
            else:
                print(f"  {test_name}")

    def run(self, filename: str) -> None:
        """Read a xUnit report and import its results in the report index.

        :param filename: Filename for the XML file that contains the xUnit
            report.
        """
        doc = etree.parse(filename)
        testsuites = doc.getroot()
        assert testsuites.tag == "testsuites"

        for testsuite in testsuites:
            assert testsuite.tag == "testsuite"
            testsuite_name = testsuite.attrib["name"]

            for testcase in testsuite:
                # Skip "properties", "system-out" and "system-err" elements so
                # that we process only "testcase" ones.
                if testcase.tag in {"properties", "system-out", "system-err"}:
                    continue
                assert testcase.tag == "testcase"

                testcase_name = testcase.attrib["name"]
                classname = testcase.attrib.get("classname")
                time_str = testcase.attrib.get("time")

                result = TestResult(
                    self.get_test_name(
                        testsuite_name, testcase_name, classname
                    )
                )
                result.time = float(time_str) if time_str else None
                status = TestStatus.PASS
                message: str | None = None
                decoding_errors: list[str] = []

                # Expect at most one "error", "failure" or "skipped" element.
                # Presence of one such element or the absence of elements
                # enables us to determine the test status. Also allow
                # "system-out" and "system-err" elements, for extra logging.
                status_found = False
                for elt in testcase:
                    if elt.tag == "error":
                        status = TestStatus.ERROR
                    elif elt.tag == "failure":
                        status = TestStatus.FAIL
                    elif elt.tag == "skipped":
                        # xUnit reports created by py.test may contain a "type"
                        # attribute that disambiguates between skip and xfail
                        # results.
                        kind = elt.attrib.get("type")
                        status = (
                            TestStatus.XFAIL
                            if kind == "pytest.xfail"
                            else TestStatus.SKIP
                        )
                    elif elt.tag in ("system-out", "system-err"):
                        if isinstance(elt.text, str):
                            result.log += f"\n\n{elt.tag}:\n"
                            result.log += elt.text
                        continue
                    else:
                        decoding_errors.append(f"unexpected tag: {elt.tag}")
                        continue

                    # Execution reaches this point only for elements that
                    # encode the test status.
                    if status_found:
                        decoding_errors.append("too many status elements")
                        continue
                    status_found = True
                    if isinstance(elt.text, str):
                        result.log += elt.text
                    message = elt.attrib.get("message")

                # Some XUnit producers are know to put full logs in the
                # "message" attribute, which produces unexpected results in
                # e3-testsuite report viewers. Keep the first line only,
                # and cap its length if needed.
                #
                # If we end up modifying it, put the unmodified version in the
                # logs, to avoid information loss.
                if message is not None:
                    original = message
                    if "\n" in message:
                        message = message.split("\n", 1)[0]
                    if len(message) > 200:
                        message = message[:200]
                    if message != original:
                        result.log.log = (
                            "Status message was too long:\n\n"
                            + original
                            + "\n\n"
                            + result.log.log
                        )
                        message = message.strip() + " [...]"

                # Now that the "unrefined" status for this result is known,
                # apply XFAIL, if needed.
                xfail_message = self.xfails.get(result.test_name)
                if xfail_message is not None:
                    # Depending on whether we have an XFAIL message and/or a
                    # test result message, create a single message for the
                    # result to store in the report.
                    new_message = (
                        (
                            f"{message} ({xfail_message})"
                            if message
                            else xfail_message
                        )
                        if xfail_message
                        else message
                    )

                    # xUnit tests often use the ERROR status for issues that
                    # are not testsuite bugs (i.e. for what we call "failures"
                    # in e3-testsuite), so be pragmatic and allow them to be
                    # covered by XFAIL.
                    if status == TestStatus.PASS:
                        status = TestStatus.XPASS
                        message = new_message
                    elif status in (TestStatus.FAIL, TestStatus.ERROR):
                        status = TestStatus.XFAIL
                        message = new_message

                # If we had trouble making sense of the XML entry for this test
                # result, turn it into an error and integrate our diagnostics.
                # This bypasses the XFAIL messages intentionally.
                if decoding_errors:
                    result.log += (
                        "\n\nErrors while decoding the xUnit report for this"
                        " testcase:\n\n"
                    )
                    for e in decoding_errors:
                        result.log += f"  * {e}\n"
                    result.log += (
                        "\nSo turning the following into an ERROR result:\n\n"
                        f"  {status.name}: {message}\n"
                    )
                    status = TestStatus.ERROR
                    message = "xUnit report decoding error"

                result.set_status(status, message)
                self.index.save_and_add_result(result)

        # Now that all tests are known, compute the set of dangling XFAILs
        self.dangling_xfails = set(self.xfails) - set(self.index.entries)

    SLUG_RE = re.compile("[a-zA-Z0-9_.]+")

    def slugify(self, name: str) -> str:
        """Normalize a string so that it is an acceptable test name component.

        :param name: Component (substring) for a name to turn into a test name
            that is acceptable for e3-testsuite.
        """
        # Normalize the string, decomposing some codepoints into ASCII
        # characters + modifiers
        name = unicodedata.normalize("NFKD", name)

        # Preserve only codepoints in [a-zA-Z0-9_.] and replace/collapse the
        # rest with hyphens.
        return "-".join(chunk for chunk in self.SLUG_RE.findall(name))

    def get_unique_test_name(self, test_name: str) -> str:
        """Return a test name that is guaranteed to be unique.

        :param test_name: Candidate test name. If the report index already has
            a test result with the same test name, this method generates
            another one based on it.
        """
        result = test_name
        counter = itertools.count(1)
        while result in self.index.entries:
            result = f"{test_name}.{next(counter)}"
        return result

    def get_test_name(
        self,
        testsuite_name: str,
        testcase_name: str,
        classname: Optional[str] = None,
    ) -> str:
        """Combine xUnit testsuite/testcase names into a unique test name.

        :param testsuite_name: Name associated with a xUnit <testsuite>
            element.
        :param testcase_name: Name associated with a xUnit <testcase> element.
        :param classname: If applicable, name of the class that owns this
            testcase.
        """
        return self.get_unique_test_name(
            ".".join(
                self.slugify(name)
                for name in [testsuite_name, classname, testcase_name]
                if name
            )
        )


class XUnitImporterApp:
    """
    Helper class to implement a xUnit report import script.

    This class provide the basic behavior, which subclasses can override if
    needed.
    """

    def __init__(self) -> None:
        self.parser = argparse.ArgumentParser(
            description="Convert a xUnit testsuite report to e3-testsuite's"
            " format."
        )
        self.add_basic_options(self.parser)
        self.add_options(self.parser)

        self.args: argparse.Namespace
        self.index: ReportIndex
        self.xfails: dict[str, str]
        self.importer: XUnitImporter

    def add_basic_options(self, parser: argparse.ArgumentParser) -> None:
        """
        Add basic command line arguments.

        Subclasses must override this to replace basic command line arguments.
        Note that most methods/properties in this class assume that these
        arguments are present: not adding them will likely require to override
        all methods/properties.
        """
        parser.add_argument(
            "--output",
            "-o",
            help="Output directory for the converted report. By default, use"
            " the current working directory.",
        )
        parser.add_argument(
            "--gaia-output",
            action="store_true",
            help="Output a GAIA-compatible testsuite report next to the YAML"
            " report.",
        )
        parser.add_argument(
            "--xfails",
            help="YAML file that describes expected failures. If provided, it"
            " must contain a mapping from test name to expected failure"
            " messages.",
        )
        parser.add_argument(
            "xml-report",
            nargs="+",
            help="xUnit XML reports to convert. If a directory is passed,"
            " recursively look for all the files matching *.xml that it"
            " contains.",
        )

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        """
        Add extra command line arguments.

        Subclasses must override this to add command line arguments in addition
        to the basic ones.
        """
        pass

    @property
    def output_dir(self) -> str:
        """Return the report output directory."""
        return self.args.output or "."

    def create_output_report_index(self) -> ReportIndex:
        """Create the index for the report this app must write."""
        result = ReportIndex(self.output_dir)
        mkdir(result.results_dir)
        return result

    def get_xfails(self) -> dict[str, str]:
        """Return the "xfails" XUnitImporter constructor argument."""
        return (
            read_xfails_from_yaml(self.args.xfails) if self.args.xfails else {}
        )

    def create_importer(self) -> XUnitImporter:
        """Create the XUnitImporter instance for this app."""
        return XUnitImporter(self.index, self.xfails)

    def iter_xunit_files(self) -> Iterable[str]:
        """Iterate through all the xUnit report files to import."""
        for path in getattr(self.args, "xml-report"):
            if os.path.isdir(path):
                for root, _, filenames in os.walk(path):
                    for f in filenames:
                        yield os.path.join(root, f)
            else:
                yield path

    @property
    def gaia_report_requested(self) -> bool:
        """Return whether a GAIA report was requested."""
        return self.args.gaia_output

    def tear_down(self) -> None:
        """
        Clean up the importer.

        Subclasses must override this for custom behavior before the app ends.
        """
        pass

    def run(self, argv: list[str] | None = None) -> None:
        # Initialize the importer
        self.args = self.parser.parse_args(argv)
        self.index = self.create_output_report_index()
        self.xfails = self.get_xfails()
        self.importer = self.create_importer()

        # Process xUnit report files
        for filename in self.iter_xunit_files():
            self.importer.run(filename)
        self.importer.warn_dangling_xfails()

        # Write reports
        self.index.write()
        if self.gaia_report_requested:
            dump_gaia_report(self.index, self.index.results_dir)

        # Clean up the importer
        self.tear_down()


def read_xfails_from_yaml(filename: str) -> dict[str, str]:
    """
    Read a XFAILs dict from a YAML file.

    See the "xfails" parameter for XUnitImporter's constructor for the expected
    YAML structure.
    """
    return e3.yaml.load_ordered(filename)


def convert_main(argv: list[str] | None = None) -> None:
    XUnitImporterApp().run(argv)
