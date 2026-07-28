# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contract tests for the local web interface DTO boundary."""

from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from bundlewalker.application import (
    MAX_INLINE_SOURCE_CHARACTERS,
    MAX_QUESTION_CHARACTERS,
    AnswerResult,
    ConceptContent,
    ConceptPage,
    ConceptSearchResult,
    ConceptSummaryResult,
    IngestionResult,
    LintResult,
    MutationResult,
    PendingReviewSummary,
    RefreshResult,
    ReviewResult,
    SynthesisResult,
    WorkspaceStatus,
)
from bundlewalker.domain import Citation, CitedAnswer, FindingOrigin, LintFinding, Severity
from bundlewalker.interfaces.mcp_schemas import MAX_MODEL_NAME_CHARACTERS
from bundlewalker.interfaces.web.contracts import (
    MAX_WEB_MODEL_NAME_CHARACTERS,
    MAX_WEB_REQUEST_BYTES,
    MAX_WEB_SOURCE_BYTES,
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
from bundlewalker.transactions import ReviewKind, ReviewStatus

REVIEW_ID = "a" * 32
CREATED_AT = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _review() -> ReviewResult:
    return ReviewResult(
        review_id=REVIEW_ID,
        kind=ReviewKind.INGESTION,
        status=ReviewStatus.PENDING,
        summary="Add agent notes",
        diff="diff --git a/topics/agents.md b/topics/agents.md\n",
        changed_paths=("topics/agents.md",),
        created_at=CREATED_AT,
        resource_uri="bundlewalker://review/pending",
    )


def _answer() -> AnswerResult:
    return AnswerResult(
        answer=CitedAnswer(
            title="Agent tools",
            body="Agents can use tools.",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        markdown="# Agent tools\n\nAgents can use tools. [1]\n",
    )


def _summary() -> ConceptSummaryResult:
    return ConceptSummaryResult(
        concept_id="topics/agents",
        type="Topic",
        title="Agents",
        description="How agents work.",
        tags=("agents",),
        resource_uri="bundlewalker://concept/topics/agents",
    )


def test_workspace_response_contains_safe_status_and_csrf() -> None:
    status = WorkspaceStatus(
        display_name="knowledge",
        config_version=3,
        concept_counts={"Topic": 1},
        pending_review=None,
    )

    response = to_web_workspace(status, csrf_token="csrf")

    assert response.csrf_token == "csrf"
    assert response.pending_review is None
    assert response.model_dump(mode="json") == {
        "display_name": "knowledge",
        "config_version": 3,
        "concept_counts": {"Topic": 1},
        "pending_review": None,
        "csrf_token": "csrf",
    }
    assert "workspace_path" not in response.model_dump()
    assert "session_id" not in response.model_dump()


@pytest.mark.parametrize(
    "summary",
    [
        "Review /Users/private/workspace/wiki/topics/agents.md",
        r"Review C:\Users\private\workspace\wiki\topics\agents.md",
        r"Review \\server\share\workspace\wiki\topics\agents.md",
        "Review path:/etc/passwd",
    ],
)
def test_workspace_response_rejects_paths_in_pending_review_summary(
    summary: str,
) -> None:
    status = WorkspaceStatus(
        display_name="knowledge",
        config_version=3,
        concept_counts={"Topic": 1},
        pending_review=PendingReviewSummary(
            review_id=REVIEW_ID,
            kind=ReviewKind.INGESTION,
            status=ReviewStatus.PENDING,
            summary=summary,
        ),
    )

    with pytest.raises(ValueError, match="absolute"):
        to_web_workspace(status, csrf_token="csrf")


@pytest.mark.parametrize(
    "encoded_path",
    [
        "path:%25%32%66etc/passwd",
        "PaTh:%25%32%46etc/passwd",
        r"path:%25%35%63Users\private",
        "PATH:%25%35%43Users%255cprivate",
    ],
)
def test_workspace_response_rejects_recursively_encoded_path_schemes(
    encoded_path: str,
) -> None:
    status = WorkspaceStatus(
        display_name="knowledge",
        config_version=3,
        concept_counts={"Topic": 1},
        pending_review=PendingReviewSummary(
            review_id=REVIEW_ID,
            kind=ReviewKind.INGESTION,
            status=ReviewStatus.PENDING,
            summary=f"Review {encoded_path}",
        ),
    )

    with pytest.raises(ValueError, match="absolute"):
        to_web_workspace(status, csrf_token="csrf")


@pytest.mark.parametrize(
    "summary",
    [
        "Review https://example.com/guides/agents?view=full#citations",
        "Review [external guide](http://example.com/guides/agents)",
    ],
)
def test_workspace_response_preserves_safe_http_urls_in_pending_review_summary(
    summary: str,
) -> None:
    status = WorkspaceStatus(
        display_name="knowledge",
        config_version=3,
        concept_counts={"Topic": 1},
        pending_review=PendingReviewSummary(
            review_id=REVIEW_ID,
            kind=ReviewKind.INGESTION,
            status=ReviewStatus.PENDING,
            summary=summary,
        ),
    )

    response = to_web_workspace(status, csrf_token="csrf")

    assert response.pending_review is not None
    assert response.pending_review.summary == summary


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (WebAskRequest, {"question": "Why?", "unexpected": True}),
        (WebLintRequest, {"semantic": False, "unexpected": True}),
        (
            WebIngestionRequest,
            {"source_name": "notes.md", "content": "Notes", "unexpected": True},
        ),
        (WebSynthesisRequest, {"question": "Why?", "unexpected": True}),
        (
            WebRefreshRequest,
            {
                "instruction": "Refresh this",
                "concept_id": "syntheses/agents",
                "unexpected": True,
            },
        ),
    ],
)
def test_request_contracts_reject_unknown_fields(
    model: type[WebAskRequest]
    | type[WebLintRequest]
    | type[WebIngestionRequest]
    | type[WebSynthesisRequest]
    | type[WebRefreshRequest],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "field", "valid", "invalid"),
    [
        (
            WebAskRequest,
            "question",
            "q" * MAX_QUESTION_CHARACTERS,
            "q" * (MAX_QUESTION_CHARACTERS + 1),
        ),
        (
            WebSynthesisRequest,
            "question",
            "q" * MAX_QUESTION_CHARACTERS,
            "q" * (MAX_QUESTION_CHARACTERS + 1),
        ),
        (
            WebRefreshRequest,
            "instruction",
            "i" * MAX_QUESTION_CHARACTERS,
            "i" * (MAX_QUESTION_CHARACTERS + 1),
        ),
        (
            WebAskRequest,
            "model",
            "m" * MAX_MODEL_NAME_CHARACTERS,
            "m" * (MAX_MODEL_NAME_CHARACTERS + 1),
        ),
    ],
)
def test_request_limits_match_application_boundaries(
    model: type[WebAskRequest] | type[WebSynthesisRequest] | type[WebRefreshRequest],
    field: str,
    valid: str,
    invalid: str,
) -> None:
    base = (
        {"question": "Why?"}
        if model is not WebRefreshRequest
        else {"instruction": "Refresh", "concept_id": "syntheses/agents"}
    )
    assert model.model_validate({**base, field: valid})
    with pytest.raises(ValidationError):
        model.model_validate({**base, field: invalid})


