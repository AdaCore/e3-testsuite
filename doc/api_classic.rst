.. _api_classic:

``e3.testsuite.driver.classic``: Common test driver facilities
==============================================================

The ``driver.classic`` module's main contribution is to provides a
``TestDriver`` convenience subclass: ``ClassicTestDriver``, that test driver
implementations are invited to derive from.

It starts with an assumption, considered to be common to most real world use
cases: testcases are atomic, meaning that the execution of each testcase is a
single chunk of work that produces a single test result. This assumption allows
to provide a simpler framework compared to the base ``TestDriver`` API, so that
test drivers are easier to write.

First, there is no need to create :ref:`fragments <test_fragments>` and handle
dependencies: the minimal requirement for ``ClassicTestDriver`` subclasses is
to define a ``run`` method. As you have probably guessed, its sole
responsibility is to proceed to testcase execution: build what needs to be
built, spawn subprocesses as needed, etc.


Working directory management
----------------------------

``ClassicTestDriver`` considers that most drivers will need to create the
temporary directories, and thus make it the default: before running the
testcase, this driver will copy the test directory to the working directory.
Subclasses can override this behavior overriding the ``copy_test_directory``
property. For instance, to disable this copy unconditionally:

.. code-block:: python

   class MyDriver(ClassicTestDriver):
       copy_test_directory = False

Alternatively, to disable it only if the ``test.yaml`` file contains a
``no-copy`` entry:

.. code-block:: python

   class MyDriver(ClassicTestDriver):
       @property
       def copy_test_directory(self):
           return not self.test_env.get("no-copy")


.. _classic_output_encodings:

Output encodings
----------------

Although the concept of "test output" is not precisely defined here,
``ClassicTestDriver`` has provisions for the very common pattern of drivers
that build a string (the test output) and that, once the test has run, analyze
of the content of this output determines whether the testcase passed or failed.
For this reason, the ``self.output`` attribute contains a ``Log`` instance (see
:ref:`result_log`).

Although drivers generally want to deal with actual strings (``str`` in
Python3, a valid sequence of Unicode codepoints), at the OS level, process
outputs are mere sequences of bytes (``bytes`` in Python3), i.e. binary data.
Such drivers need to decode the sequence of bytes into strings, and for that
they need to pick the appropriate *encoding* (UTF-8, ISO-8859-1, ...).

The ``default_encoding`` property returns the name of the default encoding used
to decode process outputs (as accepted by the ``str.encode()`` method:
``utf-8``, ``latin-1``, ...). If it returns ``binary``, outputs are not decoded
and ``self.output`` is set to a ``Log`` instance that holds bytes.

The default implementation for this property returns the ``encoding`` entry
from the ``self.test_env`` dict. If there is no such entry, it returns
``utf-8`` (the most commonly used encoding these days).


.. _api_classic_spawning_subprocesses:

Spawning subprocesses
---------------------

Spawning subprocesses is so common that this driver class provides a
convenience method to do it:

.. code-block:: python

   def shell(self, args, cwd=None, env=None, catch_error=True,
             analyze_output=True, timeout=None, encoding=None):

This will run a subprocess given a list of command-line arguments (``args``);
its standard input is redirected to ``/dev/null`` while both its standard
output/error streams are collected as a single stream. ``shell`` returns a
``ProcessResult`` instance once the subprocess exitted. ``ProcessResult`` is
just a holder for process information: its ``status`` attribute contains the
process exit code (an integer) while its ``out`` attribute contains the
captured output.

Note that the ``shell`` method also automatically appends a description of the
spawned subprocess (arguments, working directory, exit code, output) to the
:ref:`test result log <api_test_result_log>`.

Its other arguments give finer control over process execution:

``cwd``
   Without surprise for people familiar with process handling APIs: this
   argument controls the directory in which the subprocess is spawned. When
   left to ``None``, the processed is spawned in the working directory.

``env``
   Environment variables to pass to the subprocess. If left to ``None``, the
   subprocess inherit the Python interpreter's environment.

``catch_error``
   If true (the default), ``shell`` will check the exit status: if it is 0,
   nothing happen, however if it is anything else, ``shell`` raises an
   exception to abort the testcase with a failure (see
   :ref:`classic_exceptions` for more details). If set to false, nothing
   special happens for non-0 exit statuses.

``analyze_output``
   Whether to append the subprocess output to ``self.output`` (see
   :ref:`classic_output_encodings`). This is for convenience in test drivers
   based on output comparison (see :ref:`api_diff`).

``timeout``
   Number of seconds to allow for the subprocess execution: if it lasts longer,
   the subprocess is aborted and its status code is set to non-zero.

   If left to ``None``, use instead the timeout that the
   ``default_process_timeout`` property returns. The ``ClassicTestDriver``
   implementation for that property returns either the ``timeout`` entry from
   ``self.test_env`` (if present) or 300 seconds (5 minutes). Of course,
   subclasses are free to override this property if needed.

``encoding``
   Name of the encoding used to decode the subprocess output. If left to
   ``None``, use instead the encoding that the ``default_encoding`` property
   returns (see :ref:`classic_output_encodings`). Here, too, the default
   implementation returns the ``encoding`` entry from ``self.test_env`` (if
   present) or ``utf-8``. Again, subclasses are free to override this property
   if needed.

