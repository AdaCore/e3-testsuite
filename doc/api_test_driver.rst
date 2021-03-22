.. _api_test_driver:

``e3.testsuite.driver``: Core test driver API
=============================================

The first sections of this part contain information that applies to all test
drivers. However, starting with the :ref:`test_fragments` section, it describes
the low level ``TestDriver`` API, to create test drivers. You should consider
using it only if higher lever APIs, such as :ref:`ClassicTestDriver
<api_classic>` and :ref:`DiffTestDriver <api_diff>` are not powerful enough for
your needs. Still, knowing how things work under the hood may help when issues
arise, so reading this part until the end can be useful at some point.


Basic API
---------

All test drivers are classes that derive directly or indirectly from
``e3.testsuite.driver.TestDriver``. Instances contain the following attributes:

``env``
   ``e3.env.BaseEnv`` instance, inherited from the testsuite. This object
   contains information about the host/build/target platforms, the testsuite
   parsed command-line arguments, etc. More on this in :ref:`api_testsuite`.

``test_env``
   The testcase environment. It is a dictionary that contains at least the
   following entries:

   * ``test_name``: The name that the testsuite assigned to this testcase.
   * ``test_dir``: The absolute name of the directory that contains the
     testcase.
   * ``working_dir``: The absolute name of the temporary directory that this
     test driver is free to create (see :ref:`below
     <test_working_directories>`) in order to run the testcase.

   Depending on how the way the testcase has been created (see
   :ref:`api_testcase_finder`), this dictionary may contain other entries:
   for ``test.yaml``-based tests, this will also contain entries loaded from
   the ``test.yaml`` file.

``result``
   Default ``TestResult`` instance for this testcase. See :ref:`api_result`.


.. _test_working_directories:

Test/working directories
------------------------

Test drivers need to deal with two directories specific to each testcase:

Test directory
   This is the "source" of the testcase: the directory that contains the
   ``test.yaml`` file. Consider this repertory read-only: it is bad practice to
   have execution modify the source of a testcase.

Working directory
   In order to execute a testcase, it may be necessary to create files and
   directories in some temporary place, for instance to build a test program.
   While using Python's standard mechanism to create temporary files
   (``tempfile`` module) is an option, ``e3.testsuite`` provide its own
   temporary directory management facility, which is more helpful when
   investigating failures.

   Each testcase is assigned a unique subdirectory inside the testsuite's
   temporary directory: the testcase working directory, or just "working
   directory". Note that the testsuite only reserves the name of that
   subdirectory: it is up to test drivers to actually create it, should they
   need it.

Inside test driver methods, directory names are available respectively as
``self.test_env["test_dir"]`` and ``self.test_env["working_dir"]``. In
addition, two shortcut methods allow to build absolute file names inside these
directories: ``TestDriver.test_dir`` and ``TestDriver.working_dir``. Both work
similarly to ``os.path.join``:

.. code-block:: python

   # Absolute name for the "test.yaml" in the test directory
   self.test_dir("test.yaml")

   # Absolute name for the "obj/foo.o" file in the working directory
   self.test_dir("obj", "foo.o")


.. warning::
   What follows documents the advanced API. Only complex testsuites should need
   this.

.. _test_fragments:

Test fragments
--------------

The ``TestDriver`` API deals with an abstraction called *test fragments*. In
order to leverage machines with multiple cores so that testsuites run faster,
we need processings to be separated into independent parts to be scheduled in
parallel. Test fragments are such independent parts: the fact that a test
driver can create multiple fragments for a single testcase allows finer
granularity for testcase execution parallelisation compared to "a whole
testcase reserves a whole core".

When a testsuite runs, it first looks for all testcases to run, then ask their
test drivers to create all the test fragments they need to execute tests. Only
then, a scheduler is spawned to run test fragments with the desired level of
parallelism.

This design is supposed to work with workflows such as "build test program and
only then run in parallel all tests using this program". To allow this, test
drivers can create dependencies between test fragments. This formalism is very
similar to the dependency mechanism in build software such as ``make``: the
scheduler will first trigger the execution of fragments with no dependency,
then of fragments with dependencies satisfied, etc.

