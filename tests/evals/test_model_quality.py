from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, Self, cast

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bundlewalker.domain import CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import commit_transaction
from bundlewalker.workflows.ask import (
    SynthesisAlreadyCurrent,
    answer_question,
    answer_synthesis_refresh,
    prepare_synthesis_refresh,
)
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

    path: str = Field(pattern=r"^(topics|entities|syntheses)/[a-z0-9-]+$")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    body: str = Field(min_length=1)


class QualificationExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_anchor_groups: list[list[str]] = Field(min_length=1)
    clause_boundary_patterns: list[str] = Field(min_length=1)
    concessive_markers: list[str] = Field(min_length=1)
    concept_patterns: list[str] = Field(min_length=1)
    universal_scope_patterns: list[str] = Field(min_length=1)
    negation_patterns: list[str] = Field(min_length=1)
    uncertainty_patterns: list[str] = Field(min_length=1)
    direct_forbidden_patterns: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_expectation(self) -> Self:
        if any(
            not group or any(not anchor.strip() for anchor in group)
            for group in self.scope_anchor_groups
        ):
            raise ValueError("qualification anchor groups must contain non-empty alternatives")
        if any(not marker.strip() for marker in self.concessive_markers):
            raise ValueError("qualification concessive markers must not be empty")
        patterns = (
            self.clause_boundary_patterns
            + self.concept_patterns
            + self.universal_scope_patterns
            + self.negation_patterns
            + self.uncertainty_patterns
            + self.direct_forbidden_patterns
        )
        if any(not pattern.strip() for pattern in patterns):
            raise ValueError("qualification patterns must not be empty")
        try:
            for pattern in patterns:
                re.compile(pattern)
        except re.error as exc:
            raise ValueError("qualification patterns must be valid regular expressions") from exc
        return self


class QualityCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Literal["ingest", "query", "refresh"]
    sources: list[SourceFixture] = Field(default_factory=list[SourceFixture])
    concepts: list[ConceptFixture] = Field(default_factory=list[ConceptFixture])
    question: str | None = None
    refresh_target: str | None = Field(
        default=None,
        pattern=r"^syntheses/[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    expected_phrases: list[str] = Field(default_factory=list[str])
    required_citations: list[str] = Field(default_factory=list[str])
    qualification: QualificationExpectation | None = None
    minimum_shared_source_citations: int = Field(default=0, ge=0)
    shared_concept_type: Literal["Topic", "Entity"] | None = None

    @model_validator(mode="after")
    def validate_case_shape(self) -> Self:
        if self.kind == "ingest" and (
            not self.sources
            or self.concepts
            or self.question
            or self.refresh_target
            or self.required_citations
            or self.qualification
            or not self.expected_phrases
        ):
            raise ValueError("ingest cases require only source fixtures")
        if self.kind == "query" and (
            not self.concepts
            or self.sources
            or not self.question
            or self.refresh_target
            or self.qualification
            or not self.expected_phrases
        ):
            raise ValueError("query cases require concepts and a question")
        concept_ids = {concept.path for concept in self.concepts}
        if self.kind == "refresh":
            if (
                not self.concepts
                or self.sources
                or not self.question
                or not self.refresh_target
                or self.qualification is None
            ):
                raise ValueError(
                    "refresh cases require concepts, a question, a Synthesis target, "
                    "and qualification expectations"
                )
            if self.refresh_target not in concept_ids:
                raise ValueError("refresh target must identify a concept fixture")
            if self.refresh_target in self.required_citations:
                raise ValueError("refresh target cannot be a required citation")
        if not set(self.required_citations).issubset(concept_ids):
            raise ValueError("required citations must identify concept fixtures")
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
        _write_concept_fixtures(case, workspace)

    if case.kind == "query":
        await _evaluate_query_case(case, workspace, model)
    elif case.kind == "refresh":
        await _evaluate_refresh_case(case, workspace, model)


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
    assert case.question is not None
    answered = await answer_question(
        workspace,
        case.question,
        explicit_model=model,
        environment={},
    )
    assert answered.answer.citations
    cited_ids = {citation.concept_id for citation in answered.answer.citations}
    assert cited_ids.issubset(answered.read_ids)
    assert set(case.required_citations).issubset(cited_ids)
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))
    answer_text = answered.answer.body.casefold()
    for phrase in case.expected_phrases:
        assert phrase.casefold() in answer_text


def _write_concept_fixtures(case: QualityCase, workspace: Workspace) -> None:
    concept_types = {
        "topics": "Topic",
        "entities": "Entity",
        "syntheses": "Synthesis",
    }
    for fixture in case.concepts:
        category, slug = fixture.path.split("/", maxsplit=1)
        concept_path = workspace.wiki_dir / category / f"{slug}.md"
        concept_path.write_text(
            render_document(
                OkfMetadata(
                    type=concept_types[category],
                    title=fixture.title,
                    description=fixture.description,
                    tags=["evaluation"],
                ),
                fixture.body,
            ),
            encoding="utf-8",
        )
    regenerate_indexes(workspace.wiki_dir)


