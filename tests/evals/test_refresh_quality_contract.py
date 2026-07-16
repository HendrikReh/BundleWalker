from typing import cast

import pytest
from pydantic import ValidationError

from bundlewalker.domain import Citation, CitedAnswer
from tests.evals import test_model_quality as quality
from tests.evals.test_model_quality import QualityCase

TARGET = "syntheses/decision-framework-for-repository-guidance"
CONTROLLED_EVIDENCE = "topics/repository-guidance-controlled-comparison"


def test_refresh_case_allows_an_unrelated_synthesis_fixture() -> None:
    value = _refresh_case_value()
    concepts = cast(list[dict[str, str]], value["concepts"])
    concepts.append(
        {
            "path": "syntheses/unrelated-review",
            "title": "Unrelated review",
            "description": "Another synthesis that is not the refresh target.",
            "body": "# Unrelated review\n\nThis synthesis remains untouched.\n",
        }
    )

    case = QualityCase.model_validate(value)

    assert case.refresh_target == TARGET
    assert {concept.path for concept in case.concepts if concept.path.startswith("syntheses/")} == {
        TARGET,
        "syntheses/unrelated-review",
    }


def test_refresh_case_requires_the_target_synthesis_fixture() -> None:
    value = _refresh_case_value()
    value["refresh_target"] = "syntheses/missing-target"

    with pytest.raises(ValidationError, match="refresh target must identify a concept fixture"):
        QualityCase.model_validate(value)


def test_refresh_case_requires_a_synthesis_target_id() -> None:
    value = _refresh_case_value()
    value["refresh_target"] = CONTROLLED_EVIDENCE

    with pytest.raises(ValidationError, match="String should match pattern"):
        QualityCase.model_validate(value)


def test_refresh_quality_rejects_explicit_universal_overclaim_with_valid_citations() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "This controlled comparison has no meaningful limitation and proves "
        "universal generalization."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_generic_qualification_without_concrete_scope() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "The controlled evidence remains limited, and broader generalization is uncertain."
    )

    with pytest.raises(AssertionError, match="evidence-scope anchor"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_does_not_match_scope_numbers_as_substrings() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Across 30 Python repositories observed for four weeks, broader generalization remains "
        "uncertain."
    )

    with pytest.raises(AssertionError, match="evidence-scope anchor"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universal_application_after_valid_caveats() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed during a month-long study, so transfer "
        "beyond that scope remains unclear. Nevertheless, the comparison applies to every "
        "repository."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_accepts_concrete_boundary_paraphrase_without_magic_literal() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed during a month-long study. Whether those "
        "findings transfer to other languages or longer maintenance horizons remains unclear."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def _refresh_case_value() -> dict[str, object]:
    return {
        "name": "refresh-contract",
        "kind": "refresh",
        "concepts": [
            {
                "path": CONTROLLED_EVIDENCE,
                "title": "Repository guidance controlled comparison",
                "description": "A controlled comparison with explicit scope boundaries.",
                "body": (
                    "# Controlled comparison\n\n"
                    "Three Python repositories were studied for four weeks.\n"
                ),
            },
            {
                "path": TARGET,
                "title": "Decision framework",
                "description": "A framework that needs refreshing.",
                "body": "# Decision framework\n\nEarlier practitioner evidence only.\n",
            },
        ],
        "refresh_target": TARGET,
        "question": "Refresh the framework without overstating the evidence.",
        "expected_phrases": [],
        "required_citations": [CONTROLLED_EVIDENCE],
        "qualification": _qualification_value(),
    }


def _qualified_refresh_case() -> QualityCase:
    return QualityCase.model_validate(_refresh_case_value())


def _qualification_value() -> dict[str, object]:
    return {
        "scope_anchor_groups": [
            ["three", "3"],
            ["repository", "repositories", "repo", "repos"],
            ["python"],
            ["four weeks", "4 weeks", "four-week", "4-week", "one month", "month-long"],
        ],
        "uncertainty_patterns": [
            r"\b(?:not|cannot|uncertain|unknown|insufficient|unclear)\b.{0,100}"
            r"\b(?:generali[sz]|transfer|appl|extend)",
            r"\b(?:generali[sz]|transfer|appl|extend)\w*.{0,100}"
            r"\b(?:not|uncertain|unknown|unsupported|unestablished|unclear)\b",
        ],
        "forbidden_overclaim_patterns": [
            r"\bno (?:meaningful )?limitations?\b",
            r"\bproves?.{0,40}\buniversal(?:ly)?\b",
            r"\bgenerali[sz]es? (?:universally|to all|across all)\b",
            r"(?<!not )(?<!n't )\b(?:apply|applies|applicable)\s+to\s+(?:all|every)\b",
        ],
    }


def _answer(body: str) -> CitedAnswer:
    return CitedAnswer(
        title="Refreshed decision framework",
        body=body,
        citations=[Citation(number=1, concept_id=CONTROLLED_EVIDENCE)],
    )
