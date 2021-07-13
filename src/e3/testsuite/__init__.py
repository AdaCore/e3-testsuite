"""Generic testsuite framework."""

from __future__ import annotations

import argparse
import inspect
import logging
import os
import re
import sys
import tempfile
import threading
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
    cast,
)

from e3.collection.dag import DAG
from e3.env import Env, BaseEnv
from e3.fs import rm, mkdir, mv
from e3.job.scheduler import Scheduler
from e3.main import Main
from e3.os.process import quote_arg
from e3.testsuite._helpers import deprecated
from e3.testsuite.report.gaia import dump_gaia_report
from e3.testsuite.report.display import generate_report, summary_line
from e3.testsuite.report.index import ReportIndex
from e3.testsuite.report.xunit import dump_xunit_report
from e3.testsuite.result import Log, TestResult, TestStatus
from e3.testsuite.testcase_finder import (
    ParsedTest,
    ProbingError,
    TestFinder,
    YAMLTestFinder,
)
from e3.testsuite.utils import ColorConfig, isatty


if TYPE_CHECKING:  # no cover
    from e3.testsuite.driver import TestDriver
    from e3.testsuite.fragment import TestFragment


logger = logging.getLogger("testsuite")


class TestAbort(Exception):
    """Raise this to abort silently the execution of a test fragment."""

    pass


class RunningStatus:
    def __init__(self, filename: str):
        """RunningStatus constructor.

        :param filename: Name of the status file to write.
        """
        self.dag: Optional[DAG] = None
        self.filename = filename
        self.lock = threading.Lock()

        self.running: Dict[str, TestFragment] = {}
        """Set of test fragments currently running, indexed by UID."""

        self.completed: Dict[str, TestFragment] = {}
        """Set of test fragments that completed their job, indexed by UID."""

        self.status_counters: Dict[TestStatus, int] = {}
        """Snapshot of the testsuite's report index status counters.

        We preserve a copy to avoid inconsistent state due to race conditions:
        these counters are updated in the collect_result method while the other
        sets are updated in TestFragment.run, which is executed in workers
        (i.e. other threads).
        """

    def set_dag(self, dag: DAG) -> None:
        """Set the DAG that contains TestFragment instances."""
        assert self.dag is None
        self.dag = dag

    def start(self, fragment: TestFragment) -> None:
        """Put a fragment in the "running" set."""
        assert self.dag is not None
        with self.lock:
            assert fragment.uid in self.dag.vertex_data
            assert fragment.uid not in self.running
            assert fragment.uid not in self.completed
            self.running[fragment.uid] = fragment
        self.dump()

    def complete(self, fragment: TestFragment) -> None:
        """Move a fragment from the "running" set to the "completed" set."""
        assert self.dag is not None
        with self.lock:
            assert fragment.uid in self.dag.vertex_data
            assert fragment.uid not in self.completed
            f = self.running.pop(fragment.uid)
            assert f is fragment
            self.completed[f.uid] = f
        self.dump()

    def set_status_counters(self, counters: Dict[TestStatus, int]) -> None:
        copy = dict(counters)
        with self.lock:
            self.status_counters = copy
        self.dump()

    def dump(self) -> None:
        """Write a report for this status as human-readable text to "fp"."""
        lines = []
        with self.lock:
            if self.dag is None:
                lines.append("No test fragment yet")
            else:
                lines.append(
                    f"Test fragments:"
                    f" {len(self.completed)}"
                    f" / {len(self.dag.vertex_data)} completed"
                )

                lines.append("Currently running:")
                if self.running:
                    lines.extend(f"  {uid}" for uid in sorted(self.running))
                else:
                    lines.append("  <none>")

                statuses = sorted(
                    [
                        (status, count)
                        for status, count in self.status_counters.items()
                        if count
                    ],
                    key=lambda couple: couple[0].value,
                )
                lines.append("Partial results:")
                if statuses:
                    for status, count in statuses:
                        lines.append(f"  {status.name.ljust(12)} {count}")
                else:
                    lines.append("  <none>")

        text = "\n".join(lines)
        with open(self.filename, "w") as f:
            f.write(text)


