"""Closed, sanitized error translation for every delivery adapter."""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PureWindowsPath

from bundlewalker.errors import (
    AgentRunError,
    BundleWalkerError,
    ChangeSetError,
    ConfigurationError,
    OkfError,
    ReviewMismatchError,
    ReviewNotFoundError,
    ReviewPendingError,
    ReviewStaleError,
    TransactionError,
    UsageError,
    WorkspaceError,
)


class ApplicationErrorCode(StrEnum):
    """The bounded error vocabulary exposed outside BundleWalker."""

    INVALID_INPUT = "invalid_input"
    CONFIGURATION_ERROR = "configuration_error"
    WORKSPACE_ERROR = "workspace_error"
    CONCEPT_NOT_FOUND = "concept_not_found"
    OKF_ERROR = "okf_error"
    CHANGE_INVALID = "change_invalid"
    MODEL_FAILED = "model_failed"
    REVIEW_PENDING = "review_pending"
    REVIEW_NOT_FOUND = "review_not_found"
    REVIEW_ID_MISMATCH = "review_id_mismatch"
    REVIEW_STALE = "review_stale"
    TRANSACTION_FAILED = "transaction_failed"


@dataclass(frozen=True, slots=True)
class ApplicationError(Exception):
    """A public, serializable failure without provider or filesystem detail."""

    code: ApplicationErrorCode
    safe_message: str
    retryable: bool = False
    review_id: str | None = None

    def __str__(self) -> str:
        return self.safe_message


def translate_error(error: BundleWalkerError) -> ApplicationError:
    """Map bounded core failures to the one public error vocabulary."""
    if isinstance(error, ReviewPendingError):
        return ApplicationError(
            ApplicationErrorCode.REVIEW_PENDING,
            str(error),
            review_id=error.review_id,
        )
    if isinstance(error, ReviewNotFoundError):
        return ApplicationError(ApplicationErrorCode.REVIEW_NOT_FOUND, str(error))
    if isinstance(error, ReviewMismatchError):
        return ApplicationError(ApplicationErrorCode.REVIEW_ID_MISMATCH, str(error))
    if isinstance(error, ReviewStaleError):
        return ApplicationError(ApplicationErrorCode.REVIEW_STALE, str(error))
    if isinstance(error, ConfigurationError):
        return ApplicationError(
            ApplicationErrorCode.CONFIGURATION_ERROR,
            _public_message(error, "workspace configuration is invalid"),
        )
    if isinstance(error, UsageError):
        return ApplicationError(
            ApplicationErrorCode.INVALID_INPUT,
            _public_message(error, "invalid input"),
        )
    if isinstance(error, WorkspaceError):
        return ApplicationError(
            ApplicationErrorCode.WORKSPACE_ERROR,
            _public_message(error, "workspace operation failed"),
        )
    if isinstance(error, OkfError):
        return ApplicationError(
            ApplicationErrorCode.OKF_ERROR,
            _public_message(error, "knowledge bundle operation failed"),
        )
    if isinstance(error, ChangeSetError):
        return ApplicationError(
            ApplicationErrorCode.CHANGE_INVALID,
            _public_message(error, "proposed change is invalid"),
        )
    if isinstance(error, AgentRunError):
        return ApplicationError(
            ApplicationErrorCode.MODEL_FAILED,
            _public_message(error, "model-backed operation failed"),
            retryable=True,
        )
    if isinstance(error, TransactionError):
        return ApplicationError(
            ApplicationErrorCode.TRANSACTION_FAILED,
            _public_message(error, "transaction operation failed"),
        )
    return ApplicationError(
        ApplicationErrorCode.WORKSPACE_ERROR,
        "BundleWalker operation failed",
    )


def _public_message(error: BundleWalkerError, fallback: str) -> str:
    message = str(error)
    if (
        not message
        or len(message) > 1_024
        or any(unicodedata.category(character) == "Cc" for character in message)
    ):
        return fallback
    for token in message.split():
        candidate = token.strip("'\"()[]{}<>,;:")
        if (
            Path(candidate).is_absolute()
            or PureWindowsPath(candidate).is_absolute()
            or candidate.startswith(("~/", "file:"))
        ):
            return fallback
    return message
