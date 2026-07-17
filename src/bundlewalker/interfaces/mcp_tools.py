"""Low-level MCP tool definitions and workspace-application dispatch."""

import logging
import unicodedata
from typing import Any, cast

import jsonschema
from mcp import types
from mcp.server.lowlevel.server import Server
from pydantic import BaseModel, ValidationError

from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    ConceptSearchResult,
    IngestionResult,
    InlineSource,
    LintResult,
    MutationResult,
    PendingReviewResult,
    RefreshResult,
    ReviewResult,
    SynthesisResult,
    WorkspaceApplication,
    WorkspaceStatus,
)
from bundlewalker.interfaces.mcp_schemas import (
    TOOL_SPECS,
    AskInput,
    LintInput,
    PrepareIngestionInput,
    PrepareRefreshInput,
    PrepareSynthesisInput,
    ReviewIdInput,
    SearchInput,
)

logger = logging.getLogger(__name__)

_MAX_TEXT_LINE_CHARACTERS = 1_024
_TOOL_SPECS_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def register_mcp_tools(
    server: Server[None],
    application: WorkspaceApplication,
) -> None:
    """Register static definitions and the workspace-bound tool dispatcher."""

    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=spec.name,
                title=spec.title,
                description=spec.description,
                inputSchema=spec.input_model.model_json_schema(),
                outputSchema=spec.output_model.model_json_schema(),
                annotations=spec.annotations,
            )
            for spec in TOOL_SPECS
        ]

    async def _call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        return await _dispatch_tool(server, application, name, arguments)

    server.list_tools()(_list_tools)
    server.call_tool(validate_input=False)(_call_tool)


