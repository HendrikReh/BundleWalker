# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ScenarioName(StrEnum):
    INITIALIZE = "initialize"
    STATUS = "status"
    LIST_CONCEPTS = "list_concepts"
    READ_CONCEPT = "read_concept"
    SEARCH_PRESENT = "search_present"
    SEARCH_ABSENT = "search_absent"
    LINT = "lint"
    PREPARE_INGESTION = "prepare_ingestion"
    COMMIT = "commit"
    RECOVER_PREPARED = "recover_prepared"
    RECOVER_SWAPPING = "recover_swapping"
    MCP_STARTUP = "mcp_startup"


class ScenarioDisposition(StrEnum):
    PASS = "pass"
    TARGET_MISSED = "target_missed"
    CAPACITY_EXCEEDED = "capacity_exceeded"


class WorkspaceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: Literal["smoke", "small", "medium", "large", "probe"]
    document_count: int = Field(ge=1, le=10_000)
    target_wiki_bytes: int = Field(ge=1, le=104_857_600)
    source_characters: int = Field(ge=1, le=100_000)
    seed: Literal[20260719]


CheckpointName = Literal["initialized_workspace", "prepared", "interrupted", "committed", "cleaned"]
CheckpointBytes = Annotated[int, Field(ge=0)]


def _empty_checkpoint_bytes() -> dict[CheckpointName, CheckpointBytes]:
    return {}


class FixtureIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: str = Field(min_length=1, max_length=16)
    document_count: int = Field(ge=1, le=10_000)
    exact_wiki_bytes: int = Field(ge=1, le=104_857_600)
    exact_workspace_bytes: int = Field(ge=1)
    source_characters: int = Field(ge=1, le=100_000)
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SampleObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario: ScenarioName
    scenario_version: Literal[1] = 1
    profile: str | None
    duration_ns: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_bytes: dict[CheckpointName, CheckpointBytes] = Field(
        default_factory=_empty_checkpoint_bytes
    )


class EnvironmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    python_version: str = Field(min_length=1, max_length=32)
    python_implementation: str = Field(min_length=1, max_length=32)
    os_name: str = Field(min_length=1, max_length=32)
    os_release: str = Field(min_length=1, max_length=128)
    architecture: str = Field(min_length=1, max_length=32)
    logical_cpu_count: int | None = Field(default=None, ge=1)
    total_memory_bytes: int | None = Field(default=None, ge=1)
    runner_image: str | None = Field(default=None, max_length=128)
    filesystem_type: str | None = Field(default=None, max_length=64)


