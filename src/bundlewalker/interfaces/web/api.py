# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capability-shaped JSON routes for the local web interface."""

import unicodedata
from json import JSONDecodeError
from pathlib import PurePosixPath
from typing import Final

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bundlewalker.application import (
    MAX_CONCEPT_PAGE_SIZE,
    ApplicationError,
    ApplicationErrorCode,
    InlineSource,
    WorkspaceApplication,
)
from bundlewalker.interfaces.web.contracts import (
    WebAskRequest,
    WebIngestionRequest,
    WebLintRequest,
    WebRefreshRequest,
    WebSynthesisRequest,
    to_web_answer,
    to_web_concept,
    to_web_concept_page,
    to_web_ingestion,
    to_web_lint,
    to_web_mutation,
    to_web_refresh,
    to_web_review,
    to_web_search,
    to_web_synthesis,
    to_web_workspace,
)
from bundlewalker.interfaces.web.errors import map_application_error

_SESSION_COOKIE_NAME: Final = "bundlewalker_session"
_DEFAULT_SEARCH_LIMIT: Final = 10
_MAX_SEARCH_LIMIT: Final = 10


def create_api_routes(application: WorkspaceApplication) -> tuple[Route, ...]:
    """Create authenticated read routes bound to one workspace facade."""

    async def workspace(request: Request) -> Response:
        session_id = request.cookies.get(_SESSION_COOKIE_NAME, "")
        session = request.app.state.sessions.get(session_id)
        if session is None:
            return _application_error(
                ApplicationError(
                    ApplicationErrorCode.INVALID_INPUT,
                    "browser session is unavailable",
                )
            )
        try:
            status = await application.status()
            return _json_response(to_web_workspace(status, session.csrf_token))
        except ApplicationError as error:
            return _application_error(error)

    async def concepts(request: Request) -> Response:
        try:
            limit = _bounded_integer(
                request.query_params.get("limit"),
                default=MAX_CONCEPT_PAGE_SIZE,
                minimum=1,
                maximum=MAX_CONCEPT_PAGE_SIZE,
                label="concept page limit",
            )
            page = await application.list_concepts(
                cursor=request.query_params.get("cursor"),
                limit=limit,
            )
            return _json_response(to_web_concept_page(page))
        except ApplicationError as error:
            return _application_error(error)

    async def search(request: Request) -> Response:
        try:
            query = request.query_params.get("query", "")
            limit = _bounded_integer(
                request.query_params.get("limit"),
                default=_DEFAULT_SEARCH_LIMIT,
                minimum=1,
                maximum=_MAX_SEARCH_LIMIT,
                label="search limit",
            )
            result = await application.search_concepts(
                query,
                concept_type=request.query_params.get("type"),
                limit=limit,
            )
            return _json_response(to_web_search(result))
        except ApplicationError as error:
            return _application_error(error)

    async def concept(request: Request) -> Response:
        try:
            concept_id = request.path_params["concept_id"]
            if not isinstance(concept_id, str):
                raise _invalid_concept_id()
            _require_safe_concept_id(concept_id)
            result = await application.read_concept(concept_id)
            return _json_response(to_web_concept(result))
        except ApplicationError as error:
            return _application_error(error)

    async def ask(request: Request) -> Response:
        try:
            payload = WebAskRequest.model_validate(await request.json())
            result = await application.ask(
                payload.question,
                explicit_model=payload.model,
            )
            return _json_response(to_web_answer(result))
        except (JSONDecodeError, ValidationError, UnicodeDecodeError) as error:
            return _application_error(_invalid_json_request(error))
        except ApplicationError as error:
            return _application_error(error)

    async def lint(request: Request) -> Response:
        try:
            payload = WebLintRequest.model_validate(await request.json())
            result = await application.lint(
                semantic=payload.semantic,
                explicit_model=payload.model,
            )
            return _json_response(to_web_lint(result))
        except (JSONDecodeError, ValidationError, UnicodeDecodeError) as error:
            return _application_error(_invalid_json_request(error))
        except ApplicationError as error:
            return _application_error(error)

    async def ingestion(request: Request) -> Response:
        try:
            payload = WebIngestionRequest.model_validate(await request.json())
        except (
            JSONDecodeError,
            ValidationError,
            UnicodeDecodeError,
            UnicodeEncodeError,
        ) as error:
            return _application_error(_invalid_json_request(error))
        try:
            result = await application.prepare_ingestion(
                InlineSource(
                    source_name=payload.source_name,
                    content=payload.content,
                ),
                explicit_model=payload.model,
            )
            return _json_response(to_web_ingestion(result))
        except ApplicationError as error:
            return _application_error(error)

    async def synthesis(request: Request) -> Response:
        try:
            payload = WebSynthesisRequest.model_validate(await request.json())
        except (JSONDecodeError, ValidationError, UnicodeDecodeError) as error:
            return _application_error(_invalid_json_request(error))
        try:
            result = await application.prepare_synthesis(
                payload.question,
                explicit_model=payload.model,
            )
            return _json_response(to_web_synthesis(result))
        except ApplicationError as error:
            return _application_error(error)

    async def refresh(request: Request) -> Response:
        try:
            payload = WebRefreshRequest.model_validate(await request.json())
        except (JSONDecodeError, ValidationError, UnicodeDecodeError) as error:
            return _application_error(_invalid_json_request(error))
        try:
            result = await application.prepare_refresh(
                payload.instruction,
                payload.concept_id,
                explicit_model=payload.model,
            )
            return _json_response(to_web_refresh(result))
        except ApplicationError as error:
            return _application_error(error)

    async def review(_: Request) -> Response:
        try:
            pending = await application.get_pending_review()
            return _json_response(to_web_review(pending) if pending is not None else None)
        except ApplicationError as error:
            return _application_error(error)

    async def apply_review(request: Request) -> Response:
        try:
            result = await application.apply_review(request.path_params["review_id"])
            return _json_response(to_web_mutation(result))
        except ApplicationError as error:
            return _application_error(error)

    async def discard_review(request: Request) -> Response:
        try:
            result = await application.discard_review(request.path_params["review_id"])
            return _json_response(to_web_mutation(result))
        except ApplicationError as error:
            return _application_error(error)

    return (
        Route("/api/v1/workspace", workspace, methods=["GET"]),
        Route("/api/v1/concepts", concepts, methods=["GET"]),
        Route("/api/v1/concepts/search", search, methods=["GET"]),
        Route("/api/v1/review", review, methods=["GET"]),
        Route(
            "/api/v1/reviews/{review_id}/apply",
            apply_review,
            methods=["POST"],
        ),
        Route(
            "/api/v1/reviews/{review_id}/discard",
            discard_review,
            methods=["POST"],
        ),
        Route("/api/v1/concepts/{concept_id:path}", concept, methods=["GET"]),
        Route("/api/v1/ask", ask, methods=["POST"]),
        Route("/api/v1/lint", lint, methods=["POST"]),
        Route("/api/v1/ingestions", ingestion, methods=["POST"]),
        Route("/api/v1/syntheses", synthesis, methods=["POST"]),
        Route("/api/v1/refreshes", refresh, methods=["POST"]),
    )


