23.1 (Not released yet)
=======================

* `ClassicTestDriver`: make `tear_down` delete the working directory by
  default.
* `DiffTestDriver`: fix handling of encodings to read/write baselines.
* `e3-find-skipped-tests`: new script to look for always skipped tests.
* `e3-testsuite-report`: new script to display results on the terminal.
* Enable the display of error outputs (`-E/--show-error-output`) by default on
  TTYs.
* `AdaCoreLegacyTestDriver` enhance support for generated test scripts.
* Add a lightweight report index.
* `DiffTestDriver`: do not run output refiners on baselines.
* Add the `--show-time-info` command-line option.
* Add support for the `--max-consecutive-failures` command-line option.
* Follow symbolic links to find testcases.
* Force the use of UTF-8 for GAIA reports.
* Fix `ReplacePath` to work on Windows.
* `AdaCoreLegacyTestDriver`: when rewriting empty baselines with
  default file (`test.out`), just remove the baseline file.
* `driver.diff.PathSubstitute: use `realpath` rather than `abspath`.
* Fix CRLF handling when truncating too long logs.
* `AdaCoreLegacyTestDriver`: use Bash as soon as we have a Bourne shell script.
* Accept invalid regexps as testcase filters.
* Make `DiffTestDriver` add a `DIFF` failure reason (useful for advanced
  viewers).
* Switch to more common statuses in the GAIA output (`--gaia-output`: OK
  instead of `PASSED`, `XFAIL` instead of `XFAILED`, ...).
* Do not rewrite baselines for tests with expected failures.

23.0 (2020-06-04)
=================

* Small revamp of the current API (rename properties).
* Rework the list of test status.
* Rework and specify the structure of test results.
* Add mechanisms to control testcase discovery and execution.
* Add new general purpose drivers: classic and diff.
* Add compatibility layers for legacy AdaCore testsuites.
* Add a developer-friendly testsuite mode (`--dev-temp`/`-d`).
* Add a `--failure-exit-code` option, useful in continuous integration scripts.
* Add a detailed documentation.

22.0.0 (2020-03-13)
===================

* Complete switch to Python3 (3.7+). Python2 is not supported anymore.