def _median_ns(samples: tuple[int, ...]) -> int:
    return sorted(samples)[len(samples) // 2]


def _nearest_rank_p95_ns(samples: tuple[int, ...]) -> int:
    sorted_samples = sorted(samples)
    return sorted_samples[(95 * len(sorted_samples) + 99) // 100 - 1]


class ScenarioEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario: ScenarioName
    scenario_version: Literal[1] = 1
    profile: str | None
    target_ns: int = Field(ge=1)
    samples_ns: tuple[int, ...]
    median_ns: int = Field(ge=0)
    p95_ns: int = Field(ge=0)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_bytes: dict[CheckpointName, CheckpointBytes] = Field(
        default_factory=_empty_checkpoint_bytes
    )
    disposition: ScenarioDisposition

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if not self.samples_ns:
            raise ValueError("scenario evidence requires at least one sample")
        if any(sample < 0 for sample in self.samples_ns):
            raise ValueError("scenario samples must be nonnegative")
        if self.median_ns != _median_ns(self.samples_ns):
            raise ValueError("median_ns must match the recorded samples")
        if self.p95_ns != _nearest_rank_p95_ns(self.samples_ns):
            raise ValueError("p95_ns must match the recorded samples")
        if self.disposition is ScenarioDisposition.CAPACITY_EXCEEDED:
            raise ValueError("scenario evidence cannot declare capacity exceeded")
        expected_disposition = (
            ScenarioDisposition.TARGET_MISSED
            if self.median_ns > self.target_ns
            else ScenarioDisposition.PASS
        )
        if self.disposition is not expected_disposition:
            raise ValueError("scenario disposition must match the median target result")
        return self


class CapacityStop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: Literal["large", "probe"]
    scenario: ScenarioName
    deadline_ns: int = Field(ge=1)
    reason: Literal["deadline_exceeded"] = "deadline_exceeded"


_PROFILE_ORDER = ("smoke", "small", "medium", "large", "probe")
_READ_ONLY_SCENARIOS = frozenset(
    {
        ScenarioName.INITIALIZE,
        ScenarioName.STATUS,
        ScenarioName.LIST_CONCEPTS,
        ScenarioName.READ_CONCEPT,
        ScenarioName.SEARCH_PRESENT,
        ScenarioName.SEARCH_ABSENT,
        ScenarioName.LINT,
        ScenarioName.MCP_STARTUP,
    }
)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    suite_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    started_at: AwareDatetime
    completed_at: AwareDatetime
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    bundlewalker_version: str = Field(min_length=1, max_length=64)
    environment: EnvironmentRecord
    profiles: tuple[WorkspaceProfile, ...]
    fixtures: tuple[FixtureIdentity, ...]
    correctness_only: bool
    warmup_count: Literal[0, 1]
    read_only_repetitions: Literal[1, 7]
    mutation_repetitions: Literal[1, 5]
    scenarios: tuple[ScenarioEvidence, ...]
    capacity_stop: CapacityStop | None = None
    disposition: ScenarioDisposition

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")

        profile_names = tuple(profile.name for profile in self.profiles)
        if len(profile_names) != len(set(profile_names)):
            raise ValueError("profiles must have unique names")
        if profile_names != tuple(sorted(profile_names, key=_PROFILE_ORDER.index)):
            raise ValueError("profiles must use catalog order")

        fixture_names = tuple(fixture.profile for fixture in self.fixtures)
        if fixture_names != profile_names:
            raise ValueError("fixtures must contain one ordered identity for every profile")
        profiles_by_name = {profile.name: profile for profile in self.profiles}
        for fixture in self.fixtures:
            profile = profiles_by_name[fixture.profile]
            if fixture.document_count != profile.document_count:
                raise ValueError("fixture document count must match its profile")
            if fixture.source_characters != profile.source_characters:
                raise ValueError("fixture source characters must match its profile")

        profile_name_set = set(profile_names)
        for scenario in self.scenarios:
            if scenario.profile is not None and scenario.profile not in profile_name_set:
                raise ValueError("scenario references an unknown profile")

        expected_warmup, expected_read_only, expected_mutation = (
            (0, 1, 1) if self.correctness_only else (1, 7, 5)
        )
        if (
            self.warmup_count,
            self.read_only_repetitions,
            self.mutation_repetitions,
        ) != (expected_warmup, expected_read_only, expected_mutation):
            raise ValueError("measurement policy does not match correctness_only")
        for scenario in self.scenarios:
            expected_samples = (
                self.read_only_repetitions
                if scenario.scenario in _READ_ONLY_SCENARIOS
                else self.mutation_repetitions
            )
            if len(scenario.samples_ns) != expected_samples:
                raise ValueError("scenario sample count does not match measurement policy")

        if self.capacity_stop is not None and self.capacity_stop.profile not in profile_name_set:
            raise ValueError("capacity stop references an unknown profile")
        expected_disposition = (
            ScenarioDisposition.CAPACITY_EXCEEDED
            if self.capacity_stop is not None
            else ScenarioDisposition.TARGET_MISSED
            if any(
                scenario.disposition is ScenarioDisposition.TARGET_MISSED
                for scenario in self.scenarios
            )
            else ScenarioDisposition.PASS
        )
        if self.disposition is not expected_disposition:
            raise ValueError("record disposition does not match scenarios and capacity stop")
        return self
