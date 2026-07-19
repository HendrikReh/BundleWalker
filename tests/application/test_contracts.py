# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bundlewalker.application import (
    DIAGNOSTIC_CHECK_CATALOG,
    BackupResult,
    CompatibilityResult,
    DiagnosticCategory,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticSeverity,
    RestoreResult,
    SupportReport,
    UpgradeResult,
)
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
from bundlewalker.backups import (
    ARCHIVE_FORMAT,
    ARCHIVE_SCHEMA_VERSION,
    BackupManifest,
    VerifiedBackup,
)
from bundlewalker.compatibility import CompatibilityStatus
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
from bundlewalker.transactions import ReviewKind, ReviewStatus


def _diagnostic_checks(
    overrides: dict[str, DiagnosticSeverity] | None = None,
) -> tuple[DiagnosticCheck, ...]:
    selected = overrides or {}
    return tuple(
        DiagnosticCheck(
            code=code,
            category=category,
            severity=selected.get(code, DiagnosticSeverity.PASS),
            summary=f"Safe summary for {code}.",
            remediation=(),
        )
        for code, category in DIAGNOSTIC_CHECK_CATALOG
    )


def test_diagnostic_result_requires_exact_catalog_counts_and_overall_severity() -> None:
    checks = _diagnostic_checks(
        {
            "configuration.model": DiagnosticSeverity.WARNING,
            "workspace.permissions": DiagnosticSeverity.FAILURE,
        }
    )

    result = DiagnosticResult(
        overall=DiagnosticSeverity.FAILURE,
        bundlewalker_version="0.4.0a2",
        python_version="3.13.5",
        platform="linux",
        counts=DiagnosticCounts(passed=12, warnings=1, failures=1),
        checks=checks,
    )

    assert tuple(check.code for check in result.checks) == tuple(
        code for code, _category in DIAGNOSTIC_CHECK_CATALOG
    )
    assert result.counts == DiagnosticCounts(passed=12, warnings=1, failures=1)
    assert result.overall is DiagnosticSeverity.FAILURE


@pytest.mark.parametrize(
    ("counts", "overall"),
    [
        (DiagnosticCounts(passed=14, warnings=0, failures=0), DiagnosticSeverity.WARNING),
        (DiagnosticCounts(passed=13, warnings=1, failures=0), DiagnosticSeverity.PASS),
        (DiagnosticCounts(passed=13, warnings=0, failures=1), DiagnosticSeverity.WARNING),
    ],
)
def test_diagnostic_result_rejects_inconsistent_summary(
    counts: DiagnosticCounts,
    overall: DiagnosticSeverity,
) -> None:
    overrides = (
        {"configuration.model": DiagnosticSeverity.WARNING}
        if counts.warnings
        else {"workspace.permissions": DiagnosticSeverity.FAILURE}
        if counts.failures
        else {}
    )

    with pytest.raises(ValidationError):
        DiagnosticResult(
            overall=overall,
            bundlewalker_version="0.4.0a2",
            python_version="3.13.5",
            platform="linux",
            counts=counts,
            checks=_diagnostic_checks(overrides),
        )


def test_diagnostic_result_rejects_missing_reordered_and_wrong_category_checks() -> None:
    checks = list(_diagnostic_checks())
    missing = tuple(checks[:-1])
    reordered = tuple([checks[1], checks[0], *checks[2:]])
    wrong_category = tuple(
        [
            checks[0].model_copy(update={"category": DiagnosticCategory.STORAGE}),
            *checks[1:],
        ]
    )

    for candidate in (missing, reordered, wrong_category):
        with pytest.raises(ValidationError):
            DiagnosticResult(
                overall=DiagnosticSeverity.PASS,
                bundlewalker_version="0.4.0a2",
                python_version="3.13.5",
                platform="linux",
                counts=DiagnosticCounts(passed=len(candidate), warnings=0, failures=0),
                checks=candidate,
            )


def test_support_report_round_trips_and_forbids_extra_fields() -> None:
    result = DiagnosticResult(
        overall=DiagnosticSeverity.PASS,
        bundlewalker_version="0.4.0a2",
        python_version="3.13.5",
        platform="linux",
        counts=DiagnosticCounts(passed=14, warnings=0, failures=0),
        checks=_diagnostic_checks(),
    )
    report = SupportReport(
        generated_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        result=result,
    )

    assert report.schema_version == 1
    assert SupportReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        SupportReport.model_validate({**report.model_dump(), "workspace_path": "/private"})


