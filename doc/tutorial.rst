.. _tutorial:

Tutorial
========

Let's create a simple testsuite to put :ref:`core_concepts` in practice and
introduce common APIs. The goal of this testsuite will be to write tests for
the ``bc``, the famous POSIX command-line calculator.


Basic setup
-----------

First, create an empty directory and put the following Python code in a
``testsuite.py`` file:

.. code-block:: python

   #! /usr/bin/env python3

   import sys

   from e3.testsuite import Testsuite


   class BcTestsuite(Testsuite):
       """Testsuite for the bc(1) calculator."""

       pass


   if __name__ == "__main__":
       sys.exit(BcTestsuite().testsuite_main())

Just this already makes a functional (but useless) testsuite. Make this file
executable and then run it:

.. code-block:: sh

   $ chmod +x testsuite.py
   $ ./testsuite.py
   INFO     Found 0 tests
   INFO     Summary:
   _  <no test result>

That makes sense: we have an empty testsuite, so running it actually executes
no test.


.. _tutorial_creating_test_driver:

Creating a test driver
----------------------

Most testcases will check the behavior of artithmetic computations, so we have
an obvious first driver to write: it will spawn a ``bc`` process, passing a
file that contains the arithmetic expression to evaluate to it and check that
the output is as expected. Testcases using this driver just need to provide the
expression input file and an expected output file.

Creating a test driver is as simple as creating a Python class that derives
from ``e3.testsuite.drivers.TestDriver``. However, its API is quite crude, so
we will study it :ref:`later <api_test_driver>`. Let's use
``e3.testsuite.drivers.diff.DiffTestDriver`` instead: that class conveniently
provides the framework to spawn subprocesses and check their outputs against
baselines, i.e. exactly what we want to do here.

Add the following class to ``testsuite.py``:

.. code-block:: python

   from e3.testsuite.driver.diff import DiffTestDriver


   class ComputationDriver(DiffTestDriver):
       """Driver to run a computation through "bc" and check its output.

       This passes the "input.bc" to "bc" and check its output against the
       "test.out" baseline file.
       """

       def run(self):
           self.shell(["bc", "input.bc"])

The only mandatory thing to do for ``ClassicTestDriver`` concrete subclasses
(``DiffTestDriver`` is an abstract subclass) is to override the ``run`` method.
The role of this method is to do whatever actions the test driver is supposed
to do in order for testcases to exercize the tested piece of software: compile
software, prepare input files, run processes, and so on.

The very goal of ``DiffTestDriver`` is to compare a "test output" against a
baseline: the test succeeds only if both match. But what's a test output? It is
up to the ``DiffTestDriver`` subclass to define it: for example the output of
one subprocess, the concatenation of several subprocess outputs or the content
of a file that the testcase produces. Subclasses must store this test output in
the ``self.output`` attribute, and ``DiffTestDriver`` will then compare it
against the baseline, i.e. by default: the content of the ``test.out`` file.

Here, the only thing we need to do is to actually run the ``bc`` program on our
input file. ``shell`` is a method inherited from ``ClassicTestDriver`` acting
as a wrapper around Python's ``subprocess`` standard library module. This
wrapper spawns a subprocess with an empty standard input, returns its exit code
and captured output (mix of standard output/error). While the only mandatory
argument is a list of strings for the command-line to run, optional arguments
control how to spawn this subprocess and use its result, for instance:

* ``cwd`` controls the working directory for the subprocess. By default, the
  subprocess is run in the test working directory.
* ``env`` allows to control environment variables passed to the subprocess. By
  default: leave the testsuite environment variables unchanged.
* ``catch_error``: whether to consider non-zero exit code as a test failure
  (true by default).
* ``analyze_output``: whether to append the subprocess' output to
  ``self.output`` (true by default).

Thanks to these defaults, the above call to ``self.shell`` will make the test
succeed only if the ``bc`` program prints the exact expected output and stops
with exit code 0.

Now that we have a test driver, we can make ``BcTestsuite`` aware of it:

.. code-block:: python

   class BcTestsuite(Testsuite):
       test_driver_map = {"computation": ComputationDriver}
       default_driver = "computation"

The ``test_driver_map`` class attribute maps names to test driver classes. It
allows testcases to refer to the test driver they require using these names
(see the next section). ``default_driver`` gives the name of the default test
driver, for testcases that do not specify a specific driver.

With this framework, it is now possible to write actual testcases!


.. _tutorial_writing_tests:

Writing tests
-------------

As described in :ref:`core_concepts`, the standard format for testcases is:
any directory that contains a ``test.yaml`` file.  By default, the testsuite
searches all directories near the Python script file that subclasses
``e3.testsuite.Testsuite``. In our example, that means all directories near the
``testsuite.py`` file, and all nested directories.

With that in mind, let's write our first testcase: create an ``addition``
directory next to ``testsuite.py`` and fill it with testcase data:

.. code-block:: sh

   $ mkdir addition
   $ cd addition
   $ echo "driver: computation" > test.yaml
   $ echo "1 + 2" > input.bc
   $ echo 3 > test.out

