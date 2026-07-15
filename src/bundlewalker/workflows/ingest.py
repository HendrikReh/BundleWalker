from __future__ import annotations

import os
import stat
from collections.abc import Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from bundlewalker.agents.common import AgentDependencies, resolve_model
from bundlewalker.agents.ingest import AgentModel, run_ingestion_agent
from bundlewalker.changes import ChangeValidationContext, validate_change_set
from bundlewalker.domain import ChangeSet
from bundlewalker.errors import WorkspaceError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.transactions import PreparedTransaction, prepare_transaction, recover_transactions
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
    _validate_repository_path(workspace)
    source = load_raw_source(source_path, workspace)
    repository = OkfRepository(workspace.wiki_dir)
    if _contains_source_digest(repository, source.sha256):
        return DuplicateIngestion()

    conventions = _read_context(
        workspace,
        workspace.config.conventions_file,
        "workspace conventions",
    )
    root_index = _read_context(
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
    )
    return PreparedIngestion(transaction=transaction)


def _contains_source_digest(repository: OkfRepository, digest: str) -> bool:
    for document in repository.scan().values():
        if document.metadata.type != "Source":
            continue
        if (document.metadata.model_extra or {}).get("source_sha256") == digest:
            return True
    return False


def _validate_repository_path(workspace: Workspace) -> None:
    wiki_parts = _safe_configured_parts(workspace.config.wiki_dir, "configured wiki path")
    with _open_workspace_directory(workspace, wiki_parts, "configured wiki path"):
        pass


def _safe_configured_parts(value: str, description: str) -> tuple[str, ...]:
    relative = PurePosixPath(value)
    if (
        not value
        or relative.is_absolute()
        or relative == PurePosixPath(".")
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise WorkspaceError(f"{description} is not a safe workspace-relative path")
    return relative.parts


@contextmanager
def _open_workspace_directory(
    workspace: Workspace,
    parts: tuple[str, ...],
    description: str,
) -> Generator[int]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    traversed: list[str] = []
    try:
        current = os.open(workspace.root, flags)
        descriptors.append(current)
        for part in parts:
            traversed.append(part)
            current = os.open(part, flags, dir_fd=current)
            descriptors.append(current)
    except OSError as exc:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)
        location = "/".join(traversed) or "."
        raise WorkspaceError(
            f"{description} contains a symlink or non-directory: {location}"
        ) from exc
    try:
        yield current
    finally:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)


@contextmanager
def _open_workspace_file(
    workspace: Workspace,
    parts: tuple[str, ...],
    description: str,
) -> Generator[int]:
    with _open_workspace_directory(workspace, parts[:-1], description) as parent:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=parent)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("not a regular file")
        except OSError as exc:
            if descriptor is not None:
                with suppress(OSError):
                    os.close(descriptor)
            raise WorkspaceError(
                f"{description} contains a symlink or is not a regular file"
            ) from exc
        try:
            yield descriptor
        finally:
            with suppress(OSError):
                os.close(descriptor)


def _read_context(workspace: Workspace, relative_path: str, description: str) -> str:
    parts = _safe_configured_parts(relative_path, description)
    with _open_workspace_file(workspace, parts, description) as descriptor:
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65_536):
                chunks.append(chunk)
        except OSError as exc:
            raise WorkspaceError(f"could not read {description}") from exc
    try:
        return b"".join(chunks).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkspaceError(f"could not decode {description} as UTF-8") from exc
