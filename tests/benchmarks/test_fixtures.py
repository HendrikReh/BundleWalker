# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from benchmarks.fixtures import generate_fixture
from benchmarks.profiles import PROFILES
from bundlewalker.okf.lint import lint_bundle


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
