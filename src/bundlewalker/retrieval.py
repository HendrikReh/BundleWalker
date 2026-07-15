from __future__ import annotations

from dataclasses import dataclass

from bundlewalker.domain import OkfDocument
from bundlewalker.errors import UsageError
from bundlewalker.okf.repository import ConceptSummary, OkfRepository

_FIELD_WEIGHTS = {
    "title": 16,
    "description": 8,
    "tags_path": 4,
    "body": 1,
}


@dataclass(frozen=True, slots=True)
class _Score:
    phrase: int
    tokens: int


class LexicalRetriever:
    def __init__(self, repository: OkfRepository) -> None:
        self.repository = repository

    def search(
        self,
        query: str,
        concept_type: str | None,
        limit: int,
    ) -> list[ConceptSummary]:
        if not 1 <= limit <= 10:
            raise UsageError("search limit must be between 1 and 10")
        normalized_query = _normalize(query)
        if not normalized_query:
            return []
        query_tokens = normalized_query.split()

        ranked: list[tuple[_Score, str, ConceptSummary]] = []
        for document in self.repository.scan().values():
            if concept_type is not None and document.metadata.type != concept_type:
                continue
            score = _score_document(document, normalized_query, query_tokens)
            if score.phrase == 0 and score.tokens == 0:
                continue
            ranked.append((score, document.concept_id, ConceptSummary.from_document(document)))

        ranked.sort(key=lambda item: (-item[0].phrase, -item[0].tokens, item[1]))
        return [summary for _, _, summary in ranked[:limit]]


def _score_document(
    document: OkfDocument,
    query: str,
    query_tokens: list[str],
) -> _Score:
    fields = {
        "title": _normalize(document.metadata.title or ""),
        "description": _normalize(document.metadata.description or ""),
        "tags_path": _normalize(" ".join((*document.metadata.tags, document.concept_id))),
        "body": _normalize(document.body),
    }
    phrase_score = 0
    token_score = 0
    for field_name, text in fields.items():
        weight = _FIELD_WEIGHTS[field_name]
        if query in text:
            phrase_score += weight
        field_tokens = set(text.split())
        token_score += weight * sum(token in field_tokens for token in query_tokens)
    return _Score(phrase=phrase_score, tokens=token_score)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
