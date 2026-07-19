# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Protocol

from benchmarks.contracts import SampleObservation
from benchmarks.fixtures import GeneratedFixture


class ScenarioCallable(Protocol):
    def __call__(self, fixture: GeneratedFixture) -> SampleObservation: ...
