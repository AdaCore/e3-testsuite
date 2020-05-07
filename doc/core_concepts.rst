.. _core_concepts:

Core concepts
=============

Testsuite organization
----------------------

All testsuites based on ``e3-testsuite`` have the same organization. On one
side, a set of Python scripts use classes from the ``e3.testsuite`` package
tree to implement a *testsuite framework*, and provide an entry point to launch
the testsuite. On the other side, a set of *testcases* will be run by the
testsuite.

By default, the testsuite framework assumes that every testcase is materialized
as a directory that contains a ``test.yaml`` file, and that all testcases can
be arbitrarily organized in a directory tree. However, this is just a default:
the testcase format is completely customizeable.


Test results
------------

During execution, each testcase can produce one or several *test results*. A
test result contains a mandatory status (PASS, FAIL, XFAIL, ...) to determine
if the test succeeded, failed, was skipped, failed in an expected way, etc. It
can also contain optional metadata to provide details about the testcase
execution: output, logs, timing information, and so on.


Test drivers
------------

It is very common for testsuites to have lots of very similar testcases. For
instance, imagine a testsuite to validate a compiler:

* Some testcases will do unit testing: they build and execute special programs
  (for instance: ``unittest.c``) which use the compiler as a library, expecting
  these program not to crash.

* All other testcases come with a set of source files (say ``*.foo`` source
  files), on which the compiler will run:

  * Some testcases will check the enforcement of language legality rules: they
    will run the compiler and check the presence of errors.

  * Some testcases will check code generation: they will run the compiler to
    produce an executable, then run the executable and check its output.

  * Some testcases will check the generation of debug info: they will run the
    compiler with special options and then check the produced debug info.

There are two strategies to implement this scheme. One can create a "library"
that contain helpers to run the compiler, extract error messages from the
output, etc. and put in each testcase a script (for instance ``test.py``)
calling these helpers to implement the checking. For "legality rules
enforcement" tests, this could give for instance:

.. code-block:: python

   # test.py
   from support import run_compiler
   result = run_compiler("my_unit.foo")
   assert result.errors == ["my_unit.foo:2:5: syntax error"]

.. code-block:: text

   # my_unit.foo
   # Syntax error ahead:
   bar(|

An alternative strategy is to create "test macros" which, once provided
testcase data, run the desired scenario: one macro would take care of unit
testing, another would check legality rules enforcement, etc. This removes the
need for redundant testing code in all testcases.

``e3-testsuite`` uses the latter strategy: "test macros" are called *test
drivers*, and by default the entry point for a testcase is the ``test.yaml``
file. The above example looks instead like the following:

.. code-block:: yaml

   # test.yaml
   driver: legality-rules
   errors:
      - "my_unit.foo:2:5: syntax error"

.. code-block:: text

   # my_unit.foo
   # Syntax error ahead:
   bar(|

Note that when testcases are just too different, so that creating one or
several test drivers does not make sense, there is still the option of creating
a "generic" test drivers that only runs a testcase-provided script.

To summarize: think of test drivers as programs that run on testcase data and
produce a test result to describe testcase execution. All testcases need a test
driver to run.