def test_ingestion_rejects_source_over_character_or_utf8_byte_limit() -> None:
    assert MAX_WEB_SOURCE_BYTES == 4_000_000
    assert MAX_WEB_REQUEST_BYTES == 4_100_000
    assert WebIngestionRequest(
        source_name="notes.md",
        content="a" * MAX_INLINE_SOURCE_CHARACTERS,
    )

    with pytest.raises(ValidationError):
        WebIngestionRequest(
            source_name="notes.md",
            content="a" * (MAX_INLINE_SOURCE_CHARACTERS + 1),
        )

    byte_boundary = WebIngestionRequest(
        source_name="notes.md",
        content="😀" * MAX_INLINE_SOURCE_CHARACTERS,
    )
    assert len(byte_boundary.content.encode("utf-8")) == MAX_WEB_SOURCE_BYTES


@pytest.mark.parametrize("content", ["", " ", "\t\r\n"])
def test_ingestion_rejects_empty_or_whitespace_only_content(content: str) -> None:
    with pytest.raises(ValidationError, match="content"):
        WebIngestionRequest(source_name="notes.md", content=content)


@pytest.mark.parametrize(
    "source_name",
    [
        "notes",
        "notes.markdown",
        "notes.pdf",
        "notes.MD",
        ".md",
        ".txt",
        "folder/notes.md",
        r"folder\notes.md",
        "/tmp/notes.md",
        r"C:\temp\notes.md",
        "C:notes.md",
        ".",
        "..",
        "../notes.md",
        "..\\notes.md",
        "notes\nprivate.md",
        "notes\x00.md",
    ],
)
def test_ingestion_rejects_unsafe_or_unsupported_source_names(
    source_name: str,
) -> None:
    with pytest.raises(ValidationError, match="source_name"):
        WebIngestionRequest(source_name=source_name, content="Evidence.")


