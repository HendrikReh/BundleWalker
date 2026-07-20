# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from benchmarks.contracts import SampleObservation, ScenarioName
from benchmarks.fixtures import GeneratedFixture


class ScenarioCallable(Protocol):
    def __call__(self, fixture: GeneratedFixture) -> SampleObservation: ...


from benchmarks.scenarios.mcp_startup import run_mcp_startup  # noqa: E402
from benchmarks.scenarios.mutation import MUTATION_SCENARIOS  # noqa: E402
from benchmarks.scenarios.read_only import READ_ONLY_SCENARIOS  # noqa: E402

SCENARIOS: Mapping[ScenarioName, ScenarioCallable] = MappingProxyType(
    {
        **READ_ONLY_SCENARIOS,
        **MUTATION_SCENARIOS,
        ScenarioName.MCP_STARTUP: run_mcp_startup,
    }
)
