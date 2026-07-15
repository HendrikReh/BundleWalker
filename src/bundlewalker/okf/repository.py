from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from bundlewalker.domain import OkfDocument
from bundlewalker.errors import OkfError
from bundlewalker.okf.documents import RESERVED_NAMES, concept_path, parse_document


@dataclass(frozen=True, slots=True)
class ConceptSummary:
    concept_id: str
    type: str
    title: str | None
    description: str | None
    tags: tuple[str, ...]

    @classmethod
    def from_document(cls, document: OkfDocument) -> ConceptSummary:
        return cls(
            concept_id=document.concept_id,
            type=document.metadata.type,
            title=document.metadata.title,
            description=document.metadata.description,
            tags=tuple(document.metadata.tags),
        )


class OkfRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def scan(self) -> dict[str, OkfDocument]:
        if not self.root.is_dir():
            raise OkfError(f"bundle root is not a directory: {self.root}")

        documents: list[OkfDocument] = []
        folded_paths: dict[str, str] = {}
        for path in self.root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.casefold() != ".md"
                or path.name.casefold() in RESERVED_NAMES
            ):
                continue
            document = parse_document(path, self.root)
            folded = document.concept_id.casefold()
            if previous := folded_paths.get(folded):
                raise OkfError(
                    f"case-folded concept path collision: {previous} and {document.concept_id}"
                )
            folded_paths[folded] = document.concept_id
            documents.append(document)

        return {
            document.concept_id: document
            for document in sorted(documents, key=lambda item: item.concept_id)
        }

    def get(self, concept_id: str) -> OkfDocument:
        concept_path(self.root, concept_id)
        try:
            return self.scan()[concept_id]
        except KeyError as exc:
            raise OkfError(f"concept not found: {concept_id}") from exc

    def list(self, directory: str = "") -> list[ConceptSummary]:
        parent = _concept_directory(directory)
        return [
            ConceptSummary.from_document(document)
            for document in self.scan().values()
            if PurePosixPath(document.concept_id).parent == parent
        ]


def _concept_directory(directory: str) -> PurePosixPath:
    if directory in {"", "."}:
        return PurePosixPath(".")
    path = PurePosixPath(directory)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != directory:
        raise OkfError(f"unsafe concept directory: {directory}")
    return path
