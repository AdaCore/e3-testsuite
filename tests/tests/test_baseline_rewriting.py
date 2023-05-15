"""Tests for the e3.testsuite.report.rewriting module."""

import os

from e3.testsuite.report.gaia import dump_gaia_report
from e3.testsuite.report.rewriting import (
    BaseBaselineRewriter,
    RewritingError,
    RewritingSummary,
)
from e3.testsuite.result import FailureReason, TestStatus as Status
from e3.testsuite.utils import ColorConfig

from .utils import create_report, create_result


def create_initial_baselines(tests):
    return {
        test_name: f"Initial baseline for {test_name}" for test_name in tests
    }


# The baselines to update
initial_baselines = create_initial_baselines(
    [
        "t-pass",
        "t-xfail",
        "t-error",
        "t-fail-no-reason",
        "t-fail-diff",
        "t-fail-diff-crash",
        "t-bytes",
        "t-utf-8",
        "t-out-empty",
        "t-out-none",
    ]
)
initial_baselines["t-no-baseline"] = ""

# The test results used to update baselines
test_results = {
    create_result("t-pass", Status.PASS, out="INVALID"),
    create_result("t-xfail", Status.XFAIL, out="INVALID"),
    create_result("t-error", Status.ERROR, out="INVALID"),
    create_result("t-fail-no-reason", Status.FAIL, out="INVALID"),
    create_result(
        "t-fail-diff",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
        out="New baseline",
    ),
    create_result(
        "t-fail-diff-crash",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF, FailureReason.CRASH},
        out="INVALID",
    ),
    create_result(
        "t-bytes",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
        out=b"\xff\x00\x80",
    ),
    create_result(
        "t-utf-8",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
        out="\xe9",
    ),
    create_result(
        "t-latin-1",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
        out="\xe9",
        encoding="latin-1",
    ),
    create_result(
        "t-out-empty",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
        out=b"",
    ),
    create_result(
        "t-out-none",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
    ),
    create_result(
        "t-no-baseline",
        Status.FAIL,
        failure_reasons={FailureReason.DIFF},
        out="New baseline",
    ),
}

# The baselines expected after the update
updated_baselines = {
    "t-pass": b"Initial baseline for t-pass",
    "t-xfail": b"Initial baseline for t-xfail",
    "t-error": b"Initial baseline for t-error",
    "t-fail-no-reason": b"Initial baseline for t-fail-no-reason",
    "t-fail-diff": b"New baseline",
    "t-fail-diff-crash": b"Initial baseline for t-fail-diff-crash",
    "t-bytes": b"\xff\x00\x80",
    "t-utf-8": b"\xc3\xa9",
    "t-latin-1": b"\xe9",
    "t-out-empty": b"",
    "t-out-none": b"Initial baseline for t-out-none",
    "t-no-baseline": b"New baseline",
}

expected_summary = RewritingSummary(
    errors={
        "t-error",
        "t-fail-no-reason",
        "t-fail-diff-crash",
        "t-out-none",
    },
    updated_baselines={"t-fail-diff", "t-bytes", "t-utf-8"},
    new_baselines={"t-latin-1", "t-no-baseline"},
    deleted_baselines={"t-out-empty"},
)

# The GAIA format is less precise than the default one: its processing yields
# slightly different results.
gaia_updated_baselines = dict(updated_baselines)
gaia_expected_summary = RewritingSummary(
    set(expected_summary.errors),
    set(expected_summary.updated_baselines),
    set(expected_summary.new_baselines),
    set(expected_summary.deleted_baselines),
)

# The GAIA format cannot distinguish the "no output" case from the "empty
# output" one.
gaia_updated_baselines["t-out-none"] = b""

# The encoding information is also lost in GAIA reports, so we have to assume
# that everything is UTF-8.
gaia_updated_baselines["t-latin-1"] = b"\xc3\xa9"

# Some errors cannot be distinguished properly from actual diffs
for t in ("t-fail-no-reason", "t-fail-diff-crash", "t-out-none"):
    gaia_expected_summary.errors.remove(t)
gaia_expected_summary.deleted_baselines.add("t-out-none")


def baseline_filename(tmp_path, test_name):
    return str(tmp_path / "baselines" / f"{test_name}.out")


def write_baselines(tmp_path, baselines):
    """Write initial baselines under "tmp_path/baselines"."""
    (tmp_path / "baselines").mkdir()
    for test_name, baseline in baselines.items():
        if baseline:
            with open(baseline_filename(tmp_path, test_name), "w") as f:
                f.write(baseline)


def check_baselines(tmp_path, baselines):
    """Check actual baselines against expectations."""
    for test_name, baseline in baselines.items():
        filename = baseline_filename(tmp_path, test_name)
        if baseline:
            with open(filename, "rb") as f:
                assert f.read() == baseline
        else:
            assert not os.path.exists(filename)