def success_result(model: BaseModel, text: str) -> types.CallToolResult:
    """Build one successful tool result with text and validated structured data."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=model.model_dump(mode="json"),
        isError=False,
    )


def error_result(error: ApplicationError) -> types.CallToolResult:
    """Build one bounded application-error tool result."""
    payload = {
        "error": {
            "code": error.code.value,
            "message": error.safe_message,
            "retryable": error.retryable,
            "review_id": error.review_id,
        }
    }
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=error.safe_message)],
        structuredContent=payload,
        isError=True,
    )


async def report_progress(
    server: Server[None],
    token: str | int | None,
    progress: float,
    message: str,
) -> None:
    """Send one standard MCP progress notification when the client supplied a token."""
    if token is None:
        return
    await server.request_context.session.send_progress_notification(
        progress_token=token,
        progress=progress,
        total=1.0,
        message=message,
    )


async def _dispatch_tool(
    server: Server[None],
    application: WorkspaceApplication,
    name: str,
    arguments: dict[str, Any],
) -> types.CallToolResult:
    try:
        try:
            tool_input = _validate_tool_input(name, arguments)
        except _UnknownToolError:
            return _unknown_tool_result()
        except (jsonschema.ValidationError, ValidationError):
            return error_result(
                ApplicationError(
                    ApplicationErrorCode.INVALID_INPUT,
                    "invalid tool input",
                )
            )

        progress_messages = _progress_messages(name, tool_input)
        progress_token = _request_progress_token(server)
        if progress_messages is not None:
            await report_progress(server, progress_token, 0.0, progress_messages[0])

        result = await _call_application_tool(application, name, tool_input)

        if progress_messages is not None:
            try:
                await report_progress(server, progress_token, 1.0, progress_messages[1])
            except Exception:
                logger.exception(
                    "Failed to send final progress for BundleWalker tool %s",
                    name,
                )
        return result
    except ApplicationError as error:
        return error_result(error)
    except Exception:
        logger.exception("Unexpected failure while calling BundleWalker tool %s", name)
        return error_result(
            ApplicationError(
                ApplicationErrorCode.WORKSPACE_ERROR,
                "BundleWalker operation failed",
            )
        )


async def _call_application_tool(
    application: WorkspaceApplication,
    name: str,
    tool_input: BaseModel,
) -> types.CallToolResult:
    if name == "workspace_status":
        status = await application.status()
        return success_result(status, _render_workspace_status(status))

    if name == "search_concepts":
        search = cast(SearchInput, tool_input)
        result = await application.search_concepts(
            search.query,
            concept_type=search.concept_type,
            limit=search.limit,
        )
        return success_result(result, _render_search_results(result))

    if name == "ask":
        request = cast(AskInput, tool_input)
        answer = await application.ask(
            request.question,
            explicit_model=request.model,
        )
        return success_result(answer, answer.markdown)

    if name == "lint":
        request = cast(LintInput, tool_input)
        lint = await application.lint(
            semantic=request.semantic,
            explicit_model=request.model,
        )
        return success_result(lint, _render_lint(lint))

    if name == "prepare_ingestion":
        request = cast(PrepareIngestionInput, tool_input)
        ingestion = await application.prepare_ingestion(
            InlineSource(source_name=request.source_name, content=request.content),
            explicit_model=request.model,
        )
        return success_result(ingestion, _render_ingestion(ingestion))

    if name == "prepare_synthesis":
        request = cast(PrepareSynthesisInput, tool_input)
        synthesis = await application.prepare_synthesis(
            request.question,
            explicit_model=request.model,
        )
        return success_result(synthesis, _render_synthesis(synthesis))

    if name == "prepare_refresh":
        request = cast(PrepareRefreshInput, tool_input)
        refresh = await application.prepare_refresh(
            request.instruction,
            request.concept_id,
            explicit_model=request.model,
        )
        return success_result(refresh, _render_refresh(refresh))

    if name == "get_pending_review":
        pending = PendingReviewResult(review=await application.get_pending_review())
        return success_result(pending, _render_pending_review(pending))

    request = cast(ReviewIdInput, tool_input)
    if name == "apply_review":
        mutation = await application.apply_review(request.review_id)
        return success_result(mutation, _render_mutation(mutation))
    if name == "discard_review":
        mutation = await application.discard_review(request.review_id)
        return success_result(mutation, _render_mutation(mutation))
    return _unknown_tool_result()


def _request_progress_token(server: Server[None]) -> str | int | None:
    meta = server.request_context.meta
    if meta is None:
        return None
    return meta.progressToken


def _progress_messages(name: str, tool_input: BaseModel) -> tuple[str, str] | None:
    messages = {
        "ask": ("Answering workspace question", "Answered workspace question"),
        "prepare_ingestion": ("Preparing ingestion review", "Prepared ingestion review"),
        "prepare_synthesis": ("Preparing synthesis review", "Prepared synthesis review"),
        "prepare_refresh": ("Preparing refresh review", "Prepared refresh review"),
    }
    if name == "lint" and cast(LintInput, tool_input).semantic:
        return ("Running semantic lint", "Completed semantic lint")
    return messages.get(name)


def _render_ingestion(result: IngestionResult) -> str:
    if result.review is None:
        return "Source is already present; no review was created."
    return _render_prepared_review("Ingestion Review", result.review)


def _render_synthesis(result: SynthesisResult) -> str:
    return _render_prepared_review("Synthesis Review", result.review)


def _render_refresh(result: RefreshResult) -> str:
    if result.review is None:
        return _bounded_line(f"Synthesis is already current: {result.concept_id}")
    return _render_prepared_review("Refresh Review", result.review)


def _render_prepared_review(title: str, review: ReviewResult) -> str:
    return (
        f"# {title}\n\n"
        f"- Review ID: `{review.review_id}`\n"
        f"- Summary: {review.summary}\n"
        f"- Review resource: {review.resource_uri}\n\n"
        f"## Diff\n\n{review.diff}"
    )


def _render_mutation(result: MutationResult) -> str:
    return _bounded_line(f"Review {result.review_id} was {result.status}.")


def _validate_tool_input(name: str, arguments: dict[str, Any]) -> BaseModel:
    spec = _TOOL_SPECS_BY_NAME.get(name)
    if spec is None:
        raise _UnknownToolError
    jsonschema.validate(
        instance=arguments,
        schema=spec.input_model.model_json_schema(),
    )
    return spec.input_model.model_validate(arguments)


class _UnknownToolError(Exception):
    """Internal signal for an unadvertised or not-yet-dispatched tool."""


def _unknown_tool_result() -> types.CallToolResult:
    return error_result(
        ApplicationError(
            ApplicationErrorCode.INVALID_INPUT,
            "unknown or unsupported tool",
        )
    )


def _render_workspace_status(status: WorkspaceStatus) -> str:
    concepts = ", ".join(
        f"{_bounded_line(concept_type)}={count}"
        for concept_type, count in sorted(status.concept_counts.items())
    )
    lines = [
        f"Workspace: {_bounded_line(status.display_name)}",
        f"Configuration version: {status.config_version}",
        _bounded_line(f"Concepts: {concepts or 'none'}"),
    ]
    if status.pending_review is None:
        lines.append("Pending review: none")
    else:
        review = status.pending_review
        lines.append(
            _bounded_line(
                "Pending review: "
                f"{review.review_id} ({review.kind}, {review.status}) - {review.summary}"
            )
        )
    return "\n".join(lines)


def _render_search_results(result: ConceptSearchResult) -> str:
    if not result.items:
        return "No matching concepts."
    return "\n".join(_bounded_line(f"{item.concept_id} - {item.title}") for item in result.items)


def _render_lint(result: LintResult) -> str:
    if not result.findings:
        return "No lint findings."
    return "\n".join(
        _bounded_line(f"[{finding.severity}] {finding.code} ({finding.origin}): {finding.message}")
        for finding in result.findings
    )


def _render_pending_review(result: PendingReviewResult) -> str:
    review = result.review
    if review is None:
        return "No pending review."
    return (
        "# Pending Review\n\n"
        f"- Review ID: `{review.review_id}`\n"
        f"- Kind: {review.kind}\n"
        f"- Status: {review.status}\n"
        f"- Summary: {review.summary}\n\n"
        f"## Diff\n\n{review.diff}"
    )


def _bounded_line(value: str) -> str:
    sanitized = "".join(
        " " if unicodedata.category(character) == "Cc" else character for character in value
    )
    line = " ".join(sanitized.split())
    if len(line) <= _MAX_TEXT_LINE_CHARACTERS:
        return line
    return line[: _MAX_TEXT_LINE_CHARACTERS - 1] + "…"
