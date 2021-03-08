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
from typing import Dict, List, Optional
import yaml

from e3.testsuite.result import TestResult, TestStatus


@dataclass
class ReportIndexEntry:
    """ReportIndex entry for a single test result."""

    index: ReportIndex
    test_name: str
    status: TestStatus
    msg: Optional[str]

    def load(self) -> TestResult:
        with open(self.index.result_filename(self.test_name), "rb") as f:
            result = yaml.safe_load(f)
        assert isinstance(result, TestResult)
        assert result.test_name == self.test_name
        assert result.status == self.status
        assert result.msg == self.msg
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

    def add_result(self, test_result: TestResult) -> None:
        """Add an entry to this index for the given test result.

        Note that this writes the result data in the results dir.
        """
        assert isinstance(test_result.test_name, str)
        self._add_entry(
            test_result.test_name, test_result.status, test_result.msg
        )
        with open(self.result_filename(test_result.test_name), "w") as fd:
            yaml.dump(test_result, fd)

    def _add_entry(self,
                   test_name: str,
                   status: TestStatus,
                   msg: Optional[str],
                   write_on_disk: bool = False) -> None:
        """Add an entry to this index."""
        entry = ReportIndexEntry(self, test_name, status, msg)
        self.entries[entry.test_name] = entry
        self.status_counters[entry.status] += 1

    @classmethod
    def read(cls, results_dir: str) -> ReportIndex:
        """Read the index in the given results directory."""
        result = cls(results_dir)

        with open(os.path.join(results_dir, cls.INDEX_FILENAME)) as f:
            doc = json.load(f)

        # Basic sanity checking on the index file format
        assert isinstance(doc, dict) and doc["magic"] == cls.INDEX_MAGIC, (
            "Invalid index file format"
        )

        # Import all entries
        for e in doc["entries"]:
            result._add_entry(
                e["test_name"],
                TestStatus[e["status"]],
                e["msg"]
            )

        return result

    def write(self) -> None:
        """Write the index on disk."""
        # Create the JSON document to be the index file content
        entries: List[dict] = []
        doc = {"magic": self.INDEX_MAGIC, "entries": entries}
        for e in self.entries.values():
            entries.append(
                {
                    "test_name": e.test_name,
                    "status": e.status.name,
                    "msg": e.msg,
                }
            )

        # Actually write the file
        with open(
            os.path.join(self.results_dir, self.INDEX_FILENAME), "w"
        ) as f:
            json.dump(doc, f)

    def result_filename(self, test_name: str) -> str:
        """Return the name of the YAML file that contains a test result.

        :param test_name: Name of the test result.
        """
        return os.path.join(self.results_dir, f"{test_name}.yaml")
