"""Low-level MCP resources bound to one BundleWalker workspace application."""

import argparse
import asyncio
import sys
import unicodedata
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import anyio
import mcp.server.stdio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import types
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.shared.message import SessionMessage
from pydantic import AnyUrl

from bundlewalker.application import (
    ApplicationError,
    ReviewResult,
    WorkspaceApplication,
    translate_error,
)
from bundlewalker.domain import MAX_CONCEPT_ID_CHARACTERS
from bundlewalker.errors import BundleWalkerError
from bundlewalker.interfaces.mcp_tools import register_mcp_tools
from bundlewalker.workspace import discover_workspace

_CONCEPT_AUTHORITY = "concept"
_INVALID_RESOURCE_URI = "bundlewalker://invalid/resource-uri"
_PENDING_REVIEW_URI = "bundlewalker://review/pending"
_REVIEW_AUTHORITY = "review"


@asynccontextmanager
async def _lifespan(_: Server[None]) -> AsyncGenerator[None]:
    yield None


class _RawUriValidatingServer(Server[None]):
    async def run(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        initialization_options: InitializationOptions,
        raise_exceptions: bool = False,
        stateless: bool = False,
    ) -> None:
        forwarded_send, forwarded_receive = anyio.create_memory_object_stream[
            SessionMessage | Exception
        ](0)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(_forward_validated_messages, read_stream, forwarded_send)
            await super().run(
                forwarded_receive,
                write_stream,
                initialization_options,
                raise_exceptions=raise_exceptions,
                stateless=stateless,
            )
            task_group.cancel_scope.cancel()


def create_mcp_server(application: WorkspaceApplication) -> Server[None]:
    """Create a transport-free MCP server backed by ``application``."""
    server: Server[None] = _RawUriValidatingServer("bundlewalker", lifespan=_lifespan)

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
        uri_text = str(uri)
        parsed = urlsplit(uri_text)
        if (
            parsed.scheme != "bundlewalker"
            or parsed.netloc not in {_CONCEPT_AUTHORITY, _REVIEW_AUTHORITY}
            or "?" in uri_text
            or "#" in uri_text
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
    register_mcp_tools(server, application)
    return server


async def serve_stdio(application: WorkspaceApplication) -> None:
    """Serve ``application`` over the SDK's local standard-I/O transport."""
    server = create_mcp_server(application)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(
                    prompts_changed=False,
                    resources_changed=False,
                    tools_changed=False,
                ),
                experimental_capabilities={},
            ),
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Run one MCP stdio server bound to one discovered workspace."""
    parser = argparse.ArgumentParser(prog="bundlewalker-mcp")
    parser.add_argument("--workspace", type=Path)
    arguments = parser.parse_args(argv)
    try:
        workspace = discover_workspace(arguments.workspace)
    except BundleWalkerError as error:
        print(f"Error: {translate_error(error).safe_message}", file=sys.stderr)
        raise SystemExit(error.exit_code) from None
    asyncio.run(serve_stdio(WorkspaceApplication(workspace)))


async def _forward_validated_messages(
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage | Exception],
) -> None:
    async with read_stream, write_stream:
        async for message in read_stream:
            await write_stream.send(_guard_raw_resource_uri(message))


def _guard_raw_resource_uri(message: SessionMessage | Exception) -> SessionMessage | Exception:
    if isinstance(message, Exception):
        return message
    request = message.message.root
    if not isinstance(request, types.JSONRPCRequest) or request.method != "resources/read":
        return message
    params = request.params
    if not isinstance(params, dict):
        return message
    uri = params.get("uri")
    if not isinstance(uri, str) or not _has_dot_path_segment(uri):
        return message
    guarded_request = request.model_copy(
        update={"params": {**params, "uri": _INVALID_RESOURCE_URI}}
    )
    return SessionMessage(
        message=types.JSONRPCMessage(guarded_request),
        metadata=message.metadata,
    )


def _has_dot_path_segment(uri: str) -> bool:
    try:
        raw_segments = urlsplit(uri).path.split("/")
        return any(unquote(segment, errors="strict") in {".", ".."} for segment in raw_segments)
    except (UnicodeDecodeError, ValueError):
        return False


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


if __name__ == "__main__":
    main()
