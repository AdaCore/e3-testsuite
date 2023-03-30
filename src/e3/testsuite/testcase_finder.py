from __future__ import annotations

import collections.abc
from dataclasses import dataclass
import os.path
import re
from typing import List, Optional, TYPE_CHECKING, Type, Union

from e3.env import Env
import e3.yaml

from e3.testsuite.driver import TestDriver

if TYPE_CHECKING:
    from e3.testsuite import TestsuiteCore


@dataclass
class ParsedTest:
    """Basic information to instantiate a test driver."""

    test_name: str
    """Name for this testcase."""

    driver_cls: Optional[Type[TestDriver]]
    """Test driver class to instantiate, None to use the default one."""

    test_env: dict
    """Base test environment.

    Driver instantiation will complete it with test directory, test name, etc.
    """

    test_dir: str
    """Directory that contains the testcase."""

    test_matcher: Optional[str] = None
    """Textual text matcher.

    If not None, string to match against the list of requested tests to run: in
    that case, the test is ignored if there is no match. This is needed to
    filter out tests in testsuites where tests don't necessarily have dedicated
    directories.
    """


TestFinderResult = Union[Optional[ParsedTest], List[ParsedTest]]


class ProbingError(Exception):
    """Exception raised in TestFinder.probe when a test is misformatted."""

    pass


class TestFinder:
    """Interface for objects that find testcases in the tests subdirectory."""

    @property
    def test_dedicated_directory(self) -> bool:
        """Return whether each test has a dedicated test directory.

        Even though e3-testsuite is primarily designed for this to be true,
        some testsuites actually host multiple tests in the same directory.
        When this is the case, we need to probe all directories and only then
        filter which test to run using ParsedTest.test_matcher.
        """
        return True

    def probe(
        self,
        testsuite: TestsuiteCore,
        dirpath: str,
        dirnames: List[str],
        filenames: List[str],
    ) -> TestFinderResult:
        """Return a test if the "dirpath" directory contains a testcase.

        Raise a ProbingError if anything is wrong.

        :param testsuite: Testsuite instance that is looking for testcases.
        :param dirpath: Directory to probe for a testcase.
        :param dirnames: List of directories that "dirpath" contains.
        :param filenames: List of files that "dirpath" contains.
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

    def probe(
        self,
        testsuite: TestsuiteCore,
        dirpath: str,
        dirnames: List[str],
        filenames: List[str],
    ) -> TestFinderResult:
        # There is a testcase iff there is a "test.yaml" file
        if "test.yaml" not in filenames:
            return None
        test_name = testsuite.test_name(dirpath)
        yaml_file = os.path.join(dirpath, "test.yaml")

        # Load the YAML file to build the test environment
        try:
            test_env = e3.yaml.load_with_config(yaml_file, Env().to_dict())
        except e3.yaml.YamlError as exc:
            raise ProbingError("invalid syntax for test.yaml") from exc

        # Ensure that the test_env act like a dictionary. We still accept None
        # as it's a shortcut for "just use default driver" configuration files.
        if test_env is None:
            test_env = {}
        elif not isinstance(test_env, collections.abc.Mapping):
            raise ProbingError("invalid format for test.yaml")

        driver_name = test_env.get("driver")
        if driver_name is None:
            driver_cls = None
        else:
            try:
                driver_cls = testsuite.test_driver_map[driver_name]
            except KeyError as exc:
                raise ProbingError("cannot find driver") from exc

        return ParsedTest(test_name, driver_cls, test_env, dirpath)


class AdaCoreLegacyTestFinder(TestFinder):
    """Look for testcases in directories whose name matches a Ticket Number."""

    TN_RE = re.compile("[0-9A-Z]{2}[0-9]{2}-[A-Z0-9]{3}")

    def __init__(self, driver_cls: Type[TestDriver]) -> None:
        """
        Initialize an AdaCoreLegacyTestFinder instance.

        :param driver_cls: TestDriver subclass to use for all tests that are
            found.
        """
        self.driver_cls = driver_cls

    def probe(
        self,
        testsuite: TestsuiteCore,
        dirpath: str,
        dirnames: List[str],
        filenames: List[str],
    ) -> TestFinderResult:
        # There is a testcase iff the test directory name is a valid TN
        dirname = os.path.basename(dirpath)
        if not self.TN_RE.match(dirname):
            return None

        return ParsedTest(dirname, self.driver_cls, {}, dirpath)
