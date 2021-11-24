Multiprocessing: leveraging many cores
======================================

In order to take advantage of multiple cores on the machine running a
testsuite, ``e3.testsuite`` can run several tests in parallel. By default, it
uses Python threads to achieve this, which is very simple to use both for the
implementation of ``e3.testsuite`` itself, but also for testsuite implementors.
It is also *usually* more efficient than using separate processes.

However there is a disadvantage to this, at least with the most common Python
implementation (CPython): beyond some level of parallelism, the contention on
CPython's GIL is too high to benefit from more processors. When we reach this
level, it is more interesting to use multiple processes to cancel the GIL
contention.

To work around this CPython caveat, ``e3.testsuite`` provides a non-default way
to run tests in separate processes and avoid multithreading completely, which
removes GIL contention and thus allows testsuites to run faster with many
cores.


Limitations
-----------

Compared to the multithreading model, running tests in separate processes adds
several constraints on the implementation of test drivers:

* First, all code involved in test driver execution (``TestDriver`` subclasses,
  and all the code called by them) must be importable from subprocesses:
  defined in a Python module, during its initialization.

  Note that this means that test drivers must not be defined in the
  ``__main__`` module, i.e. not in the Python executable script that runs the
  testsuite, but in separate modules. This is probably the most common gotcha:
  the meaning of ``__main__`` is different between the testsuite main script
  (for instance ``run_testsuite.py``) and the internal script that will only
  run the test driver (``e3-run-test-fragment``, built in ``e3.testsuite``).

* Test environments and results (i.e. all data exchanged between the testsuite
  main and the test drivers) must be compatible with Python's standard `pickle
  module
  <https://docs.python.org/3/library/pickle.html#what-can-be-pickled-and-unpickled>`_.

There are two additional limitations that affect only users of the :ref:`low
level test driver API <api_test_driver>`:

* Return value propagation between tests is disabled: the ``previous_values``
  argument in the fragment callback is always the empty dict. Conversely, the
  fragment callback return values are always ignored.

* Test driver instances are not shared between testsuite mains (when
  ``add_test`` is invoked) and each fragment: all live in separate processes
  and the test driver classes are re-instantiated in each process.


Enabling multiprocessing
------------------------

The first thing to do is to check that your testsuite works despite the
limitations described above. The most simple way to check this is to pass the
``--force-multiprocessing`` command line flag to the testsuite. As its name
implies, it forces the use of separate processes to run test fragments (no
matter the level of parallelism).

Once this works, in order to communicate to ``e3.testsuite`` that it can
automatically enable multiprocessing (this is done only when the parallelism
level is considered high enough for this strategy to run faster), you have to
override the ``Testsuite.multiprocessing_supported`` property so that it
returns ``True`` (it returns ``False`` by default).


Advanced control of multiprocessing
-----------------------------------

Some testsuites may have test driver code that does not work in multithreading
contexts (use of global variables, environment variables, and the like). For
such testsuites, multiprocessing is not necessarily useful for performance, but
is actually needed for correct execution.

These testsuites can override the ``Testsuite.compute_use_multiprocessing``
method to override the default automatic behavior (using multiprocessing
beyond some CPU cores threshold), and always enable it. Note that this will
make the ``--force-multiprocessing`` command line option useless.

Note that this possibility is a workaround for test driver code architectural
issues, and should not be considered as a proper way to deal with parallelism.
