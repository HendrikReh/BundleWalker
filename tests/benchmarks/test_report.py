# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from benchmarks.contracts import (
    CapacityStop,
    CheckpointBytes,
    CheckpointName,
    EvidenceRecord,
    FixtureIdentity,
    ScenarioDisposition,
    ScenarioEvidence,
    ScenarioName,
)
from benchmarks.profiles import PROFILES, target_ns
from benchmarks.report import is_material_regression, render_report
from benchmarks.scenarios import SCENARIOS
from tests.benchmarks.factories import evidence_record


def _complete_record(*, os_name: str = "Linux", python_version: str = "3.13.0") -> EvidenceRecord:
    base = evidence_record(os_name=os_name, python_version=python_version)
    scenarios = (
        _scenario_evidence(ScenarioName.INITIALIZE, None),
        *(_scenario_evidence(scenario, "smoke") for scenario in SCENARIOS),
    )
    values = base.model_dump(mode="python")
    values["scenarios"] = scenarios
    return EvidenceRecord.model_validate(values)


def _matrix_record(*, os_name: str = "Linux", python_version: str = "3.13.0") -> EvidenceRecord:
    base = evidence_record(os_name=os_name, python_version=python_version)
    values = base.model_dump(mode="python")
    values["profiles"] = tuple(PROFILES.values())
    values["fixtures"] = tuple(
        FixtureIdentity(
            profile=profile.name,
            document_count=profile.document_count,
            exact_wiki_bytes=profile.target_wiki_bytes,
            exact_workspace_bytes=profile.target_wiki_bytes + 1,
            source_characters=profile.source_characters,
            profile_sha256=(str(index) * 64),
            tree_sha256=(format(index + 10, "x") * 64)[:64],
        )
        for index, profile in enumerate(PROFILES.values(), start=1)
    )
    values["scenarios"] = (
        _scenario_evidence(ScenarioName.INITIALIZE, None),
        *(
            _scenario_evidence(scenario, profile.name)
            for profile in PROFILES.values()
            for scenario in SCENARIOS
        ),
    )
    return EvidenceRecord.model_validate(values)


