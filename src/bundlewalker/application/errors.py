# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Closed, safe-by-construction error translation for every delivery adapter."""

import re
from dataclasses import dataclass
from enum import StrEnum

from bundlewalker.errors import (
    AgentRunError,
    BackupError,
    BackupVerificationError,
    BundleWalkerError,
    ChangeSetError,
    ConfigurationError,
    MigrationExecutionError,
    MigrationUnavailableError,
    OkfError,
    RestoreTargetError,
    ReviewMismatchError,
    ReviewNotFoundError,
    ReviewPendingError,
    ReviewStaleError,
    TransactionError,
    UsageError,
    WorkspaceCompatibilityError,
    WorkspaceError,
)

_REVIEW_ID = re.compile(r"^[0-9a-f]{32}$")
_SAFE_USAGE_MESSAGES = frozenset(
    {
        "question must not be empty",
        "refresh target metadata exceeds supported producer limits",
        "search limit must be between 1 and 10",
    }
)
_SAFE_CONFIGURATION_MESSAGES = frozenset(
    {
        "an agent model is required; pass --model MODEL or set BUNDLEWALKER_MODEL",
    }
)
_SAFE_CHANGE_MESSAGES = frozenset(
    {
        "change set source_sha256 does not match the raw source",
    }
)
_SAFE_AGENT_MESSAGES = frozenset(
    {
        "query answer citations cannot include raw line spans",
    }
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
    WORKSPACE_INCOMPATIBLE = "workspace_incompatible"
    BACKUP_INVALID = "backup_invalid"
    BACKUP_FAILED = "backup_failed"
    RESTORE_TARGET_INVALID = "restore_target_invalid"
    MIGRATION_UNAVAILABLE = "migration_unavailable"
    MIGRATION_FAILED = "migration_failed"
    DIAGNOSTIC_FAILED = "diagnostic_failed"


@dataclass(frozen=True, slots=True)
class ApplicationError(Exception):
    """A public, serializable failure without provider or filesystem detail."""

    code: ApplicationErrorCode
    safe_message: str
    retryable: bool = False
    review_id: str | None = None
    backup_archive_path: str | None = None
    backup_archive_sha256: str | None = None

    def __str__(self) -> str:
        return self.safe_message


def translate_error(error: BundleWalkerError) -> ApplicationError:
    """Map bounded core failures to the one public error vocabulary."""
    if isinstance(error, ReviewPendingError):
        review_id = error.review_id if _REVIEW_ID.fullmatch(error.review_id) is not None else None
        return ApplicationError(
            ApplicationErrorCode.REVIEW_PENDING,
            (
                f"workspace already has a pending review: {review_id}"
                if review_id is not None
                else "workspace already has a pending review"
            ),
            review_id=review_id,
        )
    if isinstance(error, ReviewNotFoundError):
        return ApplicationError(
            ApplicationErrorCode.REVIEW_NOT_FOUND,
            "review was not found",
        )
    if isinstance(error, ReviewMismatchError):
        return ApplicationError(
            ApplicationErrorCode.REVIEW_ID_MISMATCH,
            "review ID does not match the pending review",
        )
    if isinstance(error, ReviewStaleError):
        return ApplicationError(
            ApplicationErrorCode.REVIEW_STALE,
            "review is stale",
        )
    if isinstance(error, MigrationExecutionError):
        backup = error.backup
        return ApplicationError(
            ApplicationErrorCode.MIGRATION_FAILED,
            "workspace migration failed; restore the verified pre-upgrade backup",
            backup_archive_path=str(backup.archive_path) if backup is not None else None,
            backup_archive_sha256=backup.archive_sha256 if backup is not None else None,
        )
    if isinstance(error, MigrationUnavailableError):
        return ApplicationError(
            ApplicationErrorCode.MIGRATION_UNAVAILABLE,
            "no complete workspace migration path is available",
        )
    if isinstance(error, RestoreTargetError):
        return ApplicationError(
            ApplicationErrorCode.RESTORE_TARGET_INVALID,
            "restore target must be a new or empty directory",
        )
    if isinstance(error, BackupVerificationError):
        return ApplicationError(
            ApplicationErrorCode.BACKUP_INVALID,
            "backup archive verification failed",
        )
    if isinstance(error, BackupError):
        return ApplicationError(
            ApplicationErrorCode.BACKUP_FAILED,
            "workspace backup or restore failed",
        )
    if isinstance(error, WorkspaceCompatibilityError):
        return ApplicationError(
            ApplicationErrorCode.WORKSPACE_INCOMPATIBLE,
            "workspace format is not supported for this operation",
        )
    if isinstance(error, ConfigurationError):
        return ApplicationError(
            ApplicationErrorCode.CONFIGURATION_ERROR,
            _exact_message_or_fallback(
                error,
                _SAFE_CONFIGURATION_MESSAGES,
                "workspace configuration is invalid",
            ),
        )
    if isinstance(error, UsageError):
        return ApplicationError(
            ApplicationErrorCode.INVALID_INPUT,
            _safe_usage_message(error),
        )
    if isinstance(error, WorkspaceError):
        return ApplicationError(
            ApplicationErrorCode.WORKSPACE_ERROR,
            "workspace operation failed",
        )
    if isinstance(error, OkfError):
        return ApplicationError(
            ApplicationErrorCode.OKF_ERROR,
            "knowledge bundle operation failed",
        )
    if isinstance(error, ChangeSetError):
        return ApplicationError(
            ApplicationErrorCode.CHANGE_INVALID,
            _exact_message_or_fallback(
                error,
                _SAFE_CHANGE_MESSAGES,
                "proposed change is invalid",
            ),
        )
    if isinstance(error, AgentRunError):
        return ApplicationError(
            ApplicationErrorCode.MODEL_FAILED,
            _safe_agent_message(error),
            retryable=True,
        )
    if isinstance(error, TransactionError):
        return ApplicationError(
            ApplicationErrorCode.TRANSACTION_FAILED,
            "transaction operation failed",
        )
    return ApplicationError(
        ApplicationErrorCode.WORKSPACE_ERROR,
        "BundleWalker operation failed",
    )


def _safe_usage_message(error: UsageError) -> str:
    message = str(error)
    if message in _SAFE_USAGE_MESSAGES:
        return message
    if message.startswith("refresh target must be a canonical Synthesis concept ID "):
        return "refresh target must be a canonical Synthesis concept ID"
    if message.startswith("refresh target does not exist:"):
        return "refresh target does not exist"
    if message.startswith("refresh target is not a Synthesis:"):
        return "refresh target is not a Synthesis"
    return "invalid input"


def _safe_agent_message(error: AgentRunError) -> str:
    message = str(error)
    if message in _SAFE_AGENT_MESSAGES:
        return message
    return "model-backed operation failed"


def _exact_message_or_fallback(
    error: BundleWalkerError,
    allowed: frozenset[str],
    fallback: str,
) -> str:
    message = str(error)
    if message in allowed:
        return message
    return fallback
