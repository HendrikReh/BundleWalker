# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from bundlewalker.domain import OkfMetadata
from bundlewalker.errors import OkfError
from bundlewalker.okf.documents import (
    concept_path,
    document_digest,
    extract_links,
    parse_document,
    render_document,
)


def test_standard_okf_metadata_fields_are_modeled() -> None:
    metadata = OkfMetadata.model_validate(
        {
            "type": "Topic",
            "title": "Agents",
            "description": "Typed agent patterns.",
            "resource": "urn:bundlewalker:topic:agents",
            "tags": ["agents", "typing"],
            "timestamp": "2026-07-15T12:00:00Z",
            "owner": "Hendrik",
        }
    )

    assert metadata.title == "Agents"
    assert metadata.description == "Typed agent patterns."
    assert metadata.resource == "urn:bundlewalker:topic:agents"
    assert metadata.tags == ["agents", "typing"]
    assert metadata.timestamp == datetime.fromisoformat("2026-07-15T12:00:00+00:00")
    assert metadata.model_extra == {"owner": "Hendrik"}


def test_round_trip_preserves_extra_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "agents.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ntype: Topic\ntitle: Agents\nowner: Hendrik\n---\n\n# Agents\n\n"
        "See [Pydantic](/entities/pydantic.md).\n",
        encoding="utf-8",
    )
    parsed = parse_document(path, root)
    rendered = render_document(parsed.metadata, parsed.body)
    reparsed_path = root / "topics" / "round-trip.md"
    reparsed_path.write_text(rendered, encoding="utf-8")
    reparsed = parse_document(reparsed_path, root)
    assert reparsed.metadata.model_extra == {"owner": "Hendrik"}
    assert reparsed.links == ("/entities/pydantic.md",)


def test_parse_document_populates_identity_and_exact_byte_digest(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "café.md"
    path.parent.mkdir(parents=True)
    content = "---\ntype: Topic\ntitle: Café\n---\n\n# Café\n"
    encoded = content.encode("utf-8")
    path.write_bytes(encoded)

    parsed = parse_document(path, root)

    assert parsed.concept_id == "topics/café"
    assert parsed.path == path
    assert parsed.body == "\n# Café\n"
    assert parsed.digest == hashlib.sha256(encoded).hexdigest()
    assert document_digest(encoded) == hashlib.sha256(encoded).hexdigest()


def test_render_document_is_deterministic_and_preserves_unicode() -> None:
    metadata = OkfMetadata.model_validate({"type": "Topic", "title": "Café", "owner": "Hendrik"})

    assert render_document(metadata, "\n# Café\n") == (
        "---\ntype: Topic\ntitle: Café\nowner: Hendrik\n---\n\n# Café\n"
    )


def test_extract_links_walks_inline_token_children() -> None:
    markdown = (
        "See **[Pydantic](/entities/pydantic.md)** and [the guide](https://example.com/guide).\n"
    )

    assert extract_links(markdown) == (
        "/entities/pydantic.md",
        "https://example.com/guide",
    )


@pytest.mark.parametrize("name", ["index.md", "INDEX.md", "log.md"])
def test_parse_document_rejects_reserved_filenames(tmp_path: Path, name: str) -> None:
    root = tmp_path / "wiki"
    path = root / name
    root.mkdir()
    path.write_text("---\ntype: Topic\n---\n", encoding="utf-8")

    with pytest.raises(OkfError, match="reserved concept path"):
        parse_document(path, root)


@pytest.mark.parametrize("concept_id", ["index", "topics/index", "LOG"])
def test_concept_path_rejects_reserved_filenames(tmp_path: Path, concept_id: str) -> None:
    with pytest.raises(OkfError, match="reserved concept path"):
        concept_path(tmp_path / "wiki", concept_id)


@pytest.mark.parametrize("concept_id", ["../escape", "topics/../../escape", "/escape"])
def test_concept_path_rejects_unsafe_ids(tmp_path: Path, concept_id: str) -> None:
    with pytest.raises(OkfError, match="unsafe concept id"):
        concept_path(tmp_path / "wiki", concept_id)


def test_concept_path_rejects_symlinked_parent_that_escapes_bundle(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "topics").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OkfError, match="concept escapes bundle"):
        concept_path(root, "topics/escape")


def test_parse_document_rejects_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    root.mkdir()
    path = tmp_path / "outside.md"
    path.write_text("---\ntype: Topic\n---\n", encoding="utf-8")

    with pytest.raises(OkfError, match="document escapes bundle"):
        parse_document(path, root)


def test_parse_document_rejects_symlink_that_escapes_bundle(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "escape.md"
    target.write_text("---\ntype: Topic\n---\n", encoding="utf-8")
    path = root / "escape.md"
    path.symlink_to(target)

    with pytest.raises(OkfError, match="document escapes bundle"):
        parse_document(path, root)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("# Missing\n", "missing frontmatter"),
        ("---\n- Topic\n---\n", "frontmatter must be a mapping"),
        ("---\ntype: ''\n---\n", "invalid frontmatter"),
    ],
)
def test_parse_document_rejects_invalid_frontmatter(
    tmp_path: Path, content: str, message: str
) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "invalid.md"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(OkfError, match=message):
        parse_document(path, root)


def test_parse_document_rejects_malformed_utf8(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "invalid.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"---\ntype: Topic\n---\n\xff")

    with pytest.raises(OkfError, match="document is not UTF-8"):
        parse_document(path, root)
