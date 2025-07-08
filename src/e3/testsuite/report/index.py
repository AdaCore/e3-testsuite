"""Lightweight index for test results.

Loading all test results for big testsuites can take a lot of time because of
all the YAML parsing involved. This module provides helpers to efficiently read
and write an index of test results. This index contains only test names,
statuses and messages, so it is super fast to read. From there, users can load
individual test full results only when needed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os.path
from typing import Dict, List, Optional, Set

from e3.testsuite.result import (
    FailureReason,
    TestResult,
    TestResultSummary,
    TestStatus,
)


@dataclass
class ReportIndexEntry:
    """ReportIndex entry for a single test result."""

    index: ReportIndex
    summary: TestResultSummary
    filename: str

    @property
    def test_name(self) -> str:
        return self.summary.test_name

    @property
    def status(self) -> TestStatus:
        return self.summary.status

    @property
    def msg(self) -> Optional[str]:
        return self.summary.msg

    @property
    def failure_reasons(self) -> Set[FailureReason]:
        return self.summary.failure_reasons

    @property
    def time(self) -> Optional[float]:
        return self.summary.time

    @property
    def info(self) -> Dict[str, str]:
        return self.summary.info

    def load(self) -> TestResult:
        result = TestResult.load(
            os.path.join(self.index.results_dir, self.filename)
        )
        assert self.summary == result.summary
        return result


class ReportIndex:
    """Lightweight index for test results."""

    INDEX_FILENAME = "_index.json"
    INDEX_MAGIC = "e3.testsuite.report.index.ReportIndex:1"

    def __init__(self, results_dir: str) -> None:
        """Initialize a ReportIndex instance."""
        self.results_dir = results_dir
        """Directory that contain test results (YAML files)."""

        self.entries: Dict[str, ReportIndexEntry] = {}
        """Map test names to their ReportIndexEntry instances."""

        self.status_counters = {s: 0 for s in TestStatus}
        """Number of test result for each test status."""

        self.duration: Optional[float] = None
        """
        Optional number of seconds for the total duration of the testsuite run.
        """

    def save_and_add_result(self, result: TestResult) -> None:
        """Save a test result in the results directory and add it to the index.

        :param result: Test result to save/add.
        """
        self.add_result(result.summary, result.save(self.results_dir))

    def add_result(self, result: TestResultSummary, filename: str) -> None:
        """Add an entry to this index for the given test result.

        Note that unlike ``save_and_add_result``, this does not write the
        result data in the results dir: it is up to the caller to make sure of
        that.

        :param result: Result to add.
        :param filename: Name of the file that contains test result data.
        """
        entry = ReportIndexEntry(self, result, filename)
        self.entries[result.test_name] = entry
        self.status_counters[result.status] += 1

    @classmethod
    def read(cls, results_dir: str) -> ReportIndex:
        """Read the index in the given results directory."""
        result = cls(results_dir)

        with open(os.path.join(results_dir, cls.INDEX_FILENAME)) as f:
            doc = json.load(f)

        # Pick the optional testsuite duration. Even though we now always
        # include this information (either a float or null) in the index JSON,
        # we still want to be able to read indexes from old versions of
        # e3-testsuite.
        duration = doc.get("duration")
        if duration is not None:
            result.duration = float(duration)

        # Basic sanity checking on the index file format
        assert (
            isinstance(doc, dict) and doc["magic"] == cls.INDEX_MAGIC
        ), "Invalid index file format"

        # Import all entries
        for e in doc["entries"]:
            result.add_result(
                TestResultSummary(
                    e["test_name"],
                    TestStatus[e["status"]],
                    e["msg"],
                    {FailureReason[fr] for fr in e["failure_reasons"]},
                    e["time"],
                    e["info"],
                ),
                e["filename"],
            )

        return result

    def write(self) -> None:
        """Write the index on disk."""
        # Create the JSON document to be the index file content
        entries: List[dict] = []
        doc = {
            "magic": self.INDEX_MAGIC,
            "duration": self.duration,
            "entries": entries,
        }
        for e in self.entries.values():
            entries.append(
                {
                    "test_name": e.test_name,
                    "status": e.status.name,
                    "msg": e.msg,
                    "failure_reasons": [fr.name for fr in e.failure_reasons],
                    "time": e.time,
                    "info": e.info,
                    "filename": e.filename,
                }
            )

        # Actually write the file
        with open(
            os.path.join(self.results_dir, self.INDEX_FILENAME), "w"
        ) as f:
            json.dump(doc, f)

    @property
    def has_failures(self) -> bool:
        """Return whether there is at least one FAIL/ERROR test status."""
        return (
            self.status_counters[TestStatus.FAIL] > 0
            or self.status_counters[TestStatus.ERROR] > 0
        )
