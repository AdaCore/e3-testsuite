Computing code coverage inside a testsuite
==========================================

In order to look for missing tests, it is a common practice to compute the
coverage of tests on source code, i.e. to compute code coverage: parts of the
code that are executed while running tests are "covered", and the rest is
"uncovered", the goal being to add tests until all the source code is covered.

How exactly to compute code coverage highly depends on the programming language
its ecosystem used to develop the codebase on which one wants to compute code
coverage. Thanks to ``e3-testsuite``'s extension points, it is convenient to
compute code coverage reports directly in the testsuite scripts.

This section demonstrates how to achive this with a simple Ada program, using
`GNATcoverage <https://github.com/AdaCore/gnatcoverage>`_ as the underlying
technology for actual code coverage analysis.


Example program
---------------

First, let's create an Ada project for a `reverse Polish notation
<https://en.wikipedia.org/wiki/Reverse_Polish_notation>`_ evaluator:

.. code-block:: ada

   -- rpeval.gpr

   project Rpeval is
      for Main use ("rpeval.adb");
      for Object_Dir use "obj";
   end Rpeval;

.. code-block:: ada

   -- rpeval.adb

   with Ada.Command_Line;
   with Ada.Containers.Vectors;
   with Ada.Text_IO;

   procedure Rpeval is

      use type Ada.Containers.Count_Type;
      package Integer_Vectors is new
        Ada.Containers.Vectors (Positive, Integer);

      subtype Binary_Operator is Character
      with Static_Predicate =>
        Binary_Operator in '+' | '-' | '*' | '/';

      Stack          : Integer_Vectors.Vector;
      Number_Started : Boolean := False;
      Current_Number : Integer := 0;
      Digit_Value    : Integer;
      Left, Right    : Integer;
   begin
      for C of Ada.Command_Line.Argument (1) loop
         case C is
            when '0' .. '9' =>
               Digit_Value :=
                 Character'Pos (C)
                 - Character'Pos ('0');
               if Number_Started then
                  Current_Number :=
                    10 * Current_Number
                    + Digit_Value;
               else
                  Number_Started := True;
                  Current_Number := Digit_Value;
               end if;

            when ' ' | Binary_Operator =>
               if Number_Started then
                  Stack.Append (Current_Number);
                  Number_Started := False;
               end if;

               if C = ' ' then
                  goto Next;
               end if;

               if Stack.Length < 2 then
                  raise Program_Error
                    with "not enough operands";
               end if;
               Right := Stack.Last_Element;
               Stack.Delete_Last;
               Left := Stack.Last_Element;
               Stack.Delete_Last;
               case Binary_Operator (C) is
                  when '+' =>
                     Stack.Append (Left + Right);
                  when '-' =>
                     Stack.Append (Left - Right);
                  when '*' =>
                     Stack.Append (Left * Right);
                  when '/' =>
                     if Right = 0 then
                        raise Program_Error
                          with "division by zero";
                     end if;
                     Stack.Append (Left / Right);
               end case;

            when others =>
               raise Program_Error
                 with "syntax error";
         end case;

         <<Next>>
      end loop;

      if Number_Started then
         Stack.Append (Current_Number);
         Number_Started := False;
      end if;

      for Value of Stack loop
         Ada.Text_IO.Put_Line (Value'Image);
      end loop;
   end Rpeval;

This program takes a reverse Polish notation expression as its first command
line argument and prints the state of the evaluation stack once done:

.. code-block:: sh

   $ gprbuild -Prpeval.gpr -q
   $ obj/rpeval 1
    1
   $ obj/rpeval "1 2 +"
    3
   $ obj/rpeval "1 2 + 9"
    3
    9


Example testsuite
-----------------

Now that we have the codebase to test, let's write a testsuite to check that it
works as expected. First, the testsuite framework:

.. code-block:: python

   import os.path
   import subprocess
   import sys

   from e3.fs import mkdir
   import e3.testsuite
   from e3.testsuite.testcase_finder import ParsedTest, TestFinder
   from e3.testsuite.driver.diff import DiffTestDriver, PatternSubstitute
   import yaml


   class TestFinder(TestFinder):
       # Consider that all "*.yaml" files are tests
       def load(self, testsuite, dirpath, filename):
           abs_fn = os.path.join(dirpath, filename)
           with open(abs_fn) as f:
               return ParsedTest(
                   test_name=testsuite.test_name(abs_fn[:-5]),
                   driver_cls=RpevalDriver,
                   test_env=yaml.safe_load(f),
                   test_dir=dirpath,
               )

       def probe(self, testsuite, dirpath, dirnames, filenames):
           return [
               self.load(testsuite, dirpath, f)
               for f in filenames
               if f.endswith(".yaml")
           ]


   class RpevalDriver(DiffTestDriver):
       # Remove leading/trailing whitespaces and conflate consecutive ones into
       # single spaces.
       output_refiners = [
           PatternSubstitute("(^ *|[ \n]*$)", ""),
           PatternSubstitute("( [ ]+|\n)", " "),
       ]

       @property
       def baseline(self):
           return (None, str(self.test_env["output"]), False)

       def run(self):
           self.shell(["rpeval", str(self.test_env["input"])])


   class RpevalTestsuite(e3.testsuite.Testsuite):
       tests_subdir = "tests"
       test_finders = [TestFinder()]


   if __name__ == "__main__":
       sys.exit(RpevalTestsuite().testsuite_main())

And now the tests:

.. code-block:: yaml

   # tests/complex.yaml
   input: 1 2 3 * +
   output: 7

   # tests/div.yaml
   input: 10 2 /
   output: 5

   # tests/minus.yaml
   input: 9 4 -
   output: 5

   # tests/number.yaml
   input: 123
   output: 123

   # tests/plus.yaml
   input: 1 2 +
   output: 3

Make the ``rpeval`` executable available to the testsuite and then run it:

.. code-block:: sh

   export PATH="$PWD/obj:$PATH"
   $ python testsuite.py
   INFO     Found 5 tests
   INFO     PASS            plus
   INFO     PASS            minus
   INFO     PASS            complex
   INFO     PASS            div
   INFO     PASS            number
   INFO     Summary:
   _  PASS         5


Extending for code coverage
---------------------------

After these steps, we are ready to tackle code coverage. The base principle,
probably common to all code coverage technologies, is straightforward:

1. Each test produces one or several execution traces (i.e.  evidence that some
   parts of the code were executed).

2. Once all tests have completed, make the testsuite compute a coverage report
   using all execution traces.

In the case of GNATcoverage, there is another preliminary step: instrument the
Ada source code and build that:

.. code-block:: sh

   $ gnatcov instrument -Prpeval --level=stmt+decision
   $ gprbuild -Prpeval --src-subdirs=gnatcov-instr --implicit-with=gnatcov_rts

This is generally kept outside of the testsuite scripts, as it is common
practice for builds and tests to happen on separate setups/machines.

All that is left at this point is to extend the ``RpevalTestsuite`` class with
the following three methods:

.. code-block:: python

       def add_options(self, parser):
           # Add a command-line option to trigger code coverage computation: we
           # do not do it by default.
           parser.add_argument(
               "--coverage",
               action="store_true",
               help="Compute code coverage for rpeval.",
           )

       def set_up(self):
           if self.env.options.coverage:
               # Create a directory in which to store execution traces for
               # rpeval, then point the gnatcov coverage runtime to it. This
               # runtime takes care of creating unique trace filenames, so
               # tests can write trace files to the same directory in parallel.
               #
               # This directory is under the testsuite-wide working directory,
               # as it is not meant to be preserved once the testsuite run has
               # completed.
               self.env.traces_dir = os.path.join(self.working_dir, "_traces")
               mkdir(self.env.traces_dir)
               os.environ["GNATCOV_TRACE_FILE"] = self.env.traces_dir + "/"

               # Also create a directory to hold the coverage report. Put it
               # under the output directory, i.e. under the directory that
               # contains the testsuite report, as the coverage report is meant
               # to be preserved after the testsuite run has completed.
               self.env.coverage_dir = os.path.join(self.output_dir, "_coverage")
               mkdir(self.env.coverage_dir)

       def tear_down(self):
           if self.env.options.coverage:
               # Write a response file to list all trace files created during
               # test execution.
               traces_list = os.path.join(self.env.traces_dir, "traces.txt")
               with open(traces_list, "w") as f:
                   for filename in os.listdir(self.env.traces_dir):
                       if filename.endswith(".srctrace"):
                           print(
                               os.path.join(self.env.traces_dir, filename),
                               file=f,
                           )

               # Produce the coverage report
               subprocess.check_call(
                   [
                       "gnatcov",
                       "coverage",
                       "-Prpeval",
                       "--level=stmt+decision",
                       "--annotate=xcov+",
                       f"--output-dir={self.env.coverage_dir}",
                       f"@{traces_list}",
                   ]
               )

               # Print the coverage report on the console
               for filename in os.listdir(self.env.coverage_dir):
                   if filename.endswith(".xcov"):
                       with open(
                           os.path.join(self.env.coverage_dir, filename)
                       ) as f:
                           print(f.read())

It's show time:

.. code-block:: text

   $ python testsuite.py --coverage
   INFO     Found 5 tests
   [...]
   INFO     Summary:
     PASS         5
   [...]/rpeval.adb:
   83% of 48 lines covered
   92% statement coverage (35 out of 38)
   67% decision coverage (4 out of 6)

   Coverage level: stmt+decision
   [...]
     36 .:          when ' ' | Binary_Operator =>
     37 +:             if Number_Started then
     38 +:                Stack.Append (Current_Number);
     39 +:                Number_Started := False;
     40 .:             end if;
     41 .: 
     42 +:             if C = ' ' then
     43 +:                goto Next;
     44 .:             end if;
     45 .: 
     46 !:             if Stack.Length < 2 then
   decision "Stack.Len..." at 46:16 outcome TRUE never exercised
     47 -:                raise Program_Error
     48 -:                  with "not enough operands";
   statement "raise Pro..." at 47:16 not executed
     49 .:             end if;
   [...]