To continue with the JSON example presented in :ref:`api_result`: the test
driver can create a ``build`` fragment (with no dependency) and then one
fragment per JSON document to parse (all depending on the ``build`` fragment).
The scheduler will first trigger the execution of the ``build`` fragment: once
this fragment has run to completion, the scheduler will be able to trigger the
execution of all other fragments in parallel.


Creating test drivers
---------------------

As described in the :ref:`tutorial <tutorial_creating_test_driver>`, creating a
test driver implies creating a ``TestDriver`` subclass. The only thing such
subclasses are required to do is to provide an implementation for the
``add_test`` method, which acts as an entry point. Note that there should be no
need to override the constructor.

.. _test_driver_add_fragment:

This ``add_test`` method has one purpose: register test fragments, and the
``TestDriver.add_fragment`` method is available to do so. This latter method
has the following interface:

.. code-block:: python

   def add_fragment(self, dag, name, fun=None, after=None):

``dag``
   Data structure that hold fragments and that the testsuite scheduler will use
   to run jobs in the correct order. The ``add_test`` method must forward its
   own ``dag`` argument to ``add_fragment``.

``name``
   String to designate this new fragment in the current testcase.

``fun``
   Test fragment callback. It must accept two positional arguments:
   ``previous_values`` and ``slot``. When this test fragment is executed, this
   function is called and passed as ``previous_values`` a mapping that contains
   return values from previously executed fragments. Later, other test
   fragments executed will see ``fun``'s own return value in this record under
   the ``name`` key.

   If left to ``None``, ``add_fragment`` will fetch the test driver method
   called ``name``.

   The ``slot`` argument is described :ref:`below <test_fragment_slot>`.

``after``
   List of fragment names that this new fragment depends on. The testsuite will
   schedule the execution of this new fragment only after all the fragments
   that ``after`` designates have been executed. Note that its execution will
   happen even if one or several fragments in ``after`` terminated with an
   exception.

Let's again continue with this JSON example. It is time to roll a
``TestDriver`` subclass, define the appropriate ``add_test`` method to create
test fragments.

.. code-block:: python

   from glob import glob
   import subprocess

   from e3.testsuite.driver import TestDriver
   from e3.testsuite.result import TestResult, TestStatus


   class ParsingDriver(TestDriver):

       def add_test(self, dag):
           # Register the "build" fragment, no dependency. The fragment
           # callback is the "build" method.
           self.add_fragment(dag, "build")

           # For each input JSON file in the testcase directory, create a
           # fragment to run the parser on that JSON file.
           for json_file in glob(self.test_dir("*.json")):
               input_name = os.path.splitext(json_file)[0]
               fragment_name = "parse-" + input_name
               out_file = json_file + ".out"

               self.add_fragment(
                   dag=dag,

                   # Unique name for this fragment (specific to json_file)
                   name=fragment_name,

                   # Unique callback for this fragment (likewise)
                   fun=self.create_parse_callback(
                       fragment_name, json_file, out_file
                   ),

                   # This fragment only needs the build to happen first
                   after=["build"]
               )

       def build(self, previous_values):
           """Callback for the "build" fragment."""
           # Create the temporary directory for this testcase
           os.mkdir(self.working_dir())

           # Build the test program, writing it to this temporary directory
           # (don't ever modify the testcase source directory!).
           subprocess.check_call(
               ["gcc", "-o", "test_program", self.test_dir("test_program.c")],
               cwd=self.working_dir()
           )

           # Return True to tell next fragments that the build was successful
           return True

       def create_parse_callback(self, fragment_name, json_file, out_file):
           """
           Return a callback for a "parse" fragment applied to "json_file".
           """

           def callback(previous_values):
               """Callback for the "parse" fragments."""
               # We can't do anything if the build failed
               if not previous_values.get("build"):
                   return False

               # Create a result for this specific test fragment
               result = TestResult(fragment_name, self.test_env)

               # Run the test program on the input JSON, capture its output
               with open(self.test_dir(json_file), "rb") as f:
                   output = subprocess.check_output(
                      ["./test_program"],
                      stdin=f,
                      stderr=subprocess.STDOUT
                   )

               # The test passes iff the output is as expected
               with open(self.test_dir(out_file), "rb") as f:
                   if f.read() == output:
                       result.set_status(TestStatus.PASS)
                   else:
                       result.set_status(TestStatus.FAIL, "unexpected output")

               # Test fragment is complete. Don't forget to register this
               # result. No fragment depends on this one, so no-one will use
               # the return value in a previous_values mapping. Yet, return
               # True as a good practice.
               self.push_result(result)
               return True

