from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.changes import (
    ChangeValidationContext,
    build_prospective_wiki,
    render_draft,
    validate_change_set,
)
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
)
from bundlewalker.errors import ChangeSetError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import parse_document
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.workspace import RawSource, Workspace, initialize_workspace, load_raw_source

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _draft(
    *,
    operation: ChangeOperation = ChangeOperation.CREATE,
    path: str = "topics/agents",
    type: ConceptType = ConceptType.TOPIC,
    body: str = "# Agents\n",
    citations: list[Citation] | None = None,
    base_digest: str | None = None,
    title: str = "Agents",
) -> DraftConcept:
    return DraftConcept(
        operation=operation,
        path=path,
        type=type,
        title=title,
        description="A concise description.",
        tags=["agents"],
        body=body,
        citations=citations or [],
        base_digest=base_digest,
    )


def _write_concept(
    workspace: Workspace,
    concept_id: str,
    *,
    type: str = "Topic",
    title: str = "Existing",
    body: str = "\n# Existing\n",
    extra: str = "",
) -> None:
    path = workspace.wiki_dir / f"{concept_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"type: {type}\n"
        f"title: {title}\n"
        "description: Existing knowledge.\n"
        "tags: [existing]\n"
        f"{extra}"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)


def _raw_source(tmp_path: Path, workspace: Workspace) -> RawSource:
    path = tmp_path / "source.txt"
    path.write_text("line one\nline two\nline three\n", encoding="utf-8")
    return load_raw_source(path, workspace)


def _ingest_context(tmp_path: Path) -> tuple[Workspace, RawSource, ChangeValidationContext]:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    source = _raw_source(tmp_path, workspace)
    return (
        workspace,
        source,
        ChangeValidationContext(
            mode="ingest",
            repository=OkfRepository(workspace.wiki_dir),
            readable_concepts=frozenset(),
            source=source,
        ),
    )


def _valid_source_draft(source: RawSource, *, suffix: str = "") -> DraftConcept:
    return _draft(
        path=f"{source.concept_id}{suffix}",
        type=ConceptType.SOURCE,
        title="Incoming source",
        body="# Incoming source\n\nA source claim [1].\n",
        citations=[
            Citation(
                number=1,
                concept_id=source.concept_id,
                start_line=1,
                end_line=2,
            )
        ],
    )


def _valid_ingest(source: RawSource, *drafts: DraftConcept) -> ChangeSet:
    return ChangeSet(
        summary="Integrated an incoming source.",
        source_sha256=source.sha256,
        drafts=[_valid_source_draft(source), *drafts],
    )


@pytest.mark.parametrize(
    ("draft", "message"),
    [
        (_draft(path="entities/agents", type=ConceptType.TOPIC), "category"),
        (_draft(path="topics/index", type=ConceptType.TOPIC), "reserved"),
    ],
)
def test_validation_rejects_wrong_categories_and_reserved_paths(
    tmp_path: Path,
    draft: DraftConcept,
    message: str,
) -> None:
    workspace, source, context = _ingest_context(tmp_path)

    with pytest.raises(ChangeSetError, match=message):
        validate_change_set(_valid_ingest(source, draft), context)

    assert workspace.wiki_dir.is_dir()


def test_validation_normalizes_optional_markdown_suffixes(tmp_path: Path) -> None:
    _, source, context = _ingest_context(tmp_path)
    change_set = ChangeSet(
        summary="Integrated an incoming source.",
        source_sha256=source.sha256,
        drafts=[_valid_source_draft(source, suffix=".md")],
    )

    validate_change_set(change_set, context)


def test_validation_rejects_normalized_duplicate_paths(tmp_path: Path) -> None:
    _, source, context = _ingest_context(tmp_path)
    first = _draft(path="topics/agents")
    second = _draft(path="topics/agents.md", title="Other agents")

    with pytest.raises(ChangeSetError, match="duplicate"):
        validate_change_set(_valid_ingest(source, first, second), context)


def test_validation_enforces_create_replace_and_base_digest_rules(tmp_path: Path) -> None:
    workspace, source, context = _ingest_context(tmp_path)
    _write_concept(workspace, "topics/existing")
    existing = context.repository.get("topics/existing")

    with pytest.raises(ChangeSetError, match="already exists"):
        validate_change_set(
            _valid_ingest(source, _draft(path="topics/existing")),
            context,
        )
    with pytest.raises(ChangeSetError, match="does not exist"):
        validate_change_set(
            _valid_ingest(
                source,
                _draft(
                    operation=ChangeOperation.REPLACE,
                    path="topics/missing",
                    base_digest="0" * 64,
                ),
            ),
            context,
        )
    with pytest.raises(ChangeSetError, match="stale"):
        validate_change_set(
            _valid_ingest(
                source,
                _draft(
                    operation=ChangeOperation.REPLACE,
                    path="topics/existing",
                    base_digest="0" * 64,
                ),
            ),
            context,
        )

    valid_replacement = _draft(
        operation=ChangeOperation.REPLACE,
        path="topics/existing.md",
        base_digest=existing.digest,
    )
    validate_change_set(_valid_ingest(source, valid_replacement), context)


