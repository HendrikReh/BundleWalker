# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded application and unexpected-error responses for the web adapter."""

import logging
import secrets
from types import TracebackType
from typing import Final

from starlette.requests import Request
from starlette.responses import JSONResponse

from bundlewalker.application import ApplicationError, ApplicationErrorCode
from bundlewalker.interfaces.web.contracts import WebErrorDetail, WebErrorResponse

logger = logging.getLogger(__name__)

APPLICATION_ERROR_STATUS: Final[dict[ApplicationErrorCode, int]] = {
    ApplicationErrorCode.INVALID_INPUT: 422,
    ApplicationErrorCode.CONFIGURATION_ERROR: 400,
    ApplicationErrorCode.WORKSPACE_ERROR: 500,
    ApplicationErrorCode.CONCEPT_NOT_FOUND: 404,
    ApplicationErrorCode.OKF_ERROR: 500,
    ApplicationErrorCode.CHANGE_INVALID: 422,
    ApplicationErrorCode.MODEL_FAILED: 502,
    ApplicationErrorCode.REVIEW_PENDING: 409,
    ApplicationErrorCode.REVIEW_NOT_FOUND: 404,
    ApplicationErrorCode.REVIEW_ID_MISMATCH: 409,
    ApplicationErrorCode.REVIEW_STALE: 409,
    ApplicationErrorCode.TRANSACTION_FAILED: 500,
    ApplicationErrorCode.WORKSPACE_INCOMPATIBLE: 409,
    ApplicationErrorCode.BACKUP_INVALID: 400,
    ApplicationErrorCode.BACKUP_FAILED: 500,
    ApplicationErrorCode.RESTORE_TARGET_INVALID: 400,
    ApplicationErrorCode.MIGRATION_UNAVAILABLE: 409,
    ApplicationErrorCode.MIGRATION_FAILED: 500,
    ApplicationErrorCode.DIAGNOSTIC_FAILED: 500,
}


def map_application_error(error: ApplicationError) -> tuple[int, WebErrorResponse]:
    """Map every bounded application failure to a stable HTTP response."""
    return (
        APPLICATION_ERROR_STATUS[error.code],
        WebErrorResponse(
            error=WebErrorDetail(
                code=error.code.value,
                message=error.safe_message,
                retryable=error.retryable,
                review_id=error.review_id,
            )
        ),
    )


def map_unexpected_exception(error: Exception) -> tuple[int, WebErrorResponse]:
    """Log private diagnostics and return only an opaque browser-safe failure."""
    diagnostic_id = secrets.token_hex(16)
    traceback: TracebackType | None = error.__traceback__
    logger.error(
        "Unexpected local web failure (diagnostic %s)",
        diagnostic_id,
        exc_info=(type(error), error, traceback),
    )
    return (
        500,
        WebErrorResponse(
            error=WebErrorDetail(
                code="internal_error",
                message="An unexpected error occurred",
                retryable=False,
                diagnostic_id=diagnostic_id,
            )
        ),
    )


async def unexpected_exception_handler(
    _: Request,
    error: Exception,
) -> JSONResponse:
    """Starlette handler for otherwise-unbounded exceptions."""
    status, response = map_unexpected_exception(error)
    return JSONResponse(response.model_dump(mode="json"), status_code=status)
