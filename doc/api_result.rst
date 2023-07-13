.. _api_result:

``e3.testsuite.result``: Create test results
============================================

As presented in the :ref:`core_concepts`, each testcase can produce one or
several test results. But what is a test result exactly? The answer lies in the
``e3.testsuite.result`` module. The starting point is the ``TestResult`` class
it defines.


``TestResult``
--------------

This test result class is merely a data holder. It contains:

* the name of the test corresponding to this result;
* the test status (a ``TestStatus`` instance: see the section below) as well as
  an optional one-line message to describe it;
* various information to help post-mortem investigation, should any problem
  occur (logs, list of subprocesses spawned during test execution, environment
  variables, ...).

Even though test drivers create a default ``TestResult`` instance
(``self.result`` test driver attribute), the actual registration of test
results to the testsuite report is manual: test drivers must call their
``push_result`` method for that. This is how a single test driver instance
(i.e. a single testcase) can register multiple test results.

The typical use case for a single driver instance pushing multiple test results
is for testcases that contain multiple "inputs" and 1) compile a test program
2) run that program once for each input. In this case, it makes sense to create
one test result per input, describing whether the software behaves as expected
for each one independently rather than creating a single result that describes
whether the software behaved well for *all* inputs.

This leads to the role of the test result name (``test_name`` attribute of
``TestResult`` instances). The name of the default result that drivers create
is simply the name of the testcase. This is a nice start, since it makes it
super easy for someone looking at the report to relate the ``FAIL foo-bar``
result to the ``foo/bar`` testcase. By convention, drivers that create multiple
results assign them names such as ``TEST_NAME.INPUT_NAME``, i.e. just put a dot
between the testcase name and the name of the input that triggers the emission
of a separate result.

An example may help to clarify. Imagine a testsuite for a JSON handling
library, and the following testcase that builds a test program that 1) parses
its JSON input 2) pretty-prints that JSON document on its output:

.. code-block:: text

   parsing/
      test.yaml
      test_program.c

      empty-array.json
      empty-array.out

      zero.json
      zero.out

      ...

A test driver for this testcase could do the following:

* Build ``test_program.c``, a program using the library to test (no test result
  for that).
* Run that program on ``empty-array.json``, compare its output to
  ``empty-array.out`` and create a test result for that comparison, whose name
  is ``parsing.empty-array``.
* Likewise for ``zero.json`` and ``zero.out``, creating a ``parsing.zero`` test
  result.
* ...

Here is the exhaustive list of ``TestResult`` attributes:

``test_name``
   Name for this test result.

``env``
   Dictionary for the :ref:`test environment <api_testsuite_test_env>`.

``status``
   :ref:`Status <api_test_status>` for this test result.

``msg``
   Optional (``None`` or string) short message to describe this result. Strings
   must not contain newlines. This message usually comes as a hint to explain
   why the status is not ``PASS``: unexpected output, expected failure from
   the ``test.yaml`` file, etc.

.. _api_test_result_log:

``log``
   :ref:`Log <result_log>` instance to contain free-form text, for test
   execution post-mortem debugging purposes. Test drivers are invited to write
   content that will be useful if things go wrong during the test execution:
   test failure, test driver bug, and so on. This is what gets printed on the
   standard output when the test fails and the ``--show-error-output``
   testsuite switch is present.

``processes``
   List of free-form information to describe the subprocesses that the test
   driver spawned while running the testcase, for debugging purposes. The only
   constraint is that this attribute must contain YAML-serializable data.

   .. note:: This is likely redundant with the ``log`` attribute, so this
      attribute could be removed in the future.

``failure_reasons``
   When the test failed, optional set of reasons for the failure. This
   information is used only in advanced viewers, which may highlight
   specifically some failure reasons. For instance, highlight crashes, that may
   be more important to investigate than mere unexpected outputs.

