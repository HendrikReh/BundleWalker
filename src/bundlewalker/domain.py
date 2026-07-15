from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class OkfDocument(BaseModel):
    concept_id: str = Field(min_length=1)
    path: Path
    metadata: OkfMetadata
    body: str
    links: tuple[str, ...] = ()
    digest: str = Field(min_length=64, max_length=64)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    concept_id: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

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
    path: str = Field(min_length=1)
    type: ConceptType
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    body: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list[Citation])
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

    summary: str = Field(min_length=1)
    source_sha256: str | None = None
    drafts: list[DraftConcept] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_paths(self) -> Self:
        paths = [draft.path for draft in self.drafts]
        if len(paths) != len(set(paths)):
            raise ValueError("change set paths must be unique")
        return self


class CitedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list[Citation])


class LintFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: FindingOrigin
    severity: Severity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    path: str | None = None
    evidence_paths: list[str] = Field(default_factory=list)
    remediation: str | None = None
