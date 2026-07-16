from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

from pydantic import ValidationError

from bundlewalker.domain import (
    MAX_CITATIONS,
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
    OkfDocument,
    OkfMetadata,
)
from bundlewalker.errors import ChangeSetError, OkfError
from bundlewalker.okf.derived import prepend_log_entry, regenerate_indexes
from bundlewalker.okf.documents import concept_path, render_document
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.workspace import RawSource, Workspace

_CITATION_MARKER = re.compile(r"\[(\d+)]")
_CITATION_HEADING = re.compile(r"^# Citations[ \t]*$", re.MULTILINE)
_CATEGORY_BY_TYPE = {
    ConceptType.SOURCE: "sources",
    ConceptType.TOPIC: "topics",
    ConceptType.ENTITY: "entities",
    ConceptType.SYNTHESIS: "syntheses",
}
_SOURCE_EXTENSION_FIELDS = frozenset({"source_sha256", "raw_path"})
_CANONICAL_DRAFT_PATH = re.compile(
    r"^(?:sources|topics|entities|syntheses)/[a-z0-9]+(?:-[a-z0-9]+)*$"
)
_MAX_CITATION_DIGITS = len(str(MAX_CITATIONS))
_MAX_CITATION_MARKERS = 1_000


@dataclass(frozen=True, slots=True)
class ChangeValidationContext:
    mode: Literal["ingest", "synthesis"]
    repository: OkfRepository
    readable_concepts: frozenset[str]
    source: RawSource | None = None


def validate_change_set(
    change_set: ChangeSet,
    context: ChangeValidationContext,
) -> None:
    """Validate a model-produced proposal against live and prospective concepts."""
    try:
        change_set = ChangeSet.model_validate(change_set.model_dump(mode="python"))
    except ValidationError as exc:
        raise ChangeSetError("change set exceeds producer limits or has invalid fields") from exc
    try:
        live_documents = context.repository.scan()
    except OkfError as exc:
        raise ChangeSetError(f"cannot validate against the current wiki: {exc}") from exc

    normalized_drafts: dict[str, DraftConcept] = {}
    folded_drafts: dict[str, str] = {}
    for draft in change_set.drafts:
        concept_id = _normalized_draft_path(draft.path)
        if concept_id in normalized_drafts:
            raise ChangeSetError(f"change set contains duplicate path: {concept_id}")
        folded_id = concept_id.casefold()
        if previous := folded_drafts.get(folded_id):
            raise ChangeSetError(
                f"change set contains a case-fold path collision: {previous} and {concept_id}"
            )
        normalized_drafts[concept_id] = draft
        folded_drafts[folded_id] = concept_id

    for concept_id, draft in normalized_drafts.items():
        _validate_category(concept_id, draft.type)
        _validate_operation(concept_id, draft, live_documents)

    _validate_mode(change_set, context, normalized_drafts, live_documents)
    _validate_citations(context, normalized_drafts, live_documents)


def render_draft(
    draft: DraftConcept,
    context: ChangeValidationContext,
    *,
    occurred_at: datetime,
    prospective_drafts: Iterable[DraftConcept] = (),
) -> str:
    """Render one validated draft as deterministic OKF Markdown."""
    concept_id = _normalized_draft_path(draft.path)
    live_documents = context.repository.scan()
    existing = live_documents.get(concept_id)
    prospective_by_id = {
        _normalized_draft_path(candidate.path): candidate for candidate in prospective_drafts
    }

    extras = dict(existing.metadata.model_extra or {}) if existing is not None else {}
    for field in _SOURCE_EXTENSION_FIELDS:
        extras.pop(field, None)

    metadata_values: dict[str, object] = {
        **extras,
        "type": draft.type.value,
        "title": draft.title,
        "description": draft.description,
        "tags": draft.tags,
        "timestamp": occurred_at,
    }
    if draft.type is ConceptType.SOURCE:
        source = context.source
        if source is None or concept_id != source.concept_id:
            raise ChangeSetError("Source drafts require their matching raw source")
        metadata_values.update(
            {
                "resource": f"urn:bundlewalker:source:sha256:{source.sha256}",
                "source_sha256": source.sha256,
                "raw_path": source.stored_relative_path.as_posix(),
            }
        )

    metadata = OkfMetadata.model_validate(metadata_values)
    body = _claims_body(draft.body).rstrip()
    if draft.citations:
        references = [
            _render_citation(
                citation,
                live_documents=live_documents,
                prospective_drafts=prospective_by_id,
            )
            for citation in sorted(draft.citations, key=lambda item: item.number)
        ]
        body = f"{body}\n\n# Citations\n\n" + "\n".join(references)
    return render_document(metadata, f"{body}\n")