``truncate_logs_threshold``
   Natural number, threshold to truncate the subprocess output that ``shell``
   logs in the :ref:`test result log <api_test_result_log>`.  This threshold is
   interpreted as half the number of output lines allowed before truncation,
   and 0 means that truncation is disabled. If left to ``None``, use the
   testsuite's ``--truncate-logs`` option.


Set up/analyze/tear down
------------------------

The common organization for test driver execution has four parts:

1. Initialization: make sure input is valid: required files must be present
   (test program sources, input files), metadata is valid, start a server, and
   so on.
2. Execution: the meat happens here: run the necessary programs, write the
   necessary files, ...
3. Analysis: look at the test output and decide whether the test passed.
4. Finalization: free resources, shut down the server, ..

``ClassicTestDriver`` defines four overridable methods, one for each step:
``set_up``, ``run``, ``analyze`` and ``tear_down``. First, the ``set_up``
method is called, then the ``run`` one and then the ``analyze`` one. So far,
any unhandled exception in these methods would prevent the next ones to run.
Except for the ``tear_down`` method, which is called no matter what happens as
long as the ``set_up`` method was called.

The following example shows how this is useful. Imagine a testsuite for a
database server.  We want some test drivers only to start the server (leaving
the rest to testcases) while we want other test drivers to perform more
involved server initialization.

.. code-block:: python

   class BaseDriver(ClassicTestDriver):
       def set_up(self):
           super().set_up()
           self.start_server()

       def run(self):
           pass  # ...

       def tear_down(self):
           self.stop_server()
           super().tear_down()

   class FixturesDriver(BaseDriver):
       def set_up(self):
           super(FixturesDriver, self).set_up()
           self.install_fixtures()

The ``install_fixtures()`` call has to happen after the ``start_server()`` one,
but before the actual test execution (``run()``). If initialization, execution
and finalization all happened in ``BaseDriver.run``, it would not be possible
for ``FixturesDriver`` to insert the call at the proper place.

Note that ``ClassicTestDriver`` provide valid default implementations for all
these methods except ``run``, which subclasses have to override.

The ``analyze`` method is interesting: its default implementation calls the
``compute_failures`` method, which returns a list of error messages. If that
list is empty, it considers that there is no test failure, and thus that the
testcase passed. Otherwise, it considers that the test failed. In both cases,
it appropriately set the status/message in ``self.result`` and pushes it to the
testsuite report.

That means that in practice, test drivers only need to override this
``compute_failures`` method in order to properly analyze test output. For
instance, let's consider a test driver whose ``run`` method spawns a supbrocess
and must consider that the test succeeds iff the ``SUCCESS`` string appears in
the output. The following would do the job:

.. code-block:: python

   class FooDriver(ClassicTestDriver):
       def run(self):
           self.shell(...)

       def compute_failures(self):
           return (["no match for SUCCESS in output"]
                   if "SUCCESS" not in self.output
                   else [])


Metadata-based execution control
--------------------------------

Deciding whether to skip a testcase, or expecting a test failure are both so
common that ``ClassicTestDriver`` provides a mechanism which makes it possible
to control testcase execution thanks to metadata in that testcase.

By default, it is based on metadata from the test environment
(``self.test_env``, i.e. from the ``test.yaml`` file), but each driver can
customize this. This mechanism is described extensively in :ref:`api_control`.


.. _classic_exceptions:

Exception-based execution control
---------------------------------

The ``e3.testsuite.driver.classic`` module defines several exceptions that
``ClassicTestDriver`` subclasses can use to control the execution of testcases.
These exceptions are expected to be propagated from the ``set_up``, ``run`` and
``analyze`` methods when appropriate. When they are, this stops the execution
of the testcase (next methods are not run). Please refer to
:ref:`api_test_status` for the meaning of test statuses.

``TestSkip``
   Abort the testcase and push a ``SKIP`` test result.

``TestAbortWithError``
   Abort the testcase and push an ``ERROR`` test result.

``TestAbortWithFailure``
   Abort the testcase and push a ``FAIL`` test result, or ``XFAIL`` if a
   failure is expected (see :ref:`api_control`).


Colors
------

Long raw text logs can be difficult to read quickly. Light formatting (color,
brightness) can help in this area, revealing the structure of text logs. Since
it relies on the ``e3-core`` project, ``e3-testsuite`` already has the
`colorama <https://pypi.org/project/colorama/>`_ project in its dependencies.

``ClassicTestDriver`` subclasses can use ``self.Fore`` and ``self.Style``
attributes as "smart" shortcuts for ``colorama.Fore`` and ``colorama.Style``:
if there is a single chance for text logs to be redirected to a text file
(rather than everything to be printed in consoles), colors support is disable
and these two attributes yield empty strings instead of the regular console
escape sequences.

The ``shell`` method already uses them to format the logging of subprocesses in
``self.result.log``:

.. code-block:: python

   self.result.log += (
       self.Style.RESET_ALL + self.Style.BRIGHT
       + "Status code" + self.Style.RESET_ALL
       + ": " + self.Style.DIM + str(p.status) + self.Style.RESET_ALL
   )

This will format ``Status code`` in bright style and the status code in dim
style if formatting is enabled, and will just return ``Status code: 0```
without formatting when disabled.


Test fragment slot
------------------

Even though each testcase using a ``ClassicTestDriver`` subclass has a single
test fragment, it can be useful for drivers to know which :ref:`slot
<test_fragment_slot>` they are being run on. The slot is available in the
``self.slot`` driver attribute.
