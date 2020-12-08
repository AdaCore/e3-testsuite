.. _api_diff:

``e3.testsuite.driver.diff``: Test driver for actual/expected outputs
=====================================================================

The ``driver.diff`` module defines ``DiffTestDriver``, a ``ClassicTestDriver``
subclass specialized for drivers whose analysis is based on output comparisons.
It also defines several helper classes to control more precisely the comparison
process.


Basic API
---------

The whole ``ClassicTestDriver`` API is available in ``DiffTestDriver``, and the
overriding requirements are the same:

* subclasses must override the ``run`` method;
* they can, if need be, override the ``set_up`` and ``tear_down`` methods.

Note however that unlike its parent class, it provides an actually useful
``compute_failures`` method override, which compares the test actual output and
the output baseline:

* The test actual output is what the ``self.output`` ``Log`` instance holds:
  this is where the ``analyze_output`` from the :ref:`shell method
  <api_classic_spawning_subprocesses>` matters.

* The output baseline, which we could also call the *test expected output*, is
  by default the content of the ``test.out`` file, in the test directory. As
  explained :ref:`below <api_diff_alternative_baselines>`, this defalut can be
  changed.

Thanks to this subclass, writing real world test drivers requires little code.
The following example just runs the ``my_program`` executable with arguments
provided in the ``test.yaml`` file, and checks that its status code is 0 and
that its output matches the content of the ``test.yaml`` file:

.. code-block:: python

   from e3.testsuite.driver.diff import DiffTestDriver


   class MyTestDriver(DiffTestDriver):
       def run(self):
           argv = self.test_env.get("argv", [])
           self.shell(["my_program"] + argv)


Output encodings
----------------

See :ref:`classic_output_encodings` for basic notions regarding string
encoding/decoding concerns in ``ClassicTestDriver`` and all its subclasses.

In binary mode (the ``default_encoding`` property returns ``binary``),
``self.output`` is initialized to contain a ``Log`` instance holding ``bytes``.
The ``shell`` method doesn't decode process outputs: they stay as ``bytes`` and
thus their concatenation to ``self.output`` is valid. In addition, the baseline
file (``test.out`` by default) is read in binary mode, so in the end,
``DiffTestDriver`` only deals with ``bytes`` instances.

Conversely, in text mode, ``self.output`` is a ``Log`` instance holding ``str``
objects, which the ``shell`` method extends with decoded process outputs, and
finally the baseline file is read in text mode, decoded using the same string
encoding.


Handling output variations
--------------------------

In some cases, program outputs can contain unpredictible parts. For instance,
the following script:

.. code-block:: python

   o = object()
   print(o)

Can have the following output:

.. code-block:: text

   $ python foo.py
   <object object at 0x7f15fbce1970>

... or the following:

.. code-block:: text

   $ python foo.py
   <object object at 0x7f4f9e031970>

Although it's theoretically possible to constrain the execution environment
enough to make the printed address constant, it is hardly practical. There can
be a lot of other sources of output variation: printing the current date,
timing information, etc.

``DiffTestDriver`` provides two alternative mechanisms to handle such cases:
match actual output against regular expressions, or refine outputs before
the comparison.


Regexp-based matching
*********************

Instead of providing a file that contains byte-per-byte or
codepoint-per-codepoint expected output, the baseline can be considered as a
regular expression. With this mechanism, the following ``test.out``:

.. code-block:: text

   <object object at 0x.*>

will match the output of the ``foo.py`` example script above. This relies on
Python's standard ``re`` module: please refer to `its documentation
<https://docs.python.org/3/library/re.html>`_ for the syntax reference and the
available regexp features.

In order to switch to regexp-matching on a per-testcase basis, just add the
following to the ``test.yaml`` file:

.. code-block:: yaml

   baseline_regexp: True


.. _api_diff_output_refining:

Output refining
***************

Another option to match varying outputs is to refine them, i.e. perform
substitutions to hide varying parts from the comparison. Applied to the
previous example, the goal is to refine such outputs:

.. code-block:: text

   <object object at 0x7f15fbce1970>

To a string such as following:

.. code-block:: text

   <object object at [HEX-ADDR]>

To achieve this goal, the ``driver.diff`` module defines the following abstract
class:

.. code-block:: python

   class OutputRefiner:
       def refine(self, output):
           raise NotImplementedError

Subclasses must override the ``refine`` method so that it takes the original
output (``output`` argument) and return the refined output. Note that depending
on the encoding, ``output`` can be either a string (``str`` instance) or binary
data (``bytes`` instance): in each case it must return an object that has the
same type as the ``output`` argument.

Several very common subclasses are available in ``driver.diff``:

``Substitute(substring, replacement="")``
   Replace a specific substring. For instance:

   .. code-block:: python

      # Just remove occurences of <foo>
      # (replace them with an empty string)
      Substitute("<foo>")

      # Replace occurences of <foo> with <bar>
      Substitute("<foo>", "<bar>")

