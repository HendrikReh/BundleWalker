# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from pydantic import ValidationError

from bundlewalker.domain import (
    MAX_ANSWER_BODY_CHARACTERS,
    MAX_CHANGESET_DRAFTS,
    MAX_CITATIONS,
    MAX_DESCRIPTION_CHARACTERS,
    MAX_DRAFT_BODY_CHARACTERS,
    MAX_DRAFT_PATH_CHARACTERS,
    MAX_LINT_MESSAGE_CHARACTERS,
    MAX_PROPOSAL_CHARACTERS,
    MAX_TAG_CHARACTERS,
    MAX_TAGS,
    MAX_TITLE_CHARACTERS,
    ChangeOperation,
    ChangeSet,
    Citation,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    FindingOrigin,
    LintFinding,
    OkfMetadata,
    Severity,
)


def draft(path: str, *, operation: ChangeOperation, base_digest: str | None = None) -> DraftConcept:
    return DraftConcept(
        operation=operation,
        path=path,
        type=ConceptType.TOPIC,
        title="Typed agents",
        description="How typed agents constrain knowledge proposals.",
        tags=["agents"],
        body="# Notes\n\nTyped outputs reduce ambiguity.",
        citations=[],
        base_digest=base_digest,
    )


def test_okf_metadata_preserves_unknown_fields() -> None:
    metadata = OkfMetadata.model_validate({"type": "Unknown Type", "owner": "Hendrik"})
    assert metadata.type == "Unknown Type"
    assert metadata.model_extra == {"owner": "Hendrik"}


def test_citation_requires_both_line_bounds() -> None:
    with pytest.raises(ValidationError):
        Citation(number=1, concept_id="sources/a", start_line=3)


def test_create_rejects_base_digest() -> None:
    with pytest.raises(ValidationError):
        draft("topics/agents", operation=ChangeOperation.CREATE, base_digest="a" * 64)


def test_replace_requires_base_digest() -> None:
    with pytest.raises(ValidationError):
        draft("topics/agents", operation=ChangeOperation.REPLACE)


def test_changeset_rejects_duplicate_paths() -> None:
    item = draft("topics/agents", operation=ChangeOperation.CREATE)
    with pytest.raises(ValidationError):
        ChangeSet(summary="Duplicate", source_sha256=None, drafts=[item, item])


def test_cited_answer_rejects_raw_source_line_spans() -> None:
    with pytest.raises(ValidationError, match="line spans"):
        CitedAnswer(
            title="Answer",
            body="Supported [1].",
            citations=[Citation(number=1, concept_id="sources/a", start_line=1, end_line=2)],
        )


def test_producer_models_accept_documented_field_boundaries() -> None:
    bounded = DraftConcept(
        operation=ChangeOperation.CREATE,
        path="topics/a",
        type=ConceptType.TOPIC,
        title="t" * MAX_TITLE_CHARACTERS,
        description="d" * MAX_DESCRIPTION_CHARACTERS,
        tags=["x" * MAX_TAG_CHARACTERS] * MAX_TAGS,
        body="b" * MAX_DRAFT_BODY_CHARACTERS,
        citations=[],
    )
    answer = CitedAnswer(
        title="t" * MAX_TITLE_CHARACTERS,
        body="b" * MAX_ANSWER_BODY_CHARACTERS,
        citations=[],
    )
    finding = LintFinding(
        origin=FindingOrigin.SEMANTIC,
        severity=Severity.INFO,
        code="SEM-GAP",
        message="m" * MAX_LINT_MESSAGE_CHARACTERS,
    )

    assert len(bounded.body) == MAX_DRAFT_BODY_CHARACTERS
    assert len(answer.body) == MAX_ANSWER_BODY_CHARACTERS
    assert len(finding.message) == MAX_LINT_MESSAGE_CHARACTERS


@pytest.mark.parametrize(
    "update",
    [
        {"path": "topics/" + "a" * MAX_DRAFT_PATH_CHARACTERS},
        {"title": "t" * (MAX_TITLE_CHARACTERS + 1)},
        {"description": "d" * (MAX_DESCRIPTION_CHARACTERS + 1)},
        {"tags": ["tag"] * (MAX_TAGS + 1)},
        {"tags": ["x" * (MAX_TAG_CHARACTERS + 1)]},
        {"body": "b" * (MAX_DRAFT_BODY_CHARACTERS + 1)},
        {"citations": [Citation(number=1, concept_id="topics/a")] * (MAX_CITATIONS + 1)},
    ],
)
def test_draft_concept_rejects_values_above_documented_limits(
    update: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "operation": ChangeOperation.CREATE,
        "path": "topics/a",
        "type": ConceptType.TOPIC,
        "title": "Title",
        "description": "Description.",
        "body": "Body.",
    }
    values.update(update)

    with pytest.raises(ValidationError):
        DraftConcept.model_validate(values)


def test_change_set_rejects_draft_count_and_overall_proposal_budget() -> None:
    drafts = [
        draft(f"topics/a-{number}", operation=ChangeOperation.CREATE)
        for number in range(MAX_CHANGESET_DRAFTS + 1)
    ]
    with pytest.raises(ValidationError):
        ChangeSet(summary="Too many", drafts=drafts)

    oversized = DraftConcept(
        operation=ChangeOperation.CREATE,
        path="topics/oversized",
        type=ConceptType.TOPIC,
        title="Oversized",
        description="Oversized proposal.",
        body="b" * MAX_DRAFT_BODY_CHARACTERS,
    )
    repeated = [
        oversized.model_copy(update={"path": f"topics/oversized-{number}"})
        for number in range(MAX_PROPOSAL_CHARACTERS // MAX_DRAFT_BODY_CHARACTERS + 1)
    ]
    with pytest.raises(ValidationError, match="proposal budget"):
        ChangeSet(summary="Oversized", drafts=repeated)


def test_answer_and_lint_finding_reject_values_above_documented_limits() -> None:
    with pytest.raises(ValidationError):
        CitedAnswer(
            title="Answer",
            body="b" * (MAX_ANSWER_BODY_CHARACTERS + 1),
            citations=[],
        )
    with pytest.raises(ValidationError):
        LintFinding(
            origin=FindingOrigin.SEMANTIC,
            severity=Severity.INFO,
            code="SEM-GAP",
            message="m" * (MAX_LINT_MESSAGE_CHARACTERS + 1),
        )
