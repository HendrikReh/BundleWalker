from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import bundlewalker.workflows.ingest as ingest_workflow
from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.ingest import AgentModel
from bundlewalker.cli import app
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.workspace import RawSource, initialize_workspace

runner = CliRunner()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def test_ingest_help_does_not_require_a_workspace() -> None:
    result = runner.invoke(app, ["ingest", "--help"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert "FILE" in result.output
    assert "--model" in result.output


async def _runner(
    _model: AgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    return (
        ChangeSet(
            summary="Integrated CLI notes.",
            source_sha256=source.sha256,
            drafts=[
                DraftConcept(
                    operation=ChangeOperation.CREATE,
                    path=source.concept_id,
                    type=ConceptType.SOURCE,
                    title="CLI Notes",
                    description="Notes ingested through the CLI.",
                    tags=["cli"],
                    body="# CLI Notes\n\nA claim from the source [1].\n",
                    citations=[
                        Citation(
                            number=1,
                            concept_id=source.concept_id,
                            start_line=1,
                            end_line=1,
                        )
                    ],
                ),
                DraftConcept(
                    operation=ChangeOperation.CREATE,
                    path="topics/cli-notes",
                    type=ConceptType.TOPIC,
                    title="CLI Notes",
                    description="Accumulated CLI knowledge.",
                    tags=["cli"],
                    body="# CLI Notes\n\nA topic claim [1].\n",
                    citations=[
                        Citation(
                            number=1,
                            concept_id=source.concept_id,
                            start_line=1,
                            end_line=1,
                        )
                    ],
                ),
            ],
        ),
        frozenset(),
    )


@pytest.fixture
def cli_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    workspace = initialize_workspace(tmp_path / "knowledge")
    source = tmp_path / "notes.txt"
    source.write_bytes(b"source bytes exactly\n")
    monkeypatch.chdir(workspace.root)
    monkeypatch.setattr(ingest_workflow, "run_ingestion_agent", _runner)
    return workspace.root, source


@pytest.mark.parametrize("confirmation", ["n\n", ""])
def test_ingest_decline_or_framework_abort_discards_review_and_exits_zero(
    cli_workspace: tuple[Path, Path],
    confirmation: str,
) -> None:
    root, source = cli_workspace
    before_wiki = _tree_bytes(root / "wiki")
    before_raw = _tree_bytes(root / "raw")

    result = runner.invoke(
        app,
        ["ingest", str(source), "--model", "test:model"],
        input=confirmation,
    )

    assert result.exit_code == 0, result.output
    assert "Integrated CLI notes." in result.output
    assert "--- wiki/" in result.output and "+++ wiki/" in result.output
    assert "Review ID:" not in result.output
    assert "No changes applied." in result.output
    assert "Aborted" not in result.output
    assert _tree_bytes(root / "wiki") == before_wiki
    assert _tree_bytes(root / "raw") == before_raw
    assert not list((root / ".bundlewalker" / "transactions").glob("*"))


def test_ingest_acceptance_commits_raw_wiki_indexes_and_log(
    cli_workspace: tuple[Path, Path],
) -> None:
    root, source = cli_workspace

    result = runner.invoke(
        app,
        ["ingest", str(source), "--model", "test:model"],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert "Integrated CLI notes." in result.output
    assert "--- wiki/" in result.output and "+++ wiki/" in result.output
    raw_files = list((root / "raw").glob("*.txt"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == source.read_bytes()
    assert len(list((root / "wiki" / "sources").glob("*.md"))) == 2
    assert (root / "wiki" / "topics" / "cli-notes.md").is_file()
    assert "CLI Notes" in (root / "wiki" / "topics" / "index.md").read_text()
    assert "Integrated CLI notes." in (root / "wiki" / "log.md").read_text()
    assert not has_errors(lint_bundle(root / "wiki", root))


def test_invalid_ingest_output_exits_one_without_live_changes(
    cli_workspace: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, source = cli_workspace
    before_wiki = _tree_bytes(root / "wiki")
    before_raw = _tree_bytes(root / "raw")

    async def invalid_runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        raw_source: RawSource,
    ) -> tuple[ChangeSet, frozenset[str]]:
        change_set, read_ids = await _runner(model, dependencies, raw_source)
        return change_set.model_copy(update={"source_sha256": "f" * 64}), read_ids

    monkeypatch.setattr(ingest_workflow, "run_ingestion_agent", invalid_runner)

    result = runner.invoke(
        app,
        ["ingest", str(source), "--model", "test:model"],
        input="y\n",
    )

    assert result.exit_code == 1
    assert "source_sha256" in result.output
    assert "Apply these changes?" not in result.output
    assert _tree_bytes(root / "wiki") == before_wiki
    assert _tree_bytes(root / "raw") == before_raw
