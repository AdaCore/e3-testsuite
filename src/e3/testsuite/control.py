from enum import Enum
import os.path

from e3.testsuite import logger
from e3.testsuite.optfileparser import OptFileParse


class TestControlKind(Enum):
    """Control how to run (or not!) testcases."""

    NONE = 0
    """Run the test the regular way."""

    SKIP = 1
    """Do not run the testcase, setting it SKIP."""

    XFAIL = 2
    """
    Run the test the regular way. If its status is PASS, correct it to
    XPASS. If it succeeds, correct it to XFAIL. Leave its status unchanged in
    other cases.
    """


class TestControl:
    """Control the execution and analysis of a testcase."""

    def __init__(self, message=None, skip=False, xfail=False):
        """Initialize a TestControl instance.

        :param None|str message: Optional message to convey with the test
            status.
        :param bool skip: Whether to skip the test execution.
        :param bool xfail: Whether we expect the test to fail. If the test
            should be skipped, and xfailed, we consider it failed even though
            it did not run.
        """
        self.skip = skip
        self.xfail = xfail
        self.message = message


class TestControlCreator:
    """Abstract class to create test controls."""

    def create(self, driver):
        """Create a TestControl instance for the given test driver.

        Raise a ValueError exception if the configuration is invalid.

        :param TestDriver driver: Test driver for which we must parse the
            "control" configuration.
        """
        raise NotImplementedError


class YAMLTestControlCreator(TestControlCreator):
    """Create test controls from "test.yaml"'s "control" entries."""

    def __init__(self, condition_env=None):
        """Initialize a YAMLTestControlCreator instance.

        :param None|dict condition_env: Environment to pass to condition
            evaluation in control entries. If None, use an empty dictionary.
        """
        self.condition_env = {} if condition_env is None else condition_env

    def create(self, driver):
        # If there is a "test.opt" file while the YAML "control" entry
        # mechanism is in use, it probably means someone mistakenly wrote a
        # test.opt file that will not be interpreted: be helpful and warn about
        # it.
        if os.path.exists(driver.test_dir("test.opt")):
            logger.warning(
                '{}: "test.opt" file found whereas only "control" entries are'
                ' considered'.format(driver.test_env["test_name"])
            )

        # Read the configuration from the test environment's "control" key, if
        # present.
        default = TestControl()
        try:
            control = driver.test_env["control"]
        except KeyError:
            return default

        # Variables available to entry conditions
        condition_env = dict(self.condition_env)
        condition_env["env"] = driver.env

        # First validate the whole control structure, and only then interpret
        # it, for the same reason an language interpreter checks the syntax
        # before starting the interpretation.
        #
        # We expect control to be a list of lists of strings. The top-level
        # list is a collection of "entries": each entry conditionally selects a
        # test behavior. Each entry (list of strings) have one of the following
        # format:
        #
        #    [kind, condition]
        #    [kind, condition, message]
        #
        # "kind" is the name of any of the TestControlKind values. "condition"
        # is a Python expression that determines whether the entry applies, and
        # the optional "message" is a free form text to track which entry was
        # selected.
        entries = []

        if not isinstance(control, list):
            raise ValueError("list expected at the top level")

        for i, entry in enumerate(control, 1):
            def error(message):
                raise ValueError("entry #{}: {}".format(i, message))

            if (
                not isinstance(entry, list)
                or not len(entry) in (2, 3)
                or any(not isinstance(s, str) for s in entry)
            ):
                error("list of 2 or 3 strings expected")

            # Decode the test control kind
            try:
                kind = TestControlKind[entry[0]]
            except KeyError:
                error("invalid kind: {}".format(entry[0]))

            # Evaluate the condition
            try:
                cond = eval(entry[1], condition_env)
            except Exception as exc:
                error("invalid condition ({}): {}"
                      .format(type(exc).__name__, exc))

            message = entry[2] if len(entry) > 2 else None

            entries.append((kind, cond, message))

        # Now, select the first entry whose condition is True. By default,
        # fallback to "default".
        for kind, cond, message in entries:
            if cond:
                skip, xfail = {
                    TestControlKind.NONE: (False, False),
                    TestControlKind.SKIP: (True, False),
                    TestControlKind.XFAIL: (False, True),
                }[kind]
                return TestControl(message, skip, xfail)
        return default


class AdaCoreLegacyTestControlCreator(TestControlCreator):
    """Create test controls for "test.opt"-based legacy AdaCore testsuites."""

    def default_script(self, driver):
        """Return the default test script filename.

        :param TestDriver driver: Test driver for which we must parse the
            "control" configuration.
        """
        # Use "test.cmd" by default. If it does not exist while there is a
        # "test.py" file, use that instead.
        if (
            not os.path.isfile(driver.test_dir("test.cmd"))
            and os.path.isfile(driver.test_dir("test.py"))
        ):
            return "test.py"
        return "test.cmd"

    def default_opt_results(self, driver):
        """Return the default options. test.opt files can override these.

        By default, a test is not DEAD, SKIP, nor XFAIL. Its execution timeout
        is 780 seconds. Test script is "test.cmd" and its output is compared
        against "test.out".

        :param TestDriver driver: Test driver for which we must parse the
            "control" configuration.
        """
        return {
            "RLIMIT": "780",
            "DEAD": None,
            "XFAIL": None,
            "SKIP": None,
            "OUT": "test.out",
            "CMD": self.default_script(driver),
            "FILESIZE_LIMIT": None,
            "TIMING": None,
            "NOTE": None,
        }

    def __init__(self, system_tags, opt_filename="test.opt"):
        """Initialize a OptfileTestControlCreator instance.

        :param str|list[str] system_tags: Tags to forward to OptFileParse().
        :param str opt_filename: Name of the file to parse, relative to the
            test directory.
        """
        self.opt_filename = opt_filename
        self.system_tags = system_tags

    def create(self, driver):
        # If there is a "control" entry in the testcase's test.yaml file while
        # the optfile mechanism is in use, it probably means someone mistakenly
        # wrote a "control" entry that will not be interpreted: be helpful and
        # warn about it.
        if "control" in driver.test_env:
            logger.warning(
                '{}: "control" entry found in test.yaml whereas only test.opt'
                ' files are considered'.format(driver.test_env["test_name"])
            )

        # If it exists, parse the "test.opt" file in the test directory.
        # Create a dummy optfile otherwise.
        filename = driver.test_dir(self.opt_filename)
        optfile = (OptFileParse(self.system_tags, filename)
                   if os.path.exists(filename)
                   else OptFileParse(self.system_tags, []))

        # Create a TestControl depending on the contents of the optfile
        message = None
        skip = False
        xfail = False
        opt_results = optfile.get_values(self.default_opt_results(driver))
        if opt_results["DEAD"] is not None:
            message = opt_results["DEAD"]
            skip = True
        elif opt_results["SKIP"] is not None:
            message = opt_results["SKIP"]
            skip = True
            xfail = True
        elif opt_results["XFAIL"] is not None:
            message = opt_results["XFAIL"]
            xfail = True
        result = TestControl(message, skip, xfail)

        # Store results in the TestControl instance, so that "driver" has
        # access to it.
        result.opt_results = opt_results

        return result
