"""Generic testsuite framework."""

from __future__ import annotations

import argparse
import inspect
import itertools
import json
import logging
import os
import re
import sys
import tempfile
import time
import traceback
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    IO,
    List,
    Optional,
    Pattern,
    TYPE_CHECKING,
    Tuple,
    Type,
)

from e3.collection.dag import DAG
from e3.env import Env
from e3.fs import rm, mkdir, mv
from e3.job.scheduler import Scheduler
from e3.main import Main
from e3.os.process import quote_arg
from e3.testsuite._helpers import deprecated
import e3.testsuite.event_notifications as event_notifications
from e3.testsuite.report.gaia import (
    GAIAResultFiles,
    dump_gaia_report,
    dump_result_logs_if_needed,
)
from e3.testsuite.report.display import generate_report, summary_line
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.report.xunit import dump_xunit_report
from e3.testsuite.result import Log, TestResult, TestStatus
from e3.testsuite.running_status import RunningStatus
from e3.testsuite.testcase_finder import (
    ParsedTest,
    ProbingError,
    TestFinder,
    YAMLTestFinder,
)
from e3.testsuite.utils import (
    CleanupMode,
    ColorConfig,
    dump_environ,
    enum_to_cmdline_args_map,
    isatty,
    safe_dir_walk,
)


if TYPE_CHECKING:
    from e3.testsuite.driver import ResultQueueItem, TestDriver
    from e3.testsuite.fragment import TestFragment


logger = logging.getLogger("testsuite")


class TestAbort(Exception):
    """Raise this to abort silently the execution of a test fragment."""

    pass


