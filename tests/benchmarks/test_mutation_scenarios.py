# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
from pathlib import Path

import pytest

import benchmarks.scenarios.mutation as mutation
from benchmarks.contracts import ScenarioName
from benchmarks.evidence import materialized_bytes
from benchmarks.fixtures import generate_fixture
from benchmarks.profiles import PROFILES
from benchmarks.scenarios.mutation import prepare_ingestion_application, run_mutation
from bundlewalker.application.contracts import InlineSource
from bundlewalker.okf.lint import lint_bundle
from bundlewalker.transactions import TransactionReview
from bundlewalker.workspace import Workspace


@pytest.mark.parametrize(
    "scenario",
    [
        ScenarioName.PREPARE_INGESTION,
        ScenarioName.COMMIT,
        ScenarioName.RECOVER_PREPARED,
        ScenarioName.RECOVER_SWAPPING,
    ],
)
def test_mutation_scenarios_reach_one_safe_end_state(
    tmp_path: Path, scenario: ScenarioName
) -> None:
    fixture = generate_fixture(tmp_path / scenario.value, PROFILES["smoke"])
    observation = run_mutation(scenario, fixture)

    assert observation.scenario is scenario
    assert observation.profile == "smoke"
    assert observation.duration_ns >= 0
    assert set(observation.checkpoint_bytes).issubset(
        {"prepared", "interrupted", "committed", "cleaned"}
    )
    assert lint_bundle(fixture.workspace.wiki_dir, fixture.workspace.root) == []


def test_ingestion_uses_full_profile_source_without_network(tmp_path: Path) -> None:
    source_limit_profile = PROFILES["smoke"].model_copy(update={"source_characters": 100_000})
    fixture = generate_fixture(tmp_path / "source-limit", source_limit_profile)
    application = prepare_ingestion_application(fixture)
    result = asyncio.run(
        application.prepare_ingestion(
            InlineSource(
                source_name="benchmark-source.txt",
                content=fixture.ingestion_content,
            ),
            explicit_model="benchmark:deterministic",
        )
    )
    assert len(fixture.ingestion_content) == 100_000
    assert result.status == "pending"


@pytest.mark.parametrize(
    "scenario",
    [ScenarioName.PREPARE_INGESTION, ScenarioName.RECOVER_PREPARED],
)
def test_pending_scenarios_measure_the_prepared_transaction_tree(
    tmp_path: Path, scenario: ScenarioName
) -> None:
    fixture = generate_fixture(tmp_path / f"prepared-{scenario.value}", PROFILES["smoke"])

    observation = run_mutation(scenario, fixture)

    transactions = fixture.workspace.root / ".bundlewalker" / "transactions"
    assert observation.checkpoint_bytes == {"prepared": materialized_bytes(transactions)}


@pytest.mark.parametrize(
    "scenario",
    [ScenarioName.COMMIT, ScenarioName.RECOVER_SWAPPING],
)
def test_completed_scenarios_measure_committed_workspace_and_clean_transaction_tree(
    tmp_path: Path, scenario: ScenarioName
) -> None:
    fixture = generate_fixture(tmp_path / f"completed-{scenario.value}", PROFILES["smoke"])

    observation = run_mutation(scenario, fixture)

    transactions = fixture.workspace.root / ".bundlewalker" / "transactions"
    assert observation.checkpoint_bytes["committed"] == materialized_bytes(fixture.workspace.root)
    assert observation.checkpoint_bytes["cleaned"] == materialized_bytes(transactions)
    assert not any(transactions.iterdir())
    assert observation.checkpoint_bytes["prepared"] > 0
    if scenario is ScenarioName.RECOVER_SWAPPING:
        assert observation.checkpoint_bytes["interrupted"] > 0


def test_cleaned_checkpoint_accepts_allocated_empty_transaction_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = generate_fixture(tmp_path / "allocated-empty", PROFILES["smoke"])
    transactions = fixture.workspace.root / ".bundlewalker" / "transactions"
    allocated_empty_bytes = 4096

    def materialized_with_allocated_empty_root(root: Path) -> int:
        measured = materialized_bytes(root)
        if root == transactions and root.is_dir() and not any(root.iterdir()):
            return allocated_empty_bytes
        return measured

    monkeypatch.setattr(mutation, "materialized_bytes", materialized_with_allocated_empty_root)

    observation = mutation.run_mutation(ScenarioName.COMMIT, fixture)

    assert observation.checkpoint_bytes["cleaned"] == allocated_empty_bytes
    assert not any(transactions.iterdir())


def test_nonempty_transaction_directory_fails_structural_cleanup_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = generate_fixture(tmp_path / "nonempty-cleanup", PROFILES["smoke"])
    transactions = fixture.workspace.root / ".bundlewalker" / "transactions"
    original_get_pending_review = mutation.get_pending_review

    def inject_orphan_after_commit(workspace: Workspace) -> TransactionReview | None:
        pending = original_get_pending_review(workspace)
        if pending is None:
            (transactions / "orphan").write_text("injected", encoding="ascii")
        return pending

    monkeypatch.setattr(mutation, "get_pending_review", inject_orphan_after_commit)

    with pytest.raises(AssertionError):
        mutation.run_mutation(ScenarioName.COMMIT, fixture)
