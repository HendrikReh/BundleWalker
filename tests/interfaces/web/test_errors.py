# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Complete and bounded web error mapping tests."""

import logging

import pytest

from bundlewalker.application import ApplicationError, ApplicationErrorCode
from bundlewalker.interfaces.web.errors import (
    APPLICATION_ERROR_STATUS,
    map_application_error,
    map_unexpected_exception,
)

EXPECTED_STATUS = {
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


def test_application_error_status_map_covers_the_complete_enum() -> None:
    assert APPLICATION_ERROR_STATUS == EXPECTED_STATUS
    assert set(APPLICATION_ERROR_STATUS) == set(ApplicationErrorCode)


@pytest.mark.parametrize(("code", "expected_status"), EXPECTED_STATUS.items())
def test_application_errors_map_to_bounded_json(
    code: ApplicationErrorCode,
    expected_status: int,
) -> None:
    error = ApplicationError(
        code=code,
        safe_message="review is stale",
        retryable=False,
    )

    status, response = map_application_error(error)

    assert status == expected_status
    assert response.model_dump(mode="json") == {
        "error": {
            "code": code.value,
            "message": "review is stale",
            "retryable": False,
            "review_id": None,
            "diagnostic_id": None,
        }
    }


def test_application_error_retains_only_the_bounded_review_id() -> None:
    status, response = map_application_error(
        ApplicationError(
            ApplicationErrorCode.REVIEW_PENDING,
            "workspace already has a pending review",
            review_id="a" * 32,
            backup_archive_path="/Users/private/workspace.zip",
            backup_archive_sha256="b" * 64,
        )
    )

    assert status == 409
    assert response.error.review_id == "a" * 32
    serialized = response.model_dump_json()
    assert "workspace.zip" not in serialized
    assert "backup_archive" not in serialized


def test_unexpected_exception_is_logged_but_response_is_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private = "provider returned source secret at /Users/private/workspace/raw/source.md"

    with caplog.at_level(logging.ERROR):
        status, response = map_unexpected_exception(RuntimeError(private))

    assert status == 500
    assert response.error.code == "internal_error"
    assert response.error.message == "An unexpected error occurred"
    assert response.error.retryable is False
    assert response.error.review_id is None
    assert response.error.diagnostic_id is not None
    assert len(response.error.diagnostic_id) == 32
    assert private in caplog.text
    serialized = response.model_dump_json()
    for fragment in ("provider", "source secret", "/Users/", "RuntimeError"):
        assert fragment not in serialized