``ReplacePath(path, replacement="")``
   Replace a specific filename: ``path`` itself, the corresponding absolute
   path or the corresponding Unix-style path.

``PatternSubstitute(pattern, replacements="")``
   Replace anything matching the ``pattern`` regular expression.

Using output refiners from ``DiffTestDriver`` instances is very easy: just
override the ``output_refiners`` property in subclasses to return a list of
``OutputRefiner`` to apply on actual outputs before comparing them with
baselines.

To complete the ``foo.py`` example above, thanks to the following overriding:

.. code-block:: python

   @property
   def output_refiners(self):
       return [PatternSubstitute("0x[0-9a-f]+", "[HEX-ADDR]")]

All refined outputs from ``foo.py`` would match the following baseline:

.. code-block:: text

   <object object at [HEX-ADDR]>

Note that even though refiners only apply to actual outputs by default, it is
possible to also apply them to baselines. To do this, override the
``refine_baseline`` property:

.. code-block:: python

   @property
   def refine_baseline(self):
       return True

This behavior is disabled by default because a very common refinment is to
remove occurences of the working directory from the test output. In that case,
baselines that contain the working directory (for instance
``/home/user/my-testsuite/tmp/my-test``) will be refined as expected with the
setup of the original testcase author, but will not on another setup (for
instance when the working directory is ``/tmp/testsuite-tmp-dir``).


.. _api_diff_alternative_baselines:

Alternative baselines
---------------------

``DiffTestDriver`` subclasses can override two properties in order to select
the baseline to use as well as the output matching mode (equality vs. regexp):

The ``baseline_file`` property must return a ``(filename, is_regexp)`` couple.
The first item is the name of the baseline file (relative to the test
directory), i.e. the file that contains the output baseline. The second one is
a boolean that determines whether to use the regexp matching mode (if true) or
the equality mode (if false).

If, for some reason (for instance: extracting the baseline is more involved
than just reading the content of a file) the above is not powerful enough, it
is possible instead to override the ``baseline`` property. In that case, the
``baseline_file`` property is ignored, and ``baseline`` must return a 3-element
tuple:

1. The absolute filename for the baseline file, if any, ``None`` otherwise.
   Only a present filename allows :ref:`baseline rewriting
   <api_diff_rewriting>`.
2. The baseline itself: a string in text mode, and a ``bytes`` instance in
   binary mode.
3. Whether the baseline is a regexp.


.. _api_diff_rewriting:

Automatic baseline rewriting
----------------------------

Often, test baselines depend on formatting rules that need to evolve over time.
For example, imagine a testsuite for a program that keeps track of daily
min/max temperatures. The following could be a plausible test baseline:

.. code-block:: text

   01/01/2020 260.3 273.1
   01/02/2020 269.2 273.2

At some point, it is decided to change the format for dates. All baselines need
to be rewritten, so the above must become:

.. code-block:: text

   2020-01-01 260.3 273.1
   2020-01-02 269.2 273.2

That implies manually rewriting the baselines of potentially a lot of tests.

``DiffTestDriver`` makes it possible to automatically rewrite baselines for
all tests based on equality (not regexps). Of course, this is disabled by
default: one needs to run it only when such pervasive output changes are
expected, and baseline updates need to be carefully reviewed afterwards.

Enabling this behavior is as simple as setting ``self.env.rewrite_baselines``
to True in the ``Testsuite`` instance. The APIs to use for this are properly
introduced later, in :ref:`api_testsuite`. Here is a short example, in the
meantime:

.. code-block:: python

   class MyTestsuite(Testsuite):

       # Add a command-line flag to the testsuite script to allow users to
       # trigger baseline rewriting.
       def add_options(self, parser):
           parser.add_argument(
               "--rewrite", action="store_true",
               help="Rewrite test baselines according to current outputs"
           )

       # Before running the testsuite, keep track in the environment of our
       # desire to rewrite baselines. DiffTestDriver instances will pick it up
       # automatically from there.
       def set_up(self):
           super(MyTestsuite, self).set_up()
           self.env.rewrite_baselines = self.main.args.rewrite

Note that baseline rewriting applies only to tests that are not already
expected to fail. Imagine for instance the situation described above (date
format change), and the following testcase:

.. code-block:: yaml

   # test.yaml
   control:
      - [XFAIL, "True",
         "Precision bug: max temperature is 280.1 while it should be 280.0"]

.. code-block:: text

   # test.out
   01/01/2020 270.3 280.1

The testsuite must not rewrite ``test.out``, otherwise the precision bug
(``280.1`` instead of ``280.0``) will be recorded in the baseline, and thus the
testcase will incorrectly start to pass (``XPASS``). But this is just a
compromise: in the future, the testcase will fail not only because of the lack
of precision, but also because of the bad date formatting, so in such cases,
baselines must be manually updated.
