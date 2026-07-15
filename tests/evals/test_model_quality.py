from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self, cast

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bundlewalker.domain import OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import commit_transaction
from bundlewalker.workflows.ask import answer_question
from bundlewalker.workflows.ingest import PreparedIngestion, prepare_ingestion
from bundlewalker.workspace import Workspace, initialize_workspace

MODEL = os.getenv("BUNDLEWALKER_EVAL_MODEL")
pytestmark = pytest.mark.skipif(
    not MODEL,
    reason="set BUNDLEWALKER_EVAL_MODEL to run live model evaluations",
)

CASES_PATH = Path(__file__).parents[2] / "evals" / "cases.yaml"


class SourceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(pattern=r"^[a-z0-9-]+\.txt$")
    text: str = Field(min_length=1)


class ConceptFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(pattern=r"^(topics|entities)/[a-z0-9-]+$")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    body: str = Field(min_length=1)


class QualityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Literal["ingest", "query"]
    sources: list[SourceFixture] = Field(default_factory=list[SourceFixture])
    concepts: list[ConceptFixture] = Field(default_factory=list[ConceptFixture])
    question: str | None = None
    expected_phrases: list[str] = Field(min_length=1)
    minimum_shared_source_citations: int = Field(default=0, ge=0)
    shared_concept_type: Literal["Topic", "Entity"] | None = None

    @model_validator(mode="after")
    def validate_case_shape(self) -> Self:
        if self.kind == "ingest" and (not self.sources or self.concepts or self.question):
            raise ValueError("ingest cases require only source fixtures")
        if self.kind == "query" and (not self.concepts or self.sources or not self.question):
            raise ValueError("query cases require concepts and a question")
        if self.minimum_shared_source_citations > len(self.sources):
            raise ValueError("shared citation requirement exceeds source count")
        if self.shared_concept_type is not None and not self.minimum_shared_source_citations:
            raise ValueError("shared concept type requires a citation-count assertion")
        return self


def _load_cases() -> list[QualityCase]:
    values: object = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise TypeError("evaluation cases must be a YAML list")
    return [QualityCase.model_validate(value) for value in cast(list[object], values)]


CASES = _load_cases()


@pytest.mark.eval
@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[f"{case.name}[{MODEL or 'model-not-configured'}]" for case in CASES],
)
async def test_live_model_quality(case: QualityCase, tmp_path: Path) -> None:
    model = MODEL
    assert model is not None
    workspace = initialize_workspace(tmp_path / case.name)

    if case.kind == "ingest":
        await _evaluate_ingestion_case(case, tmp_path, workspace, model)
    else:
        await _evaluate_query_case(case, workspace, model)


async def _evaluate_ingestion_case(
    case: QualityCase,
    tmp_path: Path,
    workspace: Workspace,
    model: str,
) -> None:
    for source_number, source_fixture in enumerate(case.sources, start=1):
        source_path = tmp_path / f"{source_number}-{source_fixture.filename}"
        source_path.write_text(source_fixture.text, encoding="utf-8")
        outcome = await prepare_ingestion(
            workspace,
            source_path,
            explicit_model=model,
            environment={},
        )
        assert isinstance(outcome, PreparedIngestion)
        commit_transaction(outcome.transaction)

    documents = OkfRepository(workspace.wiki_dir).scan()
    sources = {
        concept_id: document
        for concept_id, document in documents.items()
        if document.metadata.type == "Source"
    }
    assert len(sources) == len(case.sources)
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))

    shared_documents = [
        document
        for document in documents.values()
        if document.metadata.type != "Source"
        and (case.shared_concept_type is None or document.metadata.type == case.shared_concept_type)
    ]
    corpus = "\n".join(document.body.casefold() for document in documents.values())
    for phrase in case.expected_phrases:
        assert phrase.casefold() in corpus

    if case.minimum_shared_source_citations:
        assert any(
            sum(f"/{source_id}.md" in document.body for source_id in sources)
            >= case.minimum_shared_source_citations
            for document in shared_documents
        )


async def _evaluate_query_case(
    case: QualityCase,
    workspace: Workspace,
    model: str,
) -> None:
    for fixture in case.concepts:
        category, slug = fixture.path.split("/", maxsplit=1)
        concept_path = workspace.wiki_dir / category / f"{slug}.md"
        concept_path.write_text(
            render_document(
                OkfMetadata(
                    type="Topic" if category == "topics" else "Entity",
                    title=fixture.title,
                    description=fixture.description,
                    tags=["evaluation"],
                ),
                fixture.body,
            ),
            encoding="utf-8",
        )
    regenerate_indexes(workspace.wiki_dir)

    assert case.question is not None
    answered = await answer_question(
        workspace,
        case.question,
        explicit_model=model,
        environment={},
    )
    assert answered.answer.citations
    assert {citation.concept_id for citation in answered.answer.citations}.issubset(
        answered.read_ids
    )
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))
    answer_text = answered.answer.body.casefold()
    for phrase in case.expected_phrases:
        assert phrase.casefold() in answer_text
