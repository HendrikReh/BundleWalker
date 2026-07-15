from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.ingest import AgentModel
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.errors import ChangeSetError, WorkspaceError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import commit_transaction, discard_transaction
from bundlewalker.workflows.ingest import (
    DuplicateIngestion,
    PreparedIngestion,
    prepare_ingestion,
)
from bundlewalker.workspace import RawSource, initialize_workspace

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _valid_change_set(source: RawSource, *, summary: str = "Integrated notes.") -> ChangeSet:
    return ChangeSet(
        summary=summary,
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Notes",
                description="Notes from the incoming source.",
                tags=["notes"],
                body="# Notes\n\nThe source contains two lines [1].\n",
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=2,
                    )
                ],
            )
        ],
    )


async def _valid_runner(
    model: AgentModel,
    dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    assert model == "test:model"
    assert dependencies.repository.root == dependencies.retriever.repository.root
    return _valid_change_set(source), frozenset(dependencies.read_ids)


async def test_prepare_ingestion_returns_a_staged_review_without_live_mutation(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    input_path = tmp_path / "notes.txt"
    input_path.write_text("first\nsecond\n", encoding="utf-8")
    before_wiki = _tree_bytes(workspace.wiki_dir)
    before_raw = _tree_bytes(workspace.raw_dir)

    outcome = await prepare_ingestion(
        workspace,
        input_path,
        explicit_model="test:model",
        environment={},
        runner=_valid_runner,
        occurred_at=NOW,
    )

    assert isinstance(outcome, PreparedIngestion)
    assert outcome.status == "prepared"
    assert outcome.transaction.diff
    assert _tree_bytes(workspace.wiki_dir) == before_wiki
    assert _tree_bytes(workspace.raw_dir) == before_raw
    assert outcome.transaction.transaction_dir.is_dir()
    discard_transaction(outcome.transaction)


async def test_duplicate_digest_is_a_typed_noop_before_model_resolution_or_runner(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    input_path = tmp_path / "notes.txt"
    input_path.write_text("first\nsecond\n", encoding="utf-8")
    first = await prepare_ingestion(
        workspace,
        input_path,
        explicit_model="test:model",
        environment={},
        runner=_valid_runner,
        occurred_at=NOW,
    )
    assert isinstance(first, PreparedIngestion)
    commit_transaction(first.transaction)
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("duplicate ingestion invoked the model")

    duplicate = await prepare_ingestion(
        workspace,
        input_path,
        explicit_model=None,
        environment={},
        runner=must_not_run,
        occurred_at=NOW,
    )

    assert duplicate == DuplicateIngestion()
    assert calls == 0


async def test_invalid_proposal_leaves_live_raw_and_wiki_byte_identical(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    input_path = tmp_path / "notes.txt"
    input_path.write_text("first\nsecond\n", encoding="utf-8")
    before_wiki = _tree_bytes(workspace.wiki_dir)
    before_raw = _tree_bytes(workspace.raw_dir)

    async def invalid_runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        invalid = _valid_change_set(source).model_copy(update={"source_sha256": "0" * 64})
        return invalid, frozenset()

    with pytest.raises(ChangeSetError, match="source_sha256"):
        await prepare_ingestion(
            workspace,
            input_path,
            explicit_model="test:model",
            environment={},
            runner=invalid_runner,
            occurred_at=NOW,
        )

    assert _tree_bytes(workspace.wiki_dir) == before_wiki
    assert _tree_bytes(workspace.raw_dir) == before_raw
    assert OkfRepository(workspace.wiki_dir).scan() == {}


@pytest.mark.parametrize("context_name", ["conventions.md", "wiki/index.md"])
async def test_ingestion_rejects_symlinked_protected_context_before_the_runner(
    tmp_path: Path,
    context_name: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    input_path = tmp_path / "notes.txt"
    input_path.write_text("first\nsecond\n", encoding="utf-8")
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("provider-secret", encoding="utf-8")
    context_path = workspace.root / context_name
    context_path.unlink()
    context_path.symlink_to(secret)
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("unsafe context reached the model runner")

    with pytest.raises(WorkspaceError, match="regular file"):
        await prepare_ingestion(
            workspace,
            input_path,
            explicit_model="test:model",
            environment={},
            runner=must_not_run,
            occurred_at=NOW,
        )

    assert calls == 0
