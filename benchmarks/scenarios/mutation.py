# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from benchmarks.contracts import SampleObservation, ScenarioName
from benchmarks.fixtures import GeneratedFixture, tree_sha256
from benchmarks.scenarios import ScenarioCallable
from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.ingest import AgentModel
from bundlewalker.application.contracts import InlineSource
from bundlewalker.application.facade import ApplicationDependencies, WorkspaceApplication
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
)
from bundlewalker.okf.lint import lint_bundle
from bundlewalker.transactions import ReviewStatus, get_pending_review, recover_transactions
from bundlewalker.workspace import RawSource, load_inline_source

_FIXED_NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)
_BENCHMARK_MODEL = "benchmark:deterministic"
_SOURCE_NAME = "benchmark-source.txt"
_CRASH_EXIT = 86
_CRASH_TIMEOUT_SECONDS = 180
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def deterministic_ingestion_runner(
    model: AgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    if model != _BENCHMARK_MODEL:
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


def prepare_ingestion_application(fixture: GeneratedFixture) -> WorkspaceApplication:
    return WorkspaceApplication(
        fixture.workspace,
        ApplicationDependencies(
            environment={},
            ingestion_runner=deterministic_ingestion_runner,
            clock=lambda: _FIXED_NOW,
        ),
    )


async def _measure_awaitable[T](operation: Awaitable[T]) -> tuple[T, int]:
    started = time.perf_counter_ns()
    result = await operation
    return result, time.perf_counter_ns() - started


def _inline_source(fixture: GeneratedFixture) -> InlineSource:
    return InlineSource(source_name=_SOURCE_NAME, content=fixture.ingestion_content)


def _transaction_root(fixture: GeneratedFixture) -> Path:
    return fixture.workspace.root / ".bundlewalker" / "transactions"


def _transaction_dir(fixture: GeneratedFixture, review_id: str) -> Path:
    return _transaction_root(fixture) / review_id


def _prospective_wiki(fixture: GeneratedFixture, review_id: str) -> Path:
    return _transaction_dir(fixture, review_id) / "prospective-wiki"


def _tree_size(root: Path) -> int:
    if not root.is_dir() or root.is_symlink():
        return 0
    return sum(
        path.stat().st_size for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )


def _transactions_are_clean(fixture: GeneratedFixture) -> bool:
    root = _transaction_root(fixture)
    if not root.exists():
        return not root.is_symlink()
    return root.is_dir() and not root.is_symlink() and not any(root.iterdir())


def _output_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _commit_recovery_output(
    *,
    expected_live_wiki_sha256: str,
    raw_source_sha256: str,
    pending_status: str,
    clean_transactions: bool,
) -> str:
    return _output_sha256(
        {
            "clean_transactions": clean_transactions,
            "expected_live_wiki_sha256": expected_live_wiki_sha256,
            "pending_status": pending_status,
            "raw_source_sha256": raw_source_sha256,
        }
    )


def _assert_valid_wiki(fixture: GeneratedFixture) -> None:
    assert lint_bundle(fixture.workspace.wiki_dir, fixture.workspace.root) == []


def _assert_persisted_raw(source: RawSource, fixture: GeneratedFixture) -> None:
    stored = fixture.workspace.root / source.stored_relative_path
    assert stored.is_file() and not stored.is_symlink()
    content = stored.read_bytes()
    assert content == source.content
    assert hashlib.sha256(content).hexdigest() == source.sha256


def _prepare_review(
    fixture: GeneratedFixture,
) -> tuple[WorkspaceApplication, RawSource, str, str, int]:
    source_contract = _inline_source(fixture)
    expected_source = load_inline_source(
        source_contract.source_name,
        source_contract.content,
        fixture.workspace,
    )
    application = prepare_ingestion_application(fixture)
    result = asyncio.run(
        application.prepare_ingestion(source_contract, explicit_model=_BENCHMARK_MODEL)
    )
    assert result.status == "pending"
    assert result.review is not None
    pending = get_pending_review(fixture.workspace)
    assert pending is not None
    assert pending.review_id == result.review.review_id
    assert pending.status is ReviewStatus.PENDING
    prospective = _prospective_wiki(fixture, pending.review_id)
    assert prospective.is_dir() and not prospective.is_symlink()
    prospective_sha256 = tree_sha256(prospective)
    prepared_bytes = _tree_size(fixture.workspace.root)
    assert prepared_bytes > fixture.exact_workspace_bytes
    return application, expected_source, pending.review_id, prospective_sha256, prepared_bytes


def _run_prepare_ingestion(fixture: GeneratedFixture) -> SampleObservation:
    source = _inline_source(fixture)
    application = prepare_ingestion_application(fixture)
    live_wiki_before = tree_sha256(fixture.workspace.wiki_dir)
    live_raw_before = tree_sha256(fixture.workspace.raw_dir)

    result, duration = asyncio.run(
        _measure_awaitable(application.prepare_ingestion(source, explicit_model=_BENCHMARK_MODEL))
    )

    assert result.status == "pending"
    assert result.review is not None
    pending = get_pending_review(fixture.workspace)
    assert pending is not None
    assert pending.review_id == result.review.review_id
    assert pending.status is ReviewStatus.PENDING
    assert tuple(sorted(pending.changed_paths)) == tuple(sorted(result.review.changed_paths))
    assert tree_sha256(fixture.workspace.wiki_dir) == live_wiki_before
    assert tree_sha256(fixture.workspace.raw_dir) == live_raw_before
    prospective = _prospective_wiki(fixture, pending.review_id)
    assert prospective.is_dir() and not prospective.is_symlink()
    prospective_sha256 = tree_sha256(prospective)
    prepared_bytes = _tree_size(fixture.workspace.root)
    assert prepared_bytes > fixture.exact_workspace_bytes
    _assert_valid_wiki(fixture)

    output_sha256 = _output_sha256(
        {
            "changed_paths": sorted(result.review.changed_paths),
            "live_tree_sha256": live_wiki_before,
            "prospective_tree_sha256": prospective_sha256,
            "status": result.status,
        }
    )
    return SampleObservation(
        scenario=ScenarioName.PREPARE_INGESTION,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=output_sha256,
        checkpoint_bytes={"prepared": prepared_bytes},
    )


def _run_commit(fixture: GeneratedFixture) -> SampleObservation:
    application, source, review_id, prospective_sha256, prepared_bytes = _prepare_review(fixture)

    result, duration = asyncio.run(_measure_awaitable(application.apply_review(review_id)))

    assert result.status == "applied"
    assert result.review_id == review_id
    assert tree_sha256(fixture.workspace.wiki_dir) == prospective_sha256
    _assert_persisted_raw(source, fixture)
    _assert_valid_wiki(fixture)
    assert get_pending_review(fixture.workspace) is None
    assert _transactions_are_clean(fixture)
    committed_bytes = _tree_size(fixture.workspace.root)
    cleaned_bytes = _tree_size(_transaction_root(fixture))
    assert cleaned_bytes == 0

    output_sha256 = _commit_recovery_output(
        expected_live_wiki_sha256=prospective_sha256,
        raw_source_sha256=source.sha256,
        pending_status="absent",
        clean_transactions=True,
    )
    return SampleObservation(
        scenario=ScenarioName.COMMIT,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=output_sha256,
        checkpoint_bytes={
            "prepared": prepared_bytes,
            "committed": committed_bytes,
            "cleaned": cleaned_bytes,
        },
    )


def _run_recover_prepared(fixture: GeneratedFixture) -> SampleObservation:
    live_wiki_before = tree_sha256(fixture.workspace.wiki_dir)
    live_raw_before = tree_sha256(fixture.workspace.raw_dir)
    _, source, review_id, _, prepared_bytes = _prepare_review(fixture)
    prepared_identity = tree_sha256(_transaction_root(fixture))

    started = time.perf_counter_ns()
    recover_transactions(fixture.workspace)
    duration = time.perf_counter_ns() - started

    pending = get_pending_review(fixture.workspace)
    assert pending is not None
    assert pending.review_id == review_id
    assert pending.status is ReviewStatus.PENDING
    assert tree_sha256(fixture.workspace.wiki_dir) == live_wiki_before
    assert tree_sha256(fixture.workspace.raw_dir) == live_raw_before
    assert tree_sha256(_transaction_root(fixture)) == prepared_identity
    _assert_valid_wiki(fixture)

    output_sha256 = _commit_recovery_output(
        expected_live_wiki_sha256=live_wiki_before,
        raw_source_sha256=source.sha256,
        pending_status="pending",
        clean_transactions=False,
    )
    return SampleObservation(
        scenario=ScenarioName.RECOVER_PREPARED,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=output_sha256,
        checkpoint_bytes={"prepared": prepared_bytes},
    )


def _crash_at_swapping(fixture: GeneratedFixture, review_id: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.crash_worker",
            str(fixture.workspace.root),
            "swapping",
            review_id,
        ],
        check=False,
        cwd=_PROJECT_ROOT,
        env={},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_CRASH_TIMEOUT_SECONDS,
    )
    assert result.returncode == _CRASH_EXIT