@pytest.mark.parametrize(
    "source_name",
    ["notes.md", "meeting notes.txt", "2026-07-26_agents.md", ".notes.md"],
)
def test_ingestion_accepts_safe_supported_source_names(source_name: str) -> None:
    request = WebIngestionRequest(source_name=source_name, content="Evidence.")

    assert request.source_name == source_name


def test_web_model_limit_matches_the_existing_adapter_contract() -> None:
    assert MAX_WEB_MODEL_NAME_CHARACTERS == MAX_MODEL_NAME_CHARACTERS


def test_review_mapper_omits_resource_uri_and_rejects_absolute_paths() -> None:
    response = to_web_review(_review())

    assert response.model_dump(mode="json") == {
        "review_id": REVIEW_ID,
        "kind": "ingestion",
        "status": "pending",
        "summary": "Add agent notes",
        "diff": "diff --git a/topics/agents.md b/topics/agents.md\n",
        "changed_paths": ["topics/agents.md"],
        "created_at": "2026-07-25T12:00:00Z",
    }
    assert "resource_uri" not in response.model_dump()

    unsafe = _review().model_copy(update={"changed_paths": ("/Users/private/notes.md",)})
    with pytest.raises(ValueError, match="relative"):
        to_web_review(unsafe)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary", "Review /Users/private/workspace/wiki/topics/agents.md"),
        ("summary", "Review /etc/passwd"),
        ("summary", "Review /workspace/wiki/topics/agents.md"),
        ("summary", "Review [Source](/sources/source-evidence.md)"),
        ("summary", "Review [Agents](/topics/agents.md)"),
        ("summary", r"Review C:\Users\private\workspace\wiki\topics\agents.md"),
        ("summary", r"Review \\server\share\workspace\wiki\topics\agents.md"),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- /Users/private/workspace/wiki/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ /etc/passwd\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ /workspace/wiki/topics/agents.md\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
                "+See /sources/source-evidence.md.\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
                "+[Source](/sources/../private.md)\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
                "+[Source](/sources/source-evidence.md\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
                "+[Source](/sources/source-evidence.txt)\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/syntheses/agents.md b/syntheses/agents.md\n"
                "--- a/syntheses/agents.md\n"
                "+++ b/syntheses/agents.md\n"
                "+See /topics/agents.md.\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/syntheses/agents.md b/syntheses/agents.md\n"
                "--- a/syntheses/agents.md\n"
                "+++ b/syntheses/agents.md\n"
                "+[Agents](/topics/agents.md\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                r"+++ C:\Users\private\workspace\wiki\topics\agents.md"
                "\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                r"+++ \\server\share\workspace\wiki\topics\agents.md"
                "\n"
            ),
        ),
    ],
)
def test_review_mapper_rejects_absolute_paths_in_summary_or_diff(
    field: str,
    value: str,
) -> None:
    unsafe = _review().model_copy(update={field: value})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(unsafe)