async def _evaluate_refresh_case(
    case: QualityCase,
    workspace: Workspace,
    model: str,
) -> None:
    assert case.question is not None
    assert case.refresh_target is not None
    repository = OkfRepository(workspace.wiki_dir)
    target = repository.get(case.refresh_target)
    target_digest = target.digest
    target_path = target.path
    assert target.metadata.type == "Synthesis"

    answered = await answer_synthesis_refresh(
        workspace,
        case.question,
        case.refresh_target,
        explicit_model=model,
        environment={},
    )
    assert_refresh_answer_quality(case, answered.answer, answered.read_ids)

    outcome = prepare_synthesis_refresh(workspace, answered)
    assert not isinstance(outcome, SynthesisAlreadyCurrent)
    commit_transaction(outcome)

    refreshed = OkfRepository(workspace.wiki_dir).get(case.refresh_target)
    assert refreshed.path == target_path
    assert refreshed.digest != target_digest
    assert refreshed.metadata.type == "Synthesis"
    assert answered.answer.body in refreshed.body
    assert not has_errors(lint_bundle(workspace.wiki_dir, workspace.root))


def assert_refresh_answer_quality(
    case: QualityCase,
    answer: CitedAnswer,
    read_ids: frozenset[str],
) -> None:
    assert case.kind == "refresh"
    assert case.refresh_target is not None
    assert case.qualification is not None
    assert answer.citations
    cited_ids = {citation.concept_id for citation in answer.citations}
    assert cited_ids.issubset(read_ids)
    assert case.refresh_target not in cited_ids
    assert set(case.required_citations).issubset(cited_ids)
    answer_text = answer.body.casefold()
    for phrase in case.expected_phrases:
        assert phrase.casefold() in answer_text
    _assert_refresh_qualification(answer.body, case.qualification)


def _assert_refresh_qualification(
    answer_body: str,
    expectation: QualificationExpectation,
) -> None:
    normalized = " ".join(answer_body.casefold().split())
    clauses = _split_qualification_clauses(normalized, expectation.clause_boundary_patterns)
    assertion_spans = [
        assertion
        for clause in clauses
        for assertion in _split_concessive_assertions(clause, expectation.concessive_markers)
    ]
    assertion_states = [
        (assertion, _is_qualified_assertion(assertion, expectation))
        for assertion in assertion_spans
    ]
    forbidden = next(
        (
            reason
            for assertion, _ in assertion_states
            if (reason := _forbidden_overclaim_reason(assertion, expectation)) is not None
        ),
        None,
    )
    assert forbidden is None, f"refresh answer matched forbidden overclaim pattern: {forbidden}"

    missing_anchor_groups = [
        group
        for group in expectation.scope_anchor_groups
        if not any(
            re.search(
                rf"(?<!\w){re.escape(anchor.casefold())}(?!\w)",
                normalized,
            )
            for anchor in group
        )
    ]
    assert not missing_anchor_groups, (
        f"refresh answer is missing evidence-scope anchor groups: {missing_anchor_groups}"
    )
    assert any(is_qualified for _, is_qualified in assertion_states), (
        "refresh answer does not express the required uncertainty boundary"
    )


def _split_qualification_clauses(text: str, boundary_patterns: list[str]) -> list[str]:
    boundaries = re.compile(
        "|".join(f"(?:{pattern})" for pattern in boundary_patterns),
        flags=re.IGNORECASE,
    )
    clauses: list[str] = []
    start = 0
    for boundary in boundaries.finditer(text):
        if clause := text[start : boundary.start()].strip():
            clauses.append(clause)
        start = boundary.end()
    if clause := text[start:].strip():
        clauses.append(clause)
    return clauses


def _split_concessive_assertions(clause: str, concessive_markers: list[str]) -> list[str]:
    for comma in (match.start() for match in re.finditer(",", clause)):
        left = clause[:comma].strip()
        right = clause[comma + 1 :].strip()
        if not left or not right:
            continue
        if _starts_with_concessive(left, concessive_markers) or _starts_with_concessive(
            right,
            concessive_markers,
        ):
            return [left, right]
    return [clause]


def _starts_with_concessive(assertion: str, concessive_markers: list[str]) -> bool:
    return any(
        re.match(
            rf"{re.escape(marker.casefold())}(?=\W|$)",
            assertion,
            flags=re.IGNORECASE,
        )
        for marker in sorted(concessive_markers, key=len, reverse=True)
    )


def _is_qualified_assertion(
    assertion: str,
    expectation: QualificationExpectation,
) -> bool:
    return (
        assertion.endswith("?")
        or _first_matching_pattern(assertion, expectation.uncertainty_patterns) is not None
        or _first_matching_pattern(assertion, expectation.negation_patterns) is not None
    )


def _is_affirmative_universal_overclaim(
    assertion: str,
    expectation: QualificationExpectation,
) -> bool:
    if _is_qualified_assertion(assertion, expectation):
        return False
    return (
        _first_matching_pattern(assertion, expectation.concept_patterns) is not None
        and _first_matching_pattern(assertion, expectation.universal_scope_patterns) is not None
    )


def _forbidden_overclaim_reason(
    assertion: str,
    expectation: QualificationExpectation,
) -> str | None:
    if _is_qualified_assertion(assertion, expectation):
        return None
    if direct := _first_matching_pattern(assertion, expectation.direct_forbidden_patterns):
        return direct
    if _is_affirmative_universal_overclaim(assertion, expectation):
        return "affirmative universal-scope assertion"
    return None


def _first_matching_pattern(text: str, patterns: list[str]) -> str | None:
    return next(
        (pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)),
        None,
    )
