# BundleWalker Performance and Capacity Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (- [ ]) syntax for tracking.

**Goal:** Build the merged measurement foundation for public-beta Milestone B3 without publishing
a supported-capacity claim.

**Architecture:** Add a development-only benchmarks package that generates deterministic synthetic
workspaces, executes correctness-checked scenarios in isolated workers, records strict JSON
evidence, and renders a provisional report. Normal CI runs one untimed Smoke correctness pass;
scheduled/manual CI runs the supported timing matrix and uploads candidate evidence.

**Tech Stack:** Python 3.13/3.14, Pydantic v2, pytest/pytest-asyncio, MCP Python SDK, Typer-free
internal argparse entry point, GitHub Actions, Ruff, and strict Pyright.

## Global Constraints

- Keep benchmark code outside src/bundlewalker and out of wheels and source distributions.
- Add no runtime or development dependency.
- Make no user-facing benchmark command and no supported-capacity claim in Phase 1.
- Use only deterministic ASCII synthetic content; perform no remote model call or telemetry.
- Use fixed suite version 1 and fixed seed 20260719.
- Use profiles: Smoke 50/0.5 MiB/10,000 characters; Small 250/2.5 MiB/25,000; Medium
  1,000/10 MiB/50,000; Large 5,000/50 MiB/100,000; Probe 10,000/100 MiB/100,000.
- Never exceed the existing max_source_characters = 100000 workspace contract.
- Keep macOS and Linux official on Python 3.13 and 3.14; do not claim Windows capacity.
- Exclude model/provider latency, fixture creation, fixture copying, and Python startup from
  ordinary operation durations.
- Include MCP process startup in the MCP startup scenario.
- Use perf_counter_ns, one warm-up, seven read-only samples, and five mutation/recovery samples.
- Treat correctness, integrity, cleanup, schema, and privacy failures as hard failures.
- Keep timing comparisons informational; do not add a required timing check.
- Every new Python file starts with the repository GPL-3.0-or-later copyright header.
- Do not refactor production transaction behavior unless a measured, characterized blocker is
  separately approved.

---

## File structure

Create these focused modules:

- benchmarks/__init__.py — suite constants and package boundary.
- benchmarks/contracts.py — strict profile, sample, environment, scenario, and evidence models.
- benchmarks/profiles.py — immutable profile and target catalogs.
- benchmarks/fixtures.py — deterministic workspace generation and fixture identity.
- benchmarks/evidence.py — statistics, privacy-safe environment collection, validation, and atomic
  JSON persistence.
- benchmarks/scenarios/read_only.py — initialization, status, list, read, search, and lint.
- benchmarks/scenarios/mutation.py — deterministic ingestion, commit, and recovery.
- benchmarks/scenarios/mcp_startup.py — MCP stdio initialization and tool discovery.
- benchmarks/scenarios/__init__.py — scenario registry and shared callable protocol.
- benchmarks/crash_worker.py — subprocess-only authenticated transaction crash fixture.
- benchmarks/worker.py — one isolated sample process and atomic observation output.
- benchmarks/runner.py — profile/repetition orchestration and timeout policy.
- benchmarks/report.py — deterministic provisional Markdown renderer and comparison classifier.
- benchmarks/__main__.py — development-only argparse entry point.
- tests/benchmarks/ — focused tests matching the module boundaries above.
- .github/workflows/benchmarks.yml — scheduled/manual supported-platform matrix.
- docs/performance-and-capacity.md — provisional, no-claim public documentation.

Modify:

- pyproject.toml — include benchmarks in strict Pyright checking and exclude it from distributions.
- .gitignore — ignore generated fixtures, local results, and temporary benchmark output.
- tests/test_release_metadata.py — extend GPL-header and distribution-exclusion checks.
- tests/test_project_automation.py — lock down benchmark workflow triggers, matrix, permissions,
  commands, and pinned actions.
- README.md, SUPPORT.md, docs/user-guide.md, and CHANGELOG.md — link the provisional performance
  document without changing the proof-of-concept status.

---

### Task 1: Freeze benchmark contracts and profile catalog

**Files:**

- Create: benchmarks/__init__.py
- Create: benchmarks/contracts.py
- Create: benchmarks/profiles.py
- Create: tests/benchmarks/__init__.py
- Create: tests/benchmarks/test_profiles.py
- Modify: pyproject.toml
- Modify: tests/test_release_metadata.py

**Interfaces:**

- Produces: SUITE_VERSION: Literal[1], FIXTURE_SEED: Literal[20260719]
- Produces: WorkspaceProfile, FixtureIdentity, CapacityStop, ScenarioName, ScenarioDisposition,
  SampleObservation, EnvironmentRecord, ScenarioEvidence, and EvidenceRecord
- Produces: PROFILES: Mapping[str, WorkspaceProfile]
- Produces: target_ns(scenario: ScenarioName) -> int
- Consumes: Pydantic BaseModel, ConfigDict, Field, and model validators already in dependencies

- [ ] **Step 1: Write failing profile and repository-policy tests**

Create tests/benchmarks/test_profiles.py with exact catalog assertions:

~~~python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from benchmarks import FIXTURE_SEED, SUITE_VERSION
from benchmarks.contracts import ScenarioName
from benchmarks.profiles import PROFILES, target_ns


def test_suite_and_profiles_are_fixed() -> None:
    assert SUITE_VERSION == 1
    assert FIXTURE_SEED == 20260719
    assert {
        name: (profile.document_count, profile.target_wiki_bytes, profile.source_characters)
        for name, profile in PROFILES.items()
    } == {
        "smoke": (50, 512 * 1024, 10_000),
        "small": (250, 2_621_440, 25_000),
        "medium": (1_000, 10_485_760, 50_000),
        "large": (5_000, 52_428_800, 100_000),
        "probe": (10_000, 104_857_600, 100_000),
    }
    assert all(profile.seed == FIXTURE_SEED for profile in PROFILES.values())
    assert max(profile.source_characters for profile in PROFILES.values()) == 100_000


def test_reference_targets_are_nanoseconds() -> None:
    assert target_ns(ScenarioName.SEARCH_PRESENT) == 2_000_000_000
    assert target_ns(ScenarioName.INITIALIZE) == 3_000_000_000
    assert target_ns(ScenarioName.MCP_STARTUP) == 5_000_000_000
    assert target_ns(ScenarioName.LINT) == 30_000_000_000
    assert target_ns(ScenarioName.PREPARE_INGESTION) == 60_000_000_000
    assert target_ns(ScenarioName.COMMIT) == 60_000_000_000
    assert target_ns(ScenarioName.RECOVER_SWAPPING) == 60_000_000_000
~~~

Extend test_all_python_files_have_gpl_spdx_headers in tests/test_release_metadata.py:

~~~python
python_files = sorted((PROJECT_ROOT / "src").rglob("*.py"))
python_files.extend(sorted((PROJECT_ROOT / "tests").rglob("*.py")))
python_files.extend(sorted((PROJECT_ROOT / "benchmarks").rglob("*.py")))
~~~

Add a test that built artifacts exclude development benchmark code:

~~~python
# Extend the existing pathlib import to: from pathlib import Path, PurePosixPath

