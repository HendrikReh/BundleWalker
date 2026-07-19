# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from collections.abc import Sequence

from benchmarks.contracts import EvidenceRecord, ScenarioEvidence

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
    profile_names = tuple(profile.name for profile in ordered[0].profiles)

    lines = [
        "# BundleWalker Performance and Capacity",
        "",
        "Status: provisional",
        "",
        "Measurement foundation: available",
        "",
        "Supported capacity: not yet published",
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

    measured_candidates = [name for name in ("small", "medium", "large") if name in profile_names]
    candidates = ", ".join(_label(name) for name in measured_candidates) or "none in this record"
    lines.extend(
        [
            "",
            "## Candidate interpretation",
            "",
            f"Measured candidate only profiles: {candidates}.",
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

    keys = tuple(
        (_markdown(record.environment.os_name), _python_minor(record)) for record in records
    )
    if require_matrix and (len(keys) != 4 or frozenset(keys) != _REQUIRED_MATRIX):
        raise ValueError("evidence matrix must contain exactly Darwin/Linux on Python 3.13/3.14")


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
