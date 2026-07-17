"""Low-level MCP resources bound to one BundleWalker workspace application."""

import unicodedata
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from mcp import types
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import Server
from pydantic import AnyUrl

from bundlewalker.application import (
    ApplicationError,
    ReviewResult,
    WorkspaceApplication,
)
from bundlewalker.domain import MAX_CONCEPT_ID_CHARACTERS

_CONCEPT_AUTHORITY = "concept"
_PENDING_REVIEW_URI = "bundlewalker://review/pending"
_REVIEW_AUTHORITY = "review"


@asynccontextmanager
async def _lifespan(_: Server[None]) -> AsyncGenerator[None]:
    yield None


def create_mcp_server(application: WorkspaceApplication) -> Server[None]:
    """Create a transport-free MCP server backed by ``application``."""
    server: Server[None] = Server("bundlewalker", lifespan=_lifespan)

    async def _list_resources(request: types.ListResourcesRequest) -> types.ListResourcesResult:
        cursor = request.params.cursor if request.params is not None else None
        try:
            page = await application.list_concepts(cursor=cursor, limit=100)
            resources = [
                types.Resource(
                    name=concept.concept_id,
                    title=concept.title,
                    uri=AnyUrl(concept.resource_uri),
                    description=concept.description,
                    mimeType="text/markdown",
                )
                for concept in page.items
            ]
            if cursor is None:
                review = await application.get_pending_review()
                if review is not None:
                    resources.append(_pending_review_resource())
        except ApplicationError as error:
            raise _resource_error(error) from error
        return types.ListResourcesResult(resources=resources, nextCursor=page.next_cursor)

    async def _list_resource_templates() -> list[types.ResourceTemplate]:
        return [
            types.ResourceTemplate(
                name="bundlewalker-concept",
                title="BundleWalker concept",
                uriTemplate="bundlewalker://concept/{+concept_id}",
                description="Read one OKF concept from the bound BundleWalker workspace.",
                mimeType="text/markdown",
            )
        ]

    async def _read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        parsed = urlsplit(str(uri))
        if (
            parsed.scheme != "bundlewalker"
            or parsed.netloc not in {_CONCEPT_AUTHORITY, _REVIEW_AUTHORITY}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid resource URI")

        if parsed.netloc == _CONCEPT_AUTHORITY:
            try:
                concept_id = unquote(parsed.path.removeprefix("/"), errors="strict")
            except UnicodeDecodeError as error:
                raise ValueError("invalid resource URI") from error
            if not _is_safe_concept_id(concept_id):
                raise ValueError("invalid resource URI")
            try:
                concept = await application.read_concept(concept_id)
            except ApplicationError as error:
                raise _resource_error(error) from error
            return [ReadResourceContents(content=concept.markdown, mime_type="text/markdown")]

        if parsed.path != "/pending":
            raise ValueError("invalid resource URI")
        try:
            review = await application.get_pending_review()
        except ApplicationError as error:
            raise _resource_error(error) from error
        if review is None:
            raise ValueError("pending review was not found")
        return [
            ReadResourceContents(
                content=_render_pending_review(review),
                mime_type="text/markdown",
            )
        ]

    server.list_resources()(_list_resources)
    server.list_resource_templates()(_list_resource_templates)
    server.read_resource()(_read_resource)
    return server


def _pending_review_resource() -> types.Resource:
    return types.Resource(
        name="bundlewalker-pending-review",
        title="Pending BundleWalker review",
        uri=AnyUrl(_PENDING_REVIEW_URI),
        description="Read the exact pending review diff for the bound BundleWalker workspace.",
        mimeType="text/markdown",
    )


def _is_safe_concept_id(concept_id: str) -> bool:
    path = PurePosixPath(concept_id)
    return (
        1 <= len(concept_id) <= MAX_CONCEPT_ID_CHARACTERS
        and "\\" not in concept_id
        and not any(unicodedata.category(character) == "Cc" for character in concept_id)
        and not path.is_absolute()
        and path != PurePosixPath(".")
        and not any(part in {".", ".."} for part in path.parts)
        and path.as_posix() == concept_id
    )


def _render_pending_review(review: ReviewResult) -> str:
    return (
        "# Pending Review\n\n"
        f"- Review ID: `{review.review_id}`\n"
        f"- Kind: {review.kind}\n"
        f"- Status: {review.status}\n"
        f"- Summary: {review.summary}\n\n"
        f"## Diff\n\n{review.diff}"
    )


def _resource_error(error: ApplicationError) -> ValueError:
    return ValueError(f"BundleWalker resource error: {error.code.value}")
