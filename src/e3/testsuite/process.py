"""Helpers for test drivers to spawn subprocesses.

Not only these lack documentation, these helpers as they are today are very
incomplete. For instance, it is not possible to disable relocated builds in
"gprbuild". So consider these as experimental and likely to break in the
future: use at your own risk.
"""

import os

from e3.fs import mkdir
from e3.os.process import Run
from e3.testsuite import TestAbort
from e3.testsuite.result import Log, TestStatus


def check_call(driver, cmd, test_name=None, result=None, **kwargs):
    if "cwd" not in kwargs and "working_dir" in driver.test_env:
        kwargs["cwd"] = driver.test_env["working_dir"]
    if result is None:
        result = driver.result
    if test_name is None:
        test_name = driver.test_name
    process = Run(cmd, **kwargs)
    result.processes.append(
        {
            "output": Log(process.out),
            "status": process.status,
            "cmd": cmd,
            "run_args": kwargs,
        }
    )

    # Append the status code and process output to the log to ease post-mortem
    # investigation.
    result.log += "Status code: {}\n".format(process.status)
    result.log += "Output:\n"
    result.log += process.out

    if process.status != 0:
        result.set_status(TestStatus.FAIL, "command call fails")
        driver.push_result(result)
        raise TestAbort
    return process


def gprbuild(driver, project_file=None, cwd=None, gcov=False):
    if project_file is None:
        project_file = os.path.join(driver.test_env["test_dir"], "test.gpr")
    if cwd is None:
        cwd = driver.test_env["working_dir"]
    mkdir(cwd)
    gprbuild_cmd = ["gprbuild", "--relocate-build-tree", "-p",
                    "-P", project_file]
    if gcov:
        gprbuild_cmd += ["-largs", "-lgcov"]
    check_call(driver, gprbuild_cmd, cwd=cwd)
    return True