def test_benchmark_harness_is_not_packaged(tmp_path: Path) -> None:
    result = subprocess.run(
        ["uv", "build", "--clear", "--no-sources", "--out-dir", str(tmp_path)],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("*.whl"))
    unpacked = tmp_path / "wheel"
    shutil.unpack_archive(wheel, unpacked, "zip")
    assert not (unpacked / "benchmarks").exists()
    sdist = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        assert not any(
            PurePosixPath(name).parts[1:2] == ("benchmarks",)
            for name in archive.getnames()
        )
~~~

- [ ] **Step 2: Run the focused tests and verify the imports fail**

Run:

~~~bash
uv run pytest tests/benchmarks/test_profiles.py tests/test_release_metadata.py::test_benchmark_harness_is_not_packaged -q
~~~

Expected: collection fails with ModuleNotFoundError for benchmarks.

- [ ] **Step 3: Implement strict contracts and fixed profiles**

In benchmarks/__init__.py define only:

~~~python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Literal

SUITE_VERSION: Literal[1] = 1
FIXTURE_SEED: Literal[20260719] = 20260719
~~~

In benchmarks/contracts.py define frozen, strict Pydantic models. Use extra="forbid" throughout.
The public fields and enum values are:

~~~python
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


CheckpointName = Literal[
    "initialized_workspace", "prepared", "interrupted", "committed", "cleaned"
]
CheckpointBytes = Annotated[int, Field(ge=0)]


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
    checkpoint_bytes: dict[CheckpointName, CheckpointBytes] = Field(default_factory=dict)


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
    checkpoint_bytes: dict[CheckpointName, CheckpointBytes] = Field(default_factory=dict)
    disposition: ScenarioDisposition


class CapacityStop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile: Literal["large", "probe"]
    scenario: ScenarioName
    deadline_ns: int = Field(ge=1)
    reason: Literal["deadline_exceeded"] = "deadline_exceeded"


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
~~~

Add model validators that require completed_at >= started_at, unique ordered profile names, exactly
one FixtureIdentity for every listed profile, matching profile/profile-digest relationships, no
unknown scenario profile, policy-consistent sample counts, and PASS only when every included
scenario is PASS. CAPACITY_EXCEEDED requires one CapacityStop; PASS and TARGET_MISSED forbid it.
ScenarioEvidence validates nonempty samples, nonnegative checkpoint values, median/p95
recomputation, forbids CAPACITY_EXCEEDED at scenario level, and uses TARGET_MISSED if and only if
median_ns exceeds target_ns.

In benchmarks/profiles.py build an insertion-ordered dict in the table order and define targets:

~~~python
_MIB = 1024 * 1024