def test_review_mapper_preserves_valid_exact_diff_text() -> None:
    review = _review()

    response = to_web_review(review)

    assert response.diff == review.diff


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "summary",
            "Review https://example.com/guides/agents?view=full#citations.",
        ),
        (
            "summary",
            "Review [external guide](http://example.com/guides/agents).",
        ),
        (
            "summary",
            "Review data: updated agent evidence.",
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
                "+See https://example.com/guides/agents?view=full#citations.\n"
            ),
        ),
        (
            "diff",
            (
                "diff --git a/topics/agents.md b/topics/agents.md\n"
                "--- a/topics/agents.md\n"
                "+++ b/topics/agents.md\n"
                "+[External guide](http://example.com/guides/agents)\n"
            ),
        ),
    ],
)
def test_review_mapper_preserves_safe_http_urls_unchanged(
    field: str,
    value: str,
) -> None:
    review = _review().model_copy(update={field: value})

    response = to_web_review(review)

    assert getattr(response, field) == value


@pytest.mark.parametrize(
    "label",
    [
        "/Users/private/agents.md",
        r"C:\Users\private\agents.md",
        r"\\server\share\agents.md",
        "path:/etc/passwd",
    ],
)
def test_review_mapper_scans_visible_labels_of_safe_http_links(label: str) -> None:
    diff = (
        "diff --git a/topics/agents.md b/topics/agents.md\n"
        "--- a/topics/agents.md\n"
        "+++ b/topics/agents.md\n"
        f"+[{label}](https://example.com/guides/agents)\n"
    )
    review = _review().model_copy(update={"diff": diff})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(review)


def test_review_mapper_scans_text_surrounding_safe_http_links() -> None:
    diff = (
        "diff --git a/topics/agents.md b/topics/agents.md\n"
        "--- a/topics/agents.md\n"
        "+++ b/topics/agents.md\n"
        "+[External guide](https://example.com/guides/agents) copied from /etc/passwd\n"
    )
    review = _review().model_copy(update={"diff": diff})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(review)


@pytest.mark.parametrize(
    "encoded_path",
    [
        "path:%25%32%66etc/passwd",
        "PaTh:%25%32%46etc/passwd",
        r"path:%25%35%63Users\private",
        "PATH:%25%35%43Users%255cprivate",
    ],
)
@pytest.mark.parametrize("field", ["summary", "diff"])
def test_review_mapper_rejects_recursively_encoded_path_schemes(
    field: str,
    encoded_path: str,
) -> None:
    value = (
        f"Review {encoded_path}"
        if field == "summary"
        else (
            "diff --git a/topics/agents.md b/topics/agents.md\n"
            "--- a/topics/agents.md\n"
            "+++ b/topics/agents.md\n"
            f"+[Unsafe]({encoded_path})\n"
        )
    )
    review = _review().model_copy(update={field: value})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(review)


@pytest.mark.parametrize(
    "destination",
    [
        "file:/etc/passwd",
        "data:text/plain,/etc/passwd",
        "javascript:alert('/etc/passwd')",
        "ftp://example.com/etc/passwd",
        "path:/etc/passwd",
        "https://user:secret@example.com/guides/agents",
        "https://user%40example.com/guides/agents",
        "https://example.com/guides/../private",
        "https://example.com/%5CUsers%5Cprivate",
    ],
)
def test_review_mapper_rejects_unsafe_external_link_destinations(
    destination: str,
) -> None:
    diff = (
        "diff --git a/topics/agents.md b/topics/agents.md\n"
        "--- a/topics/agents.md\n"
        "+++ b/topics/agents.md\n"
        f"+[External guide]({destination})\n"
    )
    review = _review().model_copy(update={"diff": diff})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(review)


