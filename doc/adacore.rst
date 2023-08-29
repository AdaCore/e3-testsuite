Compatibility for AdaCore's legacy testsuites
=============================================

Although all the default behaviors in ``e3.testsuite`` presented in this
documentation should be fine for most new projects, it is not realistic to
require existing big testsuites to migrate to them. A lot of testsuites at
AdaCore use similar formalisms (atomic testcases, dedicated test directories,
...), but different formats: no ``test.yaml`` file, custom files for test
execution control, etc.

These testsuites contain a huge number of testcases, and thus it is a better
investment of time to introduce compatible settings in testsuite scripts rather
than reformat all testcases. This section presents compatibility helpers for
legacy AdaCore testsuites.



Test finder
-----------

The ``e3.testsuite.testcase_finder.AdaCoreLegacyTestFinder`` class can act as a
drop-in test finder for legacy AdaCore testsuites: all directories whose name
matches a TN (Ticket Number), i.e. matching the
``[0-9A-Z]{2}[0-9]{2}-[A-Z0-9]{3}`` regular expression, are considered as
containing a testcase. Legacy AdaCore testsuites have only one driver, so this
test finder always use the same driver. For instance:

.. code-block:: python

   @property
   def test_finders(self):
       # This will create a testcase for all directories whose name matches a
       # TN, using the MyDriver test driver.
       return [AdaCoreLegacyTestFinder(MyDriver)]


Test control
------------

AdaCore legacy testsuites rely on a custom file format to lead testcase
execution control: ``test.opt`` files.

