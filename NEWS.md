23.1 (Not released yet)
=======================

* Accept invalid regexps as testcase filters
* Make DiffTestDriver add a DIFF failure reason (useful for advanced viewers)
* Switch to more common statuses in the GAIA output (--gaia-output: OK instead
  of PASSED, XFAIL instead of XFAILED, ...)
* Do not rewrite baselines for tests with expected failures.

23.0 (2020-06-04)
=================

* Small revamp of the current API (rename properties).
* Rework the list of test status.
* Rework and specify the structure of test results.
* Add mechanisms to control testcase discovery and execution.
* Add new general purpose drivers: classic and diff.
* Add compatibility layers for legacy AdaCore testsuites.
* Add a developer-friendly testsuite mode (--dev-temp/-d).
* Add a --failure-exit-code option, useful in continuous integration scripts.
* Add a detailed documentation.

22.0.0 (2020-03-13)
===================

* Complete switch to Python3 (3.7+). Python2 is not supported anymore.