``expected``, ``out`` and ``diff``
   Drivers that compare expected and actual output to validate a testcase
   should initialize these with ``Log`` instances to hold the expected test
   output (``self.expected``) and the actual test output (``self.out``). It is
   assumed that the test fails when there is at least one difference between
   both.

   Note that several drivers refine expected/actual outputs before running the
   comparison (see for instance the :ref:`output refining mechanism
   <api_diff_output_refining>`). These logs are supposed to contain the outputs
   actually passed to the diff computation function, i.e. *after* refining, so
   that whatever attemps to re-compute the diff (report production, for
   instance) get the same result.

   If, for some reason, it is not possible to store expected and actual
   outputs, ``self.diff`` can be assigned a ``Log`` instance holding the diff
   itself. For instance, the output of the ``diff -u`` command.

``time``
   Optional decimal number of seconds (``float``). Test drivers can use this
   field to track performance, most likely the time it took to run the test.
   Advanced results viewer can then plot the evolution of time over software
   evolution.

``info``
   Key/value string mapping, for unspecified use. The only restriction is that
   no string can contain a newline character.


.. _api_test_status:

``TestStatus``
--------------

This is an ``Enum`` subclass, allowing to classify results: tests that passed
(``TestStatus.PASS``), tests that failed (``TestStatus.FAIL``), etc. For
convenience, here the list of all available statuses as described in the
``result.py`` module:

PASS
   The test has run to completion and has succeeded.

FAIL
   The test has run enough for the testsuite to consider that it failed.

XFAIL
   The test has run enough for the testsuite to consider that it failed, and
   that this failure was expected.

XPASS
   The test has run to completion and has succeeded whereas a failure was
   expected. This corresponds to ``UOK`` in old AdaCore testsuites.

VERIFY
   The test has run to completion, but it could not self-verify the test
   objective (i.e. determine whether it succeeded). This test requires an
   additional verification action by a human or some external oracle.

SKIP
   The test was not executed (it has been skipped). This is appropriate when
   the test does not make sense in the current configuration (for instance it
   must run on Windows, and the current OS is GNU/Linux).

   This is equivalent to DejaGnu's UNSUPPORTED, or UNTESTED test outputs.

NOT_APPLICABLE
   The test has run and managed to automatically determine it can't work on a
   given configuration (for instance, a test scenario requires two distinct
   interrupt priorities, but only one is supported on the current target).

   The difference with SKIP is that here, the test has started when it
   determined that it would not work. The definition of when a test actually
   starts is left to the test driver.

ERROR
   The test could not run to completion because it is misformatted or due to an
   unknown error. This is very different from FAIL, because here the problem
   comes more likely from the testcase or the test framework rather than the
   tested software.

   This is equivalent to DejaGnu's UNRESOLVED test output.


.. _result_log:

``Log``
-------

This class acts as a holder for strings or sequences of bytes, to be used as
free-form textual logs, actual output, ... in ``TestResult`` instances.

The only reason to have this class instead of just holding Python's
``string``/``bytes`` objects is to control the serialization of these logs to
YAML. Interaction wiht these should be transparent to test drivers anyway, as
they are intended to be used in append-only mode. For instance, to add a line
to a test result's free-form log:

.. code-block:: python

   # In this example, self.result.log is already a Log instance holding a "str"
   # instance.
   self.result.log += "Test failed because mandatory.txt file not found.\n"


``FailureReason``
-----------------

A testcase may produce ``FAIL`` results for very various reasons: for instance
because process output is unexpected, or because the process crashed. Since
crashes may be more urgent to investigate than "mere" unexpected outputs,
advanced report viewers may want to highlight them specifically.

To answer this need, test drivers can set the ``.failure_reasons`` attribute in
``TestResult`` instances to a set of ``FailureReason`` values.
``FailureReason`` is an ``Enum`` subclass that defines the following values:

CRASH
   A process crash was detected. What is a "crash" is not clearly specified: it
   could be for instance that a "GCC internal compiler error" message is
   present in the test output.

TIMEOUT
   A process was stopped because it timed out.

MEMCHECK
   The tested software triggered an invalid memory access pattern. For
   instance, Valgrind found a conditional jump that depends on uninitialized
   data.

DIFF
   Output is not as expected.