PROFILES: Final[Mapping[str, WorkspaceProfile]] = MappingProxyType(
    {
        "smoke": WorkspaceProfile(name="smoke", document_count=50, target_wiki_bytes=_MIB // 2, source_characters=10_000, seed=FIXTURE_SEED),
        "small": WorkspaceProfile(name="small", document_count=250, target_wiki_bytes=5 * _MIB // 2, source_characters=25_000, seed=FIXTURE_SEED),
        "medium": WorkspaceProfile(name="medium", document_count=1_000, target_wiki_bytes=10 * _MIB, source_characters=50_000, seed=FIXTURE_SEED),
        "large": WorkspaceProfile(name="large", document_count=5_000, target_wiki_bytes=50 * _MIB, source_characters=100_000, seed=FIXTURE_SEED),
        "probe": WorkspaceProfile(name="probe", document_count=10_000, target_wiki_bytes=100 * _MIB, source_characters=100_000, seed=FIXTURE_SEED),
    }
)

_TARGET_SECONDS = {
    ScenarioName.INITIALIZE: 3,
    ScenarioName.STATUS: 2,
    ScenarioName.LIST_CONCEPTS: 2,
    ScenarioName.READ_CONCEPT: 2,
    ScenarioName.SEARCH_PRESENT: 2,
    ScenarioName.SEARCH_ABSENT: 2,
    ScenarioName.MCP_STARTUP: 5,
    ScenarioName.LINT: 30,
    ScenarioName.PREPARE_INGESTION: 60,
    ScenarioName.COMMIT: 60,
    ScenarioName.RECOVER_PREPARED: 60,
    ScenarioName.RECOVER_SWAPPING: 60,
}


def target_ns(scenario: ScenarioName) -> int:
    return _TARGET_SECONDS[scenario] * 1_000_000_000
~~~

Update pyproject.toml:

~~~toml
[tool.hatch.build.targets.wheel]
exclude = ["benchmarks/**"]

[tool.hatch.build.targets.sdist]
exclude = [".superpowers/**", "benchmarks/**"]

[tool.pyright]
include = ["src", "tests", "benchmarks"]
~~~

- [ ] **Step 4: Run focused quality checks**

Run:

~~~bash
uv run pytest tests/benchmarks/test_profiles.py tests/test_release_metadata.py::test_benchmark_harness_is_not_packaged tests/test_release_metadata.py::test_all_python_files_have_gpl_spdx_headers -q
uv run ruff format --check benchmarks tests/benchmarks tests/test_release_metadata.py
uv run ruff check benchmarks tests/benchmarks tests/test_release_metadata.py
uv run pyright
~~~

Expected: all commands pass.

- [ ] **Step 5: Commit the profile contract**

~~~bash
git add benchmarks tests/benchmarks pyproject.toml tests/test_release_metadata.py
git commit -m "feat: define benchmark profile contracts"
~~~

### Task 2: Generate deterministic valid workspaces

**Files:**

- Create: benchmarks/fixtures.py
- Create: tests/benchmarks/test_fixtures.py

**Interfaces:**

- Consumes: WorkspaceProfile from benchmarks.contracts
- Produces: GeneratedFixture
- Produces: generate_fixture(destination: Path, profile: WorkspaceProfile) -> GeneratedFixture
- Produces: tree_sha256(root: Path) -> str

- [ ] **Step 1: Write failing generator tests**

Create tests that use two Smoke generations and a reduced private profile:

~~~python
def test_fixture_is_deterministic_valid_and_exactly_sized(tmp_path: Path) -> None:
    first = generate_fixture(tmp_path / "first", PROFILES["smoke"])
    second = generate_fixture(tmp_path / "second", PROFILES["smoke"])

    assert first.tree_sha256 == second.tree_sha256
    assert first.exact_wiki_bytes == 512 * 1024
    assert second.exact_wiki_bytes == first.exact_wiki_bytes
    assert len(first.concept_ids) == 50
    assert len(first.ingestion_content) == 10_000
    assert first.ingestion_content.isascii()
    assert lint_bundle(first.workspace.wiki_dir, first.workspace.root) == []


def test_profile_growth_changes_only_scale(tmp_path: Path) -> None:
    smoke = generate_fixture(tmp_path / "smoke", PROFILES["smoke"])
    small = generate_fixture(tmp_path / "small", PROFILES["small"])

    assert len(smoke.concept_ids) < len(small.concept_ids)
    assert smoke.exact_wiki_bytes < small.exact_wiki_bytes
    assert smoke.type_ratios == small.type_ratios == (1, 4, 3, 2)
    assert smoke.present_query == small.present_query == "benchmark-needle"
~~~

- [ ] **Step 2: Run tests and verify the missing generator failure**

Run:

~~~bash
uv run pytest tests/benchmarks/test_fixtures.py -q
~~~

Expected: collection fails because benchmarks.fixtures does not exist.

- [ ] **Step 3: Implement generation through production document helpers**

Define GeneratedFixture as a frozen dataclass with workspace, profile, exact_wiki_bytes,
exact_workspace_bytes, tree_sha256, concept_ids, present_query, absent_query, read_concept_id,
ingestion_content, and type_ratios. Add identity() -> FixtureIdentity so the runner records the
exact generated scale rather than only the requested profile. profile_sha256 is SHA-256 over the
profile's canonical JSON (ASCII, sorted keys, compact separators); tree_sha256 covers the complete
generated workspace file tree.

Use this fixed type cycle:

~~~python
_TYPE_CYCLE = (
    ConceptType.SOURCE,
    ConceptType.TOPIC,
    ConceptType.TOPIC,
    ConceptType.TOPIC,
    ConceptType.TOPIC,
    ConceptType.ENTITY,
    ConceptType.ENTITY,
    ConceptType.ENTITY,
    ConceptType.SYNTHESIS,
    ConceptType.SYNTHESIS,
)
_CATEGORY = {
    ConceptType.SOURCE: "sources",
    ConceptType.TOPIC: "topics",
    ConceptType.ENTITY: "entities",
    ConceptType.SYNTHESIS: "syntheses",
}
_NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)
~~~

For each index, create category/concept-NNNNNN, point its Markdown link to the next concept in a
ring, and put benchmark-needle only in concept 000042. Every third document includes citation [1]
to the most recent Source concept with line range 1-1, yielding the same citation density at every
profile. Source concepts receive a deterministic two-line raw file and matching resource,
source_sha256, and raw_path metadata. Render a matching # Citations section with the production
absolute-link syntax, then call regenerate_indexes.

Reach the exact target wiki byte count after indexes exist:

~~~python
def _pad_documents(wiki_root: Path, target_bytes: int, paths: tuple[Path, ...]) -> None:
    current = _tree_size(wiki_root)
    remaining = target_bytes - current
    if remaining < 0:
        raise ValueError("profile target is smaller than the valid generated wiki")
    share, extra = divmod(remaining, len(paths))
    for index, path in enumerate(paths):
        count = share + (1 if index < extra else 0)
        if count:
            with path.open("ab") as stream:
                stream.write(b"x" * count)
    if _tree_size(wiki_root) != target_bytes:
        raise AssertionError("fixture padding did not reach the exact profile size")
~~~

Build the ingestion string with an exact character count and at least two complete lines:

~~~python
def _ingestion_content(character_count: int) -> str:
    unit = "benchmark source line\n"
    repetitions = (character_count // len(unit)) + 1
    return (unit * repetitions)[:character_count]
~~~

Validate with discover_workspace, OkfRepository.scan, and lint_bundle. Reject any finding, not just
errors, so profiles have a stable empty finding set. Compute tree_sha256 from sorted relative
POSIX paths, a NUL separator, file length, a NUL separator, and file bytes.

- [ ] **Step 4: Verify the generator**

Run:

~~~bash
uv run pytest tests/benchmarks/test_fixtures.py -q
uv run ruff format --check benchmarks/fixtures.py tests/benchmarks/test_fixtures.py
uv run ruff check benchmarks/fixtures.py tests/benchmarks/test_fixtures.py
uv run pyright
~~~

Expected: all commands pass; the focused test creates two identical valid 0.5 MiB wikis.

- [ ] **Step 5: Commit deterministic generation**

~~~bash
git add benchmarks/fixtures.py tests/benchmarks/test_fixtures.py
git commit -m "feat: generate deterministic benchmark workspaces"
~~~

### Task 3: Validate and persist privacy-safe evidence

**Files:**

- Create: benchmarks/evidence.py
- Create: tests/benchmarks/factories.py
- Create: tests/benchmarks/test_evidence.py

**Interfaces:**

- Consumes: SampleObservation, ScenarioEvidence, EvidenceRecord
- Produces: nearest_rank_p95(samples: Sequence[int]) -> int
- Produces: summarize_samples(observations, target, *, correctness_only: bool = False) ->
  ScenarioEvidence
- Produces: collect_environment(root: Path) -> EnvironmentRecord
- Produces: write_new_json(path: Path, model: BaseModel) -> None
- Produces: write_new_text(path: Path, content: str) -> None
- Produces: write_evidence(path: Path, evidence: EvidenceRecord) -> None
- Produces: load_evidence(path: Path) -> EvidenceRecord
- Produces: materialized_bytes(root: Path) -> int

- [ ] **Step 1: Write failing statistics, privacy, and atomic-write tests**

Create tests/benchmarks/factories.py with a complete reusable evidence record:

~~~python
def evidence_record(
    *, os_name: str = "Linux", python_version: str = "3.13.0"
) -> EvidenceRecord:
    profile = PROFILES["smoke"]
    return EvidenceRecord(
        run_id=f"{os_name.casefold()}-{python_version}",
        started_at=datetime(2026, 7, 19, 12, tzinfo=UTC),
        completed_at=datetime(2026, 7, 19, 12, 1, tzinfo=UTC),
        git_commit="a" * 40,
        bundlewalker_version="0.4.0a2",
        environment=EnvironmentRecord(
            python_version=python_version,
            python_implementation="CPython",
            os_name=os_name,
            os_release="reference",
            architecture="arm64" if os_name == "Darwin" else "x86_64",
            logical_cpu_count=4,
            total_memory_bytes=8 * 1024**3,
            runner_image="reference",
            filesystem_type="apfs" if os_name == "Darwin" else "ext2/ext3",
        ),
        profiles=(profile,),
        fixtures=(
            FixtureIdentity(
                profile="smoke",
                document_count=50,
                exact_wiki_bytes=512 * 1024,
                exact_workspace_bytes=600_000,
                source_characters=10_000,
                profile_sha256="d" * 64,
                tree_sha256="b" * 64,
            ),
        ),
        correctness_only=False,
        warmup_count=1,
        read_only_repetitions=7,
        mutation_repetitions=5,
        scenarios=(
            ScenarioEvidence(
                scenario=ScenarioName.STATUS,
                profile="smoke",
                target_ns=2_000_000_000,
                samples_ns=(100, 200, 300, 400, 500, 600, 700),
                median_ns=400,
                p95_ns=700,
                output_sha256="c" * 64,
                disposition=ScenarioDisposition.PASS,
            ),
        ),
        capacity_stop=None,
        disposition=ScenarioDisposition.PASS,
    )
~~~

Then add these tests:

~~~python
def test_summary_uses_median_nearest_rank_p95_and_stable_output() -> None:
    observations = tuple(
        SampleObservation(
            scenario=ScenarioName.STATUS,
            profile="smoke",
            duration_ns=value,
            output_sha256="a" * 64,
        )
        for value in (100, 200, 300, 400, 500, 600, 700)
    )
    result = summarize_samples(observations, target=350)
    assert result.median_ns == 400
    assert result.p95_ns == 700
    assert result.disposition is ScenarioDisposition.TARGET_MISSED


def test_environment_record_contains_no_identity_or_paths(tmp_path: Path) -> None:
    serialized = collect_environment(tmp_path).model_dump_json()
    if username := getpass.getuser():
        assert username not in serialized
    if hostname := platform.node():
        assert hostname not in serialized
    assert str(tmp_path) not in serialized
    assert "environment" not in serialized.casefold()


def test_evidence_writer_refuses_an_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "evidence.json"
    destination.write_text("existing\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_evidence(destination, evidence_record())
    assert destination.read_text(encoding="utf-8") == "existing\n"


def test_atomic_write_cleans_owned_temporary_file_after_link_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "evidence.json"

    def fail_link(_source: Path, _destination: Path) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="injected link failure"):
        write_evidence(destination, evidence_record())
    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))
