# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Producer boundaries are intentionally generous for a filesystem wiki whose normal scale is
# hundreds of pages. They still keep a malformed model response from becoming an unbounded
# in-memory proposal or terminal payload.
MAX_DRAFT_PATH_CHARACTERS = 240
MAX_TITLE_CHARACTERS = 300
MAX_DESCRIPTION_CHARACTERS = 1_000
MAX_TAGS = 32
MAX_TAG_CHARACTERS = 80
MAX_DRAFT_BODY_CHARACTERS = 128_000
MAX_CITATIONS = 100
MAX_CHANGESET_DRAFTS = 128
MAX_CHANGESET_SUMMARY_CHARACTERS = 2_000
MAX_PROPOSAL_CHARACTERS = 1_000_000
MAX_ANSWER_BODY_CHARACTERS = 128_000
MAX_CONCEPT_ID_CHARACTERS = 4_096
MAX_CITATION_LINE = 1_000_000
MAX_LINT_CODE_CHARACTERS = 128
MAX_LINT_MESSAGE_CHARACTERS = 8_192
MAX_LINT_PATH_CHARACTERS = 4_096
MAX_LINT_EVIDENCE_PATHS = 32
MAX_LINT_REMEDIATION_CHARACTERS = 8_192
MAX_SEMANTIC_FINDINGS = 100

Tag = Annotated[str, Field(min_length=1, max_length=MAX_TAG_CHARACTERS)]
EvidencePath = Annotated[str, Field(min_length=1, max_length=MAX_LINT_PATH_CHARACTERS)]


class ConceptType(StrEnum):
    SOURCE = "Source"
    TOPIC = "Topic"
    ENTITY = "Entity"
    SYNTHESIS = "Synthesis"


class ChangeOperation(StrEnum):
    CREATE = "create"
    REPLACE = "replace"


class FindingOrigin(StrEnum):
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class OkfMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None


class OkfDocument(BaseModel):
    concept_id: str = Field(min_length=1)
    path: Path
    metadata: OkfMetadata
    body: str
    links: tuple[str, ...] = ()
    digest: str = Field(min_length=64, max_length=64)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1, le=MAX_CITATIONS)
    concept_id: str = Field(min_length=1, max_length=MAX_CONCEPT_ID_CHARACTERS)
    start_line: int | None = Field(default=None, ge=1, le=MAX_CITATION_LINE)
    end_line: int | None = Field(default=None, ge=1, le=MAX_CITATION_LINE)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("citation line bounds must be supplied together")
        if (
            self.start_line is not None
            and self.end_line is not None
            and self.end_line < self.start_line
        ):
            raise ValueError("citation end_line must not precede start_line")
        return self


class DraftConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: ChangeOperation
    path: str = Field(min_length=1, max_length=MAX_DRAFT_PATH_CHARACTERS)
    type: ConceptType
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARACTERS)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARACTERS)
    tags: list[Tag] = Field(default_factory=list, max_length=MAX_TAGS)
    body: str = Field(min_length=1, max_length=MAX_DRAFT_BODY_CHARACTERS)
    citations: list[Citation] = Field(default_factory=list[Citation], max_length=MAX_CITATIONS)
    base_digest: str | None = None

    @model_validator(mode="after")
    def validate_operation_digest(self) -> Self:
        if self.operation is ChangeOperation.CREATE and self.base_digest is not None:
            raise ValueError("create operations cannot include base_digest")
        if self.operation is ChangeOperation.REPLACE and self.base_digest is None:
            raise ValueError("replace operations require base_digest")
        return self


class ChangeSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=MAX_CHANGESET_SUMMARY_CHARACTERS)
    source_sha256: str | None = Field(default=None, max_length=64)
    drafts: list[DraftConcept] = Field(min_length=1, max_length=MAX_CHANGESET_DRAFTS)

    @model_validator(mode="after")
    def validate_unique_paths(self) -> Self:
        paths = [draft.path for draft in self.drafts]
        if len(paths) != len(set(paths)):
            raise ValueError("change set paths must be unique")
        if _proposal_character_count(self) > MAX_PROPOSAL_CHARACTERS:
            raise ValueError(
                f"change set exceeds the {MAX_PROPOSAL_CHARACTERS}-character proposal budget"
            )
        return self


class CitedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARACTERS)
    body: str = Field(min_length=1, max_length=MAX_ANSWER_BODY_CHARACTERS)
    citations: list[Citation] = Field(default_factory=list[Citation], max_length=MAX_CITATIONS)

    @model_validator(mode="after")
    def forbid_raw_line_spans(self) -> Self:
        if any(citation.start_line is not None for citation in self.citations):
            raise ValueError("query answer citations cannot include raw line spans")
        return self


class LintFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: FindingOrigin
    severity: Severity
    code: str = Field(min_length=1, max_length=MAX_LINT_CODE_CHARACTERS)
    message: str = Field(min_length=1, max_length=MAX_LINT_MESSAGE_CHARACTERS)
    path: str | None = Field(default=None, max_length=MAX_LINT_PATH_CHARACTERS)
    evidence_paths: list[EvidencePath] = Field(
        default_factory=list,
        max_length=MAX_LINT_EVIDENCE_PATHS,
    )
    remediation: str | None = Field(default=None, max_length=MAX_LINT_REMEDIATION_CHARACTERS)


def _proposal_character_count(change_set: ChangeSet) -> int:
    """Count proposal strings with fixed iteration bounds and no numeric-sized allocations."""
    total = len(change_set.summary) + len(change_set.source_sha256 or "")
    for draft in change_set.drafts:
        total += (
            len(draft.path)
            + len(draft.title)
            + len(draft.description)
            + len(draft.body)
            + len(draft.base_digest or "")
        )
        total += sum(len(tag) for tag in draft.tags)
        total += sum(len(citation.concept_id) for citation in draft.citations)
        if total > MAX_PROPOSAL_CHARACTERS:
            return total
    return total
