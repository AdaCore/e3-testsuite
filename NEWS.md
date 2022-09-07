26.0 (Not released yet)
=======================

* Add support for `--failure-exit-code` in `e3-testsuite-report`.

25.0 (2022-08-31)
=================

* Testsuite reports on the filesystem are relocatable now.
* XUnit reports: count `XFAIL` test results as `skipped` instead of `failures`.
* Introduce the `--no-random-temp-subdir` option.
* `--gaia-output`: create the `discs` file in more cases.
* `TestsuiteCore.testsuite_main`: force UTF-8 for text report
  generation.
* Introduce the `--cleanup-mode` command line option.
* Make `--gaia-output` (report formatted for GAIA) faster.
* Fix the `--max-consecutive-failures` command line option.
* Introduce multi-processing for test fragment execution.
* Write command line options to the comment file by default.
* `AdaCoreLegacyDriver`: add the `TIMEOUT` failure reason on rlimit abort.
* GAIA reports: rename `NOT_APPLICABLE` to `NOT-APPLICABLE`.
* Fix test filtering when they don't have dedicated directories.
* Testsuite: enhance the API to ease adding inter-test dependencies.
* Add the `--generate-text-report`/`--no-generate-text-report` command-line
  options.
* Revamp the `e3-testsuite-report` script.
* Create a "status" file to allow users to check testsuite execution.
* GAIA reports: include discriminants list when available.
* Protect test probing against duplicate test names.
* Emit `ERROR` test results for trouble in test detection/parsing.
* `ClassicTestDriver`: use XFAIL message for XPASS result.
* `AdaCoreLegacyTestDriver`: stop altering shell scripts.
* `DiffTestDriver`: make it possible to refine baselines.
* Allow multiple testcases per test directory.
* `AdaCoreLegacyTestControlCreator`: also check for shell scripts (`test.sh`).
* Always enable "cross" support for testsuites.
* Make the default testsuite failure exit code customizable (1 is the "default
  default").

24.0 (2020-11-03)
=================

* `AdaCoreLegacyTestDriver`: fix working directory substitution.
* `LineByLine`: new output refiner combinator, refines each line separately.
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