~~~

- [ ] **Step 2: Run focused tests and verify failure**

Run:

~~~bash
uv run pytest tests/benchmarks/test_evidence.py -q
~~~

Expected: collection fails because benchmarks.evidence does not exist.

- [ ] **Step 3: Implement strict aggregation and atomic JSON**

Implement nearest-rank p95 as sorted_samples[ceil(0.95 * count) - 1]. Require exactly one
scenario/profile/output digest across a sample group. Require seven samples for read-only scenarios
and five for mutation/recovery scenarios; accept one sample only when correctness_only=True.
Aggregate each checkpoint with max so disk guidance remains conservative.

Use an allowlist for environment collection:

~~~python
def collect_environment(root: Path) -> EnvironmentRecord:
    return EnvironmentRecord(
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        os_name=platform.system(),
        os_release=platform.release(),
        architecture=platform.machine(),
        logical_cpu_count=os.cpu_count(),
        total_memory_bytes=_portable_total_memory(),
        runner_image=os.environ.get("ImageOS"),
        filesystem_type=_portable_filesystem_type(root),
    )
~~~

Do not call getpass.getuser, platform.node, os.environ.copy, or serialize arbitrary environment
keys. On macOS/Linux, total memory may use sysconf when available; filesystem type may use a
bounded subprocess call to stat with explicit argv and a five-second timeout. Use
["stat", "-f", "%T", root] on Darwin and ["stat", "-f", "-c", "%T", "--", root] on Linux,
capture at most one 64-character output line, and return None when a portable value is unavailable.

write_evidence delegates to write_new_json. For JSON and text writes, reject an existing
destination before creating state. Create a mode-0600 temporary
sibling with O_CREAT | O_EXCL | O_WRONLY, write canonical UTF-8 JSON with indent=2 and
sort_keys=True, flush and fsync, then publish without replacement by linking the temporary inode to
the destination with os.link. Unlink the owned temporary name and fsync the parent. Delete only the
exact temporary inode created by this call after a failure; use the support-report ownership
pattern rather than broad pathname cleanup.

- [ ] **Step 4: Verify evidence behavior**

Run:

~~~bash
uv run pytest tests/benchmarks/test_evidence.py -q
uv run ruff format --check benchmarks/evidence.py tests/benchmarks/test_evidence.py
uv run ruff check benchmarks/evidence.py tests/benchmarks/test_evidence.py
uv run pyright
~~~

Expected: all commands pass.

- [ ] **Step 5: Commit evidence contracts**

~~~bash
git add benchmarks/evidence.py tests/benchmarks/factories.py tests/benchmarks/test_evidence.py
git commit -m "feat: record strict benchmark evidence"
~~~

### Task 4: Implement correctness-checked local scenarios

**Files:**

- Create: benchmarks/scenarios/__init__.py
- Create: benchmarks/scenarios/read_only.py
- Create: tests/benchmarks/test_read_only_scenarios.py

**Interfaces:**

- Consumes: GeneratedFixture
- Produces: ScenarioCallable protocol
- Produces: READ_ONLY_SCENARIOS: Mapping[ScenarioName, ScenarioCallable]
- Produces: run_read_only(scenario: ScenarioName, fixture: GeneratedFixture) -> SampleObservation
- Produces: run_initialization(destination: Path) -> SampleObservation; INITIALIZE is intentionally
  outside READ_ONLY_SCENARIOS because it consumes a nonexistent destination rather than a fixture

- [ ] **Step 1: Write failing scenario tests**

~~~python
@pytest.mark.parametrize(
    "scenario",
    [
        ScenarioName.STATUS,
        ScenarioName.LIST_CONCEPTS,
        ScenarioName.READ_CONCEPT,
        ScenarioName.SEARCH_PRESENT,
        ScenarioName.SEARCH_ABSENT,
        ScenarioName.LINT,
    ],
)
def test_read_only_scenarios_are_correct_and_do_not_mutate(
    tmp_path: Path, scenario: ScenarioName
) -> None:
    fixture = generate_fixture(tmp_path / scenario.value, PROFILES["smoke"])
    before = fixture.tree_sha256
    observation = run_read_only(scenario, fixture)

    assert observation.scenario is scenario
    assert observation.profile == "smoke"
    assert observation.duration_ns >= 0
    assert len(observation.output_sha256) == 64
    assert tree_sha256(fixture.workspace.root) == before


def test_initialization_measures_a_new_standard_workspace(tmp_path: Path) -> None:
    observation = run_initialization(tmp_path / "new-workspace")
    assert observation.scenario is ScenarioName.INITIALIZE
    assert observation.profile is None
    assert observation.checkpoint_bytes["initialized_workspace"] > 0
~~~

- [ ] **Step 2: Verify the scenario imports fail**

Run:

~~~bash
uv run pytest tests/benchmarks/test_read_only_scenarios.py -q
~~~

Expected: collection fails because benchmarks.scenarios.read_only does not exist.

- [ ] **Step 3: Implement scenario timing around production boundaries**

In benchmarks/scenarios/__init__.py define:

~~~python
class ScenarioCallable(Protocol):
    def __call__(self, fixture: GeneratedFixture) -> SampleObservation: ...
~~~

In read_only.py, use asyncio.run for application methods and a single helper that hashes canonical
JSON output:

