# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from benchmarks.contracts import (
    EvidenceRecord,
    ScenarioDisposition,
    ScenarioEvidence,
    ScenarioName,
)
from benchmarks.profiles import PROFILES, target_ns
from benchmarks.scenarios import SCENARIOS

_PROFILE_ORDER = {
    name: index for index, name in enumerate(("smoke", "small", "medium", "large", "probe"))
}
_REQUIRED_MATRIX = frozenset(
    {
        ("Darwin", "3.13"),
        ("Darwin", "3.14"),
        ("Linux", "3.13"),
        ("Linux", "3.14"),
    }
)
_VERSION_PREFIX = re.compile(r"^(\d+)\.(\d+)(?:\.|$)")
_NUMERIC_VERSION_PREFIX = re.compile(r"^\d+(?:\.\d+)*")
_PROFILE_SCENARIOS = tuple(SCENARIOS)
_PROFILE_SCENARIO_SET = frozenset(_PROFILE_SCENARIOS)
_MUTATION_SCENARIOS = frozenset(
    {
        ScenarioName.PREPARE_INGESTION,
        ScenarioName.COMMIT,
        ScenarioName.RECOVER_PREPARED,
        ScenarioName.RECOVER_SWAPPING,
    }
)
_REQUIRED_CHECKPOINTS = {
    ScenarioName.INITIALIZE: frozenset({"initialized_workspace"}),
    ScenarioName.PREPARE_INGESTION: frozenset({"prepared"}),
    ScenarioName.COMMIT: frozenset({"prepared", "committed", "cleaned"}),
    ScenarioName.RECOVER_PREPARED: frozenset({"prepared"}),
    ScenarioName.RECOVER_SWAPPING: frozenset({"prepared", "interrupted", "committed", "cleaned"}),
}


def is_material_regression(current_ns: int, baseline_ns: int) -> bool:
    if current_ns < 0 or baseline_ns <= 0:
        raise ValueError("timing values must be positive")
    absolute_delta = current_ns - baseline_ns
    return absolute_delta >= 250_000_000 and current_ns * 100 >= baseline_ns * 125