def _run_recover_swapping(fixture: GeneratedFixture) -> SampleObservation:
    _, source, review_id, prospective_sha256, prepared_bytes = _prepare_review(fixture)
    _crash_at_swapping(fixture, review_id)
    interrupted_bytes = _tree_size(fixture.workspace.root)
    assert interrupted_bytes > 0

    started = time.perf_counter_ns()
    recover_transactions(fixture.workspace)
    duration = time.perf_counter_ns() - started

    assert tree_sha256(fixture.workspace.wiki_dir) == prospective_sha256
    _assert_persisted_raw(source, fixture)
    _assert_valid_wiki(fixture)
    assert _transactions_are_clean(fixture)
    committed_bytes = _tree_size(fixture.workspace.root)
    cleaned_bytes = _tree_size(_transaction_root(fixture))
    assert cleaned_bytes == 0

    recovered_identity = tree_sha256(fixture.workspace.root)
    recover_transactions(fixture.workspace)
    assert tree_sha256(fixture.workspace.root) == recovered_identity
    assert get_pending_review(fixture.workspace) is None
    assert _transactions_are_clean(fixture)

    output_sha256 = _commit_recovery_output(
        expected_live_wiki_sha256=prospective_sha256,
        raw_source_sha256=source.sha256,
        pending_status="absent",
        clean_transactions=True,
    )
    return SampleObservation(
        scenario=ScenarioName.RECOVER_SWAPPING,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=output_sha256,
        checkpoint_bytes={
            "prepared": prepared_bytes,
            "interrupted": interrupted_bytes,
            "committed": committed_bytes,
            "cleaned": cleaned_bytes,
        },
    )


MUTATION_SCENARIOS: Mapping[ScenarioName, ScenarioCallable] = MappingProxyType(
    {
        ScenarioName.PREPARE_INGESTION: _run_prepare_ingestion,
        ScenarioName.COMMIT: _run_commit,
        ScenarioName.RECOVER_PREPARED: _run_recover_prepared,
        ScenarioName.RECOVER_SWAPPING: _run_recover_swapping,
    }
)


def run_mutation(scenario: ScenarioName, fixture: GeneratedFixture) -> SampleObservation:
    return MUTATION_SCENARIOS[scenario](fixture)
