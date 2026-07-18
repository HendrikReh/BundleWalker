# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import cast

import pytest
from pydantic import ValidationError

from bundlewalker.domain import Citation, CitedAnswer
from tests.evals import test_model_quality as quality
from tests.evals.test_model_quality import QualityCase

TARGET = "syntheses/decision-framework-for-repository-guidance"
CONTROLLED_EVIDENCE = "topics/repository-guidance-controlled-comparison"
CASE_NAME = "stale-synthesis-refresh"


def test_refresh_case_preserves_required_phrase_contract() -> None:
    assert _live_refresh_case().expected_phrases == ["controlled", "limitation"]


@pytest.mark.parametrize(
    "expected_phrases",
    [pytest.param(None, id="missing"), pytest.param([], id="empty")],
)
def test_refresh_case_requires_expected_phrases(expected_phrases: list[str] | None) -> None:
    value = _refresh_case_value()
    if expected_phrases is None:
        value.pop("expected_phrases")
    else:
        value["expected_phrases"] = expected_phrases

    with pytest.raises(ValidationError, match="expected_phrases"):
        QualityCase.model_validate(value)


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


def test_refresh_quality_scopes_uncertainty_in_an_although_clause() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Although broader "
        "applicability is uncertain, the findings apply to all repositories."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_scopes_uncertainty_in_a_despite_clause() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Despite uncertain transfer "
        "beyond the sample, the findings transfer universally."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universally_applicable_after_a_caveat() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader applicability is "
        "uncertain. Nevertheless, the result is universally applicable across every repository."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_accepts_extension_uncertainty() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader extension beyond "
        "this sample remains unclear."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_scopes_uncertainty_in_a_suffix_although_clause() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. The findings apply to all "
        "repositories, although broader applicability remains uncertain."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_scopes_uncertainty_in_a_suffix_though_clause() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. The findings apply to all, "
        "though whether they transfer is unclear."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universally_transferable_after_a_caveat() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader transfer remains "
        "uncertain. Nevertheless, the findings are universally transferable."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universally_extendable_after_a_caveat() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader extension remains "
        "uncertain. Nevertheless, the findings are universally extendable."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universal_applicability_after_a_caveat() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Broader applicability "
        "remains uncertain. Nevertheless, the result has universal applicability."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_accepts_negated_application() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. The findings do not apply "
        "to all repositories."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_accepts_negated_universal_transfer() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. The findings are not "
        "universally transferable."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_rejects_universal_application_after_unrelated_negation() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. The findings are not "
        "limited to the studied repositories and apply universally."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universal_application_after_narrow_negation() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. The findings do not merely "
        "apply to Python repositories and instead apply universally."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_rejects_universal_application_after_separate_uncertainty() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Applicability to small "
        "edits is uncertain and the findings apply universally."
    )

    with pytest.raises(AssertionError, match="forbidden overclaim"):
        quality.assert_refresh_answer_quality(
            case,
            answer,
            frozenset({CONTROLLED_EVIDENCE}),
        )


def test_refresh_quality_accepts_a_question_governing_coordinated_predicates() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Do the findings apply to "
        "all repositories and transfer to every language?"
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_accepts_whether_uncertainty_governing_coordinated_predicates() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. It is uncertain whether the "
        "findings generalize to all languages and apply to every repository."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_accepts_uncertain_oxford_list() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Applicability across "
        "repository sizes, languages, and time horizons remains uncertain."
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_accepts_question_with_oxford_list() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Does the result apply to "
        "all repositories, tasks, and languages?"
    )

    quality.assert_refresh_answer_quality(
        case,
        answer,
        frozenset({CONTROLLED_EVIDENCE}),
    )


def test_refresh_quality_rejects_overclaim_after_qualified_comma_clause() -> None:
    case = _qualified_refresh_case()
    answer = _answer(
        "Only three Python repositories were observed for four weeks. Whether the findings "
        "generalize to all languages is uncertain, and the findings apply universally."
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
    return cast(dict[str, object], _live_refresh_case().model_dump(mode="python"))


def _qualified_refresh_case() -> QualityCase:
    return _live_refresh_case().model_copy(update={"expected_phrases": []})


def _live_refresh_case() -> QualityCase:
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
