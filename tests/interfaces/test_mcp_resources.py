from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import types
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

from bundlewalker.application import WorkspaceApplication
from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.interfaces.mcp import create_mcp_server
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)


def _workspace(tmp_path: Path, *, concept_count: int = 2) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    for index in range(concept_count):
        concept_id = "topics/agents" if index == 0 else f"topics/concept-{index:03}"
        title = "Agents" if index == 0 else f"Concept {index:03}"
        path = workspace.wiki_dir / f"{concept_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_document(
                OkfMetadata(
                    type="Topic",
                    title=title,
                    description=f"Knowledge for {title}.",
                    tags=["test"],
                    timestamp=NOW,
                ),
                f"# {title}\n\nTest knowledge.\n",
            ),
            encoding="utf-8",
        )
    regenerate_indexes(workspace.wiki_dir)
    return workspace


@pytest.fixture
def application(tmp_path: Path) -> WorkspaceApplication:
    return WorkspaceApplication(_workspace(tmp_path))


@pytest.fixture
def application_with_pending_review(tmp_path: Path) -> WorkspaceApplication:
    workspace = _workspace(tmp_path, concept_count=101)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Agent tools",
                body="# Answer\n\nAgents can use tools [1].\n",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    return WorkspaceApplication(workspace)


async def test_mcp_lists_and_reads_concept_resources(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_resources()
        uri = next(
            resource.uri for resource in listed.resources if "topics/agents" in str(resource.uri)
        )
        read = await session.read_resource(uri)

    content = read.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.mimeType == "text/markdown"
    assert "# Agents" in content.text


async def test_mcp_resource_listing_paginates_without_duplicates(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        first = await session.list_resources()
        assert first.nextCursor is not None
        second = await session.list_resources(
            params=types.PaginatedRequestParams(cursor=first.nextCursor)
        )

    first_concepts = {
        str(resource.uri)
        for resource in first.resources
        if str(resource.uri).startswith("bundlewalker://concept/")
    }
    second_concepts = {
        str(resource.uri)
        for resource in second.resources
        if str(resource.uri).startswith("bundlewalker://concept/")
    }
    assert len(first_concepts) == 100
    assert len(second_concepts) == 1
    assert first_concepts.isdisjoint(second_concepts)
    assert second.nextCursor is None


async def test_pending_review_resource_is_listed_only_on_first_page(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        first = await session.list_resources()
        assert first.nextCursor is not None
        second = await session.list_resources(
            params=types.PaginatedRequestParams(cursor=first.nextCursor)
        )

    pending_uri = "bundlewalker://review/pending"
    assert pending_uri in {str(resource.uri) for resource in first.resources}
    assert pending_uri not in {str(resource.uri) for resource in second.resources}


async def test_pending_review_resource_contains_exact_persisted_diff(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    expected = await application_with_pending_review.get_pending_review()
    assert expected is not None
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        read = await session.read_resource(AnyUrl("bundlewalker://review/pending"))

    content = read.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.mimeType == "text/markdown"
    assert expected.diff in content.text


async def test_mcp_lists_the_exact_concept_resource_template(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_resource_templates()

    assert listed.resourceTemplates == [
        types.ResourceTemplate(
            name="bundlewalker-concept",
            title="BundleWalker concept",
            uriTemplate="bundlewalker://concept/{+concept_id}",
            description="Read one OKF concept from the bound BundleWalker workspace.",
            mimeType="text/markdown",
        )
    ]


@pytest.mark.parametrize(
    "uri",
    [
        "https://concept/topics/agents",
        "bundlewalker://unknown/topics/agents",
        "bundlewalker://concept/topics/agents?view=full",
        "bundlewalker://concept/topics/agents#section",
        "bundlewalker://concept/topics//agents",
        "bundlewalker://concept/%2Fabsolute",
        "bundlewalker://concept/topics/%5Cagents",
        "bundlewalker://concept/topics/%00agents",
        "bundlewalker://concept/topics/%FFagents",
        "bundlewalker://review/other",
        "bundlewalker://review/pending?view=full",
        "bundlewalker://review/pending#diff",
    ],
)
async def test_mcp_rejects_invalid_resource_uris(
    application: WorkspaceApplication,
    uri: str,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        with pytest.raises(McpError, match="invalid resource URI"):
            await session.read_resource(AnyUrl(uri))


async def test_mcp_reports_a_bounded_error_for_a_missing_concept(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        with pytest.raises(McpError) as raised:
            await session.read_resource(AnyUrl("bundlewalker://concept/topics/missing"))

    message = str(raised.value)
    assert "concept_not_found" in message
    assert len(message) < 256
    assert str(application.workspace.root) not in message


async def test_mcp_reports_an_error_when_no_review_is_pending(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        with pytest.raises(McpError, match="pending review was not found"):
            await session.read_resource(AnyUrl("bundlewalker://review/pending"))
