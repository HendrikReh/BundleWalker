# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from benchmarks import FIXTURE_SEED
from benchmarks.contracts import ScenarioName, WorkspaceProfile

_MIB = 1024 * 1024

PROFILES: Final[Mapping[str, WorkspaceProfile]] = MappingProxyType(
    {
        "smoke": WorkspaceProfile(
            name="smoke",
            document_count=50,
            target_wiki_bytes=_MIB // 2,
            source_characters=10_000,
            seed=FIXTURE_SEED,
        ),
        "small": WorkspaceProfile(
            name="small",
            document_count=250,
            target_wiki_bytes=5 * _MIB // 2,
            source_characters=25_000,
            seed=FIXTURE_SEED,
        ),
        "medium": WorkspaceProfile(
            name="medium",
            document_count=1_000,
            target_wiki_bytes=10 * _MIB,
            source_characters=50_000,
            seed=FIXTURE_SEED,
        ),
        "large": WorkspaceProfile(
            name="large",
            document_count=5_000,
            target_wiki_bytes=50 * _MIB,
            source_characters=100_000,
            seed=FIXTURE_SEED,
        ),
        "probe": WorkspaceProfile(
            name="probe",
            document_count=10_000,
            target_wiki_bytes=100 * _MIB,
            source_characters=100_000,
            seed=FIXTURE_SEED,
        ),
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