class TestsuiteCore:
    """Testsuite Core driver.

    This class is the base of Testsuite class and should not be instantiated.
    It's not recommended to override any of the functions declared in it.

    See documentation of Testsuite class for overridable methods and
    variables.
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        testsuite_name: str = "Untitled testsuite",
    ) -> None:
        """Testsuite constructor.

        :param root_dir: Root directory for the testsuite. If left to None, use
            the directory containing the Python module that created self's
            class.
        :param testsuite_name: Name for this testsuite. It can be used to
            provide a title in some report formats.
        """
        if root_dir is None:
            root_dir = os.path.dirname(inspect.getfile(type(self)))

        self.root_dir = os.path.abspath(root_dir)
        """
        Root directory for the testsuite, i.e. directory from which the test
        directory (see ``self.test_dir``) is looked up.
        """

        self.test_dir = os.path.join(self.root_dir, self.tests_subdir)
        """
        Root directory for the tree in which testcases are searched.
        """

        logger.debug("Test directory: %s", self.test_dir)
        self.return_values: Dict[str, Any] = {}
        self.result_tracebacks: Dict[str, List[str]] = {}
        self.testsuite_name = testsuite_name

        self.running_status: RunningStatus
        """
        Object to report testsuite execution status to users and to manage
        abortion in case there are too many failures.
        """

        self.use_multiprocessing = False
        """Whether to use multi-processing for tests parallelism.

        Beyond a certain level of parallelism, Python's GIL contention is too
        high to benefit from more processors. When we reach this level, it is
        more interesting to use multiple processes to cancel the GIL
        contention.

        The actual value for this attribute is computed once the DAG is built,
        in the "compute_use_multiprocessing" method.
        """

    # Mypy does not support decorators on properties, so keep the actual
    # implementations for deprecated properties in methods.

    @deprecated(2)
    def _test_counter(self) -> int:
        return len(self.report_index.entries)

    @deprecated(2)
    def _test_status_counters(self) -> Dict[TestStatus, int]:
        return self.report_index.status_counters

    @deprecated(2)
    def _results(self) -> Dict[str, TestStatus]:
        return {
            e.test_name: e.status for e in self.report_index.entries.values()
        }

    @property
    def test_counter(self) -> int:
        """Return the number of test results in the report.

        Warning: this method is obsolete and will be removed in the future.
        """
        return self._test_counter()

    @property
    def test_status_counters(self) -> Dict[TestStatus, int]:
        """Return test result counts per test status.

        Warning: this method is obsolete and will be removed in the future.
        """
        return self._test_status_counters()

    @property
    def results(self) -> Dict[str, TestStatus]:
        """Return a mapping from test names to results.

        Warning: this method is obsolete and will be removed in the future.
        """
        return self._results()

    def compute_use_multiprocessing(self) -> bool:
        """Return whether to use multi-processing for tests parallelism.

        See docstring for the "use_multiprocessing" attribute. Subclasses are
        free to override this to take control of when multiprocessing is
        enabled. Note that this will disregard the "--force-multiprocessing"
        command line option.
        """
        raise NotImplementedError

    def testsuite_main(self, args: Optional[List[str]] = None) -> int:
        """Main for the main testsuite script.

        :param args: Command line arguments. If None, use `sys.argv`.
        :return: The testsuite status code (0 for success, a positive for
            failure).
        """
        start_time = time.time()

        self.main = Main(platform_args=True)

        # Add common options
        parser = self.main.argument_parser

        temp_group = parser.add_argument_group(
            title="temporaries handling arguments"
        )
        temp_group.add_argument(
            "-t", "--temp-dir", metavar="DIR", default=Env().tmp_dir
        )
        temp_group.add_argument(
            "--no-random-temp-subdir",
            dest="random_temp_subdir",
            action="store_false",
            help="Disable the creation of a random subdirectory in the"
            " temporary directory. Use this when you know that you have"
            " exclusive access to the temporary directory (needed in order to"
            " avoid name clashes there) to get a deterministic path for"
            " testsuite temporaries.",
        )
        temp_group.add_argument(
            "-d",
            "--dev-temp",
            metavar="DIR",
            nargs="?",
            default=None,
            const="tmp",
            help="Convenience shortcut for dev setups: forces `-t DIR"
            " --no-random-temp-subdir --cleanup-mode=none` and cleans up `DIR`"
            ' first. If no directory is provided, use the local "tmp"'
            " directory.",
        )

        cleanup_mode_map = enum_to_cmdline_args_map(CleanupMode)
        temp_group.add_argument(
            "--cleanup-mode",
            choices=list(cleanup_mode_map),
            help="Control the cleanup of working spaces.\n"
            + "\n".join(
                f"{name}: {CleanupMode.descriptions()[value]}"
                for name, value in cleanup_mode_map.items()
            ),
        )
        temp_group.add_argument(
            "--disable-cleanup",
            action="store_true",
            help="Disable cleanup of working spaces. This option is deprecated"
            " and will disappear in a future version of e3-testsuite. Please"
            " use --cleanup-mode instead.",
        )

        output_group = parser.add_argument_group(
            title="results output arguments"
        )
        output_group.add_argument(
            "-o",
            "--output-dir",
            metavar="DIR",
            default="./out",
            help="Select the output directory, where test results are to be"
            " stored (default: './out'). If --old-output-dir=DIR2 is passed,"
            " the new results are stored in DIR while DIR2 contains results"
            " from a previous run. Otherwise, the new results are stored in"
            " DIR/new/ while the old ones are stored in DIR/old. In both"
            " cases, the testsuite cleans the directory for new results"
            " first.",
        )
        output_group.add_argument(
            "--old-output-dir",
            metavar="DIR",
            help="Select the old output directory, for baseline comparison."
            " See --output-dir.",
        )
        output_group.add_argument(
            "--rotate-output-dirs",
            default=False,
            action="store_true",
            help="Rotate testsuite results: move the new results directory to"
            " the old results one before running testcases (this removes the"
            " old results directory first). If not passed, we just remove the"
            " new results directory before running testcases (i.e. just ignore"
            " the old results directory).",
        )
        output_group.add_argument(
            "--show-error-output",
            "-E",
            action="store_true",
            help="When testcases fail, display their output. This is for"
            " convenience for interactive use.",
        )
        output_group.add_argument(
            "--show-time-info",
            action="store_true",
            help="Display time information for test results, if available",
        )
        output_group.add_argument(
            "--xunit-output",
            dest="xunit_output",
            metavar="FILE",
            help="Output testsuite report to the given file in the standard"
            " XUnit XML format. This is useful to display results in"
            " continuous build systems such as Jenkins.",
        )
        output_group.add_argument(
            "--gaia-output",
            action="store_true",
            help="Output a GAIA-compatible testsuite report next to the YAML"
            " report.",
        )
        output_group.add_argument(
            "--status-update-interval",
            default=1.0,
            type=float,
            help="Minimum number of seconds between status file updates. The"
            " more often we update this file, the more often one will read"
            " garbage.",
        )

        auto_gen_default = (
            "enabled" if self.auto_generate_text_report else "disabled"
        )
        output_group.add_argument(
            "--generate-text-report",
            action="store_true",
            dest="generate_text_report",
            default=self.auto_generate_text_report,
            help=(
                f"When the testsuite completes, generate a 'report' text file"
                f" in the output directory ({auto_gen_default} by default)."
            ),
        )
        output_group.add_argument(
            "--no-generate-text-report",
            action="store_false",
            dest="generate_text_report",
            help="Disable the generation of a 'report' text file (see"
            "--generate-text-report).",
        )

        output_group.add_argument(
            "--truncate-logs",
            "-T",
            metavar="N",
            type=int,
            default=200,
            help="When outputs (for instance subprocess outputs) exceed 2*N"
            " lines, only include the first and last N lines in logs. This is"
            " necessary when storage for testsuite results have size limits,"
            " and the useful information is generally either at the beginning"
            " or the end of such outputs. If 0, never truncate logs.",
        )
        output_group.add_argument(
            "--dump-environ",
            dest="dump_environ",
            action="store_true",
            default=False,
            help="Dump all environment variables in a file named environ.sh,"
            " located in the output directory (see --output-dir). This"
            " file can then be sourced from a Bourne shell to recreate"
            " the environement that existed when this testsuite was run"
            " to produce a given testsuite report.",
        )
        output_group.add_argument(
            "--notify-events",
            help="If provided, run the given command each time a event that is"
            " tracked by the testsuite happens. See the documentation for the"
            " ``e3.testsuite.event_notifications`` module for more information"
            " about events and notification commands. Base arguments for"
            " notification commands are specified using the POSIX shell"
            " syntax. If the commands starts with `python:`, then the expected"
            " format is `python:MODULE:CALLABLE`. The Python module MODULE is"
            " imported, and its CALLABLE` attribute is fetched. It is called"
            " with one positional argument: the testsuite instance, and must"
            " return another callable that will be invoked for each"
            " notification event, with one positional argument: the"
            " corresponding TestNotification instance.",
        )

        exec_group = parser.add_argument_group(
            title="execution control arguments"
        )
        exec_group.add_argument(
            "--max-consecutive-failures",
            "-M",
            metavar="N",
            type=int,
            default=self.default_max_consecutive_failures,
            help="Number of test failures (FAIL or ERROR) that trigger the"
            " abortion of the testuite. If zero, this behavior is disabled. In"
            " some cases, aborting the testsuite when there are just too many"
            " failures saves time and costs: the software to test/environment"
            " is too broken, there is no point to continue running the"
            " testsuite.",
        )
        exec_group.add_argument(
            "-j",
            "--jobs",
            dest="jobs",
            type=int,
            metavar="N",
            default=Env().build.cpu.cores,
            help="Specify the number of jobs to run simultaneously",
        )
        exec_group.add_argument(
            "--failure-exit-code",
            metavar="N",
            type=int,
            default=self.default_failure_exit_code,
            help="Exit code the testsuite must use when at least one test"
            " result shows a failure/error. By default, this is"
            f" {self.default_failure_exit_code}. This option is useful when"
            " running a testsuite in a continuous integration setup, as this"
            " can make the testing process stop when there is a regression.",
        )
        exec_group.add_argument(
            "--force-multiprocessing",
            action="store_true",
            help="Force the use of subprocesses to execute tests, for"
            " debugging purposes. This is normally automatically enabled when"
            " both the level of requested parallelism is high enough (to make"
            " it profitable regarding the contention of Python's GIL) and no"
            " test fragment has dependencies on other fragments. This flag"
            " forces the use of multiprocessing even if any of these two"
            " conditions is false.",
        )
        exec_group.add_argument(
            "--skip-passed",
            action="store_true",
            help="Run only tests that did not pass in the previous testsuite"
            " run. This attempts to find successful tests in the report stored"
            " at the location where this run will create the testsuite report.",
        )
        exec_group.add_argument(
            "--list-json",
            action="store",
            type=str,
            default=None,
            help="Dump the tests of the testsuite into a JSON list"
            " at the given file path."
            " In this mode, the tests are not executed.",
        )
        parser.add_argument(
            "sublist", metavar="tests", nargs="*", default=[], help="test"
        )
        # Add user defined options
        self.add_options(parser)

        # Parse options
        self.main.parse_args(args)
        assert self.main.args is not None

        # If there is a chance for the logging to end up in a non-tty stream,
        # disable colors. If not, be user-friendly and automatically show error
        # outputs.
        if (
            self.main.args.log_file
            or not isatty(sys.stdout)
            or not isatty(sys.stderr)
        ):
            enable_colors = False
        else:  # interactive-only
            enable_colors = True
            self.main.args.show_error_output = True

        # If explicitly requested, disable colors.
        #
        # Do not bother having tests for this, as tests are by essence
        # non-interactive, and colors are never enabled for them.
        if self.main.args.nocolor:  # interactive-only
            enable_colors = False

        self.colors = ColorConfig(enable_colors)
        self.Fore = self.colors.Fore
        self.Style = self.colors.Style

        self.env = Env()
        self.env.enable_colors = enable_colors
        self.env.root_dir = self.root_dir
        self.env.test_dir = self.test_dir

        # Setup output directories and create an index for the results we are
        # going to produce.
        self.output_dir: str
        self.old_output_dir: Optional[str]
        self.old_report_index: ReportIndex
        self.setup_result_dirs()
        self.report_index = ReportIndex(self.output_dir)

        # Set the cleanup mode from command-line arguments
        if self.main.args.cleanup_mode is not None:
            self.env.cleanup_mode = cleanup_mode_map[
                self.main.args.cleanup_mode
            ]
        elif self.main.args.disable_cleanup:
            logger.warning(
                "--disable-cleanup is deprecated and will disappear in a"
                " future version of e3-testsuite. Please use --cleanup-mode"
                " instead."
            )
            self.env.cleanup_mode = CleanupMode.NONE
        else:
            self.env.cleanup_mode = CleanupMode.default()

        # Settings for temporary directory creation
        temp_dir: str = self.main.args.temp_dir
        random_temp_subdir: bool = self.main.args.random_temp_subdir

        # The "--dev-temp" option forces several settings
        if self.main.args.dev_temp:
            self.env.cleanup_mode = CleanupMode.NONE
            temp_dir = self.main.args.dev_temp
            random_temp_subdir = False

        # Now actually setup the temporary directory: make sure we start from a
        # clean directory if we use a deterministic directory.
        #
        # Note that we do make sure that working_dir is an absolute path, as we
        # are likely to be changing directories when running each test. A
        # relative path would no longer work under those circumstances.
        temp_dir = os.path.abspath(temp_dir)
        if not random_temp_subdir:
            self.working_dir = temp_dir
            rm(self.working_dir, recursive=True)
            mkdir(self.working_dir)

        elif not os.path.isdir(temp_dir):
            # If the temp dir is supposed to be randomized, we need to create a
            # subdirectory, so check that the parent directory exists first.
            logger.critical("temp dir '%s' does not exist", temp_dir)
            return 1

        else:
            self.working_dir = tempfile.mkdtemp("", "tmp", temp_dir)

        # Create the exchange directory (to exchange data between the testsuite
        # main and the subprocesses running test fragments). Compute the name
        # of the file to pass environment data to subprocesses.
        self.exchange_dir = os.path.join(self.working_dir, "exchange")
        self.env_filename = os.path.join(self.exchange_dir, "_env.bin")
        mkdir(self.exchange_dir)

        # Make them both available to test fragments
        self.env.exchange_dir = self.exchange_dir
        self.env.env_filename = self.env_filename

        self.gaia_result_files: Dict[str, GAIAResultFiles] = {}
        """Mapping from test names to files for results in the GAIA report."""

        # Store in global env: target information and common paths
        self.env.output_dir = self.output_dir
        self.env.working_dir = self.working_dir
        self.env.options = self.main.args

        try:
            self.event_notifier = event_notifications.EventNotifier(
                self, self.main.args.notify_events
            )
        except event_notifications.InvalidNotifyCommand:
            return 1
        self.running_status = RunningStatus(
            os.path.join(self.output_dir, "status"),
            self.main.args.status_update_interval,
            self.main.args.max_consecutive_failures,
        )

        # User specific startup
        self.set_up()

        # Retrieve the list of test
        self.test_list = self.get_test_list(self.main.args.sublist)

        if self.main.args.list_json:

            to_dump = [
                {
                    "test_name": t.test_name,
                    "test_dir": t.test_dir,
                    "test_matcher": t.test_matcher,
                }
                for t in self.test_list
            ]

            with open(self.main.args.list_json, "w") as fp:
                json.dump(to_dump, fp)

            return 0

        # If requested, filter out tests that passed the previous time
        if self.main.args.skip_passed:

            def should_skip(pt: ParsedTest) -> bool:
                """Return whether the test ``pt`` should be skipped.

                It should be skipped if 1) it was run last time and 2) it
                passed or expectedly failed.
                """
                entry = self.old_report_index.entries.get(pt.test_name)
                return entry is not None and entry.status in (
                    TestStatus.PASS,
                    TestStatus.XFAIL,
                    TestStatus.XPASS,
                )

            self.test_list = [
                pt for pt in self.test_list if not should_skip(pt)
            ]

        # Create a DAG to constraint the test execution order
        dag = DAG()
        for parsed_test in self.test_list:
            self.add_test(dag, parsed_test)
        self.adjust_dag_dependencies(dag)
        dag.check()
        self.running_status.set_dag(dag)

        # Determine whether to use multiple processes for fragment execution
        # parallelism.
        self.use_multiprocessing = self.compute_use_multiprocessing()
        self.env.use_multiprocessing = self.use_multiprocessing

        # Record modules lookup path, including for the file corresponding to
        # the __main__ module.  Subprocesses will need it to have access to the
        # same modules.
        self.env.modules_search_path = list(sys.path)
        main_module_file = sys.modules["__main__"].__file__
        if main_module_file is not None:
            self.env.modules_search_path.insert(
                0, os.path.dirname(os.path.abspath(main_module_file))
            )

        # Now that the env is supposed to be complete, dump it for the test
        # fragments to pick it up.
        self.env.store(self.env_filename)

        # For debugging purposes, dump the final DAG to a DOT file
        with open(os.path.join(self.output_dir, "tests.dot"), "w") as fd:
            fd.write(dag.as_dot())

        if self.use_multiprocessing:
            self.run_multiprocess_mainloop(dag)
        else:
            self.run_standard_mainloop(dag)

        # Compute the duration for this testsuite run
        end_time = time.time()
        self.report_index.duration = end_time - start_time

        # Dump the testsuite report in all the requested formats
        self.report_index.write()
        self.dump_testsuite_result()
        if self.main.args.xunit_output:
            dump_xunit_report(
                self.testsuite_name,
                self.report_index,
                self.main.args.xunit_output,
            )
        if self.main.args.gaia_output:
            dump_gaia_report(
                report_index=self.report_index,
                output_dir=self.output_dir,
                discs=getattr(self.env, "discs", None),
                result_files=self.gaia_result_files,
            )

        # Clean everything
        self.tear_down()

        # If requested, generate a text report
        if self.main.args.generate_text_report:
            # Use the previous testsuite results for comparison, if available
            old_index = (
                ReportIndex.read(self.old_output_dir)
                if self.old_output_dir
                else None
            )

            # Include all information, except logs for successful tests, which
            # is just too verbose.
            with open(
                os.path.join(self.output_dir, "report"), "w", encoding="utf-8"
            ) as f:
                generate_report(
                    output_file=f,
                    new_index=self.report_index,
                    old_index=old_index,
                    colors=ColorConfig(colors_enabled=False),
                    show_all_logs=False,
                    show_xfail_logs=True,
                    show_error_output=True,
                    show_time_info=True,
                )

        # Return the appropriate status code: the failure status code from the
        # --failure-exit-code=N option when there is a least one testcase
        # failure, or 0.
        return (
            self.main.args.failure_exit_code
            if self.report_index.has_failures
            else 0
        )

    def get_test_list(self, sublist: List[str]) -> List[ParsedTest]:
        """Retrieve the list of tests.

        :param sublist: A list of tests scenarios or patterns.
        """
        # Use a mapping: test name -> ParsedTest when building the result, as
        # several patterns in "sublist" may yield the same testcase.
        testcases: Dict[str, ParsedTest] = {}
        test_finders = self.test_finders

        def matches_pattern(
            pattern: Optional[Pattern[str]], name: str
        ) -> bool:
            return pattern is None or bool(pattern.search(name))

        def add_testcase(
            pattern: Optional[Pattern[str]], test: ParsedTest
        ) -> None:
            # Do not add this testcase if its test-specific matcher does not
            # match the requested pattern.
            if test.test_matcher and not matches_pattern(
                pattern, test.test_matcher
            ):
                return

            if test.test_name in testcases:
                self.add_test_error(
                    test_name=test.test_name,
                    message=f"duplicate test name: {test.test_name}",
                    tb=None,
                )
            else:
                testcases[test.test_name] = test

        def helper(spec: str) -> None:
            pattern: Optional[Pattern[str]] = None

            # If the given pattern is a directory, do not go through the whole
            # tests subdirectory.
            if os.path.isdir(spec):
                root = spec
            else:
                root = self.test_dir
                try:
                    pattern = re.compile(spec)
                except re.error as exc:
                    logger.debug(
                        "Test pattern is not a valid regexp, try to match it"
                        " as-is: {}".format(exc)
                    )
                    pattern = re.compile(re.escape(spec))

            # For each directory in the requested subdir, ask our test finders
            # to probe for a testcase. Register matches.
            for dirpath, dirnames, filenames in safe_dir_walk(root):
                # Don't descend into internal VCS directories, because it will
                # likely generate a lot of unnecessary I/O operations and we
                # don't expect to find any tests there anyway.
                for vcsdir in [".git", ".svn", "CVS"]:
                    if vcsdir in dirnames:
                        dirnames.remove(vcsdir)

                # Compute whether the pattern matches the directory only once
                # (now) instead of once per test finder (in the for loop
                # below).
                pattern_matches = matches_pattern(pattern, dirpath)

                # The first test finder that has a match "wins". When handling
                # test data, we want to deal only with absolute paths, so get
                # the absolute name now.
                dirpath = os.path.abspath(dirpath)
                for tf in test_finders:
                    # If this test finder guarantees that each testcase has a
                    # dedicated directory, do not process this directory if it
                    # does not match the requested pattern.
                    if tf.test_dedicated_directory and not pattern_matches:
                        continue

                    try:
                        test_or_list = tf.probe(
                            self, dirpath, dirnames, filenames
                        )
                    except ProbingError as exc:
                        self.add_test_error(
                            test_name=self.test_name(dirpath),
                            message=str(exc),
                            tb=traceback.format_exc(),
                        )
                        break
                    if isinstance(test_or_list, list):
                        for t in test_or_list:
                            add_testcase(pattern, t)
                        break
                    elif test_or_list is not None:
                        add_testcase(pattern, test_or_list)
                        break

        # If specific tests are requested, only look for them. Otherwise, just
        # look in the tests subdirectory.
        if sublist:
            for s in sublist:
                helper(s)
        else:
            helper(self.test_dir)

        result = list(testcases.values())
        logger.info("Found {} tests".format(len(result)))
        logger.debug("tests:\n  " + "\n  ".join(t.test_dir for t in result))
        return result

    def add_test(self, dag: DAG, parsed_test: ParsedTest) -> None:
        """Register a test to run.

        :param dag: The DAG of test fragments to execute for the testsuite.
        :param parsed_test: Test to instantiate.
        """
        test_name = parsed_test.test_name

        # Complete the test environment
        test_env = dict(parsed_test.test_env)
        test_env["test_dir"] = parsed_test.test_dir
        test_env["test_name"] = test_name

        assert isinstance(self.env.working_dir, str)
        test_env["working_dir"] = os.path.join(self.env.working_dir, test_name)

        # Fetch the test driver to use
        driver = parsed_test.driver_cls
        if not driver:
            if self.default_driver:
                driver = self.test_driver_map[self.default_driver]
            else:
                self.add_test_error(
                    test_name=test_name,
                    message="missing test driver",
                )
                return

        # Finally run the driver instantiation
        try:
            instance = driver(self.env, test_env)
            instance.Fore = self.Fore
            instance.Style = self.Style
            instance.add_test(dag)

        except Exception as e:
            self.add_test_error(
                test_name=test_name,
                message=str(e),
                tb=traceback.format_exc(),
            )
        else:
            self.event_notifier.notify_test_queue(instance.test_name)

    def dump_testsuite_result(self) -> None:
        """Log a summary of test results.

        Subclasses are free to override this to do whatever is suitable for
        them.
        """
        lines = ["Summary:"]

        # Display test count for each status, but only for status that have
        # at least one test. Sort them by status value, to get consistent
        # order.
        def sort_key(couple: Tuple[TestStatus, int]) -> Any:
            status, _ = couple
            return status.value

        stats = sorted(
            (
                (status, count)
                for status, count in self.report_index.status_counters.items()
                if count
            ),
            key=sort_key,
        )
        for status, count in stats:
            lines.append(
                "  {}{: <12}{} {}".format(
                    status.color(self.colors),
                    status.name,
                    self.Style.RESET_ALL,
                    count,
                )
            )
        if not stats:
            lines.append("  <no test result>")
        logger.info("\n".join(lines))

        # Dump the comment file
        with open(os.path.join(self.output_dir, "comment"), "w") as f:
            self.write_comment_file(f)

    def collect_result(self, fragment: TestFragment) -> None:
        """Import test results from ``fragment`` into testsuite reports.

        :param fragment: Test fragment (just completed) from which to import
            test results.
        """
        assert self.main.args

        # Process all results from this fragment
        while fragment.result_queue:
            self.add_result(fragment.result_queue.pop())

        # Send a notification if this was the last fragment to run for this
        # test driver. This is done here rather than in test fragment's
        # collect_result so that test result events are notified before test
        # end events.
        fragment.maybe_notify_ended()

        # Now that this fragment is completed, make sure to remove all
        # references to its test drivers so that it can be garbage collected.
        # This is necessary to keep memory consumption under control for big
        # testsuites.
        dag = self.running_status.dag
        assert dag is not None
        dag.vertex_data[fragment.uid].clear_driver_data()
        fragment.clear_driver_data()

    def add_result(self, item: ResultQueueItem) -> None:
        """Add a test result to the result index and log it.

        :param item: Result queue item for the result to add.
        """
        assert self.main.args

        status = item.result.status
        test_name = item.result.test_name

        # The test results that reach this point are special: there were
        # serialized/deserialized through YAML, so the Log layer disappeared.
        assert status is not None

        # Ensure that we don't have two results with the same test name: if
        # that is the case, we cannot publish the result we were given: still,
        # push a "synthetic" ERROR result to keep track of the error (this is a
        # testsuite framework error).
        #
        # There is one exception to this: ERROR results are already the symptom
        # of something that went wrong in the testing framework. Because of
        # e3-testsuite's architecture (in particular multiprocessing), it is
        # not possible to have both human-friendly result names (that cleanly
        # map to test names) and reliably creating non-conflicting result names
        # at the time the test result is produced. So if the name of an ERROR
        # result conflicts with an existing result, just look for an
        # alternative name.

        def indented_tb(tb: List[str]) -> str:
            return "".join("  {}".format(line) for line in tb)

        if test_name in self.report_index.entries:
            test_name_radix = test_name
            for i in itertools.count(1):
                test_name = f"{test_name_radix}__except{i}"
                if test_name not in self.report_index.entries:
                    break

            if item.result.status != TestStatus.ERROR:
                self.add_test_error(
                    test_name,
                    f"cannot push twice results for {test_name_radix}",
                    f"\nFirst push happened at:"
                    f"\n{indented_tb(self.result_tracebacks[test_name_radix])}"
                    f"\nThis one happened at:"
                    f"\n{indented_tb(item.traceback)}",
                )
                return

        # Now that the result is validated, add it to our internals
        self.report_index.add_result(item.result, item.filename)
        self.result_tracebacks[test_name] = item.traceback
        self.running_status.process_result(item.result)
        if item.gaia_results:
            self.gaia_result_files[test_name] = item.gaia_results

        # Log the test result. If error output is requested and the test
        # failed unexpectedly, show the detailed logs.
        log_line = summary_line(
            item.result, self.colors, self.main.args.show_time_info
        )
        if self.main.args.show_error_output and status not in (
            TestStatus.PASS,
            TestStatus.XFAIL,
            TestStatus.XPASS,
            TestStatus.SKIP,
        ):
            full_result = self.report_index.entries[test_name].load()

            def format_log(log: Log) -> str:
                return "\n" + str(log) + self.Style.RESET_ALL

            if full_result.diff:
                log_line += format_log(full_result.diff)
            else:
                log_line += format_log(full_result.log)
        logger.info(log_line)

        self.event_notifier.notify_test_result(
            item.test_name,
            item.result,
            os.path.join(self.report_index.results_dir, item.filename),
        )

    def add_test_error(
        self, test_name: str, message: str, tb: Optional[str] = None
    ) -> None:
        """Create and add an ERROR test status.

        :param test_name: Prefix for the test result to create. This adds a
            suffix to avoid clashes.
        :param str message: Error message.
        :param tb: Optional traceback for the error.
        """
        from e3.testsuite.driver import ResultQueueItem

        result = TestResult(
            test_name, env={}, status=TestStatus.ERROR, msg=message
        )
        if tb:
            result.log += tb

        self.add_result(
            ResultQueueItem(
                test_name,
                result.summary,
                result.save(self.output_dir),
                traceback.format_stack(),
                dump_result_logs_if_needed(self.env, result, self.output_dir),
            )
        )

    def setup_result_dirs(self) -> None:
        """Create the output directory in which the results are stored."""
        assert self.main.args
        args = self.main.args

        # Both the actual new/old directories to use depend on both
        # --output-dir and --old-output-dir options.
        d = os.path.abspath(args.output_dir)
        if args.old_output_dir:
            self.output_dir = d
            old_output_dir = os.path.abspath(args.old_output_dir)
        else:
            self.output_dir = os.path.join(d, "new")
            old_output_dir = os.path.join(d, "old")

        # If this testsuite run should skip tests that passed in a previous
        # testsuite run, try to load the previous testsuite report.
        if args.skip_passed:
            try:
                self.old_report_index = ReportIndex.read(self.output_dir)
            except OSError as exc:
                logger.warning(
                    f"Could not load the previous testsuite report: {exc}"
                )

                # Create a dummy report. We must run all tests that did not
                # pass last time: with no result, all tests should run.
                self.old_report_index = ReportIndex(self.output_dir)

        # Rotate results directories if requested. In both cases, make sure the
        # new results dir is clean.
        if args.rotate_output_dirs:
            if os.path.isdir(old_output_dir):
                rm(old_output_dir, recursive=True)
            if os.path.isdir(self.output_dir):
                mv(self.output_dir, old_output_dir)
        elif os.path.isdir(self.output_dir):
            rm(self.output_dir, recursive=True)
        mkdir(self.output_dir)

        # Remember about the old output directory only if it exists and does
        # contain results. If not, this info will be unused at best, or lead to
        # incorrect behavior.
        self.old_output_dir = None
        if os.path.exists(old_output_dir) and os.path.exists(
            os.path.join(old_output_dir, ReportIndex.INDEX_FILENAME)
        ):
            self.old_output_dir = old_output_dir

        if args.dump_environ:
            dump_environ(os.path.join(self.output_dir, "environ.sh"), self.env)

    def run_standard_mainloop(self, dag: DAG) -> None:
        """Run the main loop to execute test fragments in threads."""
        assert self.main.args is not None

        from e3.job import Job
        from e3.testsuite.fragment import FragmentData, ThreadTestFragment

        def job_factory(
            uid: str,
            data: Any,
            predecessors: FrozenSet[str],
            notify_end: Callable[[str], None],
        ) -> ThreadTestFragment:
            """Turn a DAG item into a ThreadTestFragment instance."""
            assert isinstance(data, FragmentData)

            # When passing return values from predecessors, remove current test
            # name from the keys to ease referencing by user (the short
            # fragment name can then be used by user without knowing the full
            # node id).
            key_prefix = data.driver.test_name + "."
            key_prefix_len = len(key_prefix)

            def filter_key(k: str) -> str:
                if k.startswith(key_prefix):
                    return k[key_prefix_len:]
                else:
                    return k

            return ThreadTestFragment(
                uid,
                data.driver,
                data.callback,
                {filter_key(k): self.return_values[k] for k in predecessors},
                notify_end,
                self.running_status,
                self.event_notifier,
            )

        def collect_result(job: Job) -> bool:
            """Collect test results from the given fragment."""
            assert isinstance(job, ThreadTestFragment)
            self.return_values[job.uid] = job.return_value
            self.collect_result(job)

            # In the e3.job.scheduler API, collect returning "True" means
            # "requeue the job". We never want to do that.
            return False

        # Create a scheduler to run all fragments for the testsuite main loop

        jobs = self.main.args.jobs
        if self.main.args.jobs <= 0:  # all: no cover
            jobs = os.cpu_count() or 1

        scheduler = Scheduler(
            job_provider=job_factory,
            tokens=jobs,
            collect=collect_result,
        )

        # Finally run the tests
        scheduler.run(dag)

    def run_multiprocess_mainloop(self, dag: DAG) -> None:
        """Run the main loop to execute test fragments in subprocesses."""
        assert self.main.args is not None

        from e3.testsuite.fragment import FragmentData, ProcessTestFragment
        from e3.testsuite.multiprocess_scheduler import MultiprocessScheduler

        def job_factory(
            uid: str, data: FragmentData, slot: int
        ) -> ProcessTestFragment:
            """Turn a DAG item into a ProcessTestFragment instance."""
            assert data.callback_by_name
            return ProcessTestFragment(
                uid,
                data.driver,
                data.name,
                slot,
                self.running_status,
                self.event_notifier,
                self.env,
            )

        def collect_result(job: ProcessTestFragment) -> None:
            """Collect test results from the given fragment."""
            job.collect_result()
            self.collect_result(job)

        scheduler: MultiprocessScheduler[FragmentData, ProcessTestFragment] = (
            MultiprocessScheduler(
                dag,
                job_factory,
                collect_result,
                self.running_status,
                jobs=self.main.args.jobs,
            )
        )

        # Finally run the tests
        scheduler.run()

    # Unlike the previous methods, the following ones are supposed to be
    # overriden.

    @property
    def tests_subdir(self) -> str:
        """
        Return the subdirectory in which tests are looked for.

        The returned directory name is considered relative to the root
        testsuite directory (self.root_dir).
        """
        raise NotImplementedError

    @property
    def test_driver_map(self) -> Dict[str, Type[TestDriver]]:
        """Return a map from test driver names to TestDriver subclasses.

        Test finders will be able to use this map to fetch the test drivers
        referenced in testcases.
        """
        raise NotImplementedError

    @property
    def default_driver(self) -> Optional[str]:
        """Return the name of the default driver for testcases.

        When tests do not query a specific driver, the one associated to this
        name is used instead. If this property returns None, all tests are
        required to query a driver.
        """
        raise NotImplementedError

    def test_name(self, test_dir: str) -> str:
        """Compute the test name given a testcase spec.

        This function can be overridden. By default it uses the name of the
        test directory. Note that the test name should be a valid filename (not
        dir seprators, or special characters such as ``:``, ...).
        """
        raise NotImplementedError

    @property
    def test_finders(self) -> List[TestFinder]:
        """Return test finders to probe tests directories."""
        raise NotImplementedError

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        """Add testsuite specific switches.

        Subclasses can override this method to add their own testsuite
        command-line options.

        :param parser: Parser for command-line arguments. See
            <https://docs.python.org/3/library/argparse.html> for usage.
        """
        raise NotImplementedError

    def set_up(self) -> None:
        """Execute operations before running the testsuite.

        Before running this, command-line arguments were parsed. After this
        returns, the testsuite will look for testcases.

        By default, this does nothing. Overriding this method allows testsuites
        to prepare the execution of the testsuite depending on their needs. For
        instance:

        * process testsuite-specific options;
        * initialize environment variables;
        * adjust self.env (object forwarded to test drivers).
        """
        raise NotImplementedError

    def tear_down(self) -> None:
        """Execute operation when finalizing the testsuite.

        By default, this cleans the working (temporary) directory in which the
        tests were run.
        """
        raise NotImplementedError

    def write_comment_file(self, comment_file: IO[str]) -> None:
        """Write the comment file's content.

        :param comment_file: File descriptor for the comment file.  Overriding
            methods should only call its "write" method (or print to it).
        """
        raise NotImplementedError

    @property
    def default_max_consecutive_failures(self) -> int:
        """Return the default maximum number of consecutive failures.

        In some cases, aborting the testsuite when there are just too many
        failures saves time and costs: the software to test/environment is too
        broken, there is no point to continue running the testsuite.

        This property must return the number of test failures (FAIL or ERROR)
        that trigger the abortion of the testuite. If zero, this behavior is
        disabled.
        """
        raise NotImplementedError

    @property
    def default_failure_exit_code(self) -> int:
        """Return the default exit code when at least one test fails."""
        raise NotImplementedError

    @property
    def auto_generate_text_report(self) -> bool:
        """Return whether to automatically generate a text report.

        This is disabled by default (and controlled by the
        --generate-text-report command-line option) because the generation of
        this report can add non-trivial overhead depending on results.
        """
        raise NotImplementedError

    def adjust_dag_dependencies(self, dag: DAG) -> None:
        """Adjust dependencies in the DAG of all test fragments.

        :param dag: DAG to adjust.
        :param fragments: Set of all fragments added so far to the DAG.
        """
        raise NotImplementedError

    @property
    def multiprocessing_supported(self) -> bool:
        """Return whether running test fragments in subprocesses is supported.

        When multiprocessing is enabled (see the "use_multiprocessing"
        attribute), test fragments are executed in a separate process, and the
        propagation of their return values is disabled (FragmentData's
        "previous_values" argument is always an empty dict).

        This means that multiprocessing can work only if test drivers and all
        code used by test fragments can be imported by subprocesses (for
        instance, class defined in the testsuite entry point are unavailable)
        and if test drivers don't use the "previous_values" mechanism.

        Testsuite authors can use the "--force-multiprocessing" testsuite
        option to check if this works.
        """
        raise NotImplementedError


class Testsuite(TestsuiteCore):
    """Testsuite class.

    When implementing a new testsuite you should create a class that
    inherit from this class.
    """

    @property
    def tests_subdir(self) -> str:
        return "."

    @property
    def test_driver_map(self) -> Dict[str, Type[TestDriver]]:
        raise NotImplementedError

    @property
    def default_driver(self) -> Optional[str]:
        return None

    def test_name(self, test_dir: str) -> str:
        # Start with a relative directory name from the tests subdirectory
        result = os.path.relpath(test_dir, self.test_dir)

        # We want to support running tests outside of the test directory, so
        # strip leading "..".
        pattern = os.path.pardir + os.path.sep
        while result.startswith(pattern):
            result = result[len(pattern) :]

        # Run some name canonicalization and replace directory separators with
        # double underscores.
        return result.replace("\\", "/").rstrip("/").replace("/", "__")

    @property
    def test_finders(self) -> List[TestFinder]:
        return [YAMLTestFinder()]

    def add_options(self, parser: argparse.ArgumentParser) -> None:
        pass

    def set_up(self) -> None:
        pass

    def tear_down(self) -> None:
        assert self.main.args

        if self.env.cleanup_mode == CleanupMode.ALL:
            rm(self.working_dir, True)

    def write_comment_file(self, comment_file: IO[str]) -> None:
        # Sensible default: just write the command line used to run the
        # testsuite. Testsuites can override or reuse this.
        quoted_cmdline = " ".join(quote_arg(arg) for arg in sys.argv)
        comment_file.write(f"Testsuite options:\n  {quoted_cmdline}\n")

    @property
    def default_max_consecutive_failures(self) -> int:
        return 0

    @property
    def default_failure_exit_code(self) -> int:
        return 1

    @property
    def auto_generate_text_report(self) -> bool:
        return False

    def adjust_dag_dependencies(self, dag: DAG) -> None:
        pass

    @property
    def multiprocessing_supported(self) -> bool:
        return False

    def compute_use_multiprocessing(self) -> bool:
        assert self.main.args

        # If multiprocessing is explicitly requested, just enable it
        if self.main.args.force_multiprocessing:
            return True

        # In practice, we noticed that running at most 16 jobs in parallel
        # creates neglectible GIL contention.
        if not self.multiprocessing_supported or self.main.args.jobs <= 16:
            return False

        return True
