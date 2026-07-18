# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest

from bundlewalker.domain import OkfDocument
from bundlewalker.errors import OkfError
from bundlewalker.okf import repository as repository_module
from bundlewalker.okf.repository import OkfRepository


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
def wiki_root(tmp_path: Path) -> Path:
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
    (root / "index.md").write_text("not valid frontmatter", encoding="utf-8")
    (root / "log.md").write_text("also not frontmatter", encoding="utf-8")
    (root / "topics" / "INDEX.md").write_text("reserved", encoding="utf-8")
    return root


def test_scan_ignores_reserved_files_and_returns_concept_id_order(
    wiki_root: Path,
) -> None:
    repository = OkfRepository(wiki_root)

    documents = repository.scan()

    assert list(documents) == [
        "topics/nested/tools",
        "topics/python",
        "topics/typed-agents",
    ]
    assert documents["topics/python"].metadata.title == "Python"


def test_list_returns_only_immediate_concepts(wiki_root: Path) -> None:
    repository = OkfRepository(wiki_root)

    summaries = repository.list("topics")

    assert [summary.concept_id for summary in summaries] == [
        "topics/python",
        "topics/typed-agents",
    ]
    assert summaries[0].type == "Topic"
    assert summaries[0].title == "Python"
    assert summaries[0].description == "A programming language."
    assert summaries[0].tags == ("language",)


def test_get_missing_concept_raises_okf_error(wiki_root: Path) -> None:
    repository = OkfRepository(wiki_root)

    with pytest.raises(OkfError, match="concept not found: topics/missing"):
        repository.get("topics/missing")


def test_list_rejects_unsafe_directory(wiki_root: Path) -> None:
    repository = OkfRepository(wiki_root)

    with pytest.raises(OkfError, match="unsafe concept directory"):
        repository.list("../topics")


def test_scan_rejects_case_folded_path_collisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "wiki"
    _write_concept(
        root,
        "topics/first",
        title="Street",
        description="First spelling.",
    )
    _write_concept(
        root,
        "topics/second",
        title="Street duplicate",
        description="Second spelling.",
    )
    real_parse_document = repository_module.parse_document

    def parse_with_colliding_identity(path: Path, bundle_root: Path) -> OkfDocument:
        document = real_parse_document(path, bundle_root)
        concept_id = "topics/Straße" if document.concept_id.endswith("first") else "topics/STRASSE"
        return document.model_copy(update={"concept_id": concept_id})

    monkeypatch.setattr(repository_module, "parse_document", parse_with_colliding_identity)

    with pytest.raises(OkfError, match="case-folded concept path collision"):
        OkfRepository(root).scan()
