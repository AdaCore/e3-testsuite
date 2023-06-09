.. _api_testcase_finder:

``e3.testsuite.testcase_finder``: Control testcase discovery
============================================================

In :ref:`core_concepts`, the default format for testcases is described as: any
directory that contains a ``test.yaml`` file. This section shows the mechanisms
to implement different formats.

Internally, the testsuite creates testcases from a list of
``e3.testsuite.testcase_finder.ParsedTest`` instances: precisely one testcase
per ``ParsedTest`` object. This class is just a holder for the information
required to create a testcase, it contains the following attributes:

``test_name``
   Name for this testcase, generally computed from ``test_dir`` using
   ``Testsuite.test_name`` (see :ref:`api_testsuite_test_name`). Only one
   testcase can have a specific name, or put differently: test names are
   unique.

``driver_cls``
   ``TestDriver`` subclass to instantiate for this testcase. When left to
   ``None``, the testsuite will use the default driver (:ref:`if available
   <api_testsuite_test_drivers>`).

``test_env``
   Dictionary for the :ref:`test environment <api_testsuite_test_env>`.

``test_dir``
   Name of the directory that contains the testcase.

``test_matcher``
   Optional "matching name", for filtering purposes, i.e. to run the testsuite
   on a subset of tests. See :ref:`below <api_testcase_dedicated_directory>`.

The next piece of code, responsible to create ``ParsedTest`` instances, is the
``e3.testsuite.testcase_finder.TestFinder`` interface. This API is very simple:
``TestFinder`` objects must support a ``probe(testsuite, dirpath, dirnames,
filenames)`` method, which is called for each directory that is a candidate to
be a testcase. The semantics for ``probe`` arguments are:

``testsuite``
   Testsuite instance that is looking for testcases.

``dirpath``
   Absolute name for the candidate directory to probe.

``dirnames``
   Base names for ``dirpath`` subdirectories.

``filenames``
   Basenames for files in ``dirpath``.

When called, ``TestFinder.probe`` overriding methods are supposed to look at
``dirpath``, ``dirnames`` and ``filenames`` to determine whether this directory
contains testcases. If needed, it can also query the directory that contains
all testcases with the ``testsuite.test_dir`` attribute. ``TestFinder.probe``
must return a list of ``ParsedTest`` instances: each one will later be used to
instantiate a ``TestDriver`` subclass for this testcase.

.. note::

   For backwards compatibility, ``probe`` methods can return ``None`` instead
   of an empty list when there is no testcase, and can return directly a
   ``ParsedTest`` instance instead of a list of one element when the probed
   directory contains exactly one testcase.

The default ``TestFinder`` instance that testsuites use come from the
``e3.testsuite.testcase_finder.YAMLTestFinder`` class. Its probe method is very
simple: consider there is a testcase iff there is ``test.yaml`` is present in
``filenames``. In that case, parse its YAML content, use the result as the test
environment and look for a ``driver`` environment entry to fetch the
corresponding test driver.

The ``Testsuite.get_test_list`` internal method is the one that takes care of
running the search for tests in the appropriate directories: in the testsuite
root directory, or in directories passed in argument to the testsuite, and
delegates the actual "testcase decoding" to ``TestFinder`` instances.

Testsuites that need custom ``TestFinder`` instances only have to override the
``test_finders`` property/class method in ``Testsuite`` subclasses, to return,
as one would probably expect, the list of test finders that will probe
candidate directories. The default implementation is eloquent:

.. code-block:: python

   @property
   def test_finders(self):
       return [YAMLTestFinder()]

Note that when there are multiple test finders, they are used in the same order
as in the returned list: the first one that returns a ``ParsedTest`` "wins",
and the directory is ignored if all test finders returned ``None``.


.. _api_testcase_dedicated_directory:

The special case of directories with multiple tests
---------------------------------------------------

To keep reasonable performance when running a subset of testcases (i.e. when
passing the ``sublist`` positional command line argument), the
``Testsuite.get_test_list`` method does not even try to call test finders on
directories that don't match a requested sublist. For instance, with the given
tree of tests:

.. code-block:: text

   tests/
      bar/
         x.txt
         y.txt
      foo/
         a.txt
         b.txt
         c.txt

The following testsuite run:

.. code-block:: sh

   ./testsuite.py tests/bar/

will call the ``TestFinder.probe`` method only on the ``tests/bar/`` directory
(and ignores ``tests/foo/``).

This is fine if each testcase has a dedicated directory, which is the
recommended strategy to encode tests. However, if indvidual tests are actually
encoded as single files (for instance ``*.txt`` files in the example above,
which can happen with legacy testsuites), then the filtering of tests to run
can work in unfriendly ways:

.. code-block:: sh

   ./testsuite.py a.txt

will run no testcase: no directory matches ``a.txt``, so the testsuite will
never call ``TestFinder.probe``, and thus the testsuite will find no test.

In order to handle such cases, and thus force the matching machinery to
consider filenames (possibly at the expanse of performance), you need to:

* override the ``TestFinder.test_dedicated_directory`` property to return
  ``False`` (it returns ``True`` by default);

* make its ``probe`` method pass ``ParsedTest``'s ``test_matcher`` constructor
  argument a string to be matched against sublists.

To continue with the previous example, let's write a test finder that creates a
testcase for every ``*.txt`` file in the test tree, using the
``TextFileDriver`` driver class:

.. code-block:: python

   class TextFileTestFinder(TestFinder):
       @property
       def test_dedicated_directory(self):
           # We create one testcase per text file. There can be multiple text
           # files in a single directory, ergo tests are not guaranteed to have
           # dedicated test directories.
           return False

       def probe(self, testsuite, dirpath, dirnames, filenames):
           # Create one test per "*.txt" file
           return [
               ParsedTest(
                   # Strip the ".txt" extension for the test name
                   test_name=testsuite.test_name(
                       os.path.join(dirpath, f[:-4])
                   ),
                   driver_cls=TextFileDriver,
                   test_env={},
                   test_dir=dirpath,
                   # Preserve the ".txt" extension so that it matches "a.txt"
                   test_matcher=os.path.join(dirpath, f),
               )
               for f in filenames:
               if not f.endswith(".txt")
           ]

Thanks to this test finder:

.. code-block:: sh

   # Run tests/bar/x.txt and tests/bar/y.txt
   ./testsuite tests/bar

   # Only run tests/bar/x.txt
   ./testsuite x.txt
