from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bundlewalker.application.contracts import (
    MAX_INLINE_SOURCE_CHARACTERS,
    MAX_SOURCE_NAME_CHARACTERS,
    IngestionResult,
    InlineSource,
    MutationResult,
    RefreshResult,
    ReviewResult,
)
from bundlewalker.application.errors import (
    ApplicationErrorCode,
    translate_error,
)
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
from bundlewalker.transactions import ReviewKind, ReviewStatus


def _review_payload() -> dict[str, object]:
    return {
        "review_id": "a" * 32,
        "kind": ReviewKind.INGESTION,
        "status": ReviewStatus.PENDING,
        "summary": "Proposed ingestion",
        "diff": "diff --git a/notes.md b/notes.md",
        "changed_paths": ("notes.md",),
        "created_at": datetime(2026, 7, 17, tzinfo=UTC),
        "resource_uri": "bundlewalker://reviews/" + "a" * 32,
    }


def test_inline_source_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        InlineSource.model_validate(
            {"source_name": "notes.md", "content": "text\n", "path": "/tmp/notes.md"}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_name", ""),
        ("source_name", "n" * (MAX_SOURCE_NAME_CHARACTERS + 1)),
        ("content", "c" * (MAX_INLINE_SOURCE_CHARACTERS + 1)),
    ],
)
def test_inline_source_rejects_values_beyond_its_contract(
    field: str, value: str
) -> None:
    payload = {"source_name": "notes.md", "content": "text\n"}
    payload[field] = value

    with pytest.raises(ValidationError):
        InlineSource.model_validate(payload)


def test_review_result_forbids_extra_fields() -> None:
    payload = _review_payload()
    payload["workspace_path"] = "/private/workspace"

    with pytest.raises(ValidationError):
        ReviewResult.model_validate(payload)


@pytest.mark.parametrize(
    "status, review",
    [
        ("duplicate", None),
        ("pending", _review_payload()),
    ],
)
def test_ingestion_result_accepts_exact_status_review_combinations(
    status: str, review: dict[str, object] | None
) -> None:
    result = IngestionResult.model_validate({"status": status, "review": review})

    assert result.status == status
    assert (result.review is not None) is (status == "pending")


@pytest.mark.parametrize(
    "status, review",
    [
        ("current", None),
        ("pending", _review_payload()),
    ],
)
def test_refresh_result_accepts_exact_status_review_combinations(
    status: str, review: dict[str, object] | None
) -> None:
    result = RefreshResult.model_validate(
        {
            "status": status,
            "concept_id": "concept-id",
            "answer": {
                "answer": {"title": "Answer", "body": "Body", "citations": []},
                "markdown": "# Answer\n",
            },
            "review": review,
        }
    )

    assert result.status == status
    assert (result.review is not None) is (status == "pending")


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "pending", "review": None},
        {"status": "duplicate", "review": _review_payload()},
    ],
)
def test_ingestion_result_rejects_invalid_status_review_combinations(
    payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        IngestionResult.model_validate(payload)


@pytest.mark.parametrize(
    "status, review",
    [
        ("pending", None),
        ("current", _review_payload()),
    ],
)
def test_refresh_result_rejects_invalid_status_review_combinations(
    status: str, review: dict[str, object] | None
) -> None:
    with pytest.raises(ValidationError):
        RefreshResult.model_validate(
            {
                "status": status,
                "concept_id": "concept-id",
                "answer": {
                    "answer": {"title": "Answer", "body": "Body", "citations": []},
                    "markdown": "# Answer\n",
                },
                "review": review,
            }
        )


@pytest.mark.parametrize("status", ["applied", "discarded"])
def test_mutation_result_accepts_exact_status_discriminator(status: str) -> None:
    result = MutationResult.model_validate({"review_id": "a" * 32, "status": status})

    assert result.status == status


def test_mutation_result_rejects_unknown_status_discriminator() -> None:
    with pytest.raises(ValidationError):
        MutationResult.model_validate({"review_id": "a" * 32, "status": "deleted"})


def test_review_pending_error_maps_without_parsing_message() -> None:
    mapped = translate_error(ReviewPendingError("a" * 32))

    assert mapped.code is ApplicationErrorCode.REVIEW_PENDING
    assert mapped.review_id == "a" * 32
    assert mapped.retryable is False
    assert "a" * 32 in mapped.safe_message


def test_application_error_redacts_absolute_paths() -> None:
    mapped = translate_error(WorkspaceError("could not read /tmp/private-source.md"))

    assert mapped.safe_message == "workspace operation failed"
    assert "/tmp" not in mapped.safe_message


@pytest.mark.parametrize(
    ("error", "code", "message", "retryable"),
    [
        (
            ConfigurationError("bad configuration"),
            ApplicationErrorCode.CONFIGURATION_ERROR,
            "bad configuration",
            False,
        ),
        (UsageError("bad request"), ApplicationErrorCode.INVALID_INPUT, "bad request", False),
        (OkfError("bad bundle"), ApplicationErrorCode.OKF_ERROR, "bad bundle", False),
        (ChangeSetError("bad change"), ApplicationErrorCode.CHANGE_INVALID, "bad change", False),
        (
            AgentRunError("provider timed out"),
            ApplicationErrorCode.MODEL_FAILED,
            "provider timed out",
            True,
        ),
        (
            ReviewNotFoundError("review missing"),
            ApplicationErrorCode.REVIEW_NOT_FOUND,
            "review missing",
            False,
        ),
        (
            ReviewMismatchError("review mismatch"),
            ApplicationErrorCode.REVIEW_ID_MISMATCH,
            "review mismatch",
            False,
        ),
        (
            ReviewStaleError("review stale"),
            ApplicationErrorCode.REVIEW_STALE,
            "review stale",
            False,
        ),
        (
            TransactionError("transaction failed"),
            ApplicationErrorCode.TRANSACTION_FAILED,
            "transaction failed",
            False,
        ),
    ],
)
def test_translate_error_maps_each_known_error(
    error: BundleWalkerError,
    code: ApplicationErrorCode,
    message: str,
    retryable: bool,
) -> None:
    mapped = translate_error(error)

    assert (mapped.code, mapped.safe_message, mapped.retryable) == (code, message, retryable)


@pytest.mark.parametrize(
    "message",
    [
        "",
        "x" * 1_025,
        "unsafe\x00message",
        "read ~/private-source.md",
        "read file:private-source.md",
    ],
)
def test_translate_error_redacts_unsafe_messages(message: str) -> None:
    mapped = translate_error(WorkspaceError(message))

    assert mapped.safe_message == "workspace operation failed"


def test_translate_error_uses_closed_fallback_for_unknown_core_error() -> None:
    mapped = translate_error(BundleWalkerError("provider secret"))

    assert mapped.code is ApplicationErrorCode.WORKSPACE_ERROR
    assert mapped.safe_message == "BundleWalker operation failed"
