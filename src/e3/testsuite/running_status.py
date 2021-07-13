from __future__ import annotations

"""
RunningStatus keep users informed about the progress of testsuite execution.
"""

from typing import Dict, Optional, TYPE_CHECKING
import threading


if TYPE_CHECKING:
    from e3.collection.dag import DAG
    from e3.testsuite.fragment import TestFragment
    from e3.testsuite.result import TestStatus


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
