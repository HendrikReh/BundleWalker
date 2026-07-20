# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import UTC, datetime

from benchmarks.contracts import (
    EnvironmentRecord,
    EvidenceRecord,
    FixtureIdentity,
    ScenarioDisposition,
    ScenarioEvidence,
    ScenarioName,
    profile_sha256,
)
from benchmarks.profiles import PROFILES


def evidence_record(*, os_name: str = "Linux", python_version: str = "3.13.0") -> EvidenceRecord:
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
                profile_sha256=profile_sha256(profile),
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
