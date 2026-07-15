import pytest
from pydantic import ValidationError

from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
    OkfMetadata,
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