Note that this driver is not perfect: calls to ``subprocess.check_call`` and
``subprocess.check_output`` may raise exceptions, for instance in
``test_program.c`` is missing or has a syntax error, if its execution fails for
some reason. Opening the ``*.out`` files also assumes that the file is present.
In all these cases, an unhandled exception will be propagated. The testsuite
framework will catch these and create an ``ERROR`` test result to include the
error in the report, so errors will not go unnoticed (good), but the error
messages will not necessarily make debugging easy (not so good).

A better driver would catch manually likely exceptions, and create
``TestResult`` instances with useful information, such as the name of the
current step (``build`` or ``parse``) and the current input JSON file (if
applicable) so that testcase developpers have all the information they need to
understand errors when they occur.


Test fragment abortion
----------------------

During their execution, test fragment callbacks can raise
``e3.testsuite.TestAbort`` exceptions: if exception propagation reaches the
callback's caller, the test fragment execution will be silently discarded. This
implies no entry left in ``previous_values`` and, unless the callback already
pushed a result (``TestDriver.push_result``), there will be no track of this
fragment in the test report.

However, if a callback raises another type of uncaught exception, the testsuite
creates and pushes a test result with an ``ERROR`` status and with the
exception traceback in its log, so that this error appears in the testsuite
report.


.. _test_fragment_slot:

Test fragment slot
------------------

Each test fragment can be scheduled to run in parallel, up to the parallelism
level requested when running the testsuite: ``--jobs=N/-jN`` testsuite argument
creates ``N`` jobs to run fragments in parallel.

Some testsuites need to create special resources for testcases to run. For
instance, the testsuite for a graphical text editor running on GNU/Linux may
need to spawn ``Xvfb`` processes (X servers) in which the text editors will
run. If the testsuite can execute ``N`` multiple fragments in parallel, it
needs at least ``N`` simultaneously running servers since each text editor
requires the exclusive use of a server. In other words, two concurrent tests
cannot use the same server.

Make each test create its own server is possible, but starting and stopping a
server is costly. In order to satisfy the above requirement and keep the
overhead minimal, it would be nice to start exactly ``N`` servers at the
beginning of the testsuite (one per testsuite job): at any time, job ``J``
would be the only user of server ``J``, so there would be no conflict between
test fragments.

This is exactly the role of the ``slot`` argument in test fragments callback:
it is a job ID between 1 and the number ``N`` of testsuite jobs (included).
Test drivers can use it to handle shared resources avoiding conflicts.


Inter-test dependencies
-----------------------

This section presents how to create dependencies between fragments that don't
belong to the same tests. But first, a warning: the design of ``e3-testsuite``
is thought primarily for tests that are independent: tests not interacting so
that each test can be executed and not the others. Introducing inter-test
dependencies removes this restriction, which introduces a fair amount of
complexity:

* The execution of tests must be synchronized so that the one that depends on
  another one must run after it.

* There is likely logistic to take care of so that whatever justifies the
  dependency is carried from one test to the other.

* A test does not depend only on what is being tested, but may also depend on
  what other tests did, which may make tests more fragile and complicates
  failure analysis.

* When a user asks to run only one test, while this test happens to depend on
  another one, the testsuite needs to make sure that this other test is also
  run.

Most of the time, these drawbacks make inter-test dependencies inappropriate,
and thus better avoided. However there are cases where they are necessary. Real
world examples include:

* Writing an ``e3-testsuite`` based test harness to exercize existing
  inter-dependent testcases that cannot be modified. For instance, the `ACATS
  (Ada Conformity Assessment Test Suite) <http://www.ada-auth.org/acats.html>`_
  has some tests which write files and other tests that then read later on.

