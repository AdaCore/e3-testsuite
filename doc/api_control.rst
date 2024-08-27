.. _api_control:

``e3.testsuite.control``: Control test execution
================================================

Expecting all testcases in a testsuite to run and pass is not always realistic.
There are two reasons for this.

Some tests may exercize features that make sense only on a specific OS: imagine
for instance a "Windows registry edit" feature, which would make no sense on
GNU/Linux or MacOS systems. It makes no sense to even run such tests when not
in the appropriate environment.

In parallel: even though our ideal is to have perfect software, real world
programs have many bugs. Some are easy to fix, but some are so hard that they
can take days, months or even *years* to resolve. Creating testcases for bugs
that are not fixed yet makes sense: such tests allow to keep track of "known"
bugs, in particular when they unexpectedly pass whereas the bug is already
supposed to be around. Running such tests has value, but clutters the testsuite
reports, potentially hiding unexpected failures in the middle of many known
ones.

For the former, it is appropriate to create SKIP test results (you can read
more about test statuses in :ref:`api_test_status`). The latter is
the raison d'être of the PASS/XPASS and FAIL/XFAIL distinctions: in theory all
results should be PASS or XFAIL, so when looking for regressions after a
software update, one only needs to look at XPASS and FAIL statuses.


Basic API
---------

The need to control whether to execute testcases and how to "transform" its
test status (PASS to XPASS, FAIL to XFAIL) is so common that ``e3-testsuite``
provides an abstraction for that: the ``TestControl`` class and the
``TestControlCreator`` interface.

Note that even though this API was initially created as a helper for
:ref:`ClassicTestDriver <api_classic>`, it is designed separately so that it
can be reused in other drivers.

``TestControl`` is just a data structure to hold the decision regarding test
control:

* the ``skip`` attribute is a boolean, specifying whether to skip the test;
* the ``xfail`` attribute is a boolean, telling whether a failure is expected
* the ``message`` attribute is an optional string: a message to convey the
  reason behind this decision.

The goal is to have one ``TestControl`` instance per test result to create.

``TestControlCreator`` instances allow test drivers to instantiate
``TestControl`` once per test result: their ``create`` method takes a test
driver and must return a ``TestControl`` instance.

The integration of this API in ``ClassicTestDriver`` is simple:

* In test driver subclasses, override the ``test_control_creator`` property to
  return a ``TestControlCreator`` instance.

* When the test is about to be executed, ``ClassicTestDriver`` will use this
  instance to get a ``TestControl`` object.

* Based on this object, the test will be skipped (creating a SKIP test
  result) or executed normally, and PASS/FAIL test result will be turned into
  XPASS/XFAIL if this object states that a failure is expected.

There is a control mechanism set up by default: the
``ClassicTestDriver.test_control_creator`` property returns a
``YAMLTestControlCreator`` instance.


.. _api_control_yaml:

``YAMLTestControlCreator``
--------------------------

This object creates ``TestControl`` instances from test environment
(``self.test_env`` in test driver instances), i.e. from the ``test.yaml`` file
in most cases (the :ref:`api_testcase_finder` later section describes when it's
not). The idea is very simple: let each testcase specify when to skip
execution/expect a failure depending on the environment (host OS, testsuite
options, etc.).

To achieve this, several "verbs" are available:

``NONE``
   Just run the testcase the regular way. This is the default.

``SKIP``
   Do not run the testcase and create a SKIP test result.

``XFAIL``
   Run the testcase the regular way, expecting a failure: if the test passes,
   emit a XPASS test result, emit a XFAIL one otherwise.

Testcases can then put metadata in their ``test.yaml``:

.. code-block:: yaml

   driver: my_driver
   control:
   - [SKIP, "env.build.os != 'Windows'", "Tests a Windows-specific feature"]
   - [XFAIL, "True", "See bug #1234"]

The ``control`` entry must contain a list of entries. Each entry contains a
verb, a Python boolean expression, and an optional message. The entries are
processed in order: only the first for which the boolean expression returns
true is considered. The verb and the message determine how to create the
``TestControl`` object.

But where does the ``env`` variable comes from in the example above? When
evaluating a boolean expression, ``YAMLTestCreator`` passes it variables
corresponding to the ``condition_env`` argument constructor argument, plus the
testsuite environment (``self.env`` in test drivers) as ``env``. Please refer
to the `e3.env documentation
<https://e3-core.readthedocs.io/en/latest/autoapi/env/index.html>`_
to know more about environments, which are instances of the ``AbstractBaseEnv``
subclasses.

.. code-block:: python

   tcc = YAMLTestControlCreator({"mode": "debug", "cpus": 8})

   # Condition expressions in driver.test_env["control"] will have access to
   # three variables: mode (containing the "debug" string), cpus (containing
   # the 8 integer) and env.
   tcc.create(driver)

``ClassicTestDriver.test_control_creator`` instantiates
``YAMLTestControlCreator`` with an empty condition environment, so by default,
only ``env`` is available.

With the example above, a ``YAMLTestControlCreator`` instance will create:

* ``TestControl("Tests a Windows-specific feature", skip=True, xfail=False)``
  on every OS but Windows;
* ``TestControl("See bug #1234", skip=False, xfail=True)``
  on Windows.
