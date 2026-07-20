# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final

from benchmarks.contracts import ScenarioName, WorkspaceProfile
from benchmarks.evidence import write_new_json
from benchmarks.fixtures import GeneratedFixture, tree_sha256
from benchmarks.profiles import PROFILES
from benchmarks.scenarios import SCENARIOS
from benchmarks.scenarios.read_only import run_initialization
from bundlewalker.okf.lint import lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.workspace import WorkspaceConfig, discover_workspace

_TYPE_CATEGORIES = (
    "sources",
    "topics",
    "topics",
    "topics",
    "topics",
    "entities",
    "entities",
    "entities",
    "syntheses",
    "syntheses",
)
_PRESENT_QUERY = "benchmark-needle"
_ABSENT_QUERY = "benchmark-absent-needle"
_TYPE_RATIOS = (1, 4, 3, 2)

# Frozen suite-v1 identities, derived once from the deterministic official profile generator.
# Any generator change that alters these complete-tree digests requires a new suite version.
SUITE_V1_TREE_SHA256: Final[Mapping[str, str]] = MappingProxyType(
    {
        "smoke": "2056081991941f2b9aab5a32ff1fa22058d959cb86f122caab1aea29e8ed5676",
        "small": "9727173321acf3c9193865d0f31df12a1a0221b4e05d25d6cfda2092409057df",
        "medium": "3f5a4083bcbab9a69169eaca55c122e2cfde01852a988d315822074b12d65cf5",
        "large": "9f99b5a5c5c7bdac10981e8889bb9ef69c25b63fc1cd424ea1030535bd869072",
        "probe": "fa6f7de49a3d3ebd2e032e5a421f4946465ec606d5d19c14523cc3257029d644",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark-worker")
    parser.add_argument("--scenario", required=True, type=ScenarioName, choices=tuple(ScenarioName))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--profile", choices=tuple(PROFILES))
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _require_unaliased_existing_directory(path: Path) -> Path:
    absolute = _absolute_path(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("benchmark path must be an existing directory")
    resolved = path.expanduser().resolve(strict=True)
    if resolved != absolute:
        raise ValueError("benchmark path must not cross a symlink boundary")
    return resolved


def _validate_initialization_destination(path: Path) -> Path:
    absolute = _absolute_path(path)
    if os.path.lexists(path):
        return absolute
    parent = _require_unaliased_existing_directory(path.parent)
    if parent != absolute.parent:
        raise ValueError("initialization destination must be a direct child")
    return absolute


def _validate_output_path(path: Path, workspace: Path) -> Path:
    absolute = _absolute_path(path)
    if os.path.lexists(path):
        raise FileExistsError(path)
    parent = _require_unaliased_existing_directory(path.parent)
    if parent != absolute.parent:
        raise ValueError("benchmark output must be a direct child of its parent")
    if absolute.is_relative_to(workspace):
        raise ValueError("benchmark output must be outside the measured workspace")
    return absolute


def _require_safe_fixture_tree(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("generated fixture must not contain symlinks")
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise ValueError("generated fixture contains an unsupported filesystem entry")


def _expected_concept_ids(profile: WorkspaceProfile) -> tuple[str, ...]:
    return tuple(
        f"{_TYPE_CATEGORIES[index % len(_TYPE_CATEGORIES)]}/concept-{index:06d}"
        for index in range(profile.document_count)
    )


def _ingestion_content(character_count: int) -> str:
    unit = "benchmark source line\n"
    repetitions = (character_count // len(unit)) + 1
    return (unit * repetitions)[:character_count]


def _regular_file_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _reconstruct_fixture(workspace_path: Path, profile: WorkspaceProfile) -> GeneratedFixture:
    root = _require_unaliased_existing_directory(workspace_path)
    _require_safe_fixture_tree(root)
    workspace = discover_workspace(root)
    if workspace.root != root:
        raise ValueError("benchmark workspace must name the generated fixture root")
    if workspace.config != WorkspaceConfig():
        raise ValueError("generated fixture must use the standard workspace profile")

    expected_ids = _expected_concept_ids(profile)
    discovered_ids = tuple(OkfRepository(workspace.wiki_dir).scan())
    if discovered_ids != tuple(sorted(expected_ids)):
        raise ValueError("generated fixture concept identity does not match its profile")
    exact_wiki_bytes = _regular_file_size(workspace.wiki_dir)
    if exact_wiki_bytes != profile.target_wiki_bytes:
        raise ValueError("generated fixture byte size does not match its profile")
    if lint_bundle(workspace.wiki_dir, workspace.root):
        raise ValueError("generated fixture must pass deterministic lint")
    actual_tree_sha256 = tree_sha256(workspace.root)
    if actual_tree_sha256 != SUITE_V1_TREE_SHA256[profile.name]:
        raise ValueError("generated fixture tree identity does not match suite v1")

    return GeneratedFixture(
        workspace=workspace,
        profile=profile,
        exact_wiki_bytes=exact_wiki_bytes,
        exact_workspace_bytes=_regular_file_size(workspace.root),
        tree_sha256=actual_tree_sha256,
        concept_ids=expected_ids,
        present_query=_PRESENT_QUERY,
        absent_query=_ABSENT_QUERY,
        read_concept_id=expected_ids[-1],
        ingestion_content=_ingestion_content(profile.source_characters),
        type_ratios=_TYPE_RATIOS,
    )


def run_worker(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    arguments = parser.parse_args(argv)
    scenario = arguments.scenario
    assert isinstance(scenario, ScenarioName)
    workspace_path = arguments.workspace
    output_path = arguments.output
    assert isinstance(workspace_path, Path)
    assert isinstance(output_path, Path)

    if scenario is ScenarioName.INITIALIZE:
        if arguments.profile is not None:
            parser.error("--profile is forbidden for initialize")
    elif arguments.profile is None:
        parser.error("--profile is required for this scenario")

    try:
        if scenario is ScenarioName.INITIALIZE:
            destination = _validate_initialization_destination(workspace_path)
            output = _validate_output_path(output_path, destination)
            observation = run_initialization(destination)
        else:
            profile_name = arguments.profile
            assert isinstance(profile_name, str)
            fixture = _reconstruct_fixture(workspace_path, PROFILES[profile_name])
            output = _validate_output_path(output_path, fixture.workspace.root)
            observation = SCENARIOS[scenario](fixture)
        write_new_json(output, observation)
    except Exception as error:
        print(f"Benchmark worker failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run_worker())