def _scenario_evidence(scenario: ScenarioName, profile: str | None) -> ScenarioEvidence:
    sample_count = (
        5
        if scenario
        in {
            ScenarioName.PREPARE_INGESTION,
            ScenarioName.COMMIT,
            ScenarioName.RECOVER_PREPARED,
            ScenarioName.RECOVER_SWAPPING,
        }
        else 7
    )
    samples = tuple(range(100, 100 + sample_count))
    checkpoint_catalog: dict[ScenarioName, dict[CheckpointName, CheckpointBytes]] = {
        ScenarioName.INITIALIZE: {"initialized_workspace": 1},
        ScenarioName.PREPARE_INGESTION: {"prepared": 1},
        ScenarioName.COMMIT: {"prepared": 1, "committed": 2, "cleaned": 0},
        ScenarioName.RECOVER_PREPARED: {"prepared": 1},
        ScenarioName.RECOVER_SWAPPING: {
            "prepared": 1,
            "interrupted": 2,
            "committed": 3,
            "cleaned": 0,
        },
    }
    checkpoints = checkpoint_catalog.get(scenario, {})
    return ScenarioEvidence(
        scenario=scenario,
        profile=profile,
        target_ns=target_ns(scenario),
        samples_ns=samples,
        median_ns=sorted(samples)[len(samples) // 2],
        p95_ns=max(samples),
        output_sha256="e" * 64,
        checkpoint_bytes=checkpoints,
        disposition=ScenarioDisposition.PASS,
    )


def _capacity_stopped_record() -> EvidenceRecord:
    base = _complete_record()
    values = base.model_dump(mode="python")
    values["profiles"] = (PROFILES["smoke"], PROFILES["large"])
    values["fixtures"] = (
        base.fixtures[0],
        FixtureIdentity(
            profile="large",
            document_count=5_000,
            exact_wiki_bytes=50 * 1024 * 1024,
            exact_workspace_bytes=50 * 1024 * 1024 + 1,
            source_characters=100_000,
            profile_sha256="f" * 64,
            tree_sha256="a" * 64,
        ),
    )
    values["capacity_stop"] = CapacityStop(
        profile="large",
        scenario=ScenarioName.STATUS,
        deadline_ns=30_000_000_000,
    )
    values["disposition"] = ScenarioDisposition.CAPACITY_EXCEEDED
    return EvidenceRecord.model_validate(values)


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
        _matrix_record(os_name=os_name, python_version=f"{minor}.0")
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
    duplicate = tuple(_complete_record() for _index in range(4))

    with pytest.raises(ValueError, match="exactly Darwin/Linux"):
        render_report(duplicate, provisional=True, require_matrix=True)


def test_required_matrix_rejects_incomplete_scenario_coverage() -> None:
    incomplete = tuple(
        evidence_record(os_name=os_name, python_version=f"{minor}.0")
        for os_name in ("Darwin", "Linux")
        for minor in ("3.13", "3.14")
    )

    with pytest.raises(ValueError, match="full-policy"):
        render_report(incomplete, provisional=True, require_matrix=True)


def test_required_matrix_rejects_smoke_only_full_measurements() -> None:
    matrix = tuple(
        _complete_record(os_name=os_name, python_version=f"{minor}.0")
        for os_name in ("Darwin", "Linux")
        for minor in ("3.13", "3.14")
    )

    with pytest.raises(ValueError, match="profile catalog"):
        render_report(matrix, provisional=True, require_matrix=True)


def test_required_matrix_rejects_noncatalog_target() -> None:
    records = [
        _matrix_record(os_name=os_name, python_version=f"{minor}.0")
        for os_name in ("Darwin", "Linux")
        for minor in ("3.13", "3.14")
    ]
    values = records[0].model_dump(mode="python")
    scenarios = list(records[0].scenarios)
    scenarios[0] = scenarios[0].model_copy(
        update={"target_ns": target_ns(ScenarioName.INITIALIZE) + 1}
    )
    values["scenarios"] = tuple(scenarios)
    records[0] = EvidenceRecord.model_validate(values)

    with pytest.raises(ValueError, match="frozen scenario targets"):
        render_report(tuple(records), provisional=True, require_matrix=True)


def test_required_matrix_accepts_exact_large_capacity_stop_prefix() -> None:
    records: list[EvidenceRecord] = []
    for os_name in ("Darwin", "Linux"):
        for minor in ("3.13", "3.14"):
            complete = _matrix_record(os_name=os_name, python_version=f"{minor}.0")
            values = complete.model_dump(mode="python")
            stop = CapacityStop(
                profile="large",
                scenario=ScenarioName.STATUS,
                deadline_ns=30_000_000_000,
            )
            stop_index = next(
                index
                for index, item in enumerate(complete.scenarios)
                if (item.profile, item.scenario) == (stop.profile, stop.scenario)
            )
            values["scenarios"] = complete.scenarios[:stop_index]
            values["capacity_stop"] = stop
            values["disposition"] = ScenarioDisposition.CAPACITY_EXCEEDED
            records.append(EvidenceRecord.model_validate(values))

    report = render_report(tuple(records), provisional=True, require_matrix=True)

    assert "Large | stopped at `status`; incomplete" in report


def test_required_matrix_rejects_scenario_at_capacity_stop() -> None:
    records: list[EvidenceRecord] = []
    for os_name in ("Darwin", "Linux"):
        for minor in ("3.13", "3.14"):
            complete = _matrix_record(os_name=os_name, python_version=f"{minor}.0")
            values = complete.model_dump(mode="python")
            values["capacity_stop"] = CapacityStop(
                profile="large",
                scenario=ScenarioName.STATUS,
                deadline_ns=30_000_000_000,
            )
            values["disposition"] = ScenarioDisposition.CAPACITY_EXCEEDED
            records.append(EvidenceRecord.model_validate(values))

    with pytest.raises(ValueError, match="scenario-prefix"):
        render_report(tuple(records), provisional=True, require_matrix=True)


def test_required_matrix_rejects_duplicate_scenario_key() -> None:
    records = [
        _matrix_record(os_name=os_name, python_version=f"{minor}.0")
        for os_name in ("Darwin", "Linux")
        for minor in ("3.13", "3.14")
    ]
    values = records[0].model_dump(mode="python")
    values["scenarios"] = (*records[0].scenarios, records[0].scenarios[-1])
    records[0] = EvidenceRecord.model_validate(values)

    with pytest.raises(ValueError, match="scenario-prefix"):
        render_report(tuple(records), provisional=True, require_matrix=True)


@pytest.mark.parametrize("miss", ["initialize", "small"])
def test_candidate_target_miss_is_measured_not_incomplete(miss: str) -> None:
    complete = _matrix_record()
    values = complete.model_dump(mode="python")
    scenarios = list(complete.scenarios)
    index = next(
        index
        for index, item in enumerate(scenarios)
        if (miss == "initialize" and item.scenario is ScenarioName.INITIALIZE)
        or (miss == "small" and item.profile == "small" and item.scenario is ScenarioName.STATUS)
    )
    item = scenarios[index]
    scenarios[index] = item.model_copy(
        update={"target_ns": 1, "disposition": ScenarioDisposition.TARGET_MISSED}
    )
    values["scenarios"] = tuple(scenarios)
    values["disposition"] = ScenarioDisposition.TARGET_MISSED
    record = EvidenceRecord.model_validate(values)

    report = render_report((record,), provisional=True)

    assert "Small | measured but target missed" in report
    assert "Small | incomplete" not in report


def test_candidate_without_initialization_is_incomplete() -> None:
    complete = _matrix_record()
    values = complete.model_dump(mode="python")
    values["scenarios"] = complete.scenarios[1:]
    record = EvidenceRecord.model_validate(values)

    report = render_report((record,), provisional=True)

    assert "Small | incomplete" in report


def test_report_sorts_full_python_versions_and_lists_every_sample() -> None:
    newer = evidence_record(python_version="3.13.10")
    older = evidence_record(python_version="3.13.9")

    report = render_report((newer, older), provisional=True)

    assert report.index("linux-3.13.9") < report.index("linux-3.13.10")
    assert "100, 200, 300, 400, 500, 600, 700" in report


def test_capacity_stop_is_explicit_and_incomplete_large_is_not_measured() -> None:
    report = render_report((_capacity_stopped_record(),), provisional=True)

    assert "Overall disposition: capacity_exceeded" in report
    assert "Capacity stop: Large / status at 30000000000 ns" in report
    assert "Measured candidate only profiles: none in this record" in report
    assert "Large | stopped at `status`; incomplete" in report
    assert "Measured candidate only profiles: Large" not in report


def test_capacity_stop_report_rejects_a_gap_before_the_stop() -> None:
    stopped = _capacity_stopped_record()
    values = stopped.model_dump(mode="python")
    values["scenarios"] = (stopped.scenarios[0], *stopped.scenarios[2:])
    gapped = EvidenceRecord.model_validate(values)

    with pytest.raises(ValueError, match="exact scenario-prefix"):
        render_report((gapped,), provisional=True)


def test_capacity_stop_report_rejects_nonreference_deadline() -> None:
    stopped = _capacity_stopped_record()
    values = stopped.model_dump(mode="python")
    assert stopped.capacity_stop is not None
    values["capacity_stop"] = stopped.capacity_stop.model_copy(update={"deadline_ns": 1})
    invalid = EvidenceRecord.model_validate(values)

    with pytest.raises(ValueError, match="invalid capacity-stop deadline"):
        render_report((invalid,), provisional=True)