Thanks to the presence of the ``addition/test.yaml`` file, the ``addition/``
directory is considered as a testcase. Its content tells the testsuite to run
it using the "computation" test driver: that driver will pick the two other
files as ``bc``'s input and the expected output. In practice:

.. code-block:: sh

   $ ./testsuite.py
   INFO     Found 1 tests
   INFO     PASS         addition
   INFO     Summary:
   _  PASS         1

Note: given that the "compute" test driver is the default one, ``driver:
computation`` in the ``test.yaml`` file is not necessary. We can show that with
a new testcase (empty ``test.yaml`` file):

.. code-block:: sh

   $ mkdir subtraction
   $ cd subtraction
   $ touch test.yaml
   $ echo "10 - 2" > input.bc
   $ echo 8 > test.out
   $ cd ..
   $ ./testsuite.py
   INFO     Found 2 tests
   INFO     PASS         addition
   INFO     PASS         subtraction
   INFO     Summary:
   _  PASS         2


Commonly used testsuite arguments
---------------------------------

So far everything worked fine. What happens when there is a test failure? Let's
create a faulty testcase to find out:

.. code-block:: sh

   $ mkdir multiplication
   $ cd multiplication
   $ touch test.yaml
   $ echo "2 * 3" > input.bc
   $ echo 8 > test.out
   $ cd ..
   $ ./testsuite.py
   INFO     Found 3 tests
   INFO     PASS         subtraction
   INFO     PASS         addition
   INFO     FAIL         multiplication: unexpected output
   INFO     Summary:
   _  PASS         2
   _  FAIL         1

Instead of the expected ``PASS`` test result, we have a ``FAIL`` one with a
message: ``unexpected output``. Even though we can easily guess the error is
that the expected output should be ``6`` (not ``8``), let's ask the testsuite
to show details thanks to the ``--show-error-output/-E`` option. We'll also ask
the testsuite to run only that failing testcase:

.. code-block:: sh

   $ ./testsuite.py -E multiplication
   INFO     Found 1 tests
   INFO     FAIL         multiplication: unexpected output
   _--- expected
   _+++ output
   _@@ -1 +1 @@
   _-8
   _+6
   INFO     Summary:
   _  FAIL         1

On baseline comparison failure, ``DiffTestDriver`` creates a unified diff
between the baseline (``--- expected``) and the actual output (``+++ output``)
showing the difference, and the testsuite's ``--show-error-output/-E`` option
displays it, making it easy to quickly spot the difference between the two.

Even though these 3 testcases take very little time to run, most testsuites
require a lot of CPU time to run to completion. Nowadays, most working stations
have several cores, so we can spawn one test per core to speedup testsuite
execution time. ``e3.testsuite`` supports the ``--jobs/-j`` option to achive
this. This option works the same way it does for the ``make`` program: ``-jN``
is the default (run at most N testcases at a time, default is 1), and ``-j0``
tells to set N to the number of CPU cores.


Test execution control
----------------------

There is no obvious bug in ``bc`` that this documentation could expect to
survive for long, so let's stick with this wrong ``multiplication`` testcase
and pretend that ``bc`` should return ``8``. This is a known bug, and so the
failure is expected for the time being. This situation occurs a lot in
software: bugs often take a lot of time to fix, sometimes test failures come
from bugs in upstream projects, etc.

To keep testsuite reports readable/usable, it is convenient to tag failures
that are temporarily accepted as ``XFAIL`` rather than ``FAIL``: the former
is a failure that has been analyzed as acceptable for now, leaving the latter
for unexpected regressions to investigate. Testcases using a driver that
inherits from ``ClassicTestDriver`` can do that by adding a ``control`` entry
in their ``test.yaml`` file. To do that, append the following to
``multiplication/test.yaml``:

.. code-block:: yaml

   control:
   - [XFAIL, "True", "erroneous multiplication: see bug #1234"]

When present, ``control`` must contain a list of 2- or 3-uplets:

* A command. Here, ``XFAIL`` to state that failure is expected: ``FAIL`` test
  statuses are turned into ``XFAIL``, and ``PASS`` are turned into ``XPASS``.
  There are two other commands available: ``NONE`` (the default: regular test
  execution), and ``SKIP`` (do not execute the testcase and create a ``SKIP``
  test result).
* A Python expression as a condition guard, to decide whether the command
  applies to this testsuite run. Here, it always applies.
* An optional message to describe why this command is here.

The first command whose guard evaluates to true applies. We can see it in
action:

.. code-block:: sh

   $ ./testsuite.py -j8
   INFO     Found 3 tests
   INFO     XFAIL        multiplication: unexpected output (erroneous multiplication: see bug #1234)
   INFO     PASS         subtraction
   INFO     PASS         addition
   INFO     Summary:
   _  PASS         2
   _  XFAIL        1

You can learn more about this specific test control mechanism and even how to
create your own mechanism in :ref:`api_control`.
