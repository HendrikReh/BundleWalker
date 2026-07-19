# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.contracts import FixtureIdentity, WorkspaceProfile
from bundlewalker.domain import ConceptType, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.okf.lint import lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.workspace import Workspace, discover_workspace, initialize_workspace

_TYPE_CYCLE = (
    ConceptType.SOURCE,
    ConceptType.TOPIC,
    ConceptType.TOPIC,
    ConceptType.TOPIC,
    ConceptType.TOPIC,
    ConceptType.ENTITY,
    ConceptType.ENTITY,
    ConceptType.ENTITY,
    ConceptType.SYNTHESIS,
    ConceptType.SYNTHESIS,
)
_CATEGORY = {
    ConceptType.SOURCE: "sources",
    ConceptType.TOPIC: "topics",
    ConceptType.ENTITY: "entities",
    ConceptType.SYNTHESIS: "syntheses",
}
_NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)
_TYPE_RATIOS = (1, 4, 3, 2)
_PRESENT_QUERY = "benchmark-needle"
_ABSENT_QUERY = "benchmark-absent-needle"
_READ_DOCUMENT_INDEX = 42


@dataclass(frozen=True, slots=True)
class GeneratedFixture:
    workspace: Workspace
    profile: WorkspaceProfile
    exact_wiki_bytes: int
    exact_workspace_bytes: int
    tree_sha256: str
    concept_ids: tuple[str, ...]
    present_query: str
    absent_query: str
    read_concept_id: str
    ingestion_content: str
    type_ratios: tuple[int, int, int, int]

    def identity(self) -> FixtureIdentity:
        return FixtureIdentity(
            profile=self.profile.name,
            document_count=len(self.concept_ids),
            exact_wiki_bytes=self.exact_wiki_bytes,
            exact_workspace_bytes=self.exact_workspace_bytes,
            source_characters=len(self.ingestion_content),
            profile_sha256=_profile_sha256(self.profile),
            tree_sha256=self.tree_sha256,
        )


def generate_fixture(destination: Path, profile: WorkspaceProfile) -> GeneratedFixture:
    if profile.document_count <= _READ_DOCUMENT_INDEX:
        raise ValueError("fixture profile must include concept 000042")

    workspace = initialize_workspace(destination, occurred_at=_NOW)
    concept_ids = tuple(_concept_id(index) for index in range(profile.document_count))
    document_paths: list[Path] = []
    latest_source_id = ""

    for index, concept_id in enumerate(concept_ids):
        concept_type = _TYPE_CYCLE[index % len(_TYPE_CYCLE)]
        path = workspace.wiki_dir / f"{concept_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if concept_type is ConceptType.SOURCE:
            latest_source_id = concept_id
            metadata = _source_metadata(workspace, concept_id, index)
        else:
            metadata = OkfMetadata(
                type=concept_type,
                title=f"Benchmark Concept {index:06d}",
                description=f"Deterministic benchmark concept {index:06d}.",
                tags=["benchmark"],
                timestamp=_NOW,
            )
        path.write_text(
            render_document(
                metadata,
                _document_body(
                    index=index,
                    concept_ids=concept_ids,
                    latest_source_id=latest_source_id,
                ),
            ),
            encoding="utf-8",
        )
        document_paths.append(path)

    regenerate_indexes(workspace.wiki_dir)
    _pad_documents(workspace.wiki_dir, profile.target_wiki_bytes, tuple(document_paths))

    discovered = discover_workspace(destination)
    documents = OkfRepository(discovered.wiki_dir).scan()
    findings = lint_bundle(discovered.wiki_dir, discovered.root)
    if len(documents) != profile.document_count:
        raise ValueError("generated fixture document count does not match its profile")
    if findings:
        raise ValueError("generated fixture has deterministic lint findings")

    ingestion_content = _ingestion_content(profile.source_characters)
    return GeneratedFixture(
        workspace=discovered,
        profile=profile,
        exact_wiki_bytes=_tree_size(discovered.wiki_dir),
        exact_workspace_bytes=_tree_size(discovered.root),
        tree_sha256=tree_sha256(discovered.root),
        concept_ids=concept_ids,
        present_query=_PRESENT_QUERY,
        absent_query=_ABSENT_QUERY,
        read_concept_id=concept_ids[_READ_DOCUMENT_INDEX],
        ingestion_content=ingestion_content,
        type_ratios=_TYPE_RATIOS,
    )


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(_regular_files(root), key=lambda item: item.relative_to(root).as_posix()):
        content = path.read_bytes()
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def _concept_id(index: int) -> str:
    concept_type = _TYPE_CYCLE[index % len(_TYPE_CYCLE)]
    return f"{_CATEGORY[concept_type]}/concept-{index:06d}"


def _source_metadata(workspace: Workspace, concept_id: str, index: int) -> OkfMetadata:
    raw_content = f"benchmark source {index:06d} line one\nbenchmark source {index:06d} line two\n"
    raw_bytes = raw_content.encode("ascii")
    raw_relative = Path(workspace.config.raw_dir) / f"source-{index:06d}.txt"
    (workspace.root / raw_relative).write_bytes(raw_bytes)
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return OkfMetadata.model_validate(
        {
            "type": ConceptType.SOURCE,
            "title": f"Benchmark Source {index:06d}",
            "description": f"Deterministic raw source for {concept_id}.",
            "resource": f"urn:bundlewalker:source:sha256:{digest}",
            "tags": ["benchmark", "source"],
            "timestamp": _NOW,
            "source_sha256": digest,
            "raw_path": raw_relative.as_posix(),
        }
    )


def _document_body(
    *,
    index: int,
    concept_ids: tuple[str, ...],
    latest_source_id: str,
) -> str:
    next_id = concept_ids[(index + 1) % len(concept_ids)]
    content = _PRESENT_QUERY if index == _READ_DOCUMENT_INDEX else f"benchmark content {index:06d}"
    citation_marker = " [1]" if index % 3 == 0 else ""
    body = (
        f"# Benchmark Concept {index:06d}\n\n"
        f"{content}{citation_marker}. [Next concept](/{next_id}.md)\n"
    )
    if index % 3 == 0:
        body += f"\n# Citations\n\n[1] [Benchmark Source](/{latest_source_id}.md) - raw lines 1-1\n"
    return body


def _pad_documents(wiki_root: Path, target_bytes: int, paths: tuple[Path, ...]) -> None:
    current = _tree_size(wiki_root)
    remaining = target_bytes - current
    if remaining < 0:
        raise ValueError("profile target is smaller than the valid generated wiki")
    share, extra = divmod(remaining, len(paths))
    for index, path in enumerate(paths):
        count = share + (1 if index < extra else 0)
        if count:
            with path.open("ab") as stream:
                stream.write(b"x" * count)
    if _tree_size(wiki_root) != target_bytes:
        raise AssertionError("fixture padding did not reach the exact profile size")


def _ingestion_content(character_count: int) -> str:
    unit = "benchmark source line\n"
    repetitions = (character_count // len(unit)) + 1
    return (unit * repetitions)[:character_count]


def _profile_sha256(profile: WorkspaceProfile) -> str:
    canonical = json.dumps(
        profile.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _regular_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file() and not path.is_symlink()]


def _tree_size(root: Path) -> int:
    return sum(path.stat().st_size for path in _regular_files(root))