class BR(BaseBaselineRewriter):
    """Simple implementation for a baseline rewriter."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        super().__init__(ColorConfig(colors_enabled=False))

    def baseline_filename(self, test_name):
        return baseline_filename(self.tmp_path, test_name)


def do_setup(tmp_path, initial_baselines, test_results, br_cls=BR):
    """Set up baselines and a testsuite report."""
    write_baselines(tmp_path, initial_baselines)
    br = br_cls(tmp_path)
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    return br, create_report(test_results, str(results_dir))


def test_report(tmp_path):
    """Test baseline updates from a "native" e3-testsuite report index."""
    br, report = do_setup(tmp_path, initial_baselines, test_results)
    assert br.rewrite(report.results_dir) == expected_summary
    check_baselines(tmp_path, updated_baselines)


def test_deleted_baseline(tmp_path):
    """Test baseline deletion when the baseline is already missing."""
    br, report = do_setup(tmp_path, initial_baselines, test_results)
    # Remove the baseline
    os.remove(os.path.join(tmp_path, "baselines", "t-out-empty.out"))
    deleted_expected_summary = RewritingSummary(
        set(expected_summary.errors),
        set(expected_summary.updated_baselines),
        set(expected_summary.new_baselines),
        set(),
    )
    assert br.rewrite(report.results_dir) == deleted_expected_summary
    check_baselines(tmp_path, updated_baselines)


def test_gaia(tmp_path):
    """Test baseline updates from a GAIA report."""
    br, report = do_setup(tmp_path, initial_baselines, test_results)
    gaia_dir = tmp_path / "gaia"
    gaia_dir.mkdir()
    dump_gaia_report(report, gaia_dir)
    assert br.rewrite(str(gaia_dir)) == gaia_expected_summary
    check_baselines(tmp_path, gaia_updated_baselines)


def test_no_report(tmp_path):
    """Check that no report found is properly reported."""
    br = BR(tmp_path)
    try:
        br.rewrite(str(tmp_path))
    except RewritingError as exc:
        br.print_error(str(exc))
    else:
        raise AssertionError()


def test_gaia_short_status(tmp_path):
    """Check that GAIA's special single-letter ".result" files are handled."""
    initial_baselines = create_initial_baselines(
        ["t-pass", "t-fail", "t-problem", "t-diff"]
    )
    test_results = {
        create_result("t-pass", Status.PASS, out="INVALID"),
        create_result("t-fail", Status.FAIL, out="INVALID"),
        create_result("t-problem", Status.ERROR, out="INVALID"),
        create_result(
            "t-diff",
            Status.FAIL,
            failure_reasons={FailureReason.DIFF},
            out="New baseline",
        ),
    }
    br, report = do_setup(tmp_path, initial_baselines, test_results)

    updated_baselines = {
        "t-pass": b"Initial baseline for t-pass",
        "t-fail": b"Initial baseline for t-fail",
        "t-problem": b"Initial baseline for t-problem",
        "t-diff": b"New baseline",
    }

    # Create the GAIA report and patch the "*.result" files
    gaia_dir = tmp_path / "gaia"
    gaia_dir.mkdir()
    dump_gaia_report(report, gaia_dir)
    for test_name, letter in [
        ("t-pass", "O"),
        ("t-fail", "I"),
        ("t-problem", "C"),
        ("t-diff", "D"),
    ]:
        with (tmp_path / "gaia" / f"{test_name}.result").open("w") as f:
            f.write(letter)

    assert br.rewrite(str(gaia_dir)) == RewritingSummary(
        errors={"t-problem"},
        updated_baselines={"t-diff"},
        new_baselines=set(),
        deleted_baselines=set(),
    )
    check_baselines(tmp_path, updated_baselines)


def test_baseline_postprocessing(tmp_path):
    """Check that baseline postprocessing works as expected."""

    class PPBR(BR):
        def postprocess_baseline(self, baseline):
            return baseline.decode("ascii").lower().encode("ascii")

    initial_baselines = create_initial_baselines(["t"])
    test_results = {
        create_result(
            "t",
            Status.FAIL,
            failure_reasons={FailureReason.DIFF},
            out="New Baseline",
        ),
    }
    updated_baselines = {"t": b"new baseline"}

    br, report = do_setup(tmp_path, initial_baselines, test_results, PPBR)
    assert br.rewrite(report.results_dir) == RewritingSummary(
        errors=set(),
        updated_baselines={"t"},
        new_baselines=set(),
        deleted_baselines=set(),
    )

    check_baselines(tmp_path, updated_baselines)
