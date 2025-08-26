"""Tests for the events notification system."""

from __future__ import annotations

import os
import dataclasses
import shlex
import sys

from e3.testsuite.driver import TestDriver as Driver
import e3.testsuite.driver.classic as classic
from e3.testsuite.result import TestResult as Result, TestStatus as Status

from .utils import create_testsuite, extract_results, run_testsuite


notify_script = os.path.join(os.path.dirname(__file__), "ts_notify_hook.py")


def test_basic(tmp_path):
    """Basic test for --notify-events."""

    # Define the set of tests/fragments to run, and the set of results they
    # emit. To have deterministic results, also define the order in which these
    # fragments are run.

    @dataclasses.dataclass(frozen=True)
    class Fragment:
        test_name: str
        fragment_name: str
        result_status: Status | None = None

        @property
        def uid(self):
            return f"{self.test_name}.{self.fragment_name}"

        @property
        def result_name(self):
            assert self.result_status is not None
            return (
                self.test_name
                if self.fragment_name == "run"
                else f"{self.test_name}.{self.fragment_name}"
            )

    fragments = [
        Fragment("t1", "set_up"),
        Fragment("t2", "sub1", Status.PASS),
        Fragment("t1", "run"),
        Fragment("t1", "analyze", Status.PASS),
        Fragment("t1", "tear_down"),
        Fragment("t2", "sub2", Status.FAIL),
        Fragment("t3", "run", Status.XPASS),
        Fragment("t2", "sub3", Status.XFAIL),
        Fragment("t4", "run"),
        Fragment("t2", "tear_down"),
        Fragment("t4", "tear_down"),
        Fragment("t5", "run", Status.SKIP),
    ]
    tests = sorted({fragment.test_name for fragment in fragments})

    class MyDriver(Driver):
        def add_test(self, dag):
            for fragment in fragments:
                if fragment.test_name == self.test_name:
                    self.add_fragment(
                        dag,
                        name=fragment.fragment_name,
                        fun=self.fragment_callback(fragment),
                    )

        def fragment_callback(self, fragment):
            def callback(prev, slot):
                if fragment.result_status is None:
                    return

                self.push_result(
                    Result(fragment.result_name, status=fragment.result_status)
                )

            return callback

    def adjust_dag_deps(testsuite, dag):
        for i, fragment in enumerate(fragments[:-1]):
            dag.update_vertex(
                vertex_id=fragments[i + 1].uid, predecessors=[fragment.uid]
            )

    notify_filename = tmp_path / "new" / "notifs.txt"
    notify_cmd = shlex.join(
        [sys.executable, notify_script, str(notify_filename)]
    )

    suite = run_testsuite(
        create_testsuite(tests, MyDriver, adjust_dag_deps=adjust_dag_deps),
        [
            "-j1",
            "--failure-exit-code=0",
            f"--output-dir={tmp_path}",
            "--notify-events=" + notify_cmd,
        ],
    )
    assert extract_results(suite) == {
        fragment.result_name: fragment.result_status
        for fragment in fragments
        if fragment.result_status is not None
    }
    with notify_filename.open() as f:
        notifs = [line.strip() for line in f.readlines()]
    assert notifs == [
        "--queue t1",
        "--queue t2",
        "--queue t3",
        "--queue t4",
        "--queue t5",
        "--start t1",
        "--start t2",
        "--result t2 t2.sub1 PASS",
        "--result t1 t1.analyze PASS",
        "--end t1",
        "--result t2 t2.sub2 FAIL",
        "--start t3",
        "--result t3 t3 XPASS",
        "--end t3",
        "--result t2 t2.sub3 XFAIL",
        "--start t4",
        "--end t2",
        "--end t4",
        "--start t5",
        "--result t5 t5 SKIP",
        "--end t5",
    ]


def test_crashing_cmd(caplog, tmp_path):
    """Test when the event notify command crashes."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            pass

    notify_cmd = shlex.join([sys.executable, notify_script, "--crash"])

    suite = run_testsuite(
        create_testsuite(["t1", "t2"], MyDriver),
        ["--notify-events=" + notify_cmd],
    )
    assert extract_results(suite) == {"t1": Status.PASS, "t2": Status.PASS}

    errors = [
        r.getMessage()
        for r in caplog.records
        if r.name == "testsuite" and r.levelname == "ERROR"
    ]
    # 4 notifications are triggered for each test (queue, start, result, end),
    # so for 2 tests we expect 8 errors.
    assert errors == ["Error while running the event notification command"] * 8
    caplog.clear()


def test_python_notify_callback(tmp_path):
    """Test passing a Python callback to --notify-events."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            pass

    sys.path.append(os.path.dirname(__file__))
    notify_cmd = "python:ts_notify_hook:create_notify_callback"
    notify_filename = tmp_path / "new" / "notifs_python.txt"

    suite = run_testsuite(
        create_testsuite(["t1"], MyDriver),
        [
            "-j1",
            "--failure-exit-code=0",
            f"--output-dir={tmp_path}",
            "--notify-events=" + notify_cmd,
        ],
    )
    assert extract_results(suite) == {"t1": Status.PASS}
    with notify_filename.open() as f:
        notifs = [line.strip() for line in f.readlines()]
    assert notifs == [
        "--queue t1",
        "--start t1",
        "--result t1 t1 PASS",
        "--end t1",
    ]


def test_invalid_python_callback(caplog, tmp_path):
    """Test passing invalid Python callbacks to --notify-events."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            pass

    sys.path.append(os.path.dirname(__file__))

    for cmd, error in [
        (
            "python:invalid-syntax1:foo",
            "Wrong format: 'python:invalid-syntax1:foo'",
        ),
        (
            "python:invalid_syntax1.foo",
            "Wrong format: 'python:invalid_syntax1.foo'",
        ),
        (
            "python:no_such_module:foo",
            "Cannot load module 'no_such_module'",
        ),
        (
            "python:ts_notify_hook:foo",
            "Cannot load callback 'foo'",
        ),
        (
            "python:ts_notify_hook:invalid_cb_creator",
            "Cannot create notification callback",
        ),
    ]:
        run_testsuite(
            create_testsuite(["t1"], MyDriver),
            ["--notify-events=" + cmd],
            expect_failure=True,
        )
        errors = [
            r.getMessage()
            for r in caplog.records
            if r.name == "testsuite" and r.levelname == "ERROR"
        ]
        assert errors == [error]
        caplog.clear()


def test_crashing_python_callback(caplog, tmp_path):
    """Test when the Python event notify callback crashes."""

    class MyDriver(classic.ClassicTestDriver):
        def run(self):
            pass

    sys.path.append(os.path.dirname(__file__))

    suite = run_testsuite(
        create_testsuite(["t1", "t2"], MyDriver),
        ["--notify-events=python:ts_notify_hook:create_crashing_callback"],
    )
    assert extract_results(suite) == {"t1": Status.PASS, "t2": Status.PASS}

    errors = [
        r.getMessage()
        for r in caplog.records
        if r.name == "testsuite" and r.levelname == "ERROR"
    ]
    # 4 notifications are triggered for each test (queue, start, result, end),
    # so for 2 tests we expect 8 errors.
    assert (
        errors == ["Error while executing the event notification callback"] * 8
    )
    caplog.clear()
