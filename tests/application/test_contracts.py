from collections.abc import Callable
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


def _pending_error_with_message(message: str) -> ReviewPendingError:
    error = ReviewPendingError("a" * 32)
    error.args = (message,)
    return error


_REVIEW_ERROR_CASES: tuple[tuple[Callable[[str], BundleWalkerError], str], ...] = (
    (_pending_error_with_message, "workspace already has a pending review"),
    (ReviewNotFoundError, "review was not found"),
    (ReviewMismatchError, "review ID does not match the pending review"),
    (ReviewStaleError, "review is stale"),
)


@pytest.mark.parametrize(
    "message",
    ["could not read /tmp/private-source.md", "unsafe\x00message"],
)
@pytest.mark.parametrize(
    ("error_factory", "fallback"),
    _REVIEW_ERROR_CASES,
)
def test_review_errors_redact_unsafe_messages(
    error_factory: Callable[[str], BundleWalkerError], fallback: str, message: str
) -> None:
    mapped = translate_error(error_factory(message))

    assert mapped.safe_message == fallback
    assert "/tmp" not in mapped.safe_message
    assert "\x00" not in mapped.safe_message


def test_review_pending_error_retains_typed_review_id_after_message_redaction() -> None:
    mapped = translate_error(_pending_error_with_message("token=private-token"))

    assert mapped.code is ApplicationErrorCode.REVIEW_PENDING
    assert mapped.review_id == "a" * 32
    assert "private-token" not in mapped.safe_message


@pytest.mark.parametrize(
    "message",
    [
        "path=/tmp/private-source.md",
        r"path=C:\\Users\\private-source.md",
        "path=~/private-source.md",
        "path=file:///tmp/private-source.md",
        "token=private-token",
        "api_key=private-key",
        "Authorization: Bearer private-token",
        '{"token":"private-token","choices":[{"message":"provider output"}]}',
    ],
)
def test_translate_error_redacts_embedded_paths_credentials_and_provider_payloads(
    message: str,
) -> None:
    mapped = translate_error(AgentRunError(message))

    assert mapped.safe_message == "model-backed operation failed"
    assert all(
        unsafe not in mapped.safe_message
        for unsafe in ("/tmp", "C:\\Users", "private", "token", "api_key", "Bearer", "choices")
    )


@pytest.mark.parametrize(
    "message",
    [
        "location=/tmp/private-source.md",
        r"destination=C:\\Users\\private-source.md",
        "label=~/private-source.md",
        "reference=file:///tmp/private-source.md",
    ],
)
def test_translate_error_redacts_path_values_after_arbitrary_labels(message: str) -> None:
    mapped = translate_error(WorkspaceError(message))

    assert mapped.safe_message == "workspace operation failed"
    assert "private-source" not in mapped.safe_message


@pytest.mark.parametrize(
    "message",
    [
        "location:/tmp/private-source.md",
        r"destination:C:\\Users\\private-source.md",
        "label:~/private-source.md",
        "reference:file:///tmp/private-source.md",
    ],
)
def test_translate_error_redacts_colon_delimited_path_values(message: str) -> None:
    mapped = translate_error(WorkspaceError(message))

    assert mapped.safe_message == "workspace operation failed"
    assert "private-source" not in mapped.safe_message


@pytest.mark.parametrize(
    "message",
    [
        "api key=private-key",
        "api-key=private-key",
        "access token=private-token",
        "authorization=private-token",
        "password: private-password",
        "credential=private-credential",
    ],
)
def test_translate_error_redacts_normalized_credential_markers(message: str) -> None:
    mapped = translate_error(AgentRunError(message))

    assert mapped.safe_message == "model-backed operation failed"
    assert "private" not in mapped.safe_message


@pytest.mark.parametrize(
    "message",
    [
        'provider error: {"response": {"id": "private"}}',
        'provider error: ["private", "payload"]',
    ],
)
def test_translate_error_redacts_payload_fragments_embedded_in_prose(message: str) -> None:
    mapped = translate_error(AgentRunError(message))

    assert mapped.safe_message == "model-backed operation failed"
    assert "private" not in mapped.safe_message


@pytest.mark.parametrize(
    "message",
    [
        "provider output: [12345, 67890]",
        "provider output: [true, false, null]",
    ],
)
def test_translate_error_redacts_scalar_array_fragments_embedded_in_prose(message: str) -> None:
    mapped = translate_error(AgentRunError(message))

    assert mapped.safe_message == "model-backed operation failed"
    assert "provider output" not in mapped.safe_message


def test_translate_error_uses_closed_fallback_for_unknown_core_error() -> None:
    mapped = translate_error(BundleWalkerError("provider secret"))

    assert mapped.code is ApplicationErrorCode.WORKSPACE_ERROR
    assert mapped.safe_message == "BundleWalker operation failed"