def test_review_mapper_preserves_safe_root_relative_source_citation_in_exact_diff() -> None:
    diff = (
        "diff --git a/topics/agents.md b/topics/agents.md\n"
        "--- a/topics/agents.md\n"
        "+++ b/topics/agents.md\n"
        "@@ -1,2 +1,4 @@\n"
        "+Claim supported by source [1].\n"
        "+[1] [Source](/sources/source-evidence.md) — raw lines 1\N{EN DASH}2\n"
    )
    review = _review().model_copy(update={"diff": diff})

    response = to_web_review(review)

    assert response.diff == diff


@pytest.mark.parametrize(
    "destination",
    [
        "/topics/agents.md",
        "/topics/agents/tools.md",
        "/entities/agent%20tools.md",
        "/syntheses/agent-tools.md#citations",
        "/topics/agents.md?view=full%20page",
    ],
)
def test_review_mapper_preserves_safe_root_relative_concept_links_in_exact_diff(
    destination: str,
) -> None:
    diff = (
        "diff --git a/syntheses/agents.md b/syntheses/agents.md\n"
        "--- a/syntheses/agents.md\n"
        "+++ b/syntheses/agents.md\n"
        f"+[1] [Agents]({destination})\n"
    )
    review = _review().model_copy(update={"diff": diff})

    response = to_web_review(review)

    assert response.diff == diff


@pytest.mark.parametrize(
    "destination",
    [
        "/Users/private/agents.md",
        "/home/private/agents.md",
        "/etc/passwd.md",
        "/var/log/agents.md",
        "/tmp/agents.md",
        "/private/agents.md",
        "/Volumes/private/agents.md",
        "/topics/../agents.md",
        "/topics/%2e%2e/agents.md",
        "/topics/%2E/agents.md",
        "/topics/%2Fetc.md",
        "/topics/%5cprivate.md",
        "/topics/%00private.md",
        "/topics/%252e%252e/agents.md",
        "/topics/%252Fetc.md",
        "/topics/%2525252Fetc.md",
        "/topics/%2525252525252525252Fetc.md",
        r"/topics\agents.md",
        "/topics/agent tools.md",
        "/topics//agents.md",
        "/topics/.md",
        "/unknown/agents.md",
        "/topics/agents%2.md",
        "/topics/agents%GG.md",
        "/topics/agents.md?next=/etc/passwd",
        "/topics/agents.md?next=%2525252Fetc/passwd",
        "/topics/agents.md#/%2e%2e/etc",
        "/topics/agents.md#%2525252e%2525252e%2525252Fetc",
        "file:///topics/agents.md",
        "file:/etc/passwd",
        "FILE:/etc/passwd",
        "FiLe:///etc/passwd",
        "file:%2fetc/passwd",
        "FILE:%252fetc/passwd",
    ],
)
def test_review_mapper_rejects_unsafe_internal_concept_link_destinations(
    destination: str,
) -> None:
    diff = (
        "diff --git a/syntheses/agents.md b/syntheses/agents.md\n"
        "--- a/syntheses/agents.md\n"
        "+++ b/syntheses/agents.md\n"
        f"+[Agents]({destination})\n"
    )
    review = _review().model_copy(update={"diff": diff})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(review)


@pytest.mark.parametrize(
    "label",
    [
        "/etc/passwd",
        r"C:\Users\private",
        r"\\server\share\secret",
    ],
)
def test_review_mapper_rejects_absolute_paths_in_safe_source_link_labels(
    label: str,
) -> None:
    diff = (
        "diff --git a/topics/agents.md b/topics/agents.md\n"
        "--- a/topics/agents.md\n"
        "+++ b/topics/agents.md\n"
        f"+[{label}](/sources/source-evidence.md)\n"
    )
    review = _review().model_copy(update={"diff": diff})

    with pytest.raises(ValueError, match="absolute"):
        to_web_review(review)


