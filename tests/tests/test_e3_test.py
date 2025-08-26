"""Tests for the e3-test script."""

import sys

import yaml

from e3.fs import cp, mkdir
from e3.testsuite import Testsuite as Suite
import e3.testsuite.driver.classic as classic
from e3.testsuite.main import main
from e3.testsuite.result import TestStatus as Status


if __name__ == "__main__":

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            pass

    class MySuite(Suite):
        tests_subdir = "tests"
        test_driver_map = {"my_driver": MyDriver}

    sys.exit(MySuite().testsuite_main())


from .utils import chdir_ctx, check_result_dirs


def setup_testsuite(tmp_path, **config):
    """Set up the testsuite tree under the given temporary directory."""
    # Copy this file to act at the testsuite script (see the __name__ check
    # above).
    cp(__file__, str(tmp_path / "run.py"))

    # Create the hierarchy of test directories
    for test_dir in [
        "tests/a",
        "tests/b",
        "tests/c/0",
        "tests/c/1",
        "tests/c/2",
    ]:
        p = tmp_path / test_dir
        mkdir(p)
        with (p / "test.yaml").open("w") as f:
            yaml.dump({"driver": "my_driver"}, f)

    with (tmp_path / "e3-test.yaml").open("w") as f:
        yaml.dump({"main": "run.py", **config}, f)


def test_root_dir(caplog, tmp_path):
    """Check root directory computation for e3-test."""
    setup_testsuite(tmp_path)

    # e3-tests is expected to run all tests present in the current working
    # directory as well as in its subdirectories.
    for cwd, *expected_results in [
        ("tests/a", "a"),
        ("tests/b", "b"),
        ("tests/c", "c__0", "c__1", "c__2"),
        ("tests/c/0", "c__0"),
        ("tests/c/1", "c__1"),
        ("tests/c/2", "c__2"),
    ]:
        with chdir_ctx(tmp_path / cwd):
            assert main() == 0
            check_result_dirs(
                new={t: Status.PASS for t in expected_results},
                new_dir=str(tmp_path / "out" / "new"),
            )


def test_default_args(caplog, tmp_path):
    """Check handling for the default_args entry in e3-test.yaml."""
    setup_testsuite(tmp_path, default_args=["-o", "my_results"])
    with chdir_ctx(tmp_path / "tests" / "b"):
        assert main() == 0
        check_result_dirs(
            new={"b": Status.PASS},
            new_dir=str(tmp_path / "my_results" / "new"),
        )


def test_invalid_e3_test_yaml(caplog, tmp_path):
    """Check validation code for missing/incorrect e3-test.yaml files."""

    def check_errors(messages):
        assert main() == 1
        assert [
            r.getMessage() for r in caplog.records if r.levelname == "ERROR"
        ] == messages
        caplog.clear()

    with chdir_ctx(tmp_path):
        # Missing e3-test.yaml
        check_errors(["cannot find e3-test.yaml"])

        # Missing "main" entry
        with (tmp_path / "e3-test.yaml").open("w") as f:
            yaml.dump({"dummy": None}, f)

        check_errors(["cannot find testsuite main"])
