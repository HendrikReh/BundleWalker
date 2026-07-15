from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from bundlewalker.agents.common import AgentDependencies, resolve_model
from bundlewalker.agents.semantic_lint import (
    AgentModel,
    run_semantic_lint_agent,
    validate_semantic_findings,
)
from bundlewalker.domain import LintFinding, OkfDocument, Severity
from bundlewalker.errors import AgentRunError, OkfError
from bundlewalker.okf.lint import has_errors, lint_bundle
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.retrieval import LexicalRetriever
from bundlewalker.transactions import recover_transactions
from bundlewalker.workflows.context import read_context, validate_repository_path
from bundlewalker.workspace import Workspace

type SemanticLintRunner = Callable[
    [AgentModel, AgentDependencies, tuple[LintFinding, ...]],
    Awaitable[tuple[list[LintFinding], frozenset[str]]],
]

_SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


@dataclass(frozen=True, slots=True)
class LintRun:
    findings: tuple[LintFinding, ...]
    deterministic_has_errors: bool


async def run_lint(
    workspace: Workspace,
    *,
    semantic: bool,
    explicit_model: str | None,
    environment: Mapping[str, str] | None = None,
    runner: SemanticLintRunner | None = None,
) -> LintRun:
    """Run deterministic lint and, when requested, one read-only semantic pass."""
    recover_transactions(workspace)
    deterministic_findings = tuple(lint_bundle(workspace.wiki_dir, workspace.root))
    deterministic_has_errors = has_errors(deterministic_findings)
    if not semantic:
        return _lint_run(deterministic_findings, deterministic_has_errors)

    model = resolve_model(
        explicit_model,
        environment if environment is not None else os.environ,
    )
    if _deterministic_parsing_is_unusable(deterministic_findings):
        return _lint_run(deterministic_findings, deterministic_has_errors)

    validate_repository_path(workspace)
    repository, audited_reads = _audited_repository(workspace.wiki_dir)
    try:
        repository.scan()
    except OkfError:
        return _lint_run(deterministic_findings, deterministic_has_errors)

    conventions = read_context(
        workspace,
        workspace.config.conventions_file,
        "workspace conventions",
    )
    root_index = read_context(
        workspace,
        (PurePosixPath(workspace.config.wiki_dir) / "index.md").as_posix(),
        "root index",
    )
    dependencies = AgentDependencies(
        repository=repository,
        retriever=LexicalRetriever(repository),
        conventions=conventions,
        root_index=root_index,
    )
    selected_runner = runner if runner is not None else run_semantic_lint_agent
    semantic_findings, reported_reads = await selected_runner(
        model,
        dependencies,
        deterministic_findings,
    )
    actual_reads = frozenset(dependencies.read_ids)
    independent_reads = frozenset(audited_reads)
    if not reported_reads == actual_reads == independent_reads:
        raise AgentRunError(
            "semantic lint runner read history does not match the independent read audit"
        )
    validated_semantic = validate_semantic_findings(semantic_findings, independent_reads)
    return _lint_run(
        (*deterministic_findings, *validated_semantic),
        deterministic_has_errors,
    )


def _audited_repository(root: Path) -> tuple[OkfRepository, set[str]]:
    audited_reads: set[str] = set()

    class AuditedRepository(OkfRepository):
        def get(self, concept_id: str) -> OkfDocument:
            document = super().get(concept_id)
            audited_reads.add(document.concept_id)
            return document

    return AuditedRepository(root), audited_reads


def _deterministic_parsing_is_unusable(findings: tuple[LintFinding, ...]) -> bool:
    return any(
        finding.code == "OKF001" and finding.severity is Severity.ERROR for finding in findings
    )


def _lint_run(
    findings: tuple[LintFinding, ...],
    deterministic_has_errors: bool,
) -> LintRun:
    ordered = sorted(
        findings,
        key=lambda finding: (
            _SEVERITY_ORDER[finding.severity],
            finding.code,
            finding.path or "",
            finding.message,
            finding.origin.value,
        ),
    )
    return LintRun(
        findings=tuple(ordered),
        deterministic_has_errors=deterministic_has_errors,
    )