~~~python
def _measure(
    fixture: GeneratedFixture,
    scenario: ScenarioName,
    operation: Callable[[], object],
) -> SampleObservation:
    started = time.perf_counter_ns()
    result = operation()
    duration = time.perf_counter_ns() - started
    canonical = json.dumps(
        _jsonable(result), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return SampleObservation(
        scenario=scenario,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=hashlib.sha256(canonical).hexdigest(),
    )
~~~

The exact correctness checks are:

- status concept counts sum to profile.document_count and pending_review is None;
- list_concepts(limit=100) returns the first 100 or all concepts in canonical order;
- read_concept(fixture.read_concept_id) returns that exact ID and Markdown containing its unique
  benchmark token;
- present search returns fixture.read_concept_id first;
- absent search returns an empty tuple;
- lint with semantic=False returns no findings and deterministic_has_errors is False;
- initialization validates a new default workspace and records its materialized byte count.

Compute each output digest only after its assertions pass. Catch no BundleWalker exception; a
production failure must fail the worker.

- [ ] **Step 4: Verify read-only scenarios**

Run:

~~~bash
uv run pytest tests/benchmarks/test_read_only_scenarios.py -q
uv run ruff format --check benchmarks/scenarios tests/benchmarks/test_read_only_scenarios.py
uv run ruff check benchmarks/scenarios tests/benchmarks/test_read_only_scenarios.py
uv run pyright
~~~

Expected: all commands pass.

- [ ] **Step 5: Commit local scenarios**

~~~bash
git add benchmarks/scenarios tests/benchmarks/test_read_only_scenarios.py
git commit -m "feat: measure read-only workspace scenarios"
~~~

### Task 5: Implement deterministic ingestion, commit, and recovery scenarios

**Files:**

- Create: benchmarks/scenarios/mutation.py
- Create: benchmarks/crash_worker.py
- Modify: benchmarks/scenarios/__init__.py
- Create: tests/benchmarks/test_mutation_scenarios.py

**Interfaces:**

- Consumes: GeneratedFixture and WorkspaceApplication
- Produces: MUTATION_SCENARIOS: Mapping[ScenarioName, ScenarioCallable]
- Produces: run_mutation(scenario: ScenarioName, fixture: GeneratedFixture) -> SampleObservation
- Produces: prepare_ingestion_application(fixture: GeneratedFixture) -> WorkspaceApplication
- Consumes privately: transactions._write_manifest only inside crash_worker.py, matching existing
  abrupt-termination tests

- [ ] **Step 1: Write failing mutation and recovery tests**

~~~python
@pytest.mark.parametrize(
    "scenario",
    [
        ScenarioName.PREPARE_INGESTION,
        ScenarioName.COMMIT,
        ScenarioName.RECOVER_PREPARED,
        ScenarioName.RECOVER_SWAPPING,
    ],
)
def test_mutation_scenarios_reach_one_safe_end_state(
    tmp_path: Path, scenario: ScenarioName
) -> None:
    fixture = generate_fixture(tmp_path / scenario.value, PROFILES["smoke"])
    observation = run_mutation(scenario, fixture)

    assert observation.scenario is scenario
    assert observation.profile == "smoke"
    assert observation.duration_ns >= 0
    assert set(observation.checkpoint_bytes).issubset(
        {"prepared", "interrupted", "committed", "cleaned"}
    )
    assert lint_bundle(fixture.workspace.wiki_dir, fixture.workspace.root) == []


def test_ingestion_uses_full_profile_source_without_network(tmp_path: Path) -> None:
    source_limit_profile = PROFILES["smoke"].model_copy(
        update={"source_characters": 100_000}
    )
    fixture = generate_fixture(tmp_path / "source-limit", source_limit_profile)
    application = prepare_ingestion_application(fixture)
    result = asyncio.run(
        application.prepare_ingestion(
            InlineSource(source_name="benchmark-source.txt", content=fixture.ingestion_content),
            explicit_model="benchmark:deterministic",
        )
    )
    assert len(fixture.ingestion_content) == 100_000
    assert result.status == "pending"
~~~

- [ ] **Step 2: Run focused tests and verify failure**

Run:

~~~bash
uv run pytest tests/benchmarks/test_mutation_scenarios.py -q
~~~

Expected: collection fails because benchmarks.scenarios.mutation does not exist.

- [ ] **Step 3: Implement the deterministic ingestion runner**

Use ApplicationDependencies with environment={}, a fixed UTC clock, and this runner:

~~~python
async def deterministic_ingestion_runner(
    model: AgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    if model != "benchmark:deterministic":
        raise AssertionError("benchmark model boundary changed")
    change_set = ChangeSet(
        summary="Integrated deterministic benchmark source.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Benchmark source",
                description="Deterministic benchmark ingestion.",
                tags=["benchmark"],
                body="# Benchmark source\n\nA deterministic claim [1].\n",
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=1,
                    )
                ],
            )
        ],
    )
    return change_set, frozenset()
~~~

For PREPARE_INGESTION, create InlineSource before starting the timer; time only
WorkspaceApplication.prepare_ingestion. Verify a pending review exists, live wiki/raw identities
are unchanged, and record the prepared transaction tree bytes. Its output digest covers status,
sorted changed paths, live tree digest, and prospective tree digest; it excludes the random review
ID, transaction directory name, timestamps, and absolute paths.

For COMMIT, prepare the durable review before starting the timer, then time apply_review. Verify
the review is absent, the stored raw source digest matches, the wiki is valid, and the transaction
root is empty. Record prepared, committed, and cleaned bytes.
Commit/recovery output digests cover only the expected live wiki digest, raw-source digest, pending
status, and clean-transaction boolean so repetitions remain comparable across random transaction
IDs.

Extend benchmarks/scenarios/__init__.py with
SCENARIOS = {**READ_ONLY_SCENARIOS, **MUTATION_SCENARIOS}; Task 6 adds MCP_STARTUP to the same
registry.

- [ ] **Step 4: Implement authenticated crash fixtures and recovery**

benchmarks/crash_worker.py accepts workspace path, phase, and review ID. It patches only
transactions._write_manifest, calls the original writer first, then exits with code 86 after the
selected phase has been durably written:

