# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from bundlewalker.agents.common import AgentDependencies, read_concept
from bundlewalker.agents.semantic_lint import AgentModel
from bundlewalker.domain import (
    Citation,
    CitedAnswer,
    FindingOrigin,
    LintFinding,
    OkfMetadata,
    Severity,
)
from bundlewalker.errors import AgentRunError, WorkspaceError
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import get_pending_review
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workflows.lint import LintRun, run_lint
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _workspace(tmp_path: Path, *, regenerate: bool) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    (workspace.wiki_dir / "topics" / "agents.md").write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    if regenerate:
        regenerate_indexes(workspace.wiki_dir)
    return workspace


def _read(dependencies: AgentDependencies, concept_id: str) -> None:
    result = read_concept(
        RunContext(deps=dependencies, model=TestModel(), usage=RunUsage()),
        concept_id,
    )
    assert "error" not in result


async def test_plain_lint_without_pending_transaction_is_sorted_offline_and_read_only(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, regenerate=False)
    workspace.conventions_file.unlink()
    before = _tree_bytes(workspace.root)

    result = await run_lint(
        workspace,
        semantic=False,
        explicit_model=None,
        environment={},
    )

    assert isinstance(result, LintRun)
    assert result.deterministic_has_errors is True
    assert [(finding.severity, finding.code) for finding in result.findings] == [
        (Severity.ERROR, "INDEX001"),
        (Severity.WARNING, "ORPHAN001"),
    ]
    assert all(finding.origin is FindingOrigin.DETERMINISTIC for finding in result.findings)
    assert _tree_bytes(workspace.root) == before


async def test_plain_lint_recovers_authenticated_swap_before_scanning(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, regenerate=True)
    prepared = prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Interrupted lint fixture",
                body="Agents use tools [1].",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    expected_wiki = _tree_bytes(workspace.wiki_dir)
    manifest_path = prepared.transaction_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase"] = "swapping"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    workspace.wiki_dir.rename(prepared.backup_wiki)

    result = await run_lint(
        workspace,
        semantic=False,
        explicit_model=None,
        environment={},
    )

    assert result.deterministic_has_errors is False
    assert workspace.wiki_dir.is_dir()
    assert _tree_bytes(workspace.wiki_dir) == expected_wiki
    assert not prepared.transaction_dir.exists()


@pytest.mark.parametrize("semantic", [False, True], ids=["plain", "semantic"])
async def test_lint_leaves_a_pending_review_untouched(
    tmp_path: Path,
    semantic: bool,
) -> None:
    workspace = _workspace(tmp_path, regenerate=True)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Pending lint fixture",
                body="Agents use tools [1].",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    pending = get_pending_review(workspace)
    assert pending is not None

    async def semantic_runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        _read(dependencies, "topics/agents")
        return [], frozenset({"topics/agents"})

    await run_lint(
        workspace,
        semantic=semantic,
        explicit_model="test:model" if semantic else None,
        environment={},
        runner=semantic_runner if semantic else None,
    )

    current = get_pending_review(workspace)
    assert current is not None
    assert current.review_id == pending.review_id


async def test_semantic_lint_runs_after_deterministic_lint_and_stays_advisory(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, regenerate=True)
    before = _tree_bytes(workspace.root)
    calls: list[tuple[str, tuple[str, ...]]] = []

    async def runner(
        model: AgentModel,
        dependencies: AgentDependencies,
        deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        calls.append((str(model), tuple(finding.code for finding in deterministic_findings)))
        assert dependencies.root_index.startswith("# Knowledge Index")
        _read(dependencies, "topics/agents")
        return (
            [
                LintFinding(
                    origin=FindingOrigin.DETERMINISTIC,
                    severity=Severity.ERROR,
                    code="SEM-GAP",
                    path="topics/agents.md",
                    message="The topic could use another source.",
                    evidence_paths=["topics/agents"],
                )
            ],
            frozenset({"topics/agents"}),
        )

    result = await run_lint(
        workspace,
        semantic=True,
        explicit_model="test:model",
        environment={},
        runner=runner,
    )

    assert calls == [("test:model", ("ORPHAN001",))]
    assert result.deterministic_has_errors is False
    assert [(finding.origin, finding.code) for finding in result.findings] == [
        (FindingOrigin.SEMANTIC, "SEM-GAP"),
        (FindingOrigin.DETERMINISTIC, "ORPHAN001"),
    ]
    assert _tree_bytes(workspace.root) == before


async def test_semantic_lint_revalidates_injected_runner_read_evidence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, regenerate=True)

    async def lying_runner(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        return (
            [
                LintFinding(
                    origin=FindingOrigin.SEMANTIC,
                    severity=Severity.INFO,
                    code="SEM-GAP",
                    message="Unread evidence.",
                    evidence_paths=["topics/agents"],
                )
            ],
            frozenset({"topics/agents"}),
        )

    with pytest.raises(AgentRunError, match="read history"):
        await run_lint(
            workspace,
            semantic=True,
            explicit_model="test:model",
            environment={},
            runner=lying_runner,
        )


@pytest.mark.parametrize(
    "forged_id",
    ["topics/agents", "topics/missing"],
    ids=["existing-unread", "nonexistent"],
)
async def test_semantic_lint_rejects_public_read_ledger_forgery(
    tmp_path: Path,
    forged_id: str,
) -> None:
    workspace = _workspace(tmp_path, regenerate=True)

    async def forging_runner(
        _model: AgentModel,
        dependencies: AgentDependencies,
        _deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        dependencies.read_ids.add(forged_id)
        return (
            [
                LintFinding(
                    origin=FindingOrigin.SEMANTIC,
                    severity=Severity.INFO,
                    code="SEM-GAP",
                    message="Forged evidence.",
                    evidence_paths=[forged_id],
                )
            ],
            frozenset({forged_id}),
        )

    with pytest.raises(AgentRunError, match="audit"):
        await run_lint(
            workspace,
            semantic=True,
            explicit_model="test:model",
            environment={},
            runner=forging_runner,
        )


async def test_semantic_lint_skips_agent_when_deterministic_parsing_is_unusable(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    (workspace.wiki_dir / "topics" / "broken.md").write_text(
        "---\ntitle: Missing type\n---\n# Broken\n",
        encoding="utf-8",
    )
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("unusable repository reached semantic agent")

    result = await run_lint(
        workspace,
        semantic=True,
        explicit_model="test:model",
        environment={},
        runner=must_not_run,
    )

    assert result.deterministic_has_errors is True
    assert any(finding.code == "OKF001" for finding in result.findings)
    assert calls == 0


async def test_semantic_lint_refuses_symlinked_protected_context_before_runner(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, regenerate=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("secret", encoding="utf-8")
    workspace.conventions_file.unlink()
    workspace.conventions_file.symlink_to(outside)
    calls = 0

    async def must_not_run(
        _model: AgentModel,
        _dependencies: AgentDependencies,
        _deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        nonlocal calls
        calls += 1
        raise AssertionError("unsafe context reached semantic agent")

    with pytest.raises(WorkspaceError, match="regular file"):
        await run_lint(
            workspace,
            semantic=True,
            explicit_model="test:model",
            environment={},
            runner=must_not_run,
        )

    assert calls == 0
