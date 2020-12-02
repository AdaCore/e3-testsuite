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
contains testcases. It must return a list of ``ParsedTest`` instances: each one
will later be used to instantiate a ``TestDriver`` subclass for this testcase.

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