* External constraints require separate tests to host the validation of data
  produced in other tests. For instance a qualification testsuite (in the
  context of software certification) that needs a single test (say
  ``report-format-check``) to check that all the outputs of a qualified tool
  throughout the testsuite (say output of tests ``feature-A``, ``feature-B``,
  ...) respect a given constraint.

  Notice how, in this case, the outcome of such a test depends on how the
  testsuite is run: if ``report-format-check`` detects a problem in the output
  from ``feature-A`` but not in outputs from other tests, then
  ``report-format-check`` will pass or fail depending on the specific set of
  tests that the testsuite is requested to run.

With these pitfalls in mind, let's see how to create inter-test dependencies.
First, a bit of theory regarding the logistics of test fragments in the
testsuite:

The description of the :ref:`TestDriver.add_fragment method
<test_driver_add_fragment>` above mentionned a crucial data structure in the
testsuite: the DAG (Directed Acyclic Graph). This graph (an instance of
``e3.collections.dag.DAG``) contains the list of fragments to run as nodes and
the dependencies between these fragments as edges. The DAG is then is used to
schedule their execution: first execute fragments that have no dependencies,
then fragments that depend on these, etc.

Each node in this graph is a ``FragmentData`` instance, that the
``add_fragment`` method creates. This class has four fields:

* ``uid``, a string used as an identifier for this fragment that is unique in
  the whole DAG (it corresponds to the ``VertexID`` generic type in
  ``e3.collections.dag``). ``add_fragment`` automatically creates it from the
  driver's ``test_name`` field and ``add_fragment``'s own ``name`` argument.

* ``driver``, the test driver that created this fragment.

* ``name``, the ``name`` argument passed to ``add_fragment``.

* ``callback``, the ``fun`` argument passed to ``add_fragment``.

Our goal here is, once the DAG is populated with all the ``FragmentData`` to
run, to add dependencies between them to express scheduling constraints.
Overriding the ``Testsuite.adjust_dag_dependencies`` method allows this: this
method is called when the DAG was created and populated, and right before the
scheduling and starting the execution of fragments.

As as simplistic example, suppose that a testsuite has two kinds of drivers:
``ComputeNumberDriver`` and ``SumDriver``. Tests running with
``ComputeNumberDriver`` have no dependencies, while each test using
``SumDriver`` needs the result of all ``ComputeNumberDriver`` (i.e. depends on
all of them). Also assume that each driver creates only one fragment (more on
this later), then the following method overriding would do the job:

.. code-block:: python

     def adjust_dag_dependencies(self, dag: DAG) -> None:
         # Get the list of all fragments for...

         # ... ComputeNumberDriver
         comp_fragments = []

         # ... SumDriver
         sum_fragments = []

         # "dag.vertex_data" is a dict that maps fragment UIDs to FragmentData
         # instances.
         for fg in dag.vertex_data.values():
             if isinstance(fg.driver, ComputeNumberDriver):
                 comp_fragments.append(fg)
             elif isinstance(fg.driver, SumDriver):
                 sum_fragments.append(fg)

         # Pass the list of ComputeNumberDriver fragments to all SumDriver
         # instances and make sure SumDriver fragments run after all
         # ComputeNumberDriver ones.
         comp_uids = [fg.uid for fg in comp_fragments]
         for fg in sum_fragments:
             # This allows code in SumDriver to have access to all
             # ComputeNumberDriver fragments.
             fg.driver.comp_fragments = comp_fragments

             # This creates the scheduling constraint: the "fg" fragment must
             # run only after all "comp_uids" fragments have run.
             dag.update_vertex(vertex_id=fg.uid, predecessors=comp_uids)

Note the use of the ``DAG.update_vertex`` method rather than
``.set_predecessors``: the former adds predecessors (i.e. preserves existing
ones, that the ``TestDriver.add_fragment`` method already created) while the
latter would override them.

Some drivers create more than one fragment: for instance
``e3.testsuite.driver.BasicDriver`` creates a ``set_up`` fragment, a ``run``
one, a ``tear_down`` one and a ``analyze`` one, which each fragment having a
dependency on the previous one. To deal with them, ``adjust_dag_dependencies``
need to check the ``FragmentData.name`` field to get access to specific
fragments:

.. code-block:: python

   # Look for the "run" fragment from FooDriver tests
   if fg.name == "run" and isinstance(fg.driver, FooDriver):
      ...

   # FragmentData provides a helper to do this:
   if fg.matches(FooDriver, "run"):
      ...
