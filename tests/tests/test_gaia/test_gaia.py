"""Test for --gaia-output."""

import os.path

from e3.testsuite import Testsuite as Suite
from e3.testsuite.driver import BasicTestDriver as BasicDriver
from e3.testsuite.result import FailureReason, Log, TestStatus as Status


class TestGAIA:
    class MyDriver(BasicDriver):
        """Dummy driver, push a result built from the test environment."""

        def run(self, prev, slot):
            pass

        def analyze(self, prev, slot):
            status = Status[self.test_env["status"]]
            message = self.test_env.get("message", None)
            self.result.set_status(status, message)

            self.result.failure_reasons = {
                FailureReason[r] for r in self.test_env.get("reasons", [])
            }

            def to_log(key):
                content = self.test_env.get(key)
                return None if content is None else Log(content)

            self.result.log = to_log("log")
            self.result.expected = to_log("expected")
            self.result.out = to_log("out")
            self.result.diff = to_log("diff")

            self.result.time = self.test_env.get("time")
            self.result.info = self.test_env.get("info")

            self.push_result()

    def test(self):
        class Mysuite(Suite):
            test_driver_map = {"mydriver": self.MyDriver}
            default_driver = "mydriver"

        # Run the testsuite, expecting no failure
        suite = Mysuite(os.path.dirname(__file__))
        assert suite.testsuite_main(["--gaia-output"]) == 1

        # Check the content of the GAIA output: first, the summary
        with open(os.path.join("out", "new", "results")) as f:
            lines = sorted(f.read().splitlines())
            assert lines == [
                "fail-binary-out:FAIL:",
                "fail-crash:CRASH:",
                "fail-expected-out-diff:FAIL:",
                "fail-info:FAIL:",
                "fail-memcheck-diff:PROBLEM:",
                "fail-out:FAIL:",
                "fail-simple:FAIL:",
                "fail-timeout:TIMEOUT:",
                "not_applicable:NOT-APPLICABLE:",
                "pass-log:OK:",
                "pass-time:OK:",
                "pass:OK:",
                "skip:DEAD:This test was skipped",
                "xfail-crash:XFAIL:",
                "xfail-out:XFAIL:",
            ]

        # Check the presence and content of log files
        def check_logs(
            test_name,
            *,
            log=None,
            expected=None,
            out=None,
            diff=None,
            time=None,
            info=None
        ):
            for extension, content in [
                (".log", log),
                (".expected", expected),
                (".out", out),
                (".diff", diff),
                (".time", time),
                (".info", info),
            ]:
                filename = os.path.join("out", "new", test_name + extension)
                mode = "r" if isinstance(content, str) else "rb"
                if content is None:
                    assert not os.path.exists(filename)
                else:
                    with open(filename, mode) as f:
                        assert content == f.read()

        check_logs("fail-binary-out", out=b"h\xe9llo")
        check_logs("fail-crash")
        check_logs(
            "fail-expected-out-diff",
            expected="expected\noutput",
            out="actual\noutput",
            diff="-expected\n+actual\n output",
        )
        check_logs("fail-info", info="key1:value1\nkey2:value2")
        check_logs("fail-memcheck-diff")
        check_logs("fail-out", out="output of failed testcase\n")
        check_logs("fail-simple")
        check_logs("fail-timeout")
        check_logs("not_applicable")
        check_logs("pass-log", log="Log for a successful test.\n")
        check_logs("pass-time", time="1.230000000")
        check_logs("pass")
        check_logs("skip")
        check_logs("xfail-crash")
        check_logs("xfail-out", out="Output of failing test in expected way")