@pytest.mark.parametrize("value", ["line\nbreak", "tab\tvalue", "control\x00value"])
def test_diagnostic_text_rejects_control_characters(value: str) -> None:
    with pytest.raises(ValidationError):
        DiagnosticCheck(
            code="runtime.python",
            category=DiagnosticCategory.RUNTIME,
            severity=DiagnosticSeverity.PASS,
            summary=value,
            remediation=(),
        )


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
def test_inline_source_rejects_values_beyond_its_contract(field: str, value: str) -> None:
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
    payload: dict[str, object],
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
            "workspace configuration is invalid",
            False,
        ),
        (UsageError("bad request"), ApplicationErrorCode.INVALID_INPUT, "invalid input", False),
        (
            OkfError("bad bundle"),
            ApplicationErrorCode.OKF_ERROR,
            "knowledge bundle operation failed",
            False,
        ),
        (
            ChangeSetError("bad change"),
            ApplicationErrorCode.CHANGE_INVALID,
            "proposed change is invalid",
            False,
        ),
        (
            AgentRunError("provider timed out"),
            ApplicationErrorCode.MODEL_FAILED,
            "model-backed operation failed",
            True,
        ),
        (
            ReviewNotFoundError("review missing"),
            ApplicationErrorCode.REVIEW_NOT_FOUND,
            "review was not found",
            False,
        ),
        (
            ReviewMismatchError("review mismatch"),
            ApplicationErrorCode.REVIEW_ID_MISMATCH,
            "review ID does not match the pending review",
            False,
        ),
        (
            ReviewStaleError("review stale"),
            ApplicationErrorCode.REVIEW_STALE,
            "review is stale",
            False,
        ),
        (
            TransactionError("transaction failed"),
            ApplicationErrorCode.TRANSACTION_FAILED,
            "transaction operation failed",
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
    (
        _pending_error_with_message,
        "workspace already has a pending review: " + "a" * 32,
    ),
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


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            TransactionError("could not create raw source: raw/deadbeef-private-name.txt"),
            "transaction operation failed",
        ),
        (
            WorkspaceError("could not read wiki/topics/private-topic.md"),
            "workspace operation failed",
        ),
        (
            TransactionError("journal failure at .bundlewalker/transactions/private/manifest.json"),
            "transaction operation failed",
        ),
        (
            AgentRunError("token private-token"),
            "model-backed operation failed",
        ),
        (
            AgentRunError("provider response: private prompt contents"),
            "model-backed operation failed",
        ),
        (
            AgentRunError("upstream returned non-JSON body: private plaintext payload"),
            "model-backed operation failed",
        ),
    ],
)
def test_translate_error_never_relays_relative_paths_credentials_or_provider_prose(
    error: BundleWalkerError,
    expected: str,
) -> None:
    mapped = translate_error(error)

    assert mapped.safe_message == expected
    assert all(
        private not in mapped.safe_message
        for private in ("raw/", "wiki/", ".bundlewalker", "private", "provider", "upstream")
    )


def test_translate_error_uses_closed_fallback_for_unknown_core_error() -> None:
    mapped = translate_error(BundleWalkerError("provider secret"))

    assert mapped.code is ApplicationErrorCode.WORKSPACE_ERROR
    assert mapped.safe_message == "BundleWalker operation failed"


def test_lifecycle_result_contracts_are_strict_and_json_round_trip() -> None:
    backup = BackupResult(
        archive_path="/tmp/knowledge.zip",
        archive_sha256="a" * 64,
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        workspace_format=1,
        file_count=4,
        byte_count=100,
    )
    results = (
        CompatibilityResult(
            installed_version="0.4.0a1",
            workspace_path="/tmp/knowledge",
            workspace_format=1,
            compatibility=CompatibilityStatus.CURRENT,
            readable=True,
            writable=True,
            upgrade_available=False,
        ),
        backup,
        RestoreResult(
            target_path="/tmp/restored",
            archive_sha256="a" * 64,
            workspace_format=1,
            file_count=4,
            byte_count=100,
        ),
        UpgradeResult(
            status="upgraded",
            workspace_path="/tmp/knowledge",
            source_version=1,
            target_version=2,
            backup=backup,
        ),
    )

    for result in results:
        assert type(result).model_validate_json(result.model_dump_json()) == result
        with pytest.raises(ValidationError):
            type(result).model_validate({**result.model_dump(), "private": "not public"})


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            WorkspaceCompatibilityError("too_new"),
            ApplicationErrorCode.WORKSPACE_INCOMPATIBLE,
            "workspace format is not supported for this operation",
        ),
        (
            BackupVerificationError("archive contains token=private"),
            ApplicationErrorCode.BACKUP_INVALID,
            "backup archive verification failed",
        ),
        (
            BackupError("could not read /tmp/private"),
            ApplicationErrorCode.BACKUP_FAILED,
            "workspace backup or restore failed",
        ),
        (
            RestoreTargetError("target /tmp/private is occupied"),
            ApplicationErrorCode.RESTORE_TARGET_INVALID,
            "restore target must be a new or empty directory",
        ),
        (
            MigrationUnavailableError("private migration details"),
            ApplicationErrorCode.MIGRATION_UNAVAILABLE,
            "no complete workspace migration path is available",
        ),
    ],
)
def test_translate_error_maps_lifecycle_errors_without_raw_details(
    error: BundleWalkerError,
    code: ApplicationErrorCode,
    message: str,
) -> None:
    mapped = translate_error(error)

    assert mapped.code is code
    assert mapped.safe_message == message
    assert "private" not in mapped.safe_message
    assert mapped.backup_archive_path is None
    assert mapped.backup_archive_sha256 is None


def test_translate_migration_failure_retains_only_verified_backup_identity() -> None:
    manifest = BackupManifest(
        archive_format=ARCHIVE_FORMAT,
        schema_version=ARCHIVE_SCHEMA_VERSION,
        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        bundlewalker_version="0.4.0a1",
        workspace_format_version=1,
        directories=(),
        files=(),
    )
    backup = VerifiedBackup(Path("pre-upgrade.zip"), "a" * 64, manifest)

    mapped = translate_error(MigrationExecutionError("token=private-cause", backup=backup))

    assert mapped.code is ApplicationErrorCode.MIGRATION_FAILED
    assert mapped.safe_message == (
        "workspace migration failed; restore the verified pre-upgrade backup"
    )
    assert mapped.backup_archive_path == "pre-upgrade.zip"
    assert mapped.backup_archive_sha256 == "a" * 64
    assert "private-cause" not in mapped.safe_message
