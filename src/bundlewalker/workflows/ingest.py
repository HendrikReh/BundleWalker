from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from bundlewalker.agents.common import AgentDependencies, resolve_model
from bundlewalker.agents.ingest import AgentModel, run_ingestion_agent
from bundlewalker.changes import ChangeValidationContext, validate_change_set
from bundlewalker.domain import ChangeSet
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.transactions import (
    PreparedTransaction,
    ReviewKind,
    prepare_transaction,
    recover_transactions,
)
from bundlewalker.workflows.context import read_context, validate_repository_path
from bundlewalker.workspace import RawSource, Workspace, load_raw_source

type IngestionRunner = Callable[
    [AgentModel, AgentDependencies, RawSource],
    Awaitable[tuple[ChangeSet, frozenset[str]]],
]


@dataclass(frozen=True, slots=True)
class DuplicateIngestion:
    status: Literal["duplicate"] = "duplicate"


@dataclass(frozen=True, slots=True)
class PreparedIngestion:
    transaction: PreparedTransaction
    status: Literal["prepared"] = "prepared"


type IngestionOutcome = DuplicateIngestion | PreparedIngestion


async def prepare_ingestion(
    workspace: Workspace,
    source_path: Path,
    *,
    explicit_model: str | None,
    environment: Mapping[str, str] | None = None,
    runner: IngestionRunner | None = None,
    occurred_at: datetime | None = None,
) -> IngestionOutcome:
    """Prepare a validated ingestion transaction without changing live knowledge."""
    recover_transactions(workspace)
    validate_repository_path(workspace)
    source = load_raw_source(source_path, workspace)
    repository = OkfRepository(workspace.wiki_dir)
    if _contains_source_digest(repository, source.sha256):
        return DuplicateIngestion()

    conventions = read_context(
        workspace,
        workspace.config.conventions_file,
        "workspace conventions",
    )
    root_index = read_context(
        workspace,
        (PurePosixPath(workspace.config.wiki_dir) / "index.md").as_posix(),
        "root index",
    )
    model = resolve_model(explicit_model, environment if environment is not None else os.environ)
    dependencies = AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions=conventions,
        root_index=root_index,
    )
    selected_runner = runner if runner is not None else run_ingestion_agent
    change_set, read_ids = await selected_runner(model, dependencies, source)
    context = ChangeValidationContext(
        mode="ingest",
        repository=repository,
        readable_concepts=read_ids,
        source=source,
    )
    validate_change_set(change_set, context)
    transaction = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        occurred_at or datetime.now(UTC),
        kind=ReviewKind.INGESTION,
    )
    return PreparedIngestion(transaction=transaction)


def _contains_source_digest(repository: OkfRepository, digest: str) -> bool:
    for document in repository.scan().values():
        if document.metadata.type != "Source":
            continue
        if (document.metadata.model_extra or {}).get("source_sha256") == digest:
            return True
    return False
