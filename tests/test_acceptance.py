from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from typer.testing import CliRunner

import bundlewalker.workflows.ask as ask_workflow
import bundlewalker.workflows.ingest as ingest_workflow
import bundlewalker.workflows.lint as lint_workflow
from bundlewalker.agents.common import AgentDependencies, read_concept
from bundlewalker.agents.ingest import AgentModel as IngestionModel
from bundlewalker.agents.query import AgentModel as QueryModel
from bundlewalker.agents.semantic_lint import AgentModel as SemanticLintModel
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.cli import app
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    FindingOrigin,
    LintFinding,
    OkfDocument,
    Severity,
)
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import (
    PreparedTransaction,
    ReviewKind,
    prepare_transaction,
    recover_transactions,
)
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import (
    RawSource,
    discover_workspace,
    initialize_workspace,
    load_raw_source,
)

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)
runner = CliRunner()


def _knowledge_bytes(root: Path) -> dict[str, bytes]:
    """Snapshot durable knowledge while excluding transaction-only state."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and not path.is_symlink()
        and ".bundlewalker" not in path.relative_to(root).parts
    }


def _ingestion_change_set(source: RawSource) -> ChangeSet:
    topic_id = "topics/review-first-knowledge"
    return ChangeSet(
        summary="Integrated review-first knowledge.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=source.concept_id,
                type=ConceptType.SOURCE,
                title="Review-first notes",
                description="Notes about a review-first knowledge workflow.",
                tags=["knowledge", "review"],
                body=(
                    "# Review-first notes\n\n"
                    "Durable changes require review [1].\n\n"
                    "See [Review-first knowledge](/topics/review-first-knowledge.md).\n"
                ),
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=2,
                    )
                ],
            ),
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=topic_id,
                type=ConceptType.TOPIC,
                title="Review-first knowledge",
                description="Knowledge changes are reviewed before persistence.",
                tags=["knowledge", "review"],
                body="# Review-first knowledge\n\nDurable changes require review [1].\n",
                citations=[
                    Citation(
                        number=1,
                        concept_id=source.concept_id,
                        start_line=1,
                        end_line=2,
                    )
                ],
            ),
        ],
    )


def _answer() -> CitedAnswer:
    return CitedAnswer(
        title="Why review knowledge changes?",
        body="# Answer\n\nReview keeps durable knowledge changes inspectable [1].\n",
        citations=[Citation(number=1, concept_id="topics/review-first-knowledge")],
    )


def _refreshed_answer() -> CitedAnswer:
    return CitedAnswer(
        title="Why review knowledge changes now?",
        body=("# Updated answer\n\nCurrent evidence still supports inspectable review [1].\n"),
        citations=[Citation(number=1, concept_id="topics/review-first-knowledge")],
    )


def _set_swapping(prepared: PreparedTransaction) -> None:
    manifest_path = prepared.transaction_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase"] = "swapping"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    prepared.workspace.wiki_dir.rename(prepared.backup_wiki)


def _set_accepted(prepared: PreparedTransaction) -> None:
    manifest_path = prepared.transaction_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase"] = "accepted"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prepare_accepted_ingestion(tmp_path: Path) -> tuple[PreparedTransaction, RawSource]:
    workspace = initialize_workspace(tmp_path / "accepted-knowledge", occurred_at=NOW)
    source_path = tmp_path / "accepted-review-notes.txt"
    source_path.write_bytes(b"Accepted review survives interruption.\nSecond line.\n")
    source = load_raw_source(source_path, workspace)
    change_set = _ingestion_change_set(source)
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    _set_accepted(prepared)
    return prepared, source


def test_accepted_review_recovers_to_committed_raw_and_wiki(tmp_path: Path) -> None:
    prepared, source = _prepare_accepted_ingestion(tmp_path)
    prospective = {
        path.relative_to(prepared.prospective_wiki).as_posix(): path.read_bytes()
        for path in sorted(prepared.prospective_wiki.rglob("*"))
        if path.is_file()
    }

    recover_transactions(prepared.workspace)

    live = {
        path.relative_to(prepared.workspace.wiki_dir).as_posix(): path.read_bytes()
        for path in sorted(prepared.workspace.wiki_dir.rglob("*"))
        if path.is_file()
    }
    assert live == prospective
    assert (prepared.workspace.root / source.stored_relative_path).read_bytes() == source.content
    assert not prepared.transaction_dir.exists()


def test_accepted_review_rolls_back_when_live_base_changed(tmp_path: Path) -> None:
    prepared, source = _prepare_accepted_ingestion(tmp_path)
    external = prepared.workspace.wiki_dir / "external.md"
    external.write_text("external live bytes\n", encoding="utf-8")
    knowledge_after_external_edit = _knowledge_bytes(prepared.workspace.root)

    recover_transactions(prepared.workspace)

    assert _knowledge_bytes(prepared.workspace.root) == knowledge_after_external_edit
    assert external.read_bytes() == b"external live bytes\n"
    assert not (prepared.workspace.root / source.stored_relative_path).exists()
    assert not prepared.transaction_dir.exists()


def test_complete_offline_review_first_workflow_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    source_path = tmp_path / "review-notes.txt"
    source_bytes = b"Review every durable change.\r\nKeep the exact source bytes.\n"
    source_path.write_bytes(source_bytes)

    initialized = runner.invoke(app, ["init", str(root)], catch_exceptions=False)
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.chdir(root)

    clean_lint = runner.invoke(app, ["lint"], catch_exceptions=False)
    assert clean_lint.exit_code == 0, clean_lint.output
    assert "No lint findings." in clean_lint.output

    ingestion_calls: list[str] = []

    async def fake_ingestion_runner(
        model: IngestionModel,
        _dependencies: AgentDependencies,
        source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        ingestion_calls.append(str(model))
        assert source.content == source_bytes
        return _ingestion_change_set(source), frozenset()

    monkeypatch.setattr(ingest_workflow, "run_ingestion_agent", fake_ingestion_runner)

    before_decline = _knowledge_bytes(root)
    declined = runner.invoke(
        app,
        ["ingest", str(source_path), "--model", "test:model"],
        input="n\n",
        catch_exceptions=False,
    )
    assert declined.exit_code == 0, declined.output
    assert "--- /dev/null" in declined.output
    assert "+++ wiki/" in declined.output
    assert "No changes applied." in declined.output
    assert _knowledge_bytes(root) == before_decline

    accepted = runner.invoke(
        app,
        ["ingest", str(source_path), "--model", "test:model"],
        input="y\n",
        catch_exceptions=False,
    )
    assert accepted.exit_code == 0, accepted.output
    assert "Changes applied." in accepted.output
    assert ingestion_calls == ["test:model", "test:model"]

    raw_files = list((root / "raw").glob("*.txt"))
    source_pages = [
        path for path in (root / "wiki" / "sources").glob("*.md") if path.name != "index.md"
    ]
    assert len(raw_files) == 1 and raw_files[0].read_bytes() == source_bytes
    assert len(source_pages) == 1
    assert (root / "wiki" / "topics" / "review-first-knowledge.md").is_file()
    assert "Review-first knowledge" in (root / "wiki" / "topics" / "index.md").read_text(
        encoding="utf-8"
    )
    assert "Integrated review-first knowledge." in (root / "wiki" / "log.md").read_text(
        encoding="utf-8"
    )
    assert not has_errors(lint_bundle(root / "wiki", root))

    duplicate = runner.invoke(
        app,
        ["ingest", str(source_path)],
        catch_exceptions=False,
    )
    assert duplicate.exit_code == 0, duplicate.output
    assert "already ingested" in duplicate.output
    assert ingestion_calls == ["test:model", "test:model"]

    query_calls: list[str] = []
    pending_recovery: PreparedTransaction | None = None

    async def fake_query_runner(
        model: QueryModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        query_calls.append(f"{model}:{question}")
        if pending_recovery is not None:
            assert (root / "wiki").is_dir()
            assert not pending_recovery.transaction_dir.exists()
        read_result = read_concept(
            RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
            "topics/review-first-knowledge",
        )
        assert "error" not in read_result
        return _answer(), frozenset({"topics/review-first-knowledge"})

    monkeypatch.setattr(ask_workflow, "run_query_agent", fake_query_runner)

    before_ask = _knowledge_bytes(root)
    asked = runner.invoke(
        app,
        ["ask", "Why review knowledge changes?", "--model", "test:model"],
        catch_exceptions=False,
    )
    assert asked.exit_code == 0, asked.output
    assert "inspectable [1]" in asked.output
    assert "[1] [Review-first knowledge](/topics/review-first-knowledge.md)" in asked.output
    assert len(query_calls) == 1
    assert _knowledge_bytes(root) == before_ask

    before_save_decline = _knowledge_bytes(root)
    declined_save = runner.invoke(
        app,
        ["ask", "Why review knowledge changes?", "--model", "test:model", "--save"],
        input="n\n",
        catch_exceptions=False,
    )
    assert declined_save.exit_code == 0, declined_save.output
    assert "Saved synthesis: Why review knowledge changes?" in declined_save.output
    assert len(query_calls) == 2
    assert _knowledge_bytes(root) == before_save_decline

    accepted_save = runner.invoke(
        app,
        ["ask", "Why review knowledge changes?", "--model", "test:model", "--save"],
        input="y\n",
        catch_exceptions=False,
    )
    assert accepted_save.exit_code == 0, accepted_save.output
    assert len(query_calls) == 3
    synthesis_path = root / "wiki" / "syntheses" / "why-review-knowledge-changes.md"
    assert synthesis_path.is_file()

    refresh_calls: list[str] = []

    async def fake_refresh_runner(
        model: QueryModel,
        dependencies: AgentDependencies,
        question: str,
        target: OkfDocument,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        refresh_calls.append(f"{model}:{question}")
        assert target.concept_id == "syntheses/why-review-knowledge-changes"
        assert "Review keeps durable knowledge changes inspectable" in target.body
        read_result = read_concept(
            RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
            "topics/review-first-knowledge",
        )
        assert "error" not in read_result
        return _refreshed_answer(), frozenset({"topics/review-first-knowledge"})

    monkeypatch.setattr(ask_workflow, "run_refresh_query_agent", fake_refresh_runner)

    before_refresh_decline = _knowledge_bytes(root)
    declined_refresh = runner.invoke(
        app,
        [
            "ask",
            "Refresh the saved synthesis with current evidence.",
            "--model",
            "test:model",
            "--refresh",
            "syntheses/why-review-knowledge-changes",
        ],
        input="n\n",
        catch_exceptions=False,
    )
    assert declined_refresh.exit_code == 0, declined_refresh.output
    assert "--- wiki/syntheses/why-review-knowledge-changes.md" in declined_refresh.output
    assert "+++ wiki/syntheses/why-review-knowledge-changes.md" in declined_refresh.output
    assert "No changes applied." in declined_refresh.output
    assert refresh_calls == ["test:model:Refresh the saved synthesis with current evidence."]
    assert _knowledge_bytes(root) == before_refresh_decline

    accepted_refresh = runner.invoke(
        app,
        [
            "ask",
            "Refresh the saved synthesis with current evidence.",
            "--model",
            "test:model",
            "--refresh",
            "syntheses/why-review-knowledge-changes",
        ],
        input="y\n",
        catch_exceptions=False,
    )
    assert accepted_refresh.exit_code == 0, accepted_refresh.output
    assert len(refresh_calls) == 2
    refreshed_text = synthesis_path.read_text(encoding="utf-8")
    assert "title: Why review knowledge changes now?" in refreshed_text
    assert "Current evidence still supports inspectable review [1]." in refreshed_text
    assert "[1] [Review-first knowledge](/topics/review-first-knowledge.md)" in refreshed_text
    assert "Refreshed synthesis: Why review knowledge changes now?" in (
        root / "wiki" / "log.md"
    ).read_text(encoding="utf-8")
    assert not has_errors(lint_bundle(root / "wiki", root))

    semantic_calls: list[str] = []

    async def fake_semantic_runner(
        model: SemanticLintModel,
        dependencies: AgentDependencies,
        _findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        semantic_calls.append(str(model))
        read_result = read_concept(
            RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
            "topics/review-first-knowledge",
        )
        assert "error" not in read_result
        return (
            [
                LintFinding(
                    origin=FindingOrigin.SEMANTIC,
                    severity=Severity.INFO,
                    code="SEM-GAP",
                    message="A related comparison could deepen the topic.",
                    evidence_paths=["topics/review-first-knowledge"],
                )
            ],
            frozenset({"topics/review-first-knowledge"}),
        )

    monkeypatch.setattr(lint_workflow, "run_semantic_lint_agent", fake_semantic_runner)
    before_semantic_lint = _knowledge_bytes(root)
    semantic_lint = runner.invoke(
        app,
        ["lint", "--semantic", "--model", "test:model"],
        catch_exceptions=False,
    )
    assert semantic_lint.exit_code == 0, semantic_lint.output
    assert "SEM-GAP" in semantic_lint.output
    assert semantic_calls == ["test:model"]
    assert _knowledge_bytes(root) == before_semantic_lint

    workspace = discover_workspace(root)
    legacy = prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Legacy prepared synthesis",
                body="# Legacy prepared synthesis\n\nReview is inspectable [1].\n",
                citations=[Citation(number=1, concept_id="topics/review-first-knowledge")],
            ),
            read_ids=frozenset({"topics/review-first-knowledge"}),
        ),
        occurred_at=NOW,
    )
    legacy_knowledge = _knowledge_bytes(root)
    legacy_manifest_path = legacy.transaction_dir / "manifest.json"
    legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
    legacy_manifest["schema_version"] = 1
    legacy_manifest_path.write_text(
        json.dumps(legacy_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    legacy_identity_path = legacy.transaction_dir / "identity.json"
    legacy_identity = json.loads(legacy_identity_path.read_text(encoding="utf-8"))
    legacy_identity.pop("review_digest")
    legacy_identity_path.write_text(
        json.dumps(legacy_identity, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    recover_transactions(workspace)

    assert _knowledge_bytes(root) == legacy_knowledge
    assert not legacy.transaction_dir.exists()

    interrupted = prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Interrupted synthesis",
                body="# Interrupted synthesis\n\nReview is inspectable [1].\n",
                citations=[Citation(number=1, concept_id="topics/review-first-knowledge")],
            ),
            read_ids=frozenset({"topics/review-first-knowledge"}),
        ),
        occurred_at=NOW,
    )
    live_before_interruption = _knowledge_bytes(root)
    _set_swapping(interrupted)
    pending_recovery = interrupted
    assert not workspace.wiki_dir.exists()
    assert interrupted.backup_wiki.is_dir()

    recovered_then_asked = runner.invoke(
        app,
        ["ask", "Why review knowledge changes?", "--model", "test:model"],
        catch_exceptions=False,
    )
    assert recovered_then_asked.exit_code == 0, recovered_then_asked.output
    assert "inspectable [1]" in recovered_then_asked.output
    assert len(query_calls) == 4
    assert ingestion_calls == ["test:model", "test:model"]
    assert _knowledge_bytes(root) == live_before_interruption
    assert not interrupted.transaction_dir.exists()
