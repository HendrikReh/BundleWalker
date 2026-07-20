# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

import pytest

from benchmarks.fixtures import generate_fixture
from benchmarks.profiles import PROFILES
from benchmarks.worker import SUITE_V1_TREE_SHA256
from bundlewalker.okf.lint import lint_bundle


@pytest.mark.parametrize("profile_name", tuple(PROFILES))
def test_read_workload_targets_the_unique_final_canonical_concept(
    tmp_path: Path, profile_name: str
) -> None:
    fixture = generate_fixture(tmp_path / profile_name, PROFILES[profile_name])
    matching_documents = tuple(
        path.relative_to(fixture.workspace.wiki_dir).with_suffix("").as_posix()
        for path in fixture.workspace.wiki_dir.rglob("*.md")
        if fixture.present_query in path.read_text(encoding="utf-8")
    )

    assert fixture.read_concept_id == fixture.concept_ids[-1]
    assert matching_documents == (fixture.read_concept_id,)
    assert len(fixture.ingestion_content) == fixture.profile.source_characters <= 100_000
    assert fixture.tree_sha256 == SUITE_V1_TREE_SHA256[profile_name]


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
