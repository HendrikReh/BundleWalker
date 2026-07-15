from __future__ import annotations

from pathlib import Path

import pytest

from bundlewalker.errors import UsageError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever


def _write_concept(
    root: Path,
    concept_id: str,
    *,
    concept_type: str = "Topic",
    title: str,
    description: str,
    tags: tuple[str, ...] = (),
    body: str = "# Notes\n",
) -> None:
    path = root / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tag_lines = "".join(f"  - {tag}\n" for tag in tags)
    tags_field = f"tags:\n{tag_lines}" if tags else "tags: []\n"
    path.write_text(
        f"---\ntype: {concept_type}\ntitle: {title}\n"
        f"description: {description}\n{tags_field}---\n\n{body}",
        encoding="utf-8",
    )


@pytest.fixture
def repository(tmp_path: Path) -> OkfRepository:
    root = tmp_path / "wiki"
    _write_concept(
        root,
        "topics/typed-agents",
        title="Typed Agents",
        description="Patterns for checked agent workflows.",
        tags=("agents", "typing"),
    )
    _write_concept(
        root,
        "topics/python",
        title="Python",
        description="A programming language.",
        tags=("language",),
        body="# Python\n\nTyped agents share a stable signal.\n",
    )
    _write_concept(
        root,
        "topics/nested/tools",
        concept_type="Entity",
        title="Tools",
        description="Useful utilities.",
        body="# Tools\n\nA stable signal supports discovery.\n",
    )
    return OkfRepository(root)


def test_title_match_outranks_body_match(repository: OkfRepository) -> None:
    retriever = LexicalRetriever(repository)

    results = retriever.search("typed agents", concept_type=None, limit=10)

    assert [item.concept_id for item in results[:2]] == [
        "topics/typed-agents",
        "topics/python",
    ]


def test_equal_scores_use_concept_id_order(repository: OkfRepository) -> None:
    retriever = LexicalRetriever(repository)

    results = retriever.search("stable signal", concept_type=None, limit=10)

    assert [item.concept_id for item in results] == [
        "topics/nested/tools",
        "topics/python",
    ]


def test_search_normalizes_unicode_case_and_whitespace(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    _write_concept(
        root,
        "topics/strasse",
        title="Straße Agents",
        description="Unicode case folding.",
    )
    retriever = LexicalRetriever(OkfRepository(root))

    results = retriever.search("  STRASSE\nAGENTS  ", concept_type=None, limit=10)

    assert [item.concept_id for item in results] == ["topics/strasse"]


def test_exact_phrase_outranks_separated_title_tokens(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    _write_concept(
        root,
        "topics/exact",
        title="Typed Agents",
        description="Exact phrase.",
    )
    _write_concept(
        root,
        "topics/tokens",
        title="Typed Reliable Agents",
        description="Separated tokens.",
    )
    retriever = LexicalRetriever(OkfRepository(root))

    results = retriever.search("typed agents", concept_type=None, limit=10)

    assert [item.concept_id for item in results] == [
        "topics/exact",
        "topics/tokens",
    ]


def test_search_filters_type_and_applies_limit(repository: OkfRepository) -> None:
    retriever = LexicalRetriever(repository)

    results = retriever.search("stable signal", concept_type="Topic", limit=1)

    assert [item.concept_id for item in results] == ["topics/python"]


@pytest.mark.parametrize("limit", [0, 11])
def test_search_rejects_limits_outside_supported_range(
    repository: OkfRepository,
    limit: int,
) -> None:
    retriever = LexicalRetriever(repository)

    with pytest.raises(UsageError, match="search limit must be between 1 and 10"):
        retriever.search("agents", concept_type=None, limit=limit)


def test_blank_query_returns_no_results(repository: OkfRepository) -> None:
    retriever = LexicalRetriever(repository)

    assert retriever.search(" \n ", concept_type=None, limit=10) == []
