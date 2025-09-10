27.4 (Not released yet)
=======================

27.3 (2025-09-10)
=================

* Introduce a notification system (`--notify-events` testsuite argument).
* Add a `--list-json=FILE` CLI argument to dump the list of tests in a
  testsuite to a file in JSON format.
* `e3-convert-xunit`: add testcase-level `<system-out>` and
  `<system-err>` handling.
* `e3-convert-xunit`: robustify for unexpected status tags.
* `e3-convert-xunit`: copy capped messages to result logs.

27.2 (2025-06-17)
=================

* Rework handling of `ERROR` test results: only append `__except` suffixes in
  case of duplicate result names.
* Make testcase discovery resilient to symlink loops.
* `ClassicTestDriver.shell`: bind e3.os.process.Run's input argument.
* `e3.testsuite.optfileparser`: restrict syntax for discriminants.
* Fix test filtering when not all test finders have dedicated directories.
* `PatternSubstitute`: update annotations to accept replacement callbacks.
* `e3.testsuite.report.xunit`: add a `XUnitImportApp` class to make it possible
  to create customized versions of the `e3-convert-xunit` script without code
  duplication.
* `e3-opt-check`: new script to look for syntax errors in opt files.
* `e3-opt-parse`: exit gracefully and give line number information in case of
  syntax error.
* `e3-convert-xunit`: truncate too long test result messages.
* `e3-convert-xunit`: warn about dangling XFAILs annotations.
* `DiffTestDriver`: tolerate missing baseline files when rewriting baselines.
* The `--xunit-name` argument of `e3-testsuite-report` is now used to
  fill the `classname` information of each XUnit individual test report.

26.0 (2023-01-19)
=================

* `DiffTestDriver`: handle diff context size customization.
* Add a XUnit results importer for report indexes.
* `AdaCoreLegacyDriver`: avoid CRLF line endings in test scripts.
* `AdaCoreLegacyDriver`: fix handling of non-ASCII test scripts.
* Detailed logs in case of subprocess output decoding error.
* `e3.testsuite.report.display.generate_report`: fix spurious write to
  sys.stdout.
* Introduce a new testsuite option: `--skip-result`.
* Fix XUnit reports when logs include control characters.
* Introduce `e3.testsuite.report.rewriting`.
* GAIA reports: add missing ``.result`` file for each test.
* Make it easier to generate a GAIA-compatible report without a testsuite run.
* Disable the use of ANSI sequences in logging when `--nocolor` is passed.
* Make `DiffTestDriver` perform a full match for regexp baselines.
* Fix memory leaks for test driver data.
* Include total testsuite and testcase durations in XUnit reports.
* Add support for `--xunit-output` in `e3-testsuite-report`.
* Add support for `--failure-exit-code` in `e3-testsuite-report`.
* Ignore VCS directories like .git when looking for tests.

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
