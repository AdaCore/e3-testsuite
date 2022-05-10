"""Tests for the results output facilities."""

import os.path
import shutil

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import TestDriver as Driver
from e3.testsuite.result import TestStatus as Status

from .utils import check_result_dirs, run_testsuite


# Helpers for all tests in this module


class MyDriver(Driver):
    def add_test(self, dag):
        self.add_fragment(dag, "run")

    def run(self, prev, slot):
        self.result.set_status(self.env.return_status)
        self.push_result()


class Mysuite(Suite):
    tests_subdir = "simple-tests"
    test_driver_map = {"default": MyDriver}
    default_driver = "default"

    def add_options(self, parser):
        parser.add_argument("return_status")

    def set_up(self):
        self.env.return_status = Status[self.main.args.return_status]


results_pass = {"test1": Status.PASS, "test2": Status.PASS}
results_fail = {"test1": Status.FAIL, "test2": Status.FAIL}
results_skip = {"test1": Status.SKIP, "test2": Status.SKIP}


def run(status, args=None, expect_failure=False):
    args = args if args is not None else []
    run_testsuite(
        Mysuite, args=args + [status.name], expect_failure=expect_failure
    )


# Actual tests


def test_default():
    """Check that with default options, results only get overwritten."""
    # Do a first testsuite run, checking the results
    run(Status.PASS)
    check_result_dirs(new=results_pass)
    assert not os.path.exists(os.path.join("out", "old"))

    # Then do a second one. We expect the "new" directory to just get replaced,
    # and still have no "old" directory.
    run(Status.FAIL, expect_failure=True)
    check_result_dirs(new=results_fail)
    assert not os.path.exists(os.path.join("out", "old"))


def test_output_dir(tmp_path):
    """Check that --output-dir alone behaves as expected."""
    args = ["--output-dir", str(tmp_path)]
    new_dir = str(tmp_path / "new")
    old_path = tmp_path / "old"

    # Do a first testsuite run, checking the results
    run(Status.PASS, args)
    check_result_dirs(new=results_pass, new_dir=new_dir)
    assert not old_path.exists()

    # Run it a second time. We expect the new results to replace the previous
    # ones in the "new" directory and still not to have any old results.
    run(Status.FAIL, args, expect_failure=True)
    check_result_dirs(new=results_fail, new_dir=new_dir)
    assert not old_path.exists()


def test_rotation(tmp_path):
    """Check that results rotation works as expected."""

    def do_reset():
        shutil.rmtree(str(tmp_path))
        tmp_path.mkdir()

    def check(args, new_dir, old_dir, reset=True):
        if reset:
            do_reset()

        # Do a first testsuite run, checking the results
        run(Status.PASS, args)
        check_result_dirs(new=results_pass, new_dir=new_dir)
        assert not os.path.exists(old_dir)

        # Run it a second time. We expect the previous "new" directory to be
        # renamed to "old", and the new results to be written to a fresh "new"
        # directory.
        run(Status.FAIL, args, expect_failure=True)
        check_result_dirs(
            new=results_fail,
            new_dir=new_dir,
            old=results_pass,
            old_dir=old_dir,
        )

        # Run it a third time. We expect:
        #
        # * the previous "old" directory to be removed
        # * the previous "new" directory to be renamed to "old"
        # * the new results to be written to a fresh "new" directory.
        run(Status.SKIP, args)
        check_result_dirs(
            new=results_skip,
            new_dir=new_dir,
            old=results_fail,
            old_dir=old_dir,
        )

    # Check log rotation with...

    # ... default output directories (out/new and out/old)
    saved_cwd = os.getcwd()
    os.chdir(str(tmp_path))
    try:
        check(
            args=["--rotate-output-dirs"],
            new_dir=str(tmp_path / "out" / "new"),
            old_dir=str(tmp_path / "out" / "old"),
            reset=False,
        )
    finally:
        os.chdir(saved_cwd)

    # ... output directory only (new and old are subdirectories)
    check(
        args=["--rotate-output-dirs", "--output-dir", str(tmp_path / "foo")],
        new_dir=str(tmp_path / "foo" / "new"),
        old_dir=str(tmp_path / "foo" / "old"),
    )

    # ... both explicit output directory and old output directory
    check(
        args=[
            "--rotate-output-dirs",
            "--output-dir",
            str(tmp_path / "foo"),
            "--old-output-dir",
            str(tmp_path / "bar"),
        ],
        new_dir=str(tmp_path / "foo"),
        old_dir=str(tmp_path / "bar"),
    )


def test_empty_old_output_dir_report(tmp_path):
    """Check text report generation with an empty old output dir.

    The testsuite framework used to crash in such a case.
    """
    new_dir = tmp_path / "new"
    old_path = tmp_path / "old"
    old_path.mkdir()

    args = [
        f"--output-dir={new_dir}",
        f"--old-output-dir={old_path}",
        "--generate-text-report",
    ]
    run(Status.PASS, args)