def build_prospective_wiki(
    workspace: Workspace,
    change_set: ChangeSet,
    context: ChangeValidationContext,
    destination: Path,
    occurred_at: datetime,
) -> None:
    """Build and lint the complete wiki tree that a proposal would produce."""
    validate_change_set(change_set, context)
    _validate_destination_location(workspace.root, destination)
    _require_empty_destination(destination)
    _validate_copy_symlinks(workspace.wiki_dir)
    try:
        shutil.copytree(
            workspace.wiki_dir,
            destination,
            dirs_exist_ok=destination.exists(),
            symlinks=False,
        )
        for draft in change_set.drafts:
            target = concept_path(destination, _normalized_draft_path(draft.path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                render_draft(
                    draft,
                    context,
                    occurred_at=occurred_at,
                    prospective_drafts=change_set.drafts,
                ),
                encoding="utf-8",
            )
        regenerate_indexes(destination)
        prepend_log_entry(destination, change_set.summary, date=occurred_at)
    except (OSError, OkfError) as exc:
        raise ChangeSetError(f"could not build prospective wiki: {exc}") from exc

    findings = lint_bundle(destination, workspace.root)
    if has_errors(findings):
        codes = ", ".join(sorted({item.code for item in findings if item.severity == "error"}))
        raise ChangeSetError(f"prospective wiki failed deterministic lint: {codes}")


def _normalized_draft_path(value: str) -> str:
    if _CANONICAL_DRAFT_PATH.fullmatch(value) is None:
        raise ChangeSetError(
            f"concept path must be canonical <category>/<lowercase-ascii-slug>: {value}"
        )
    try:
        concept_path(Path("/bundle"), value)
    except OkfError as exc:
        raise ChangeSetError(str(exc)) from exc
    return value


def _validate_category(concept_id: str, concept_type: ConceptType) -> None:
    parts = PurePosixPath(concept_id).parts
    expected = _CATEGORY_BY_TYPE[concept_type]
    if not parts or parts[0] != expected:
        raise ChangeSetError(
            f"{concept_type.value} path must be in the {expected} category: {concept_id}"
        )
    if len(parts) < 2:
        raise ChangeSetError(
            f"{concept_type.value} path must include a concept name below {expected}: {concept_id}"
        )


def _validate_operation(
    concept_id: str,
    draft: DraftConcept,
    live_documents: dict[str, OkfDocument],
) -> None:
    existing = live_documents.get(concept_id)
    folded_existing = {item.casefold(): item for item in live_documents}
    if draft.operation is ChangeOperation.CREATE:
        collision = folded_existing.get(concept_id.casefold())
        if collision is not None:
            raise ChangeSetError(f"create target already exists: {collision}")
        return
    if existing is None:
        raise ChangeSetError(f"replace target does not exist: {concept_id}")
    if draft.base_digest != existing.digest:
        raise ChangeSetError(f"replace target has a stale base digest: {concept_id}")


def _validate_mode(
    change_set: ChangeSet,
    context: ChangeValidationContext,
    normalized_drafts: dict[str, DraftConcept],
    live_documents: dict[str, OkfDocument],
) -> None:
    if context.mode == "ingest":
        source = context.source
        if source is None:
            raise ChangeSetError("ingestion validation requires a raw source")
        if change_set.source_sha256 != source.sha256:
            raise ChangeSetError("change set source_sha256 does not match the raw source")
        source_drafts = [
            (concept_id, draft)
            for concept_id, draft in normalized_drafts.items()
            if draft.type is ConceptType.SOURCE
        ]
        if len(source_drafts) != 1:
            raise ChangeSetError("ingestion requires exactly one Source draft")
        if source_drafts[0][0] != source.concept_id:
            raise ChangeSetError(
                f"ingestion Source path must match source concept: {source.concept_id}"
            )
        if any(draft.type is ConceptType.SYNTHESIS for draft in normalized_drafts.values()):
            raise ChangeSetError("ingestion cannot create a Synthesis concept")
        return

    if context.mode != "synthesis":
        raise ChangeSetError(f"unknown change validation mode: {context.mode}")
    if context.source is not None or change_set.source_sha256 is not None:
        raise ChangeSetError("synthesis validation must not include a source")
    draft_items = list(normalized_drafts.items())
    if len(draft_items) != 1 or draft_items[0][1].type is not ConceptType.SYNTHESIS:
        raise ChangeSetError("synthesis mode requires exactly one Synthesis draft")

    concept_id, draft = draft_items[0]
    if draft.operation is ChangeOperation.REPLACE:
        existing = live_documents.get(concept_id)
        if existing is None or existing.metadata.type != ConceptType.SYNTHESIS.value:
            raise ChangeSetError("synthesis replacement target must be an existing Synthesis")


def _validate_citations(
    context: ChangeValidationContext,
    normalized_drafts: dict[str, DraftConcept],
    live_documents: dict[str, OkfDocument],
) -> None:
    prospective_types = {
        concept_id: draft.type.value for concept_id, draft in normalized_drafts.items()
    }
    live_types = {
        concept_id: document.metadata.type for concept_id, document in live_documents.items()
    }

    for concept_id, draft in normalized_drafts.items():
        claims = _claims_body(draft.body)
        markers = _bounded_marker_numbers(claims, concept_id)
        marker_order = list(dict.fromkeys(markers))
        citation_numbers = [citation.number for citation in draft.citations]
        all_numbers = sorted(set(markers) | set(citation_numbers))
        expected = list(range(1, max(all_numbers) + 1)) if all_numbers else []
        if all_numbers != expected or (marker_order and marker_order != expected):
            raise ChangeSetError(f"citation numbers must be contiguous starting at 1: {concept_id}")
        if set(markers) != set(citation_numbers) or len(citation_numbers) != len(
            set(citation_numbers)
        ):
            raise ChangeSetError(
                f"citation markers do not match structured citations: {concept_id}"
            )

        for citation in draft.citations:
            live_type = live_types.get(citation.concept_id)
            if context.mode == "synthesis":
                if draft.operation is ChangeOperation.REPLACE and citation.concept_id == concept_id:
                    raise ChangeSetError(f"synthesis replacement cannot cite itself: {concept_id}")
                if live_type is None:
                    raise ChangeSetError(
                        "synthesis citation must target an existing live concept: "
                        f"{citation.concept_id}"
                    )
                if citation.concept_id not in context.readable_concepts:
                    raise ChangeSetError(
                        f"synthesis citation target was not read: {citation.concept_id}"
                    )
                target_type = live_type
            else:
                target_type = prospective_types.get(citation.concept_id) or live_type
            if target_type is None:
                raise ChangeSetError(f"citation target does not exist: {citation.concept_id}")
            if citation.start_line is None:
                continue
            if target_type != ConceptType.SOURCE.value:
                raise ChangeSetError(
                    f"citation line range must target a Source: {citation.concept_id}"
                )
            source = context.source
            if source is not None and citation.concept_id == source.concept_id:
                assert citation.end_line is not None
                if citation.end_line > source.line_count:
                    raise ChangeSetError(
                        "citation span is outside raw source lines "
                        f"1-{source.line_count}: {citation.concept_id}"
                    )


def _claims_body(body: str) -> str:
    heading = _CITATION_HEADING.search(body)
    return body if heading is None else body[: heading.start()]


def _bounded_marker_numbers(body: str, concept_id: str) -> list[int]:
    numbers: list[int] = []
    for count, match in enumerate(_CITATION_MARKER.finditer(body), start=1):
        if count > _MAX_CITATION_MARKERS:
            raise ChangeSetError(f"too many citation markers: {concept_id}")
        digits = match.group(1)
        if len(digits) > _MAX_CITATION_DIGITS:
            raise ChangeSetError(f"citation number exceeds supported limits: {concept_id}")
        number = int(digits)
        if number < 1 or number > MAX_CITATIONS:
            raise ChangeSetError(f"citation number exceeds supported limits: {concept_id}")
        numbers.append(number)
    return numbers


def _render_citation(
    citation: Citation,
    *,
    live_documents: dict[str, OkfDocument],
    prospective_drafts: dict[str, DraftConcept],
) -> str:
    prospective = prospective_drafts.get(citation.concept_id)
    existing = live_documents.get(citation.concept_id)
    if prospective is not None:
        title = prospective.title
    elif existing is not None:
        title = existing.metadata.title or PurePosixPath(citation.concept_id).name
    else:
        raise ChangeSetError(f"citation target does not exist: {citation.concept_id}")
    escaped_title = title.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")
    target = quote(f"/{citation.concept_id}.md", safe="/")
    rendered = f"[{citation.number}] [{escaped_title}]({target})"
    if citation.start_line is not None:
        assert citation.end_line is not None
        rendered += f" — raw lines {citation.start_line}\u2013{citation.end_line}"
    return rendered


def _require_empty_destination(destination: Path) -> None:
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ChangeSetError(f"prospective destination must be an empty directory: {destination}")
    if destination.is_dir():
        try:
            if any(destination.iterdir()):
                raise ChangeSetError(f"prospective destination must be empty: {destination}")
        except OSError as exc:
            raise ChangeSetError(
                f"could not inspect prospective destination: {destination}"
            ) from exc


def _validate_destination_location(workspace_root: Path, destination: Path) -> None:
    resolved_workspace = workspace_root.resolve(strict=False)
    resolved_destination = destination.resolve(strict=False)
    if resolved_destination.is_relative_to(resolved_workspace):
        raise ChangeSetError(
            "prospective destination must be outside the live workspace and "
            f"outside the live wiki: {destination}"
        )


def _validate_copy_symlinks(root: Path) -> None:
    resolved_root = root.resolve(strict=False)
    try:
        paths = root.rglob("*")
        for path in paths:
            if not path.is_symlink():
                continue
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ChangeSetError(f"wiki contains an unsafe symlink: {path}") from exc
            if not target.is_relative_to(resolved_root):
                raise ChangeSetError(f"wiki symlink escapes the bundle: {path}")
    except OSError as exc:
        raise ChangeSetError(f"could not inspect wiki links: {root}") from exc
