``e3.testsuite.report``: reading/writing reports
================================================

Is is sometimes useful to directly use e3-testsuite's API: this allows to
create a e3-testsuite report, for instance to import results from a third-party
testsuite framework. This can also be useful to implement a custom testsuite
report viewer (alternative to the ``e3-testsuite-report`` command).

For both kinds of uses, the concepts are the same: a ``ReportIndex`` instance
maintains a list of ``TestResult`` instances (see :ref:`api_result`), storing
files in a directory: ``results_dir``.


Reading reports
---------------

Reading a testsuite report is as simple as building a ``ReportIndex`` with the
``ReportIndex.read(results_dir)`` class method and then processing the
``ReportIndex`` attributes:

``status_counters``
   Dict that maps each test status (see :ref:`api_test_status`) to the number
   of test results with that test status.

``duration``
   Decimal number of seconds for the total duration of the testsuite run, or
   ``None`` if this information is not available.

``entries``
  Dict that maps each test name to a ``ReportIndexEntry`` instance for each
  test result. ``ReportIndexEntry`` objects contain the same information as
  ``TestResultSummary`` (test name, test status, ...), and their ``.load()``
  method allows to fetch the corresponding ``TestResult`` instance.

  The ``ReportIndexEntry`` indirection between the report index and the
  ``TestResult`` instance is necessary to keep performance reasonable: reading
  the information necessary to build a ``TestResult`` instance (logs, ...) is
  slow, so it should be avoided whenever possible. Scripts often want to
  process only tests that failed, and in most test reports, most test results
  are successful, so most ``TestResult`` instances are not needed in practice.

Usage example:

.. code-block:: python

   from e3.testsuite.report.index import ReportIndex
   from e3.testsuite.result import TestStatus


   # Read the testsuite report present in the "report"
   # directory
   index = ReportIndex.read("report")

   # Print a summary of the results: number of results
   # for each test status, sorted by status.
   summary = [
       (status, count)
       for status, count in index.status_counters.items()
       if count
   ]
   summary.sort(key=lambda item: item[0].value)
   for status, count in summary:
       print(f"{status.name}: {count}")

   # Process details for each test that did not pass,
   # sorted by test name. To keep performance reasonable
   # for big reports, do not load the result itself
   # unless necessary.
   for test_name, entry in index.entries.items():
       if entry.status not in {
           TestStatus.PASS,
           TestStatus.UOK,
           TestStatus.SKIP,
       }:
           result = entry.load()
           ...


Writing reports
---------------

Writing a report happens in 4 stages:

1. ensure the result directory (``results_dir``) exists;
2. create a ``ReportIndex`` instance;
3. for each test result (``TestResult`` instance), save it to the result
   directory and add it to the index;
4. finally, write the index itself to the result directory.

Usage example:

.. code-block:: python

   from collections.abc import Iterable
   import os.path

   from e3.testsuite.report.index import ReportIndex
   from e3.testsuite.result import TestResult


   # The purpose of this function is to produce the
   # list of results to include in the testsuite
   # report.
   def iter_results() -> Iterable[TestResult]: ...

   # Ensure that the results directory exists
   results_dir = os.path.abspath("report")
   if not os.path.exists(results_dir):
       os.mkdir(results_dir)

   # Create a testsuite report in "results_dir"
   index = ReportIndex(results_dir)

   # Save each result to a file and add it to the
   # index.
   for result in iter_results():
       index.save_and_add_result(result)

   # Write the index itself to the disk
   index.write()


Exporting to other formats
--------------------------

Once a ``ReportIndex`` instance has been read or written, it is possible to
export it to a third-party format for a third-party report reader to process
it.

GAIA
****

GAIA is AdaCore's internal viewer for the production system. It has its own
file format to store testsuite reports, which the
``e3.testsuite.report.gaia.dump_gaia_report`` function can produce in a given
output directory from a report index:

.. code-block:: python

   from e3.testsuite.report.gaia import dump_gaia_report
   from e3.testsuite.report.index import ReportIndex


   index = ReportIndex.read("e3-testsuite-report")
   dump_gaia_report(index, output_dir="gaia-report")


xUnit
*****

Testing tools in the `xUnit/JUnit family
<https://en.wikipedia.org/wiki/XUnit>`_ share a common XML format to store
testsuite reports. The ``e3.testsuite.xunit.dump_xunit_report`` function can
write an XML file for a given report index:

.. code-block:: python

   from e3.testsuite.report.index import ReportIndex
   from e3.testsuite.report.xunit import dump_xunit_report


   index = ReportIndex.read("e3-testsuite-report")
   dump_xunit_report("my-testsuite", index, filename="report.xml")
