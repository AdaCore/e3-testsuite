.. _api_testsuite:

``e3.testsuite``: Testsuite API
===============================

So far, this documentation focused on writing test drivers. Although these
really are the meat of each testsuite, there are also testsuite-wide features
and customizations to consider.


.. _api_testsuite_test_drivers:

Test drivers
------------

The :ref:`tutorial` already covered how to register the set of test drivers in
the testsuite, so that each testcase can chose which driver to use. Just
creating ``TestDriver`` subclasses is not enough: testsuite must associate a
name to each available driver.

This all happens in ``Testsuite.test_driver_map``, which as usual can be either
a class attribute or a property. It must contain/return a dict, mapping driver
names to ``TestDriver`` subclasses:

.. code-block:: python

   from e3.testsuite import Testsuite
   from e3.testsuite.driver import TestDriver


   class MyDriver1(TestDriver):
       # ...
       pass


   class MyDriver2(TestDriver):
       # ...
       pass


   class MyTestsuite(Testsuite):
       test_driver_map = {"driver1": MyDriver1, "driver2": MyDriver2}

This is the only mandatory customization when creating a ``Testsuite``
subclass. A nice optional addition is the definition of a default driver:
if most testcases use a single test driver, this will make it handier to create
tests.

.. code-block:: python

   class MyTestsuite(Testsuite):
       test_driver_map = {"driver1": MyDriver1, "driver2": MyDriver2}

       # Testcases that don't specify a "driver" in their test.yaml file will
       # automatically run with MyDriver2.
       default_driver = "driver2"


.. _api_testsuite_test_env:

Testsuite environment
---------------------

``Testsuite`` and ``TestDriver`` instances all have a ``self.env`` attribute.
This holds a ``e3.env.BaseEnv`` instance: the testsuite originally creates it
when starting and forwards it to test drivers.

This environment holds information about the platform for which tests are
running (host OS, target CPU, ... as well as parsed options from the
command-line (see below). The testsuite is also free to add more information to
this environment.

If a testsuite actually needs to deal with non-native targets, for instance
running on GNU/Linux for x86_64 tests that involve programs for bare ARM ELF
targets, then it's useful to override the ``enable_cross_support`` class
attribute/property to return true (it returns false by default):

.. code-block:: python

   class MyTestsuite(Testsuite):
       enable_cross_support = True

In this case, the testsuite will add ``--build``, ``--host`` and ``--target``
command-line arguments. These have the same semantics as the homonym options in
GNU ``configure`` scripts: see `The GNU configure and build system
<https://airs.com/ian/configure/configure_6.html>`_. The testsuite will then
use these arguments to build the appropriate environment in ``self.env``, and
thus for instance ``self.env.target.cpu.name`` will reflect the target CPU.


Command-line options
--------------------

.. note:: This section assumes that readers are familiar with Python's famous
   ``argparse`` standard package. Please read `its documentation
   <https://docs.python.org/3/library/argparse.html>`_ if this is the first
   time you hear about it.

Testsuites often have multiple operating modes. A very common mode is: does it
run programs under Valgrind? Doing this has great value, as it helps finding
invalid memory accesses, use of uninitialized values, etc. but comes at a great
performance cost. So always using Valgrind is not realistic.

Adding a testsuite command-line option is a way to solve this problem: by
default (for the most common cases: day-to-day development runs) Valgrind
support is disabled, and the testsuite enables it when run with a
``--valgrind`` argument (used in continuous builders, for instance).

Adding testsuite options is very simple: in the ``Testsuite`` subclass,
override the ``add_options`` method. It takes a single argument: the
``argparse.ArgumentParser`` instance that is responsible for parsing the
testsuite command-line arguments. To implement the Valgrind example discussed
above, we can have:

.. code-block:: python

   class MyTestsuite(Testsuite):
       def add_options(self, parser):
           parser.add_argument("--valgrind", action="store_true",
                               help="Run tests under Valgrind")

The result of command-line parsing, i.e. the result of ``parser.parse_args()``
is made available in ``self.env.options``. This means that test drivers can
then check for the presence of the ``--valgrind`` on the command line the
following way:

.. code-block:: python

   class MyDriver(ClassicTestDriver):
       def run(self):
           argv = self.test_program_command_line

           # If the testsuite is run with the --valgrind option, run the test
           # program under Valgrind.
           if self.env.options.valgrind:
               argv = ["valgrind", "--leak-check=full", "-q"] + argv

           self.shell(argv)


Set up/tear down
----------------

Testsuites that need to execute arbitrary operations right before looking for
tests and running them can override the ``Testsuite.set_up`` method. Similarly,
testsuites that need to execute actions after all testcases ran to completion
and after testsuite reports were emitted can override the
``Testsuite.tear_down`` method.

.. code-block:: python

   class MyTestsuite(Testsuite):
       def set_up(self):
           # Let the base class' set_up method do its job
           super().set_up()

           # Then do whatever is required before running testcases.
           # Note that by the time this is executed, command-line
           # options are parsed and the environment (self.env)
           # is fully initialized.

           # ...

       def tear_down(self):
           # Do whatever is required to after the testsuite has
           # run to completion.

           # ...

           # Then let the base class' tear_down method do its job
           super().tear_down()


Overriding tests subdirectory
-----------------------------

As described in the :ref:`tutorial <tutorial_writing_tests>`, by default the
testsuite looks for tests in the testsuite root directory, i.e. the directory
that contains the Python script in which ``e3.testsuite.Testsuite`` is
subclassed. Testsuites can override this behavior with the ``tests_subdir``
property:

.. code-block:: python

   class MyTestsuite(Testsuite):
       @property
       def tests_subdir(self):
           return "tests"

This property must return a directory name that is relative to the testsuite
root: testcases are looked for in all of its subdirectories.

The :ref:`next section <api_testcase_finder>` describes how to go deeper and
change the testcase discovery process itself.


.. _api_testsuite_test_name:

Changing the testcase naming scheme
-----------------------------------

Testsuite require unique names for all testcases. These name must be valid
filenames: no directory separator or special character such as ``:`` are
allowed.

By default, this name is computed from the name of the testcase directory,
relative to the tests subdirectory: directory separators are just replaced with
``__`` (two underscores). For instance, the testcase ``a/b-c/d`` is assigned
the ``a__b-c__d`` name.

Changing the naming scheme is as easy as overriding the ``test_name`` method,
which takes the name of the test directory and must return the test name,
conforming to the constraints described above:

.. code-block:: python

   class MyTestsuite(Testsuite):
       def test_name(self, test_dir):
           return custom_computation(test_dir)
