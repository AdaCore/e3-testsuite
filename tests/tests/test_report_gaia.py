"""Tests for the e3.testsuite.report.gaia module."""

import os
from pathlib import Path

import pytest

from e3.testsuite.report.gaia import dump_gaia_report, dump_result_logs
from e3.testsuite.result import FailureReason, TestStatus as Status

from .utils import create_report, create_result


def check(results, tmp_path, expected_files):
    """Generate a GAIA report and check its contents."""
    # Prepare output directories
    index_dir = tmp_path / "index"
    gaia_report_dir = tmp_path / "report"
    index_dir.mkdir()
    gaia_report_dir.mkdir()

    # Write test entries on disk
    index = create_report(results, str(index_dir))

    # Generate the GAIA report from them
    dump_gaia_report(index, str(gaia_report_dir))

    actual_files = {}
    for filename in os.listdir(gaia_report_dir):
        with open(gaia_report_dir / filename) as f:
            actual_files[filename] = f.read()

    assert actual_files == expected_files


def test_basics(tmp_path):
    """Test basic GAIA report features."""
    check(
        [
            create_result(
                "foo1",
                Status.PASS,
                msg="foo1 is ok",
                log="Logs for foo1.\n",
            ),
            create_result(
                "foo2",
                Status.FAIL,
                msg="baseline diff",
                out="foo\nbar\n",
                expected="foo\nbar\nbaz\n",
                diff="<some-diff>",
                failure_reasons={FailureReason.DIFF},
            ),
            create_result(
                "foo3",
                Status.XFAIL,
                msg="",
                failure_reasons={FailureReason.CRASH},
            ),
        ],
        tmp_path,
        {
            "results": (
                "foo1:OK:foo1 is ok\n"
                "foo2:DIFF:baseline diff\n"
                "foo3:XFAIL:\n"
            ),
            "foo1.result": "OK:foo1 is ok\n",
            "foo1.log": "Logs for foo1.\n",
            "foo2.result": "DIFF:baseline diff\n",
            "foo2.out": "foo\nbar\n",
            "foo2.expected": "foo\nbar\nbaz\n",
            "foo2.diff": "<some-diff>",
            "foo3.result": "XFAIL:\n",
        },
    )


@pytest.mark.parametrize("pre_generated", (False, True))
def test_overwrite_existing_report(
    tmp_path: Path, pre_generated: bool
) -> None:
    """Replace existing GAIA files with the latest report contents."""
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    for phase in ("first", "second"):
        index_dir = tmp_path / phase
        index_dir.mkdir()
        result = create_result(
            "foo",
            Status.FAIL,
            msg=phase,
            log=f"{phase} log\n",
            out=f"{phase} output\n",
            expected=f"{phase} expected\n",
            diff=f"{phase} diff\n",
            time=1.0 if phase == "first" else 2.0,
        )
        result.info["phase"] = phase
        index = create_report((result,), str(index_dir))
        files = (
            {"foo": dump_result_logs(result, str(report_dir))}
            if pre_generated
            else None
        )
        dump_gaia_report(index, str(report_dir), result_files=files)

        assert {p.name: p.read_text() for p in report_dir.iterdir()} == {
            "results": f"foo:FAIL:{phase}\n",
            "foo.result": f"FAIL:{phase}\n",
            "foo.log": f"{phase} log\n",
            "foo.out": f"{phase} output\n",
            "foo.expected": f"{phase} expected\n",
            "foo.diff": f"{phase} diff\n",
            "foo.time": "1.000000000" if phase == "first" else "2.000000000",
            "foo.info": f"phase:{phase}",
        }
