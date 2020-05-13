import collections.abc
import os.path
import re

from e3.env import Env
import e3.yaml


class ParsedTest:
    """Basic information to instantiate a test driver."""

    def __init__(self, test_name, driver_cls, test_env, test_dir):
        """
        Initialize a ParsedTest instance.

        :param str test_name: Name for this testcase.
        :param None|TestDriver driver_cls: Test driver class to instantiate,
            None to use the default one.
        :param dict test_env: Base test environment. Driver instantiation will
            complete it with test directory, test name, etc.
        :param str test_dir: Directory that contains the testcase.
        """
        self.test_name = test_name
        self.driver_cls = driver_cls
        self.test_env = test_env
        self.test_dir = test_dir


class ProbingError(Exception):
    """Exception raised in TestFinder.probe when a test is misformatted."""

    pass


class TestFinder:
    """Interface for objects that find testcases in the tests subdirectory."""

    def probe(self, testsuite, dirpath, dirnames, filenames):
        """Return a test if the "dirpath" directory contains a testcase.

        Raise a ProbingError if anything is wrong.

        :param e3.testsuite.Testsuite testsuite: Testsuite instance that is
            looking for testcases.
        :param str dirpath: Directory to probe for a testcase.
        :param list[str] dirnames: List of directories that "dirpath" contains.
        :param list[str] filenames: List of files that "dirpath" contains.

        :rtype: None|ParsedTest
        """
        raise NotImplementedError


class YAMLTestFinder(TestFinder):
    """
    Look for "test.yaml"-based tests.

    This considers that all directories that contain a "test.yaml" file are
    testcases. This file is parsed as YAML, the result is used as a test
    environment, and if it contains a "driver" key, it uses the testsuite
    driver whose name corresponds to the associated string value.
    """

    def probe(self, testsuite, dirpath, dirnames, filenames):
        # There is a testcase iff there is a "test.yaml" file
        if "test.yaml" not in filenames:
            return None
        test_name = testsuite.test_name(dirpath)
        yaml_file = os.path.join(dirpath, "test.yaml")

        # Load the YAML file to build the test environment
        try:
            test_env = e3.yaml.load_with_config(yaml_file, Env().to_dict())
        except e3.yaml.YamlError:
            raise ProbingError(
                "invalid syntax for test.yaml in '{}'".format(test_name)
            )

        # Ensure that the test_env act like a dictionary. We still accept None
        # as it's a shortcut for "just use default driver" configuration files.
        if test_env is None:
            test_env = {}
        elif not isinstance(test_env, collections.abc.Mapping):
            raise ProbingError(
                "invalid format for test.yaml in '{}'".format(test_name)
            )

        driver_name = test_env.get("driver")
        if driver_name is None:
            driver_cls = None
        else:
            try:
                driver_cls = testsuite.test_driver_map[driver_name]
            except KeyError:
                raise ProbingError(
                    "cannot find driver for test '{}'".format(test_name)
                )

        return ParsedTest(test_name, driver_cls, test_env, dirpath)


class AdaCoreLegacyTestFinder(TestFinder):
    """Look for testcases in directories whose name matches a Ticket Number."""

    TN_RE = re.compile("[0-9A-Z]{2}[0-9]{2}-[A-Z0-9]{3}")

    def __init__(self, driver_cls):
        """
        Initialize an AdaCoreLegacyTestFinder instance.

        :param e3.testsuite.driver.TestDriver driver_cls: TestDriver subclass
            to use for all tests that are found.
        """
        self.driver_cls = driver_cls

    def probe(self, testsuite, dirpath, dirnames, filenames):
        # There is a testcase iff the test directory name is a valid TN
        dirname = os.path.basename(dirpath)
        if not self.TN_RE.match(dirname):
            return None

        return ParsedTest(dirname, self.driver_cls, {}, dirpath)
