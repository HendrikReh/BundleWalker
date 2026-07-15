from __future__ import annotations

from importlib import resources
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model

from bundlewalker.agents.common import AgentDependencies, frame_untrusted_data, read_tools
from bundlewalker.domain import MAX_SEMANTIC_FINDINGS, FindingOrigin, LintFinding
from bundlewalker.errors import AgentRunError

type AgentModel = Model | KnownModelName | str

_ALLOWED_CODES = frozenset(
    {
        "SEM-CONTRADICTION",
        "SEM-STALE",
        "SEM-UNSUPPORTED",
        "SEM-MISSING",
        "SEM-GAP",
    }
)


def create_semantic_lint_agent(
    model: AgentModel,
) -> Agent[AgentDependencies, list[LintFinding]]:
    """Create the provider-neutral semantic reviewer with read-only knowledge tools."""
    instructions = (
        resources.files("bundlewalker.agents.prompts")
        .joinpath("semantic-lint.md")
        .read_text(encoding="utf-8")
    )
    return Agent(
        model,
        deps_type=AgentDependencies,
        output_type=list[LintFinding],
        tools=read_tools,
        retries=2,
        instructions=instructions,
    )


async def run_semantic_lint_agent(
    model: AgentModel,
    dependencies: AgentDependencies,
    deterministic_findings: tuple[LintFinding, ...],
) -> tuple[list[LintFinding], frozenset[str]]:
    """Run one advisory semantic pass and verify evidence against this run's reads."""
    previous_reads = frozenset(dependencies.read_ids)
    payload: dict[str, Any] = {
        "workspace_conventions": {
            "character_count": len(dependencies.conventions),
            "content": dependencies.conventions,
        },
        "root_index": {
            "character_count": len(dependencies.root_index),
            "content": dependencies.root_index,
        },
        "deterministic_lint_signals": {
            "count": len(deterministic_findings),
            "content": [finding.model_dump(mode="json") for finding in deterministic_findings],
        },
    }
    try:
        result = await create_semantic_lint_agent(model).run(
            frame_untrusted_data(payload),
            deps=dependencies,
        )
    except Exception:
        pass
    else:
        run_reads = frozenset(dependencies.read_ids).difference(previous_reads)
        findings = validate_semantic_findings(result.output, run_reads)
        return findings, run_reads
    raise AgentRunError("semantic lint agent could not produce findings") from None


def validate_semantic_findings(
    findings: list[LintFinding],
    read_ids: frozenset[str],
) -> list[LintFinding]:
    """Normalize semantic origin and reject unsupported codes or unread evidence."""
    if len(findings) > MAX_SEMANTIC_FINDINGS:
        raise AgentRunError(
            f"semantic lint returned too many findings; maximum is {MAX_SEMANTIC_FINDINGS}"
        )
    validated: list[LintFinding] = []
    for finding in findings:
        if finding.code not in _ALLOWED_CODES:
            raise AgentRunError(f"semantic lint code is not allowed: {finding.code}")
        if not finding.evidence_paths:
            raise AgentRunError("semantic lint finding must include evidence paths")
        for evidence_path in finding.evidence_paths:
            if evidence_path not in read_ids:
                raise AgentRunError(f"semantic lint evidence path was not read: {evidence_path}")
        validated.append(finding.model_copy(update={"origin": FindingOrigin.SEMANTIC}))
    return validated
