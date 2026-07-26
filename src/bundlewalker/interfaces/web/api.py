# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capability-shaped JSON routes for the local web interface."""

import unicodedata
from pathlib import PurePosixPath
from typing import Final

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bundlewalker.application import (
    MAX_CONCEPT_PAGE_SIZE,
    ApplicationError,
    ApplicationErrorCode,
    WorkspaceApplication,
)
from bundlewalker.interfaces.web.contracts import (
    to_web_concept,
    to_web_concept_page,
    to_web_search,
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

    return (
        Route("/api/v1/workspace", workspace, methods=["GET"]),
        Route("/api/v1/concepts", concepts, methods=["GET"]),
        Route("/api/v1/concepts/search", search, methods=["GET"]),
        Route("/api/v1/concepts/{concept_id:path}", concept, methods=["GET"]),
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


def _json_response(model: BaseModel) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"))


def _application_error(error: ApplicationError) -> JSONResponse:
    status, response = map_application_error(error)
    return JSONResponse(response.model_dump(mode="json"), status_code=status)