~~~python
def crash_after_manifest(workspace_root: Path, phase: str, review_id: str) -> NoReturn:
    original = transactions._write_manifest  # pyright: ignore[reportPrivateUsage]

    def write_then_exit(
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        original(transaction_dir, manifest)
        if manifest.phase == phase:
            os._exit(86)

    transactions._write_manifest = write_then_exit  # pyright: ignore[reportPrivateUsage]
    workspace = discover_workspace(workspace_root)
    apply_pending_review(workspace, review_id)
    raise AssertionError("crash phase was not reached")
~~~

RECOVER_PREPARED prepares a review before timing, calls recover_transactions inside the timed
interval, and verifies the same pending review remains with an unchanged live wiki.

RECOVER_SWAPPING prepares a review, invokes python -m benchmarks.crash_worker with phase=swapping
before timing, requires exit code 86, records interrupted bytes, then times recover_transactions.
Verify the exact prospective wiki became live, raw content persisted, no pending review remains,
and the transaction root is empty. Call recovery a second time outside the timed interval and
verify identity is unchanged.

- [ ] **Step 5: Verify mutation and recovery safety**

Run:

~~~bash
uv run pytest tests/benchmarks/test_mutation_scenarios.py tests/test_transaction_crash_recovery.py -q
uv run ruff format --check benchmarks/scenarios/mutation.py benchmarks/crash_worker.py tests/benchmarks/test_mutation_scenarios.py
uv run ruff check benchmarks/scenarios/mutation.py benchmarks/crash_worker.py tests/benchmarks/test_mutation_scenarios.py
uv run pyright
~~~

Expected: all commands pass, including existing abrupt-termination coverage.

- [ ] **Step 6: Commit mutation scenarios**

~~~bash
git add benchmarks/scenarios/__init__.py benchmarks/scenarios/mutation.py benchmarks/crash_worker.py tests/benchmarks/test_mutation_scenarios.py
git commit -m "feat: measure transaction and recovery scenarios"
~~~

### Task 6: Measure MCP startup and isolate every sample

**Files:**

- Create: benchmarks/scenarios/mcp_startup.py
- Create: benchmarks/worker.py
- Modify: benchmarks/scenarios/__init__.py
- Create: tests/benchmarks/test_worker.py

**Interfaces:**

- Produces: run_mcp_startup(fixture: GeneratedFixture) -> SampleObservation
- Produces: run_worker(argv: Sequence[str] | None = None) -> int
- Worker argv: --scenario NAME --workspace PATH [--profile NAME] --output PATH
- Worker output: one schema-valid SampleObservation JSON object

- [ ] **Step 1: Write failing MCP and worker tests**

~~~python
def test_mcp_startup_discovers_stable_tools_and_cleans_process(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "mcp", PROFILES["smoke"])
    observation = run_mcp_startup(fixture)
    assert observation.scenario is ScenarioName.MCP_STARTUP
    assert observation.duration_ns > 0
    assert observation.output_sha256 == hashlib.sha256(
        json.dumps(EXPECTED_TOOL_NAMES, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def test_worker_writes_one_valid_observation_atomically(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    output = tmp_path / "observation.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.worker",
            "--scenario",
            "status",
            "--workspace",
            str(fixture.workspace.root),
            "--profile",
            "smoke",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    observation = SampleObservation.model_validate_json(output.read_text(encoding="utf-8"))
    assert observation.scenario is ScenarioName.STATUS
~~~

- [ ] **Step 2: Run tests and verify missing modules**

Run:

~~~bash
uv run pytest tests/benchmarks/test_worker.py -q
~~~

Expected: collection fails because the MCP scenario and worker do not exist.

- [ ] **Step 3: Implement MCP startup timing**

Use mcp.client.stdio.stdio_client with sys.executable -m bundlewalker.interfaces.mcp --workspace
PATH. Start perf_counter_ns immediately before entering stdio_client. Inside anyio.fail_after(30),
create ClientSession, await initialize, await list_tools, sort tool names, and stop the timer.
Validate names against this sorted tuple:

~~~python
EXPECTED_TOOL_NAMES = (
    "apply_review",
    "ask",
    "discard_review",
    "get_pending_review",
    "lint",
    "prepare_ingestion",
    "prepare_refresh",
    "prepare_synthesis",
    "search_concepts",
    "workspace_status",
)
~~~

Close both async context managers before returning. Capture stderr in a TemporaryFile and require it
to be empty.

- [ ] **Step 4: Implement the one-sample worker**

For INITIALIZE, --workspace must not exist and --profile is forbidden; call run_initialization on
that destination. For every other scenario, --workspace must be a discovered generated fixture and
--profile is required.

The worker discovers the existing fixture, reconstructs GeneratedFixture metadata from the fixed
profile and generated IDs, selects from SCENARIOS, and writes only SampleObservation JSON. Add
MCP_STARTUP: run_mcp_startup to SCENARIOS before implementing the worker.
Use the evidence module's exclusive atomic writer. Errors go to stderr as
"Benchmark worker failed: CLASS_NAME" with no raw exception message; this prevents path-bearing
domain errors from entering logs. Return 1 on a domain/scenario failure and 2 for argparse errors.

The worker does not measure its own startup. Controller process duration is used only to enforce a
deadline.

- [ ] **Step 5: Verify subprocess cleanup and protocol behavior**

Run:

~~~bash
uv run pytest tests/benchmarks/test_worker.py tests/interfaces/test_mcp_stdio.py -q
uv run ruff format --check benchmarks/scenarios/mcp_startup.py benchmarks/worker.py tests/benchmarks/test_worker.py
uv run ruff check benchmarks/scenarios/mcp_startup.py benchmarks/worker.py tests/benchmarks/test_worker.py
uv run pyright
~~~

Expected: all commands pass and no MCP process remains.

- [ ] **Step 6: Commit isolated workers**

~~~bash
git add benchmarks/scenarios/__init__.py benchmarks/scenarios/mcp_startup.py benchmarks/worker.py tests/benchmarks/test_worker.py
git commit -m "feat: isolate benchmark sample workers"
~~~

### Task 7: Orchestrate repetitions and render provisional reports

**Files:**

- Create: benchmarks/runner.py
- Create: benchmarks/report.py
- Create: benchmarks/__main__.py
- Create: tests/benchmarks/test_runner.py
- Create: tests/benchmarks/test_report.py

**Interfaces:**

- Produces: run_benchmarks(config: RunConfig) -> EvidenceRecord
- Produces: render_report(records: Sequence[EvidenceRecord], provisional: bool, require_matrix:
  bool = False) -> str
- Produces: is_material_regression(current_ns: int, baseline_ns: int) -> bool
- Development command: python -m benchmarks run --profiles smoke --correctness-only --output PATH
  [--run-id SAFE_ID] [--work-root DIRECTORY]
- Development command: python -m benchmarks run --profiles smoke,small,medium,large,probe --output
  PATH [--run-id SAFE_ID] [--work-root DIRECTORY]
- Development command: python -m benchmarks report --evidence DIRECTORY --output PATH --provisional
  [--require-matrix]

- [ ] **Step 1: Write failing controller and report tests**

~~~python
def test_correctness_only_runner_writes_one_sample_per_scenario(tmp_path: Path) -> None:
    evidence = run_benchmarks(
        RunConfig(
            profiles=(PROFILES["smoke"],),
            output=tmp_path / "evidence.json",
            work_root=tmp_path / "work",
            run_id="test-smoke",
            correctness_only=True,
        )
    )
    assert evidence.disposition is ScenarioDisposition.PASS
    assert {len(item.samples_ns) for item in evidence.scenarios} == {1}
    assert load_evidence(tmp_path / "evidence.json") == evidence


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
~~~

- [ ] **Step 2: Run focused tests and verify missing controller**

Run:

~~~bash
uv run pytest tests/benchmarks/test_runner.py tests/benchmarks/test_report.py -q
~~~

Expected: collection fails because runner and report modules do not exist.

- [ ] **Step 3: Implement controller deadlines, copies, and repetitions**

Define RunConfig as a frozen dataclass with profiles, output, work_root, run_id, and
correctness_only. The controller:

1. creates each fixture once under work_root/fixtures;
2. runs INITIALIZE once per sample at a unique nonexistent work-root child, independently of
   profiles;
3. performs one unrecorded warm-up per scenario unless correctness_only;
4. runs seven measured samples for initialization/read-only/MCP and five for
   ingestion/commit/recovery, or one for correctness_only;
5. reuses the fixture for read-only samples;
6. copies the complete fixture to a unique path before every mutation/recovery sample;
7. invokes sys.executable -m benchmarks.worker with explicit argv and no shell;
8. applies timeout=max(30, 3 * target_seconds);
9. terminates then kills a timed-out child using bounded waits;
10. requires one complete observation file and stable output digest across repetitions;
11. summarizes, validates, and atomically writes EvidenceRecord.

Use subprocess.run with capture_output=True and the calculated timeout for ordinary bounded
workers. On TimeoutExpired, set EvidenceRecord.capacity_stop and CAPACITY_EXCEEDED only for
Large/Probe, omit the incomplete scenario, and stop larger profiles. For Smoke through Medium,
raise BenchmarkRunError and publish no complete evidence. Any nonzero worker exit, invalid JSON,
unexpected profile/scenario, inconsistent digest, or cleanup residue raises BenchmarkRunError at
every profile.

Resolve git_commit with git rev-parse HEAD using explicit argv and require a lowercase 40-character
SHA. Read BundleWalker version from importlib.metadata.version. Set completed_at only after all
scenario records validate. Store every GeneratedFixture.identity() and set the explicit execution
policy fields: correctness-only records use warmup_count=0 and repetition values 1/1; full records
use warmup_count=1 and repetition values 7/5. Overall disposition precedence is
CAPACITY_EXCEEDED, then TARGET_MISSED, then PASS.

- [ ] **Step 4: Implement deterministic provisional rendering**

render_report sorts environments by os_name then Python version and scenarios by profile order then
ScenarioName value. It emits:

- the explicit provisional status;
- profile definitions and exact fixture sizes;
- measurement policy and reference targets;
- environment allowlist fields;
- per-scenario median and nearest-rank p95;
- checkpoint byte maxima;
- candidate profiles with candidate-only wording;
- model/provider and hardware limitations; and
- reproduction commands.

When provisional=True, reject any caller-supplied supported-envelope value and always render
Supported capacity: not yet published. When require_matrix=True, validate matrix keys are exactly
(Darwin, 3.13), (Darwin, 3.14), (Linux, 3.13), and (Linux, 3.14). A local provisional report may
render one or more records without implying matrix completeness. Derive 3.13/3.14 from the first
two numeric components of EnvironmentRecord.python_version and retain the full version in output.

Implement:

~~~python
def is_material_regression(current_ns: int, baseline_ns: int) -> bool:
    if current_ns < 0 or baseline_ns <= 0:
        raise ValueError("timing values must be positive")
    absolute_delta = current_ns - baseline_ns
    return absolute_delta >= 250_000_000 and current_ns * 100 >= baseline_ns * 125
~~~

Write reports atomically with the same ownership-safe helper as evidence.

- [ ] **Step 5: Add the internal argparse dispatcher**

benchmarks/__main__.py has required subcommands run and report. Use argparse only. Reject duplicate
profiles, unknown profiles, an existing output path, and output paths inside a generated fixture.
Default run is the full ordered profile list; correctness-only requires exactly Smoke. An omitted
run ID becomes local-YYYYMMDDTHHMMSSZ from the same captured start time; an explicit ID must match
[A-Za-z0-9._-]{1,128}. An omitted work root becomes benchmark-work/RUN_ID; an explicit work root
must be outside the output path and must not be a symlink. Create a missing output parent with mode
0700 before workers start, reject a symlink/non-directory parent, and never create parents above
the immediate requested output directory.

The module exits 0 on success, 1 on BenchmarkRunError/report validation failure, and 2 on argparse
errors. It prints only the created relative result/report filename to stdout and bounded errors to
stderr.

- [ ] **Step 6: Verify controller and report**

Run:

~~~bash
uv run pytest tests/benchmarks/test_runner.py tests/benchmarks/test_report.py -q
uv run python -m benchmarks run --profiles smoke --correctness-only --output benchmark-results/evidence.json
uv run python -m benchmarks report --evidence benchmark-results --output benchmark-results/report.md --provisional
uv run ruff format --check benchmarks tests/benchmarks
uv run ruff check benchmarks tests/benchmarks
uv run pyright
~~~

Expected: tests and quality checks pass; both temporary outputs are created with no supported
capacity claim. Move the exact benchmark-results directory to the system trash after inspecting
it; do not use a recursive delete.

- [ ] **Step 7: Commit orchestration and rendering**

~~~bash
git add benchmarks/runner.py benchmarks/report.py benchmarks/__main__.py tests/benchmarks/test_runner.py tests/benchmarks/test_report.py
git commit -m "feat: orchestrate benchmark evidence runs"
~~~

### Task 8: Add correctness CI and scheduled measurement workflow

**Files:**

- Create: .github/workflows/benchmarks.yml
- Modify: .github/workflows/ci.yml
- Modify: .gitignore
- Modify: tests/test_project_automation.py

**Interfaces:**

- Pull-request command: uv run python -m benchmarks run --profiles smoke --correctness-only
- Measurement command: uv run python -m benchmarks run
- Workflow artifact names: benchmark-evidence-OS-pyVERSION and benchmark-matrix-summary

- [ ] **Step 1: Write failing workflow-policy tests**

Add to tests/test_project_automation.py:

~~~python
def test_benchmark_workflow_is_scheduled_manual_and_nonblocking() -> None:
    workflow = _yaml(".github/workflows/benchmarks.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["schedule"] == [{"cron": "17 3 * * 2"}]
    assert "workflow_dispatch" in workflow["on"]
    assert "pull_request" not in workflow["on"]
    measure = workflow["jobs"]["measure"]
    assert measure["strategy"]["fail-fast"] == "false"
    assert measure["strategy"]["matrix"] == {
        "os": ["ubuntu-24.04", "macos-15"],
        "python-version": ["3.13", "3.14"],
    }
    commands = _run_commands(workflow, "measure")
    assert "uv sync --locked" in commands
    assert "uv run python -m benchmarks run" in commands
    assert "smoke,small,medium,large,probe" in commands
    assert "suite-1-${{ github.sha }}" in commands
    assert "${{ github.run_id }}.json" in commands
    assert workflow["jobs"]["summarize"]["needs"] == ["measure"]
    _assert_actions_are_sha_pinned(workflow)


def test_normal_ci_runs_benchmark_correctness_without_timing_assertions() -> None:
    workflow = _yaml(".github/workflows/ci.yml")
    commands = _run_commands(workflow, "supported")
    assert (
        "uv run python -m benchmarks run --profiles smoke --correctness-only "
        '--output "$RUNNER_TEMP/benchmark-smoke.json"' in commands
    )
    assert "benchmark baseline" not in commands.casefold()
~~~

- [ ] **Step 2: Run workflow tests and verify the missing file failure**

Run:

~~~bash
uv run pytest tests/test_project_automation.py -q
~~~

Expected: failure because .github/workflows/benchmarks.yml does not exist.

- [ ] **Step 3: Add generated-output ignore rules**

Append exact anchored rules:

~~~gitignore
/benchmark-results/
/benchmark-work/
/dist/
/.benchmark-*.json
/.benchmark-*.md
*.partial
~~~

Do not ignore benchmarks/evidence because Phase 2 will commit reviewed evidence there.

- [ ] **Step 4: Add the scheduled/manual workflow**

Create .github/workflows/benchmarks.yml with:

~~~yaml
name: Performance evidence

on:
  schedule:
    - cron: "17 3 * * 2"
  workflow_dispatch:

permissions:
  contents: read

env:
  UV_VERSION: "0.11.28"

jobs:
  measure:
    name: Measure (${{ matrix.os }}, Python ${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-15]
        python-version: ["3.13", "3.14"]
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990
        with:
          version: ${{ env.UV_VERSION }}
          python-version: ${{ matrix.python-version }}
          enable-cache: true
          cache-suffix: benchmark-${{ matrix.os }}-py${{ matrix.python-version }}
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Run complete benchmark sequence
        run: >-
          uv run python -m benchmarks run
          --profiles smoke,small,medium,large,probe
          --run-id "github-${{ github.run_id }}"
          --work-root "${{ runner.temp }}/benchmark-work"
          --output "benchmark-results/suite-1-${{ github.sha }}-${{ runner.os }}-py${{ matrix.python-version }}-${{ github.run_id }}.json"
      - name: Upload complete evidence
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: benchmark-evidence-${{ runner.os }}-py${{ matrix.python-version }}
          path: benchmark-results/*.json
          if-no-files-found: error
          retention-days: 30

  summarize:
    name: Summarize matrix
    if: always()
    needs: [measure]
    runs-on: ubuntu-24.04
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Download matrix evidence
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
        with:
          pattern: benchmark-evidence-*
          path: benchmark-results
          merge-multiple: true
      - name: Render provisional summary
        run: >-
          uv run python -m benchmarks report
          --evidence benchmark-results
          --output benchmark-results/summary.md
          --provisional
          --require-matrix
      - name: Upload matrix summary
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a
        with:
          name: benchmark-matrix-summary
          path: benchmark-results/summary.md
          if-no-files-found: error
          retention-days: 30
~~~

Keep the timing workflow separate from the required aggregator in ci.yml.

- [ ] **Step 5: Add one-sample Smoke correctness to supported CI**

After the offline pytest step in the supported job, add:

~~~yaml
      - name: Run benchmark correctness smoke
        run: >-
          uv run python -m benchmarks run --profiles smoke --correctness-only
          --output "$RUNNER_TEMP/benchmark-smoke.json"
          --work-root "$RUNNER_TEMP/benchmark-work"
~~~

Do not add it to experimental Windows because B3 has no Windows capacity contract.

- [ ] **Step 6: Verify workflow structure and local smoke**

Run:

~~~bash
uv run pytest tests/test_project_automation.py -q
uv run python -m benchmarks run --profiles smoke --correctness-only --output .benchmark-ci-smoke.json
uv run ruff format --check .
uv run ruff check .
uv run pyright
~~~

Expected: all commands pass; the workflow is SHA-pinned and has no pull_request trigger. Move the
exact local smoke output to the system trash.

- [ ] **Step 7: Commit CI integration**

~~~bash
git add .github/workflows/benchmarks.yml .github/workflows/ci.yml .gitignore tests/test_project_automation.py
git commit -m "ci: add performance evidence workflow"
~~~

### Task 9: Publish provisional capacity documentation

**Files:**

- Create: docs/performance-and-capacity.md
- Modify: README.md
- Modify: SUPPORT.md
- Modify: docs/user-guide.md
- Modify: CHANGELOG.md
- Modify: tests/test_release_metadata.py

**Interfaces:**

- Public link target: docs/performance-and-capacity.md
- Required status sentence: Supported capacity is not yet published.

- [ ] **Step 1: Write failing documentation-contract test**

Add:

~~~python
def test_performance_document_is_provisional_and_linked() -> None:
    performance = (PROJECT_ROOT / "docs/performance-and-capacity.md").read_text(
        encoding="utf-8"
    )
    assert "Supported capacity is not yet published." in performance
    assert "candidate only" in performance
    assert "100,000 Unicode characters" in performance
    assert "remote model-provider latency is excluded" in performance
    assert "Windows remains experimental" in performance
    assert "BundleWalker supports up to" not in performance

    for relative in ("README.md", "SUPPORT.md", "docs/user-guide.md"):
        content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "performance-and-capacity.md" in content
~~~

- [ ] **Step 2: Run the documentation test and verify failure**

Run:

~~~bash
uv run pytest tests/test_release_metadata.py::test_performance_document_is_provisional_and_linked -q
~~~

Expected: failure because docs/performance-and-capacity.md does not exist.

- [ ] **Step 3: Write the provisional performance document**

Create these sections with concrete Phase 1 wording:

1. Status — measurement foundation available; Supported capacity is not yet published.
2. What will be measured — all named scenarios and deterministic local boundary.
3. Profiles — exact corrected profile table from the approved spec.
4. Interpretation — results are candidate only; no universal hardware SLA.
5. Exclusions — remote model-provider latency is excluded; Windows remains experimental.
6. Privacy — synthetic content and allowlisted metadata only.
7. Reproduction — correctness-only and full commands.
8. Evidence process — merged workflow first, reviewed evidence PR second.

State that benchmarks is a maintainer/developer harness available from a repository checkout and is
intentionally absent from installed wheels and source distributions.

The full command is:

~~~text
uv run python -m benchmarks run \
  --profiles smoke,small,medium,large,probe \
  --output benchmark-results/local.json
~~~

State that Large and Probe both use 100,000 Unicode characters because that is the existing public
workspace limit; Phase 1 does not raise it.

- [ ] **Step 4: Add restrained public links**

In README Current scope, link to the performance document after the producer-limits paragraph and
retain the proof-of-concept wording.

In SUPPORT Supported scope, state that no supported workspace capacity is published until reviewed
cross-platform evidence exists.

In docs/user-guide.md near operational limitations, link users to the performance document and
explain that provider latency is not controlled by BundleWalker.

In CHANGELOG Unreleased Added, record the reproducible synthetic benchmark foundation,
scheduled/manual supported-platform evidence workflow, and provisional capacity documentation.
Do not mention a supported size, beta completion, version, publication, or release.

- [ ] **Step 5: Verify documentation contracts**

Run:

~~~bash
uv run pytest tests/test_release_metadata.py::test_performance_document_is_provisional_and_linked -q
git diff --check
~~~

Expected: both commands pass.

- [ ] **Step 6: Commit provisional documentation**

~~~bash
git add docs/performance-and-capacity.md README.md SUPPORT.md docs/user-guide.md CHANGELOG.md tests/test_release_metadata.py
git commit -m "docs: publish provisional capacity methodology"
~~~

### Task 10: Run the Phase 1 release-quality gate

**Files:**

- Verify all files changed by Tasks 1–9
- Do not modify files unless a verification failure exposes a scoped defect

**Interfaces:**

- Consumes the complete benchmark foundation
- Produces fresh local verification evidence and a clean branch ready for review

- [ ] **Step 1: Run the complete offline suite**

Run:

~~~bash
uv run pytest -m 'not eval' -q
~~~

Expected: all tests pass.

- [ ] **Step 2: Run formatting, lint, types, and lock checks**

Run:

~~~bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv lock --check
~~~

Expected: all four commands pass and uv.lock remains unchanged.

- [ ] **Step 3: Build and inspect distributions**

Run:

~~~bash
uv build --clear --no-sources
uv run twine check dist/*
uv run pytest tests/test_release_metadata.py::test_benchmark_harness_is_not_packaged -q
~~~

Expected: wheel and source distribution build, metadata passes, and neither artifact ships the
benchmarks package.

- [ ] **Step 4: Run one final correctness-only Smoke pass**

Run:

~~~bash
uv run python -m benchmarks run --profiles smoke --correctness-only --output .benchmark-final-smoke.json
~~~

Expected: exit 0, one validated sample per scenario, no model network request, no unresolved
transaction, and no supported-capacity claim. Inspect the JSON and move that exact file to the
system trash.

- [ ] **Step 5: Check repository scope**

Run:

~~~bash
git status --short
git log --oneline --decorate -12
git diff origin/master...HEAD --stat
~~~

Expected: only the intentional B3 design, plan, and Phase 1 commits are present; generated
fixtures/results and build artifacts are ignored or outside the commit. If a verification command
fails, return to the task that owns the failing file, add a focused failing test there, correct the
implementation, rerun that task's exact checks, and use that task's explicit git-add list. Create no
empty verification commit.

## Phase 1 completion gate

Phase 1 is ready for a pull request only when:

- the complete offline suite and all static gates pass;
- Smoke correctness passes on supported local development;
- benchmark code is absent from wheel and source distribution;
- the scheduled/manual workflow is SHA-pinned and not required for pull requests;
- provisional documentation contains no capacity claim;
- no remote model call, telemetry, user path, username, hostname, or credential can enter evidence;
- no version, tag, release, or package publication changed; and
- the branch contains no generated fixtures or unreviewed timing evidence.

After Phase 1 merges to master, dispatch the measurement workflow. Do not start Phase 2 until all
four supported matrix artifacts are available and validated against the exact merged commit.
