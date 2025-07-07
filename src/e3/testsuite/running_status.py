from __future__ import annotations

"""
RunningStatus keeps users informed about the progress of testsuite execution
and aborts when there are too many consecutive failures/errors (see the
--max-consecutive-failures command-line option).
"""

from typing import Dict, Optional, TYPE_CHECKING
import threading
import time

from e3.testsuite.result import TestResultSummary, TestStatus


if TYPE_CHECKING:
    from e3.collection.dag import DAG
    from e3.testsuite.fragment import TestFragment


class RunningStatus:
    def __init__(
        self,
        filename: str,
        update_interval: float = 1.0,
        max_consecutive_failures: int = 0,
    ):
        """RunningStatus constructor.

        :param filename: Name of the status file to write.
        :param update_interval: Minimum number of seconds between status file
            updates.
        :param max_consecutive_failures:
            Number of test failures (FAIL or ERROR) that trigger the abortion
            of the testuite. If zero, this behavior is disabled.
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

        self.update_interval = update_interval
        self.no_update_before = 0.0

        self.max_consecutive_failures = max_consecutive_failures

        self.consecutive_failures = 0
        """
        Number of consecutive failure/error results we just processed. Used to
        abort the testsuite when there are too many issues.
        """

        self.aborted_too_many_failures = False
        """
        Whether the testsuite aborted because of too many consecutive test
        failures (see the --max-consecutive-failures command-line option).
        """

    def set_dag(self, dag: DAG) -> None:
        """Set the DAG that contains TestFragment instances."""
        assert self.dag is None
        self.dag = dag

    def start(self, fragment: TestFragment) -> None:
        """Put a fragment in the "running" set."""
        assert self.dag is not None
        driver = fragment.driver

        with self.lock:
            assert fragment.uid in self.dag.vertex_data
            assert fragment.uid not in self.running
            assert fragment.uid not in self.completed
            self.running[fragment.uid] = fragment

            fragment.started_test = not driver.execution_started
            driver.execution_started = True
        self.dump()

    def complete(self, fragment: TestFragment) -> None:
        """Move a fragment from the "running" set to the "completed" set."""
        assert self.dag is not None
        driver = fragment.driver

        with self.lock:
            assert fragment.uid in self.dag.vertex_data
            assert fragment.uid not in self.completed
            f = self.running.pop(fragment.uid)
            assert f is fragment
            self.completed[f.uid] = f

            driver.pending_fragments.remove(fragment.uid)
            fragment.ended_test = not driver.pending_fragments

        self.dump()

    def process_result(self, result: TestResultSummary) -> None:
        """Integrate a test result in the testsuite status.

        This increments status counters and triggers testsuite abortion if
        there were too many consecutive failures.
        """
        with self.lock:
            try:
                self.status_counters[result.status] += 1
            except KeyError:
                self.status_counters[result.status] = 1

            # Keep track of the number of consecutive failures seen so far: if
            # it reaches the maximum number allowed, we must abort the
            # testsuite.
            if result.status in (TestStatus.ERROR, TestStatus.FAIL):
                self.consecutive_failures += 1
                if (
                    not self.aborted_too_many_failures
                    and self.max_consecutive_failures > 0
                    and (
                        self.consecutive_failures
                        >= self.max_consecutive_failures
                    )
                ):
                    from e3.testsuite import logger

                    self.aborted_too_many_failures = True
                    logger.error(
                        "Too many consecutive failures, aborting the testsuite"
                    )
            else:
                self.consecutive_failures = 0

        self.dump()

    def dump(self) -> None:
        """Write a report for this status as human-readable text to "fp"."""
        # Do not update the status file more than once per second
        now = time.time()
        if self.update_interval and now < self.no_update_before:
            return
        self.no_update_before = now + self.update_interval

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