Similarly to the :ref:`YAML-based control descriptions <api_control_yaml>`,
this format provides a declarative formalism to describe settings depending on
the environment, and more precisely on a set of *discriminants* ("the
configuration"): simple case insensitive names for environment specificities.
For instance: ``linux`` on a Linux system, ``windows`` on a Windows one,
``x86`` on Intel 32 bits architecture, ``vxworks`` when targetting a VxWorks is
involved, etc. The set of discriminants for a given testsuite run is stored in
testsuite reports, and visible in GAIA's ``Discriminants`` testsuite report
section.

A parser for such files is included in ``e3.testsuite`` (see the
``optfileparser`` module), and most importantly, a ``TestControlCreator``
subclass binds it to the rest of the testsuite framework:
``AdaCoreLegacyTestControlCreator``, from the ``e3.testsuite.control`` module.
Its constructor requires the list of discriminants used to selectively evaluate
``test.opt`` directives. The ``e3.env.Env`` class provides a `discriminants
<https://e3-core.readthedocs.io/en/latest/autoapi/e3/env/index.html#e3.env.AbstractBaseEnv.discriminants>`_
method to compute a basic set of discriminants based on the current context
(build/host/target platforms, ...), then testsuites are free to add more
discriminants as they see fit.

This file format not only controls test execution with its ``DEAD``, ``XFAIL``
and ``SKIP`` commands: it also allows to control the name of the script file to
run (``CMD`` command), the name of the output baseline file (``OUT``), the time
limit for the script (``RLIMIT``), etc. For this reason,
``AdaCoreLegacyTestControlCreator`` works best with the AdaCore legacy test
driver: see the next section.


Test driver
-----------

All legacy AdaCore testsuites use actual/expected test output comparisons to
determine if a test passes, so the reference test driver for them derives from
``DiffTestDriver``: ``e3.testsuite.driver.adacore.AdaCoreLegacyTestDriver``.
This driver is coupled with a custom test execution control mechanism:
``test.opt`` files (see the previous section), and thus overrides the
``test_control_creator`` property accordingly.

This driver has two requirements for ``Testsuite`` subclasses using it:

* Put a process environment (string dictionary) for subprocesses in
  ``self.env.test_environ``. By default they can just put a copy of the
  testsuite's own environment: ``dict(os.environ)``.

* Put the list of discriminants (list of strings) in ``self.env.discs``.
  For the latter, starting from the result of the
  ``e3.env.AbstractEnv.discriminants`` property can help, as it computes
  standard discriminants based on the current host/build/target platforms.
  Testsuites can then add more discriminants as needed.

For instance, imagine a testsuite that wants standard dircriminants plus the
``valgrind`` discriminant if the ``--valgrind`` command-line option is passed
to the testsuite:

.. code-block:: python

   class MyTestsuite(Testsuite):
       def add_options(self, parser):
           parser.add_argument("--valgrind", action="store_true",
                               help="Run tests under Valgrind")

       def set_up(self):
           super(MyTestsuite, self).set_up()
           self.env.test_environ = dict(os.environ)
           self.env.discs = self.env.discriminants
           if self.env.options.valgrind:
               self.env.discs.append("valgrind")

There is little point describing precisely the convoluted behavior for this
driver, so we will stick here to a summary, with a few pointers to go further:

* All testcases must provide a script to run. Depending on testsuite defaults
  (``AdaCoreLegacyTestControlCreator.default_script`` property) and the content
  of each ``test.opt`` testcase file, this script can be a Windows batch script
  (``*.cmd``), a Bourne-compatible shell script (``*.sh``) or a Python script
  (``*.py``).

* It is the output of this script that is compared against the output baseline.
  To hide environment-specific differences, output refiners turn backslashes
  into forward slashes, remove ``.exe`` extensions and also remove occurences
  of the working directory.

* On Unix systems, this driver has a very crude conversion of Windows batch
  script to Bourne-compatible scripts: text substitution remove some ``.exe``
  extensions, replaces ``%VAR%`` environment variable references with ``$VAR``,
  etc. See ``AdaCoreLegacyTestDriver.get_script_command_line``. Note that
  subclasses can override this method to automatically generate a test script.

Curious readers are invited to read the sources to know the details: doing so
is necessary anyway to override specific behaviors so that this driver fits the
precise need of some testsuite. Hopefully, this documentation and inline
comments have made this process easier.


``test.opt`` syntax
-------------------

The ``test.opt`` syntax allows users to add Ada-style comments anywhere in the
``test.opt`` file. When ``--`` is encountered every character until the next
line break will be ignored.

The ``test.opt`` grammar is the following:

.. code-block:: text

   testopt   : testopt line
             |         line
             ;
   line      : flag_list ASCII.LF
             | flag_list command ASCII.LF
             | flag_list command argument ASCII.LF
             | ASCII.LF
             ;
   flag_list : flag_list ',' expr   /* no space is allowed between flags */
             | expr
   expr      : !FLAG | FLAG
   command   : CMD|OUT|DEAD|REQUIRED|XFAIL|SKIP|RLIMIT

Basically, each line of a ``test.opt`` file is composed of three fields
separated by white spaces (the number of white spaces between each fields is
not fixed):

* The first field is either a single flag or a list of flags separated by
  commas (without spaces between them). Flags can prefixed by a ``!`` which
  behave as a boolean ``NOT``.

* The second field is the command.

* The last is the argument of the command. Notice that the argument can contain
  spaces as the parser will take every character from the end of the command
  field up to the next newline (or comment). Notice that the ``test.opt``
  parser is case insensitive.


``test.opt`` semantics
----------------------

For each line in the ``test.opt`` file, the ``test.opt`` parser/interpreter
compares the list of flags on the line to those defined for the current
configuration. If all flags on the current line belong to the list of
configuration flags (or absent from it in the case of an exclamation sign in
front of the flag) then the line is taken into account. When this occurs, all
subsequent lines with the same command type (``CMD``, ``OUT``, ..) are ignored,
except if the current line only contains the ``ALL`` flag.

Here is an example:

.. code-block:: text

   Linux         CMD linux.cmd
   Linux,PowerPC CMD linuxppc.cmd
   ALL           CMD default.cmd
   AIX           CMD aix.cmd

Depending on the configuration the following lines will be matched:

* ``Linux,x86``: first line matches.
* ``Linux,PowerPC``: first line matches. If you want the second line to match
  as well, then you need to swap first and second line of the ``test.opt``.
* ``AIX,PowerPC``: last line matches.
* ``VMS,Alpha``: third line matches.

Each type of command is handled independently except for the ``DEAD`` command.
When a given configuration matches a line with the ``DEAD`` command, the
``DEAD`` command will be taken into account only if the current configuration
does not match any line with another type of command.

If a line containing no command is matched, the main effect is to disable
subsequent ``DEAD`` commands.


``test.opt`` commands manual
----------------------------

``CMD``
  On Microsoft Windows systems, the default script file is ``test.cmd`` (and
  ``test.sh`` if ``test.cmd`` does not exist). Note that ``test.cmd`` is
  processed by the Windows command interpreter. On other systems the default
  script file is ``test.sh`` (and ``test.cmd`` if ``test.sh`` does not exist).
  If you want to override the default, use ``CMD``. In this case the third
  field will be the filename of the script to be used. Note that when you
  override the defaults, if the script has a ``.sh`` extension then ``sh`` will
  be used. Otherwise, the default system shell is used (``cmd`` on Windows,
  ``sh`` on Unixes).

``OUT``
  By default, when a test is executed, its output is compared to a file called
  ``test.out``. If the contents are the same then the test is marked as passed.
  If there is no ``test.out`` then a null output is expected from the test. In
  order to override this default you can use ``OUT`` command and set the third
  argument to a file that contains the expected output. Notice that even if the
  output differs between two platforms, you can often use the same ``test.out``
  for both. Indeed test drivers often perform some filtering/processing of both
  the output and the ``test.out`` file in order to remove differences like
  ``/`` and ``\`` in paths.

``DEAD``
  Do not run this test on the specified configuration, with the aforementioned
  provision about the interaction with other commands. If it is honored, the
  status of the test will be ``SKIPPED`` (``DEAD`` on GAIA); in this case, if a
  third field is specified, it will be added as a comment to the report.

  Example:

  .. code-block:: text

     AIX DEAD this feature is not supported on AIX

``REQUIRED``
  Do not run a test if the current configuration does not contain the specified
  discriminant. The ``REQUIRED`` command is a variant of the ``DEAD`` command.
  Its main difference is that it cannot be cancelled by other matching lines.
  Currently it's mainly used in the GPRbuild testsuite in order to simplify the
  ``test.opt``:

  .. code-block:: text

     Ada,C REQUIRED
     Linux test-linux.cmd
     Aix   DEAD

  In this example, running the testcase requires at least Ada and C
  discriminants to be present. Other lines are not considered if not.

``XFAIL``
  Expect a test failure on specified target. The mandatory third field is the
  comment explaining why we expect a failure for this test.

  Example:

  .. code-block:: text

     IA64 XFAIL currently this test is failing on IA64

  If the test fails for the specified target(s) the status will be ``XFAIL``.
  If the test passes then its status will be ``XPASS`` (for unexpected passed,
  ``UOK`` on GAIA).

  ``XFAIL`` should be used instead of ``DEAD`` if we intend to make the test
  pass on this configuration someday.

``SKIP``
  Expect a test failure on specified target. The difference with the ``XFAIL``
  command is that there is no attempt to run the test. This is useful for tests
  that are for example affecting machine stability, or for tests that sometimes
  pass "by accident". As for the ``XFAIL`` command, the test is marked as
  ``XFAIL`` with an annotation added to the comment signaling that the test has
  not been run. As for the ``XFAIL`` command the mandatory third field is a
  short comment explaining why we expect the failure.

``RLIMIT <duration in seconds>``
  Override the default time limit (780s) for this test on the specified
  configuration (as passed to e3's ``rlimit`` program).

<empty>
  Do run this test on specified target if not already explicitly cancelled. This
  is not a command; in particular, it will not override a previous ``DEAD`` command
  that is explicitly matched (i.e. a non-``ALL`` ``DEAD`` command). But it will
  override a previous ``ALL DEAD`` command, as well as disable all subsequent
  ``DEAD`` commands that would have otherwise matched.


``test.opt`` important advice
-----------------------------

When you need to create a ``test.opt`` file, you should think twice when
choosing the characteristic(s) that will be used to make the distinction
between two configurations. Here are two examples:

First let's say that a new functionality is available only on Linux and
Windows. The more evident ``test.opt`` will be:

.. code-block:: text

   ALL   DEAD
   NT
   Linux

This approach is **very bad**. Indeed when the functionality is added on more
exotic platforms, the test won't be executed... except if the famous "someone"
updates all the tests related to that functionality. The good approach in this
is to open an issue and ask testsuite maintainers maintainers to add a new tag
that describes this functionality:

.. code-block:: text

   ALL                   DEAD
   great-functionality

This way when the functionality is implemented on a new platform, the test will
be automatically activated.

The second advice concerns differences between versions of GCC. For example
assume we have currently the default output for GCC 3.4.x builds and we
introduce the builds for GCC 4.1.x. If the test output differs it's better to
write the ``test.opt`` this way:

.. code-block:: text

   GCC34 OUT test_gcc34.out

Than this way:

.. code-block:: text

   GCC41 OUT test_gcc41.out

Indeed if you introduce afterward the builds for GCC 4.2.x, there is more
chance that the new output match the GCC 4.1.x one than the GCC 3.4.x one. So
when there is a difference trigerred by different GCC versions, use the last
GCC version as the default.


Testing a test.opt file
-----------------------

In order to test a ``test.opt`` file you can use the following script provided
by ``e3-testsuite``:

.. code-block:: sh

   $ cat test.opt
   Linux         CMD linux.cmd
   Linux,PowerPC CMD linuxppc.cmd
   ALL           CMD default.cmd
   AIX           CMD aix.cmd
   $ e3-opt-parser ALL,Linux ./test.opt
   cmd="linux.cmd"
   $ e3-opt-parser ALL,AIX ./test.opt
   cmd="aix.cmd"
