# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import benchmarks.worker as worker
from benchmarks.contracts import SampleObservation, ScenarioName
from benchmarks.fixtures import generate_fixture, tree_sha256
from benchmarks.profiles import PROFILES
from benchmarks.scenarios import SCENARIOS
from benchmarks.scenarios.mcp_startup import EXPECTED_TOOL_NAMES, run_mcp_startup
from bundlewalker.okf.lint import lint_bundle

PROJECT_ROOT = Path(__file__).parents[2]
WORKER_TIMEOUT_SECONDS = 30


def _run_worker(
    *,
    scenario: str,
    workspace: Path,
    output: Path,
    profile: str | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable,
        "-m",
        "benchmarks.worker",
        "--scenario",
        scenario,
        "--workspace",
        str(workspace),
    ]
    if profile is not None:
        arguments.extend(["--profile", profile])
    arguments.extend(["--output", str(output)])
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=WORKER_TIMEOUT_SECONDS,
        cwd=PROJECT_ROOT,
    )


def _assert_bounded_failure(
    result: subprocess.CompletedProcess[str],
    output: Path,
    class_name: str,
) -> None:
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"Benchmark worker failed: {class_name}\n"
    assert not output.exists()
    assert not output.is_symlink()


def _mcp_processes_for(workspace: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["ps", "-axo", "command="],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    marker = str(workspace)
    return tuple(
        line
        for line in result.stdout.splitlines()
        if "bundlewalker.interfaces.mcp" in line and marker in line
    )


def test_mcp_startup_discovers_stable_tools_and_cleans_process(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "mcp", PROFILES["smoke"])

    observation = run_mcp_startup(fixture)

    assert observation.scenario is ScenarioName.MCP_STARTUP
    assert observation.profile == "smoke"
    assert observation.duration_ns > 0
    assert (
        observation.output_sha256
        == hashlib.sha256(
            json.dumps(EXPECTED_TOOL_NAMES, separators=(",", ":")).encode("ascii")
        ).hexdigest()
    )
    assert _mcp_processes_for(fixture.workspace.root) == ()


def test_mcp_startup_is_available_to_isolated_workers() -> None:
    assert SCENARIOS[ScenarioName.MCP_STARTUP] is run_mcp_startup


def test_worker_writes_one_valid_observation_atomically(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    output = tmp_path / "observation.json"

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    observation = SampleObservation.model_validate_json(output.read_text(encoding="utf-8"))
    assert observation.scenario is ScenarioName.STATUS
    assert observation.profile == "smoke"
    assert json.loads(output.read_text(encoding="utf-8")) == observation.model_dump(mode="json")


def test_worker_independently_reads_the_final_canonical_concept(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    output = tmp_path / "observation.json"

    result = _run_worker(
        scenario="read_concept",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    observation = SampleObservation.model_validate_json(output.read_text(encoding="utf-8"))
    assert observation.scenario is ScenarioName.READ_CONCEPT


def test_worker_initializes_only_a_nonexistent_profileless_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "new-workspace"
    output = tmp_path / "initialize.json"

    result = _run_worker(
        scenario="initialize",
        workspace=workspace,
        output=output,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    observation = SampleObservation.model_validate_json(output.read_text(encoding="utf-8"))
    assert observation.scenario is ScenarioName.INITIALIZE
    assert observation.profile is None
    assert workspace.is_dir()


@pytest.mark.parametrize(
    ("scenario", "profile"),
    [("initialize", "smoke"), ("status", None)],
)
def test_worker_rejects_scenario_profile_contract_as_argparse_error(
    tmp_path: Path,
    scenario: str,
    profile: str | None,
) -> None:
    workspace = tmp_path / "workspace"
    if scenario != "initialize":
        generate_fixture(workspace, PROFILES["smoke"])
    output = tmp_path / "invalid.json"

    result = _run_worker(
        scenario=scenario,
        workspace=workspace,
        profile=profile,
        output=output,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("usage: benchmark-worker")
    assert not output.exists()


def test_worker_rejects_wrong_fixed_profile_without_leaking_workspace_path(
    tmp_path: Path,
) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    output = tmp_path / "wrong-profile.json"

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="small",
        output=output,
    )

    _assert_bounded_failure(result, output, "ValueError")
    assert str(tmp_path) not in result.stderr


def test_worker_rejects_non_generated_fixture_identity(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    concept = fixture.workspace.wiki_dir / "topics" / "concept-000001.md"
    moved = fixture.workspace.wiki_dir / "topics" / "unexpected-concept.md"
    concept.rename(moved)
    output = tmp_path / "invalid-fixture.json"

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    _assert_bounded_failure(result, output, "ValueError")


def test_worker_rejects_same_size_lint_valid_fixture_mutation(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    concept = fixture.workspace.wiki_dir / "sources" / "concept-000000.md"
    original = concept.read_bytes()
    padding_index = original.rfind(b"x")
    assert padding_index >= 0
    concept.write_bytes(original[:padding_index] + b"y" + original[padding_index + 1 :])
    assert concept.stat().st_size == len(original)
    assert lint_bundle(fixture.workspace.wiki_dir, fixture.workspace.root) == []
    output = tmp_path / "mutated-fixture.json"

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    _assert_bounded_failure(result, output, "ValueError")


def test_worker_rejects_the_previous_concept_42_fixture_identity(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    old_target = fixture.workspace.wiki_dir / "topics" / "concept-000042.md"
    new_target = fixture.workspace.wiki_dir / "syntheses" / "concept-000049.md"
    old_target.write_bytes(
        old_target.read_bytes().replace(b"benchmark content 000042", b"benchmark-needle", 1)
    )
    new_target.write_bytes(
        new_target.read_bytes().replace(b"benchmark-needle", b"benchmark content 000049", 1)
    )
    assert tree_sha256(fixture.workspace.root) == (
        "9b9a039500fde21786f3f467023f68d43d4446059b21a3f68dfbc67b1c1ba52d"
    )
    output = tmp_path / "old-fixture.json"

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    _assert_bounded_failure(result, output, "ValueError")


def test_suite_v1_tree_digest_catalog_is_closed_and_matches_generated_smoke(
    tmp_path: Path,
) -> None:
    assert dict(worker.SUITE_V1_TREE_SHA256) == {
        "smoke": "2056081991941f2b9aab5a32ff1fa22058d959cb86f122caab1aea29e8ed5676",
        "small": "9727173321acf3c9193865d0f31df12a1a0221b4e05d25d6cfda2092409057df",
        "medium": "3f5a4083bcbab9a69169eaca55c122e2cfde01852a988d315822074b12d65cf5",
        "large": "9f99b5a5c5c7bdac10981e8889bb9ef69c25b63fc1cd424ea1030535bd869072",
        "probe": "fa6f7de49a3d3ebd2e032e5a421f4946465ec606d5d19c14523cc3257029d644",
    }
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    assert worker.SUITE_V1_TREE_SHA256["smoke"] == fixture.tree_sha256


@pytest.mark.parametrize("boundary", ["workspace_symlink", "nested_path"])
def test_worker_rejects_workspace_boundary_aliases(tmp_path: Path, boundary: str) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    if boundary == "workspace_symlink":
        workspace = tmp_path / "fixture-link"
        workspace.symlink_to(fixture.workspace.root, target_is_directory=True)
    else:
        workspace = fixture.workspace.wiki_dir
    output = tmp_path / "boundary.json"

    result = _run_worker(
        scenario="status",
        workspace=workspace,
        profile="smoke",
        output=output,
    )

    _assert_bounded_failure(result, output, "ValueError")


def test_worker_rejects_symlink_inside_generated_fixture(tmp_path: Path) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    (fixture.workspace.root / "fixture-link").symlink_to(fixture.workspace.raw_dir)
    output = tmp_path / "symlink-fixture.json"

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    _assert_bounded_failure(result, output, "ValueError")


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_worker_never_replaces_an_existing_output(tmp_path: Path, existing_kind: str) -> None:
    fixture = generate_fixture(tmp_path / "fixture", PROFILES["smoke"])
    output = tmp_path / "observation.json"
    protected = tmp_path / "protected.json"
    if existing_kind == "file":
        output.write_text("keep", encoding="ascii")
    else:
        protected.write_text("keep", encoding="ascii")
        output.symlink_to(protected)

    result = _run_worker(
        scenario="status",
        workspace=fixture.workspace.root,
        profile="smoke",
        output=output,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Benchmark worker failed: FileExistsError\n"
    if existing_kind == "file":
        assert output.read_text(encoding="ascii") == "keep"
    else:
        assert output.is_symlink()
        assert protected.read_text(encoding="ascii") == "keep"
