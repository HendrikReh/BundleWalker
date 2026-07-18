# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Iterable, Iterator
from hashlib import sha256
from pathlib import Path, PurePosixPath

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import ValidationError

from bundlewalker.domain import OkfDocument, OkfMetadata
from bundlewalker.errors import OkfError

RESERVED_NAMES = frozenset({"index.md", "log.md"})

_MARKDOWN = MarkdownIt("commonmark")


def concept_path(root: Path, concept_id: str) -> Path:
    relative = PurePosixPath(f"{concept_id}.md")
    if relative.is_absolute() or ".." in relative.parts:
        raise OkfError(f"unsafe concept id: {concept_id}")
    if relative.name.casefold() in RESERVED_NAMES:
        raise OkfError(f"reserved concept path: {concept_id}")
    candidate = root.joinpath(*relative.parts)
    resolved_parent = candidate.parent.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if not resolved_parent.is_relative_to(resolved_root):
        raise OkfError(f"concept escapes bundle: {concept_id}")
    return candidate


def document_digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def extract_links(markdown: str) -> tuple[str, ...]:
    links: list[str] = []
    for token in _walk_tokens(_MARKDOWN.parse(markdown)):
        if token.type == "link_open" and isinstance(href := token.attrGet("href"), str):
            links.append(href)
    return tuple(links)


def parse_document(path: Path, root: Path) -> OkfDocument:
    relative = _relative_document_path(path, root)
    if relative.name.casefold() in RESERVED_NAMES:
        raise OkfError(f"reserved concept path: {relative.as_posix()}")

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise OkfError(f"cannot read document: {path}") from exc
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OkfError(f"document is not UTF-8: {path}") from exc

    frontmatter, body = _split_frontmatter(text, path)
    try:
        raw_metadata: object = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise OkfError(f"invalid frontmatter: {path}") from exc
    if not isinstance(raw_metadata, dict):
        raise OkfError(f"frontmatter must be a mapping: {path}")
    try:
        metadata = OkfMetadata.model_validate(raw_metadata)
    except ValidationError as exc:
        raise OkfError(f"invalid frontmatter: {path}") from exc

    return OkfDocument(
        concept_id=relative.with_suffix("").as_posix(),
        path=path,
        metadata=metadata,
        body=body,
        links=extract_links(body),
        digest=document_digest(content),
    )


def render_document(metadata: OkfMetadata, body: str) -> str:
    frontmatter = yaml.safe_dump(
        metadata.model_dump(mode="python", exclude_unset=True),
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{frontmatter}---\n{body}"


def _relative_document_path(path: Path, root: Path) -> Path:
    absolute_path = path.absolute()
    absolute_root = root.absolute()
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError as exc:
        raise OkfError(f"document escapes bundle: {path}") from exc

    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_root):
        raise OkfError(f"document escapes bundle: {path}")
    return relative


def _split_frontmatter(text: str, path: Path) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise OkfError(f"missing frontmatter: {path}")
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise OkfError(f"missing frontmatter: {path}")


def _walk_tokens(tokens: Iterable[Token]) -> Iterator[Token]:
    for token in tokens:
        yield token
        if token.children:
            yield from _walk_tokens(token.children)