def render_report(
    records: Sequence[EvidenceRecord],
    provisional: bool,
    require_matrix: bool = False,
) -> str:
    if not records:
        raise ValueError("at least one evidence record is required")
    if not provisional:
        raise ValueError("phase one reports must remain provisional")

    ordered = tuple(sorted(records, key=_record_sort_key))
    _validate_records(ordered, require_matrix=require_matrix)
    overall_disposition = _overall_disposition(ordered)

    lines = [
        "# BundleWalker Performance and Capacity",
        "",
        "Status: provisional",
        "",
        "Measurement foundation: available",
        "",
        "Supported capacity: not yet published",
        "",
        f"Overall disposition: {overall_disposition.value}",
        "",
    ]
    capacity_stops = tuple(
        record.capacity_stop for record in ordered if record.capacity_stop is not None
    )
    if capacity_stops:
        for stop in capacity_stops:
            lines.append(
                f"Capacity stop: {_label(stop.profile)} / {stop.scenario.value} "
                f"at {stop.deadline_ns} ns"
            )
    else:
        lines.append("Capacity stop: none")
    lines.extend(
        [
            "",
            (
                "These measurements describe candidate profiles only. They do not establish a "
                "supported capacity envelope."
            ),
            "",
            "## Profiles",
            "",
            "| Profile | Documents | Profile wiki bytes | Ingestion source characters |",
            "|---|---:|---:|---:|",
        ]
    )
    for profile in ordered[0].profiles:
        lines.append(
            f"| {_label(profile.name)} | {profile.document_count} | "
            f"{profile.target_wiki_bytes} | {profile.source_characters} |"
        )

    lines.extend(
        [
            "",
            "### Exact generated fixture sizes",
            "",
            "| Profile | Exact wiki bytes | Exact workspace bytes | Tree SHA-256 |",
            "|---|---:|---:|---|",
        ]
    )
    for fixture in ordered[0].fixtures:
        lines.append(
            f"| {_label(fixture.profile)} | {fixture.exact_wiki_bytes} | "
            f"{fixture.exact_workspace_bytes} | `{fixture.tree_sha256}` |"
        )

    lines.extend(
        [
            "",
            "Small, Medium, and Large are candidate only profiles. Smoke is a correctness "
            "profile. Probe is exploratory and is not a support claim.",
            "",
            "## Measurement policy and reference targets",
            "",
            (
                "Full measurements use one untimed warm-up, seven initialization/read-only/MCP "
                "samples, and five ingestion/commit/recovery samples. Correctness-only records "
                "use one sample and no warm-up. Medians determine target outcomes; p95 uses the "
                "nearest-rank method."
            ),
            "",
            "| Operation | Median target |",
            "|---|---:|",
            "| Status, list, read, and lexical search | 2 s |",
            "| Workspace initialization | 3 s |",
            "| MCP startup and discovery | 5 s |",
            "| Deterministic lint | 30 s |",
            "| Ingestion preparation, commit, and recovery | 60 s |",
            "",
            "## Environments",
            "",
            (
                "Only allowlisted execution metadata is shown: OS name/release, full Python "
                "version and implementation, architecture, logical CPU count, total memory, "
                "runner image, and filesystem type."
            ),
            "",
            (
                "| Run | OS | Release | Python | Implementation | Architecture | CPUs | "
                "Memory bytes | Runner image | Filesystem |"
            ),
            "|---|---|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for record in ordered:
        environment = record.environment
        cpu_count = _optional_number(environment.logical_cpu_count)
        lines.append(
            f"| {_markdown(record.run_id)} | {_markdown(environment.os_name)} | "
            f"{_markdown(environment.os_release)} | {_markdown(environment.python_version)} | "
            f"{_markdown(environment.python_implementation)} | "
            f"{_markdown(environment.architecture)} | {cpu_count} | "
            f"{_optional_number(environment.total_memory_bytes)} | "
            f"{_optional_text(environment.runner_image)} | "
            f"{_optional_text(environment.filesystem_type)} |"
        )

    lines.extend(
        [
            "",
            "## Scenario results",
            "",
            "Durations are nanoseconds. Every recorded sample is retained in the evidence JSON.",
            "",
            (
                "| Run | Profile | Scenario | Median ns | Nearest-rank p95 ns | Target ns | "
                "Disposition | Samples ns | Checkpoint byte maxima |"
            ),
            "|---|---|---|---:|---:|---:|---|---|---|",
        ]
    )
    for record in ordered:
        for scenario in sorted(record.scenarios, key=_scenario_sort_key):
            lines.append(_scenario_row(record, scenario))

    candidate_names = tuple(
        profile.name
        for profile in ordered[0].profiles
        if profile.name in {"small", "medium", "large"}
    )
    candidate_statuses = {name: _candidate_status(ordered, name) for name in candidate_names}
    measured_candidates = [
        name
        for name in candidate_names
        if candidate_statuses[name] == "complete successful candidate measurement"
    ]
    candidates = ", ".join(_label(name) for name in measured_candidates) or "none in this record"
    lines.extend(
        [
            "",
            "## Candidate interpretation",
            "",
            f"Measured candidate only profiles: {candidates}.",
            "",
            "| Profile | Candidate measurement status |",
            "|---|---|",
        ]
    )
    for name in candidate_names:
        lines.append(f"| {_label(name)} | {candidate_statuses[name]} |")
    lines.extend(
        [
            "",
            (
                "Timing from remote models and providers is excluded. Results describe the "
                "listed hardware and filesystem; slower hardware, unusual filesystems, and "
                "different model/provider latency are not guaranteed to match them."
            ),
            "",
            "## Reproduction",
            "",
            "```console",
            (
                "python -m benchmarks run --profiles smoke --correctness-only "
                "--output benchmark-results/evidence.json"
            ),
            (
                "python -m benchmarks run --profiles smoke,small,medium,large,probe "
                "--output benchmark-results/evidence.json"
            ),
            (
                "python -m benchmarks report --evidence benchmark-results "
                "--output benchmark-results/report.md --provisional"
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_records(records: Sequence[EvidenceRecord], *, require_matrix: bool) -> None:
    first = records[0]
    relationship = (
        first.schema_version,
        first.suite_version,
        first.git_commit,
        first.bundlewalker_version,
        first.profiles,
        first.fixtures,
    )
    for record in records[1:]:
        candidate = (
            record.schema_version,
            record.suite_version,
            record.git_commit,
            record.bundlewalker_version,
            record.profiles,
            record.fixtures,
        )
        if candidate != relationship:
            raise ValueError("evidence records must describe one suite, commit, and fixture set")
    for record in records:
        _validate_capacity_stop_prefix(record)

    keys = tuple(
        (_markdown(record.environment.os_name), _python_minor(record)) for record in records
    )
    if require_matrix and (len(keys) != 4 or frozenset(keys) != _REQUIRED_MATRIX):
        raise ValueError("evidence matrix must contain exactly Darwin/Linux on Python 3.13/3.14")
    if require_matrix:
        for record in records:
            _validate_full_policy_record(record)


def _validate_full_policy_record(record: EvidenceRecord) -> None:
    if (
        record.correctness_only
        or record.warmup_count != 1
        or record.read_only_repetitions != 7
        or record.mutation_repetitions != 5
        or record.profiles != tuple(PROFILES.values())
    ):
        raise ValueError("matrix evidence requires the frozen full-policy profile catalog")

    actual_keys = tuple((scenario.profile, scenario.scenario) for scenario in record.scenarios)
    catalog_keys = (
        (None, ScenarioName.INITIALIZE),
        *(
            (profile.name, scenario)
            for profile in record.profiles
            for scenario in _PROFILE_SCENARIOS
        ),
    )
    expected_keys = catalog_keys
    if record.capacity_stop is not None:
        stop_key = (record.capacity_stop.profile, record.capacity_stop.scenario)
        try:
            stop_index = catalog_keys.index(stop_key)
        except ValueError as error:
            raise ValueError("matrix evidence has an invalid capacity-stop position") from error
        expected_keys = catalog_keys[:stop_index]
        expected_deadline = max(30_000_000_000, 3 * target_ns(record.capacity_stop.scenario))
        if record.capacity_stop.deadline_ns != expected_deadline:
            raise ValueError("matrix evidence has an invalid capacity-stop deadline")
    if actual_keys != expected_keys or len(actual_keys) != len(set(actual_keys)):
        raise ValueError("matrix evidence requires exact full-policy scenario-prefix coverage")

    for scenario in record.scenarios:
        if scenario.target_ns != target_ns(scenario.scenario):
            raise ValueError("matrix evidence must use the frozen scenario targets")
        expected_samples = 5 if scenario.scenario in _MUTATION_SCENARIOS else 7
        if len(scenario.samples_ns) != expected_samples:
            raise ValueError("matrix evidence requires complete full-policy sample counts")
        required = _REQUIRED_CHECKPOINTS.get(scenario.scenario, frozenset())
        if frozenset(scenario.checkpoint_bytes) != required:
            raise ValueError("matrix evidence requires complete full-policy checkpoints")


def _validate_capacity_stop_prefix(record: EvidenceRecord) -> None:
    if record.capacity_stop is None:
        return
    catalog_keys = (
        (None, ScenarioName.INITIALIZE),
        *(
            (profile.name, scenario)
            for profile in record.profiles
            for scenario in _PROFILE_SCENARIOS
        ),
    )
    stop_key = (record.capacity_stop.profile, record.capacity_stop.scenario)
    try:
        stop_index = catalog_keys.index(stop_key)
    except ValueError as error:
        raise ValueError("capacity stop has an invalid scenario-prefix position") from error
    actual_keys = tuple((scenario.profile, scenario.scenario) for scenario in record.scenarios)
    if actual_keys != catalog_keys[:stop_index] or len(actual_keys) != len(set(actual_keys)):
        raise ValueError("capacity stop requires exact scenario-prefix coverage")


def _candidate_status(
    records: Sequence[EvidenceRecord], profile: str
) -> (
    Literal[
        "complete successful candidate measurement",
        "measured but target missed",
        "incomplete",
    ]
    | str
):
    stops = tuple(
        record.capacity_stop
        for record in records
        if record.capacity_stop is not None and record.capacity_stop.profile == profile
    )
    if stops:
        return f"stopped at `{stops[0].scenario.value}`; incomplete"

    all_complete = True
    all_successful = True
    for record in records:
        initialization = tuple(
            item
            for item in record.scenarios
            if item.profile is None and item.scenario is ScenarioName.INITIALIZE
        )
        scenarios = tuple(item for item in record.scenarios if item.profile == profile)
        complete = (
            len(initialization) == 1
            and len(scenarios) == len(_PROFILE_SCENARIOS)
            and frozenset(item.scenario for item in scenarios) == _PROFILE_SCENARIO_SET
        )
        all_complete = all_complete and complete
        all_successful = (
            all_successful
            and complete
            and all(
                item.disposition is ScenarioDisposition.PASS
                for item in (*initialization, *scenarios)
            )
        )
    if not all_complete:
        return "incomplete"
    if not all_successful:
        return "measured but target missed"
    return "complete successful candidate measurement"


def _overall_disposition(records: Sequence[EvidenceRecord]) -> ScenarioDisposition:
    dispositions = {record.disposition for record in records}
    if ScenarioDisposition.CAPACITY_EXCEEDED in dispositions:
        return ScenarioDisposition.CAPACITY_EXCEEDED
    if ScenarioDisposition.TARGET_MISSED in dispositions:
        return ScenarioDisposition.TARGET_MISSED
    return ScenarioDisposition.PASS


def _python_minor(record: EvidenceRecord) -> str:
    match = _VERSION_PREFIX.match(record.environment.python_version)
    if match is None:
        raise ValueError("Python version must begin with two numeric components")
    return f"{int(match.group(1))}.{int(match.group(2))}"


def _record_sort_key(record: EvidenceRecord) -> tuple[str, tuple[int, ...], str]:
    match = _NUMERIC_VERSION_PREFIX.match(record.environment.python_version)
    if match is None:
        raise ValueError("Python version must begin with numeric components")
    version = tuple(int(component) for component in match.group().split("."))
    if len(version) < 2:
        raise ValueError("Python version must begin with two numeric components")
    return record.environment.os_name, version, record.run_id


def _scenario_sort_key(scenario: ScenarioEvidence) -> tuple[int, str]:
    profile_order = -1 if scenario.profile is None else _PROFILE_ORDER[scenario.profile]
    return profile_order, scenario.scenario.value


def _scenario_row(record: EvidenceRecord, scenario: ScenarioEvidence) -> str:
    profile = "Environment" if scenario.profile is None else _label(scenario.profile)
    checkpoints = ", ".join(
        f"{name}={value}" for name, value in sorted(scenario.checkpoint_bytes.items())
    )
    samples = ", ".join(str(value) for value in scenario.samples_ns)
    return (
        f"| {_markdown(record.run_id)} | {profile} | `{scenario.scenario.value}` | "
        f"{scenario.median_ns} | {scenario.p95_ns} | {scenario.target_ns} | "
        f"{scenario.disposition.value} | {samples} | {checkpoints or 'none'} |"
    )


def _markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _optional_text(value: str | None) -> str:
    return "not available" if value is None else _markdown(value)


def _optional_number(value: int | None) -> str:
    return "not available" if value is None else str(value)


def _label(name: str) -> str:
    return name.capitalize()