@pytest.mark.parametrize("source_count", [0, 2])
def test_ingestion_requires_exactly_one_matching_source_draft(
    tmp_path: Path,
    source_count: int,
) -> None:
    _, source, context = _ingest_context(tmp_path)
    source_drafts = [_valid_source_draft(source) for _ in range(source_count)]
    if source_count == 2:
        source_drafts[1] = source_drafts[1].model_copy(update={"path": f"sources/{'f' * 12}-other"})
    change_set = ChangeSet(
        summary="Invalid source cardinality.",
        source_sha256=source.sha256,
        drafts=[*source_drafts, _draft()],
    )

    with pytest.raises(ChangeSetError, match="exactly one Source"):
        validate_change_set(change_set, context)


def test_ingestion_rejects_wrong_source_identity_and_synthesis(tmp_path: Path) -> None:
    _, source, context = _ingest_context(tmp_path)
    wrong_source = _valid_source_draft(source).model_copy(update={"path": "sources/wrong-source"})

    with pytest.raises(ChangeSetError, match="source concept"):
        validate_change_set(
            ChangeSet(
                summary="Wrong identity.",
                source_sha256=source.sha256,
                drafts=[wrong_source],
            ),
            context,
        )
    with pytest.raises(ChangeSetError, match="Synthesis"):
        validate_change_set(
            _valid_ingest(
                source,
                _draft(path="syntheses/answer", type=ConceptType.SYNTHESIS),
            ),
            context,
        )


def test_ingestion_requires_matching_change_set_source_digest(tmp_path: Path) -> None:
    _, source, context = _ingest_context(tmp_path)
    change_set = _valid_ingest(source).model_copy(update={"source_sha256": "0" * 64})

    with pytest.raises(ChangeSetError, match="source_sha256"):
        validate_change_set(change_set, context)