def test_review_mapper_preserves_arbitrary_non_path_source_link_label() -> None:
    diff = (
        "diff --git a/topics/agents.md b/topics/agents.md\n"
        "--- a/topics/agents.md\n"
        "+++ b/topics/agents.md\n"
        "+[Primary evidence: source #1](/sources/source-evidence.md)\n"
    )
    review = _review().model_copy(update={"diff": diff})

    response = to_web_review(review)

    assert response.diff == diff


@pytest.mark.parametrize(
    "changed_path",
    [
        r"topics\agents.md",
        "C:topics/agents.md",
        "C:/topics/agents.md",
        "/topics/agents.md",
        r"\topics\agents.md",
        r"\\server\share\agents.md",
        "topics/../agents.md",
        "topics/./agents.md",
        "topics//agents.md",
        "topics/agents.md\nprivate",
        "topics/\x00agents.md",
    ],
)
def test_review_mapper_rejects_noncanonical_relative_changed_paths(
    changed_path: str,
) -> None:
    review = _review().model_copy(update={"changed_paths": (changed_path,)})

    with pytest.raises(ValueError, match="relative"):
        to_web_review(review)


@pytest.mark.parametrize(
    "changed_path",
    [
        "topics/agents.md",
        "topics/agent notes.md",
        "nested/topics/agents-v2.md",
    ],
)
def test_review_mapper_preserves_safe_forward_slash_changed_paths(
    changed_path: str,
) -> None:
    review = _review().model_copy(update={"changed_paths": (changed_path,)})

    response = to_web_review(review)

    assert response.changed_paths == (changed_path,)


def test_explicit_result_mappers_publish_only_web_fields() -> None:
    summary = _summary()
    content = ConceptContent(
        **summary.model_dump(exclude={"resource_uri"}),
        resource_uri=summary.resource_uri,
        markdown="# Agents\n",
        digest="b" * 64,
    )
    finding = LintFinding(
        origin=FindingOrigin.DETERMINISTIC,
        severity=Severity.WARNING,
        code="missing-description",
        message="Description is missing.",
        path="topics/agents.md",
        evidence_paths=["topics/agents.md"],
        remediation="Add a description.",
    )
    web_results = (
        to_web_concept_page(ConceptPage(items=(summary,), next_cursor="next")),
        to_web_concept(content),
        to_web_search(ConceptSearchResult(items=(summary,))),
        to_web_answer(_answer()),
        to_web_lint(LintResult(findings=(finding,), deterministic_has_errors=False)),
        to_web_ingestion(IngestionResult(status="duplicate", review=None)),
        to_web_synthesis(SynthesisResult(answer=_answer(), review=_review())),
        to_web_mutation(MutationResult(review_id=REVIEW_ID, status="applied")),
    )

    payload = [result.model_dump(mode="json") for result in web_results]

    assert all("resource_uri" not in str(item) for item in payload)
    assert payload[0]["items"][0]["concept_id"] == "topics/agents"
    assert payload[1]["markdown"] == "# Agents\n"
    assert payload[3]["markdown"].startswith("# Agent tools")
    assert payload[4]["findings"][0]["origin"] == "deterministic"
    assert payload[5] == {"status": "duplicate", "review": None}
    assert payload[6]["review"]["review_id"] == REVIEW_ID
    assert payload[7] == {"review_id": REVIEW_ID, "status": "applied"}


@pytest.mark.parametrize("status", ["current", "pending"])
def test_refresh_mapper_preserves_discriminated_states(
    status: Literal["current", "pending"],
) -> None:
    application_result = RefreshResult(
        status=status,
        concept_id="syntheses/agents",
        answer=_answer(),
        review=_review() if status == "pending" else None,
    )

    payload = to_web_refresh(application_result).model_dump(mode="json")

    assert payload["status"] == status
    if status == "current":
        assert payload["review"] is None
    else:
        assert payload["review"]["review_id"] == REVIEW_ID