def _bounded_integer(
    value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ApplicationError(
            ApplicationErrorCode.INVALID_INPUT,
            f"{label} must be an integer",
        ) from error
    if not minimum <= parsed <= maximum:
        raise ApplicationError(
            ApplicationErrorCode.INVALID_INPUT,
            f"{label} must be between {minimum} and {maximum}",
        )
    return parsed


def _require_safe_concept_id(concept_id: str) -> None:
    path = PurePosixPath(concept_id)
    if (
        not concept_id
        or "\\" in concept_id
        or any(unicodedata.category(character) == "Cc" for character in concept_id)
        or path.is_absolute()
        or path == PurePosixPath(".")
        or any(part in {".", ".."} for part in path.parts)
        or path.as_posix() != concept_id
    ):
        raise _invalid_concept_id()


def _invalid_concept_id() -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.INVALID_INPUT,
        "concept ID must be a normalized relative path",
    )


def _invalid_json_request(_error: Exception) -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.INVALID_INPUT,
        "request body does not match the expected JSON contract",
    )


def _json_response(model: BaseModel | None) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json") if model is not None else None)


def _application_error(error: ApplicationError) -> JSONResponse:
    status, response = map_application_error(error)
    return JSONResponse(response.model_dump(mode="json"), status_code=status)
