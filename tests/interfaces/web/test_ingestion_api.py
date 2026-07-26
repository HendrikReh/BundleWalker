# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authenticated paste and single-file-text ingestion API coverage."""

from pathlib import Path
from typing import Protocol

import pytest
from httpx2 import Response

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.ingest import AgentModel
from bundlewalker.application import (
    MAX_INLINE_SOURCE_CHARACTERS,
    ApplicationDependencies,
    IngestionResult,
    InlineSource,
    WorkspaceApplication,
)
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
)
from bundlewalker.workspace import RawSource


class AuthenticatedWebClient(Protocol):
    csrf_token: str
    expected_origin: str

    def post(
        self,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | str | None = None,
    ) -> Response: ...

    def post_json(self, path: str, body: object) -> Response: ...


def _live_tree_bytes(application: WorkspaceApplication) -> dict[str, bytes]:
    workspace = application.workspace
    return {
        path.relative_to(workspace.root).as_posix(): path.read_bytes()
        for root in (workspace.raw_dir, workspace.wiki_dir)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _ingestion_change_set(source: RawSource) -> ChangeSet:
    return ChangeSet(
        summary="Integrated browser notes.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Browser notes",
                description="Notes submitted through the local web interface.",
                tags=["notes"],
                body="# Browser notes\n\nThe source contains evidence [1].\n",
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


async def _ingestion_runner(
    model: AgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    assert model == "test:model"
    return _ingestion_change_set(source), frozenset()


@pytest.mark.parametrize("source_name", ["notes.md", "notes.txt"])
async def test_ingestion_constructs_one_inline_source_and_calls_facade_once(
    source_name: str,
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls: list[tuple[InlineSource, str | None]] = []

    async def prepare_ingestion(
        source: InlineSource,
        *,
        explicit_model: str | None,
    ) -> IngestionResult:
        calls.append((source, explicit_model))
        return IngestionResult(status="duplicate", review=None)

    application.prepare_ingestion = prepare_ingestion  # type: ignore[method-assign]

    response = authenticated_client.post_json(
        "/api/v1/ingestions",
        {
            "source_name": source_name,
            "content": "# Notes\n\nEvidence.",
            "model": "test:model",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "duplicate", "review": None}
    assert calls == [
        (
            InlineSource(source_name=source_name, content="# Notes\n\nEvidence."),
            "test:model",
        )
    ]
    assert all(not isinstance(value, Path) for value in calls[0])


@pytest.mark.parametrize(
    ("source_name", "content"),
    [
        pytest.param("notes.md", "", id="empty-content"),
        pytest.param("notes.md", " \t\r\n", id="blank-content"),
        pytest.param(
            "notes.md",
            "a" * (MAX_INLINE_SOURCE_CHARACTERS + 1),
            id="oversized-content",
        ),
        pytest.param("notes.pdf", "Evidence.", id="unsupported-suffix"),
        pytest.param("notes.MD", "Evidence.", id="uppercase-suffix"),
        pytest.param(".md", "Evidence.", id="dot-md"),
        pytest.param(".txt", "Evidence.", id="dot-txt"),
        pytest.param("folder/notes.md", "Evidence.", id="posix-separator"),
        pytest.param(r"folder\notes.md", "Evidence.", id="windows-separator"),
        pytest.param("../notes.md", "Evidence.", id="dot-segment"),
        pytest.param("notes\nprivate.md", "Evidence.", id="newline"),
        pytest.param("notes\x00.md", "Evidence.", id="nul"),
    ],
)
async def test_ingestion_rejects_invalid_content_and_names_before_facade_dispatch(
    source_name: str,
    content: str,
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls = 0

    async def prepare_ingestion(
        _source: InlineSource,
        *,
        explicit_model: str | None,
    ) -> IngestionResult:
        nonlocal calls
        calls += 1
        return IngestionResult(status="duplicate", review=None)

    application.prepare_ingestion = prepare_ingestion  # type: ignore[method-assign]

    response = authenticated_client.post_json(
        "/api/v1/ingestions",
        {"source_name": source_name, "content": content, "model": None},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert calls == 0


async def test_ingestion_rejects_invalid_utf8_json_before_facade_dispatch(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls = 0

    async def prepare_ingestion(
        _source: InlineSource,
        *,
        explicit_model: str | None,
    ) -> IngestionResult:
        nonlocal calls
        calls += 1
        return IngestionResult(status="duplicate", review=None)

    application.prepare_ingestion = prepare_ingestion  # type: ignore[method-assign]

    response = authenticated_client.post(
        "/api/v1/ingestions",
        headers={
            "Content-Type": "application/json",
            "Origin": authenticated_client.expected_origin,
            "X-BundleWalker-CSRF": authenticated_client.csrf_token,
        },
        content=b'{"source_name":"notes.md","content":"\xff","model":null}',
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert calls == 0


async def test_pending_ingestion_returns_exact_review_without_live_tree_mutation(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    application.dependencies = ApplicationDependencies(
        environment={},
        ingestion_runner=_ingestion_runner,
    )
    before = _live_tree_bytes(application)

    response = authenticated_client.post_json(
        "/api/v1/ingestions",
        {
            "source_name": "notes.md",
            "content": "# Notes\n\nEvidence.",
            "model": "test:model",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    pending = await application.get_pending_review()
    assert pending is not None
    assert body["status"] == "pending"
    assert body["review"]["review_id"] == pending.review_id
    assert "resource_uri" not in body["review"]
    assert _live_tree_bytes(application) == before


async def test_duplicate_ingestion_returns_no_review_or_navigation_data(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    application.dependencies = ApplicationDependencies(
        environment={},
        ingestion_runner=_ingestion_runner,
    )
    payload = {
        "source_name": "notes.txt",
        "content": "Evidence.\n",
        "model": "test:model",
    }
    prepared = authenticated_client.post_json("/api/v1/ingestions", payload)
    assert prepared.status_code == 200, prepared.text
    review_id = prepared.json()["review"]["review_id"]
    await application.apply_review(review_id)
    before = _live_tree_bytes(application)

    duplicate = authenticated_client.post_json(
        "/api/v1/ingestions",
        {**payload, "model": None},
    )

    assert duplicate.status_code == 200
    assert duplicate.json() == {"status": "duplicate", "review": None}
    assert _live_tree_bytes(application) == before


async def test_review_pending_conflict_happens_before_runner_work(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    application.dependencies = ApplicationDependencies(
        environment={},
        ingestion_runner=_ingestion_runner,
    )
    prepared = authenticated_client.post_json(
        "/api/v1/ingestions",
        {
            "source_name": "first.md",
            "content": "# First\n\nEvidence.",
            "model": "test:model",
        },
    )
    assert prepared.status_code == 200, prepared.text
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("pending review invoked ingestion runner")

    application.dependencies = ApplicationDependencies(
        environment={},
        ingestion_runner=must_not_run,
    )

    response = authenticated_client.post_json(
        "/api/v1/ingestions",
        {
            "source_name": "second.txt",
            "content": "Different evidence.",
            "model": "test:model",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_pending"
    assert calls == 0
