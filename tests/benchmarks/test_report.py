# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from benchmarks.report import is_material_regression, render_report
from tests.benchmarks.factories import evidence_record


@pytest.mark.parametrize(
    ("current", "baseline", "flagged"),
    [
        (1_249_999_999, 1_000_000_000, False),
        (1_250_000_000, 1_000_000_000, True),
        (200_000_000, 100_000_000, False),
        (350_000_000, 100_000_000, True),
    ],
)
def test_material_regression_requires_relative_and_absolute_delta(
    current: int, baseline: int, flagged: bool
) -> None:
    assert is_material_regression(current, baseline) is flagged


def test_provisional_report_cannot_publish_a_supported_envelope() -> None:
    matrix = tuple(
        evidence_record(os_name=os_name, python_version=f"{minor}.0")
        for os_name in ("Darwin", "Linux")
        for minor in ("3.13", "3.14")
    )

    report = render_report(matrix, provisional=True, require_matrix=True)

    assert "# BundleWalker Performance and Capacity" in report
    assert "Measurement foundation: available" in report
    assert "Supported capacity: not yet published" in report
    assert "candidate only" in report
    assert "BundleWalker supports up to" not in report


@pytest.mark.parametrize(("current", "baseline"), [(-1, 1), (1, 0), (1, -1)])
def test_material_regression_rejects_invalid_timings(current: int, baseline: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        is_material_regression(current, baseline)


def test_required_matrix_rejects_duplicate_environment_keys() -> None:
    duplicate = tuple(evidence_record() for _index in range(4))

    with pytest.raises(ValueError, match="exactly Darwin/Linux"):
        render_report(duplicate, provisional=True, require_matrix=True)


def test_report_sorts_full_python_versions_and_lists_every_sample() -> None:
    newer = evidence_record(python_version="3.13.10")
    older = evidence_record(python_version="3.13.9")

    report = render_report((newer, older), provisional=True)

    assert report.index("linux-3.13.9") < report.index("linux-3.13.10")
    assert "100, 200, 300, 400, 500, 600, 700" in report
