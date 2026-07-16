from typing import cast

import pytest
from pydantic import ValidationError

from bundlewalker.domain import Citation, CitedAnswer
from tests.evals import test_model_quality as quality
from tests.evals.test_model_quality import QualityCase

TARGET = "syntheses/decision-framework-for-repository-guidance"
CONTROLLED_EVIDENCE = "topics/repository-guidance-controlled-comparison"
CASE_NAME = "stale-synthesis-refresh"


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


def test_refresh_quality_accepts_applicability_uncertainty() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. It remains unclear whether "
        "the findings apply to all repositories."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_accepts_an_applicability_question() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Do the findings apply to "
        "all repositories?"
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_rejects_affirmative_transfer_after_a_caveat() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader transfer is "
        "uncertain. Nevertheless, findings transfer universally to every repository and language."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_affirmative_extension_after_a_caveat() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader applicability "
        "remains uncertain. However, the findings extend to all repositories, languages, and "
        "time horizons."
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
    return cast(dict[str, object], _qualified_refresh_case().model_dump(mode="python"))


def _qualified_refresh_case() -> QualityCase:
    matches = [case for case in quality.CASES if case.name == CASE_NAME]
    assert len(matches) == 1, f"expected exactly one {CASE_NAME} evaluation case"
    case = matches[0]
    assert case.qualification is not None
    return case


def _answer(body: str) -> CitedAnswer:
    return CitedAnswer(
        title="Refreshed decision framework",
        body=body,
        citations=[Citation(number=1, concept_id=CONTROLLED_EVIDENCE)],
    )
