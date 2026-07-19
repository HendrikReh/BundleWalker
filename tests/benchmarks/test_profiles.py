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
