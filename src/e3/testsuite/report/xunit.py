"""Helpers to generate testsuite reports using the XUnit XML format."""

from __future__ import annotations

import xml.etree.ElementTree as etree

from e3.testsuite.report.index import ReportIndex
from e3.testsuite.result import TestStatus


def dump_xunit_report(name: str, index: ReportIndex, filename: str) -> None:
    """
    Dump a testsuite report to `filename` in the standard XUnit XML format.

    :param name: Name for the teststuite report.
    :param index: Report index for the testsuite results to report.
    :param filename: Name of the text file to write.
    """
    testsuites = etree.Element("testsuites", name=name)
    testsuite = etree.Element("testsuite", name=name)
    testsuites.append(testsuite)

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

        # The only class involved in testcases (that we know of in this
        # testsuite framework) is the TestDriver subclass, but this is not
        # useful for the report, so leave this dummy "e3-testsuite-driver"
        # instead.
        testcase = etree.Element(
            "testcase", name=test_name, classname="e3-testsuite-driver"
        )
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
                status_elt.set("message", result.msg)

            if counter_key in ("errors", "failures"):
                status_elt.set("type", "error")

            assert isinstance(result.log, str)
            status_elt.text = result.log

        elif result.log:
            system_out = etree.Element("system-out")
            system_out.text = str(result.log)
            testcase.append(system_out)

    # Include counters in <testsuite> and <testsuites> elements
    for key, count in sorted(counters.items()):
        testsuite.set(key, str(count))
        testsuites.set(key, str(count))

    # The report is ready: write it to the requested file
    tree = etree.ElementTree(testsuites)
    tree.write(filename, encoding="utf-8", xml_declaration=True)