class TestsuiteCore:
    """Testsuite Core driver.

    This class is the base of Testsuite class and should not be instanciated.
    It's not recommended to override any of the functions declared in it.

    See documentation of Testsuite class for overridable methods and
    variables.
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        testsuite_name: str = "Untitled testsute",
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
        self.test_dir = os.path.join(self.root_dir, self.tests_subdir)
        logger.debug("Test directory: %s", self.test_dir)
        self.consecutive_failures = 0
        self.return_values: Dict[str, Any] = {}
        self.result_tracebacks: Dict[str, List[str]] = {}
        self.testsuite_name = testsuite_name

        self.aborted_too_many_failures = False
        """
        Whether the testsuite aborted because of too many consecutive test
        failures (see the --max-consecutive-failures command-line option).
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

    def job_factory(
        self,
        uid: str,
        data: Any,
        predecessors: FrozenSet[str],
        notify_end: Callable[[str], None],
    ) -> TestFragment:
        """Run internal function.

        See e3.job.scheduler
        """
        from e3.testsuite.fragment import FragmentData, TestFragment

        assert isinstance(data, FragmentData)

        # When passing return values from predecessors, remove current test
        # name from the keys to ease referencing by user (the short fragment
        # name can then be used by user without knowing the full node id).
        key_prefix = data.driver.test_name + "."
        key_prefix_len = len(key_prefix)

        def filter_key(k: str) -> str:
            if k.startswith(key_prefix):
                return k[key_prefix_len:]
            else:
                return k

        return TestFragment(
            uid,
            data.driver,
            data.callback,
            {filter_key(k): self.return_values[k] for k in predecessors},
            notify_end,
            self.running_status,
        )

    def testsuite_main(self, args: Optional[List[str]] = None) -> int:
        """Main for the main testsuite script.

        :param args: Command line arguments. If None, use `sys.argv`.
        :return: The testsuite status code (0 for success, a positive for
            failure).
        """
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
            "-d",
            "--dev-temp",
            nargs="?",
            default=None,
            const="tmp",
            help="Unlike --temp-dir, use this very directory to store"
            " testsuite temporaries (i.e. no random subdirectory). Also"
            " automatically disable temp dir cleanup, to be developer"
            " friendly. If no directory is provided, use the local"
            ' "tmp" directory',
        )
        temp_group.add_argument(
            "--disable-cleanup",
            dest="enable_cleanup",
            action="store_false",
            default=True,
            help="disable cleanup of working space",
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
        self.colors = ColorConfig(enable_colors)
        self.Fore = self.colors.Fore
        self.Style = self.colors.Style

        self.env = BaseEnv.from_env()
        self.env.enable_colors = enable_colors
        self.env.root_dir = self.root_dir
        self.env.test_dir = self.test_dir

        # Setup output directories and create an index for the results we are
        # going to produce.
        self.output_dir: str
        self.old_output_dir: Optional[str]
        self.setup_result_dirs()
        self.report_index = ReportIndex(self.output_dir)

        # Prepare the working directory, where tests will run. Keep the working
        # dir as short as possible, to avoid the risk of having a path that's
        # too long (a problem often seen on Windows, or when using WRS tools
        # that have their own max path limitations).
        #
        # Note that we do make sure that working_dir is an absolute path, as we
        # are likely to be changing directories when running each test. A
        # relative path would no longer work under those circumstances.
        if self.main.args.dev_temp:
            # Use a temporary directory for developers: make sure it is an
            # empty directory and disable cleanup to ease post-mortem
            # investigation.
            self.working_dir = os.path.abspath(self.main.args.dev_temp)
            rm(self.working_dir, recursive=True)
            mkdir(self.working_dir)
            self.main.args.enable_cleanup = False

        else:
            # If the temp dir is supposed to be randomized, we need to create a
            # subdirectory, so check that the parent directory exists first.
            if not os.path.isdir(self.main.args.temp_dir):
                logger.critical(
                    "temp dir '%s' does not exist", self.main.args.temp_dir
                )
                return 1

            self.working_dir = tempfile.mkdtemp(
                "", "tmp", os.path.abspath(self.main.args.temp_dir)
            )

        # Store in global env: target information and common paths
        self.env.output_dir = self.output_dir
        self.env.working_dir = self.working_dir
        self.env.options = self.main.args

        # Create an object to report testsuite execution status to users
        self.running_status = RunningStatus(
            os.path.join(self.output_dir, "status")
        )

        # User specific startup
        self.set_up()

        # Retrieve the list of test
        self.test_list = self.get_test_list(self.main.args.sublist)

        # Create a DAG to constraint the test execution order
        dag = DAG()
        for parsed_test in self.test_list:
            self.add_test(dag, parsed_test)
        self.adjust_dag_dependencies(dag)
        dag.check()
        self.running_status.set_dag(dag)

        # For debugging purposes, dump the final DAG to a DOT file
        with open(os.path.join(self.output_dir, "tests.dot"), "w") as fd:
            fd.write(dag.as_dot())

        # Create a scheduler to run all fragments for the testsuite main loop
        self.scheduler = Scheduler(
            job_provider=self.job_factory,
            tokens=self.main.args.jobs,
            # correct_result expects specifically TestFragment instances (a Job
            # subclass), while Scheduler only guarantees Job instances.
            # Test drivers are supposed to register only TestFragment
            # instances, so the following cast should be fine.
            collect=cast(Any, self.collect_result),
        )

        # Run the tests. Note that when the testsuite aborts because of too
        # many consecutive test failures, we still want to produce a report and
        # exit through regular ways, to catch KeyboardInterrupt exceptions,
        # which e3's scheduler uses to abort the execution loop, but only in
        # such cases. In other words, let the exception propagates if it's the
        # user that interrupted the testsuite.
        try:
            self.scheduler.run(dag)
        except KeyboardInterrupt:
            if not self.aborted_too_many_failures:  # interactive-only
                raise

        self.report_index.write()
        self.dump_testsuite_result()
        if self.main.args.xunit_output:
            dump_xunit_report(self, self.main.args.xunit_output)
        if self.main.args.gaia_output:
            dump_gaia_report(self, self.output_dir)

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
            with open(os.path.join(self.output_dir, "report"), "w") as f:
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

        # Return the appropriate status code: 1 when there is a framework
        # issue, the failure status code from the --failure-exit-code=N option
        # when there is a least one testcase failure, or 0.
        statuses = {
            s
            for s, count in self.report_index.status_counters.items()
            if count
        }
        if TestStatus.FAIL in statuses or TestStatus.ERROR in statuses:
            return self.main.args.failure_exit_code
        else:
            return 0

    def get_test_list(self, sublist: List[str]) -> List[ParsedTest]:
        """Retrieve the list of tests.

        :param sublist: A list of tests scenarios or patterns.
        """
        # Use a mapping: test name -> ParsedTest when building the result, as
        # several patterns in "sublist" may yield the same testcase.
        testcases: Dict[str, ParsedTest] = {}
        test_finders = self.test_finders
        dedicated_dirs_only = all(
            tf.test_dedicated_directory for tf in test_finders
        )

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
            for dirpath, dirnames, filenames in os.walk(
                root, followlinks=True
            ):
                # If all tests are guaranteed to have a dedicated directory,
                # do not process directories that don't match the requested
                # pattern.
                if dedicated_dirs_only and not matches_pattern(
                    pattern, dirpath
                ):
                    continue

                # The first test finder that has a match "wins". When handling
                # test data, we want to deal only with absolute paths, so get
                # the absolute name now.
                dirpath = os.path.abspath(dirpath)
                for tf in test_finders:
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

    def collect_result(self, job: TestFragment) -> bool:
        """Run internal function.

        :param job: A job that is finished.
        """
        assert self.main.args

        # Keep track of the number of consecutive failures seen so far if it
        # reaches the maximum number allowed, we must abort the testsuite.
        max_consecutive_failures = self.main.args.max_consecutive_failures
        consecutive_failures = 0

        self.return_values[job.uid] = job.return_value

        while job.driver.result_queue:
            result, tb = job.driver.result_queue.pop()

            self.add_result(result, tb)

            # Update the number of consecutive failures, aborting the testsuite
            # if appropriate
            if result.status in (TestStatus.ERROR, TestStatus.FAIL):
                consecutive_failures += 1
                if (
                    max_consecutive_failures > 0
                    and consecutive_failures >= max_consecutive_failures
                ):
                    self.aborted_too_many_failures = True
                    logger.error(
                        "Too many consecutive failures, aborting the testsuite"
                    )
                    raise KeyboardInterrupt
            else:
                consecutive_failures = 0

        return False

    def add_result(self, result: TestResult, tb: List[str]) -> None:
        """Add a test result to the result index and log it.

        :param result: Test result to add.
        :param tb: Traceback for the code that created this result, for
            debugging purposes.
        """
        assert self.main.args

        # The test results that reach this point are special: there were
        # serialized/deserialized through YAML, so the Log layer disappeared.
        assert result.status is not None

        # Log the test result. If error output is requested and the test
        # failed unexpectedly, show the detailed logs.
        log_line = summary_line(
            result, self.colors, self.main.args.show_time_info
        )
        if self.main.args.show_error_output and result.status not in (
            TestStatus.PASS,
            TestStatus.XFAIL,
            TestStatus.XPASS,
            TestStatus.SKIP,
        ):

            def format_log(log: Log) -> str:
                return "\n" + str(log) + self.Style.RESET_ALL

            if result.diff:
                log_line += format_log(result.diff)
            else:
                log_line += format_log(result.log)
        logger.info(log_line)

        def indented_tb(tb: List[str]) -> str:
            return "".join("  {}".format(line) for line in tb)

        assert result.test_name not in self.report_index.entries, (
            f"cannot push twice results for {result.test_name}"
            f"\nFirst push happened at:"
            f"\n{indented_tb(self.result_tracebacks[result.test_name])}"
            f"\nThis one happened at:"
            f"\n{indented_tb(tb)}"
        )
        self.report_index.add_result(result)
        self.result_tracebacks[result.test_name] = tb
        self.running_status.set_status_counters(
            self.report_index.status_counters
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
        result = TestResult(
            f"{test_name}__except{len(self.report_index.entries)}",
            env={},
            status=TestStatus.ERROR,
            msg=message,
        )
        if tb:
            result.log += tb
        self.add_result(result, traceback.format_stack())

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
        if (
            os.path.exists(old_output_dir)
            and os.path.exists(
                os.path.join(old_output_dir, ReportIndex.INDEX_FILENAME)
            )
        ):
            self.old_output_dir = old_output_dir

        if args.dump_environ:
            with open(os.path.join(self.output_dir, "environ.sh"), "w") as f:
                for var_name in sorted(os.environ):
                    f.write(
                        "export {}={}\n".format(
                            var_name, quote_arg(os.environ[var_name])
                        )
                    )

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

        if self.main.args.enable_cleanup:
            rm(self.working_dir, True)

    def write_comment_file(self, comment_file: IO[str]) -> None:
        # Sensible default: just write the command line used to run the
        # testsuite. Testsuites can override or reuse this.
        quoted_cmdline = " ".join(quote_arg(arg) for arg in sys.argv)
        comment_file.write(
            f"Testsuite options:"
            f"\n  {quoted_cmdline}"
            f"\n"
        )

    @property
    def default_max_consecutive_failures(self) -> int:
        return 0

    @property
    def default_failure_exit_code(self) -> int:
        return 0

    @property
    def auto_generate_text_report(self) -> bool:
        return False

    def adjust_dag_dependencies(self, dag: DAG) -> None:
        pass