def test_synthesis_requires_one_create_only_synthesis_and_no_source(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    context = ChangeValidationContext(
        mode="synthesis",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
    )

    with pytest.raises(ChangeSetError, match="one create-only Synthesis"):
        validate_change_set(
            ChangeSet(summary="Wrong type.", drafts=[_draft()]),
            context,
        )

    source = _raw_source(tmp_path, workspace)
    invalid_context = ChangeValidationContext(
        mode="synthesis",
        repository=context.repository,
        readable_concepts=frozenset(),
        source=source,
    )
    synthesis = _draft(path="syntheses/answer", type=ConceptType.SYNTHESIS)
    with pytest.raises(ChangeSetError, match="must not include a source"):
        validate_change_set(ChangeSet(summary="Answer.", drafts=[synthesis]), invalid_context)


@pytest.mark.parametrize(
    ("body", "citations", "message"),
    [
        ("# Agents\n\nClaim [1].\n", [], "markers"),
        (
            "# Agents\n",
            [Citation(number=1, concept_id="sources/missing")],
            "markers",
        ),
        (
            "# Agents\n\nClaims [1] and [3].\n",
            [
                Citation(number=1, concept_id="sources/missing"),
                Citation(number=3, concept_id="sources/missing"),
            ],
            "contiguous",
        ),
    ],
)
def test_validation_rejects_missing_extra_and_noncontiguous_citations(
    tmp_path: Path,
    body: str,
    citations: list[Citation],
    message: str,
) -> None:
    _, source, context = _ingest_context(tmp_path)
    topic = _draft(body=body, citations=citations)

    with pytest.raises(ChangeSetError, match=message):
        validate_change_set(_valid_ingest(source, topic), context)


def test_validation_rejects_nonexistent_citation_targets(tmp_path: Path) -> None:
    _, source, context = _ingest_context(tmp_path)
    topic = _draft(
        body="# Agents\n\nClaim [1].\n",
        citations=[Citation(number=1, concept_id="sources/missing")],
    )

    with pytest.raises(ChangeSetError, match="does not exist"):
        validate_change_set(_valid_ingest(source, topic), context)


def test_synthesis_rejects_unread_citations(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    _write_concept(workspace, "topics/agents")
    context = ChangeValidationContext(
        mode="synthesis",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
    )
    synthesis = _draft(
        path="syntheses/answer",
        type=ConceptType.SYNTHESIS,
        body="# Answer\n\nA conclusion [1].\n",
        citations=[Citation(number=1, concept_id="topics/agents")],
    )

    with pytest.raises(ChangeSetError, match="not read"):
        validate_change_set(ChangeSet(summary="Saved answer.", drafts=[synthesis]), context)


@pytest.mark.parametrize(("start", "end"), [(1, 4), (4, 4)])
def test_validation_rejects_source_spans_outside_raw_line_count(
    tmp_path: Path,
    start: int,
    end: int,
) -> None:
    _, source, context = _ingest_context(tmp_path)
    source_draft = _valid_source_draft(source).model_copy(
        update={
            "citations": [
                Citation(
                    number=1,
                    concept_id=source.concept_id,
                    start_line=start,
                    end_line=end,
                )
            ]
        }
    )

    with pytest.raises(ChangeSetError, match=r"lines 1-3"):
        validate_change_set(
            ChangeSet(
                summary="Out-of-range evidence.",
                source_sha256=source.sha256,
                drafts=[source_draft],
            ),
            context,
        )


def test_render_draft_preserves_unknown_metadata_and_normalizes_citations(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    raw_bytes = b"source evidence\n"
    digest = hashlib.sha256(raw_bytes).hexdigest()
    raw_relative = Path(f"raw/{digest[:12]}-evidence.txt")
    (workspace.root / raw_relative).write_bytes(raw_bytes)
    source_id = f"sources/{digest[:12]}-evidence"
    _write_concept(
        workspace,
        source_id,
        type="Source",
        title="Evidence source",
        extra=(
            f"resource: urn:bundlewalker:source:sha256:{digest}\n"
            f"source_sha256: {digest}\n"
            f"raw_path: {raw_relative.as_posix()}\n"
        ),
    )
    _write_concept(
        workspace,
        "topics/agents",
        title="Old title",
        body="\n# Old title\n",
        extra="owner: Hendrik\nreview_state: draft\n",
    )
    repository = OkfRepository(workspace.wiki_dir)
    existing = repository.get("topics/agents")
    context = ChangeValidationContext(
        mode="ingest",
        repository=repository,
        readable_concepts=frozenset({source_id, "topics/agents"}),
        source=None,
    )
    replacement = _draft(
        operation=ChangeOperation.REPLACE,
        path="topics/agents.md",
        title="New title",
        body="# New title\n\nEvidence [1].\n\n# Citations\n\n[99] stale\n",
        citations=[Citation(number=1, concept_id=source_id, start_line=1, end_line=1)],
        base_digest=existing.digest,
    )

    rendered = render_draft(
        replacement,
        context,
        occurred_at=NOW,
        prospective_drafts=(replacement,),
    )
    rendered_path = tmp_path / "rendered.md"
    rendered_path.write_text(rendered, encoding="utf-8")
    parsed = parse_document(rendered_path, tmp_path)

    assert parsed.metadata.type == "Topic"
    assert parsed.metadata.title == "New title"
    assert parsed.metadata.description == "A concise description."
    assert parsed.metadata.tags == ["agents"]
    assert parsed.metadata.timestamp == NOW
    assert parsed.metadata.model_extra == {"owner": "Hendrik", "review_state": "draft"}
    assert "resource:" not in rendered
    assert parsed.body == (
        "# New title\n\nEvidence [1].\n\n"
        "# Citations\n\n"
        f"[1] [Evidence source](/{source_id}.md) — raw lines 1\u20131\n"
    )


def test_build_prospective_wiki_updates_derived_files_and_logs_once(
    tmp_path: Path,
) -> None:
    workspace, source, context = _ingest_context(tmp_path)
    (workspace.root / source.stored_relative_path).write_bytes(source.content)
    change_set = _valid_ingest(
        source,
        _draft(
            path="topics/agents",
            body="# Agents\n\nIncoming evidence [1].\n",
            citations=[
                Citation(
                    number=1,
                    concept_id=source.concept_id,
                    start_line=2,
                    end_line=3,
                )
            ],
        ),
    )
    destination = tmp_path / "prospective"
    before_log = (workspace.wiki_dir / "log.md").read_text(encoding="utf-8")

    build_prospective_wiki(workspace, change_set, context, destination, NOW)

    assert (destination / f"{source.concept_id}.md").is_file()
    assert "[Agents](agents.md)" in (destination / "topics/index.md").read_text(encoding="utf-8")
    after_log = (destination / "log.md").read_text(encoding="utf-8")
    assert after_log.count("Integrated an incoming source.") == 1
    assert after_log.count("* **Update**:") == before_log.count("* **Update**:") + 1


def test_build_prospective_wiki_refuses_deterministic_lint_errors(
    tmp_path: Path,
) -> None:
    workspace, source, context = _ingest_context(tmp_path)
    (workspace.root / source.stored_relative_path).write_bytes(source.content)
    (workspace.wiki_dir / "log.md").write_text(
        "# Knowledge Update Log\n\n## 2026-02-30\n\n* **Update**: Invalid.\n",
        encoding="utf-8",
    )

    with pytest.raises(ChangeSetError, match="LOG001"):
        build_prospective_wiki(
            workspace,
            _valid_ingest(source),
            context,
            tmp_path / "prospective",
            NOW,
        )
