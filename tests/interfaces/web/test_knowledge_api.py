# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authenticated Ask and lint API coverage."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from httpx2 import Response

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.query import AgentModel as QueryAgentModel
from bundlewalker.agents.semantic_lint import AgentModel as LintAgentModel
from bundlewalker.application import (
    MAX_QUESTION_CHARACTERS,
    ApplicationDependencies,
    WorkspaceApplication,
)
from bundlewalker.application.contracts import AnswerResult, LintResult
from bundlewalker.domain import Citation, CitedAnswer, FindingOrigin, LintFinding, Severity
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis


class AuthenticatedWebClient(Protocol):
    def post_json(self, path: str, body: object) -> Response: ...


def _prepare_pending_review(application: WorkspaceApplication) -> str:
    prepared = prepare_synthesis(
        application.workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Existing proposal",
                body="Agents can use tools [1].",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
    )
    return prepared.transaction_id


async def test_ask_returns_cited_markdown_once_without_changing_review(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    runner_calls: list[tuple[str, str]] = []
    facade_calls: list[tuple[str, str | None]] = []

    async def runner(
        model: QueryAgentModel,
        dependencies: AgentDependencies,
        question: str,
    ) -> tuple[CitedAnswer, frozenset[str]]:
        runner_calls.append((str(model), question))
        dependencies.read_ids.add("topics/agents")
        return (
            CitedAnswer(
                title="Agent tools",
                body="# Answer\n\nAgents can use tools [1].\n",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            frozenset({"topics/agents"}),
        )

    application.dependencies = ApplicationDependencies(environment={}, query_runner=runner)
    original_ask = application.ask

    async def recording_ask(
        question: str,
        *,
        explicit_model: str | None,
    ) -> AnswerResult:
        facade_calls.append((question, explicit_model))
        return await original_ask(question, explicit_model=explicit_model)

    application.ask = recording_ask  # type: ignore[method-assign]
    expected_review_id = _prepare_pending_review(application)
    before = await application.get_pending_review()
    assert before is not None
    assert before.review_id == expected_review_id

    response = authenticated_client.post_json(
        "/api/v1/ask",
        {"question": "What do agents use?", "model": "test:model"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "title": "Agent tools",
        "markdown": (
            "# Answer\n\nAgents can use tools [1].\n\n"
            "# Citations\n\n[1] [Agents](/topics/agents.md)\n"
        ),
        "citations": [{"number": 1, "concept_id": "topics/agents"}],
    }
    assert facade_calls == [("What do agents use?", "test:model")]
    assert runner_calls == [("test:model", "What do agents use?")]
    assert await application.get_pending_review() == before


async def test_ask_contract_rejects_invalid_questions_before_facade_dispatch(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls = 0
    original_ask = application.ask

    async def recording_ask(
        question: str,
        *,
        explicit_model: str | None,
    ) -> AnswerResult:
        nonlocal calls
        calls += 1
        return await original_ask(question, explicit_model=explicit_model)

    application.ask = recording_ask  # type: ignore[method-assign]

    responses = (
        authenticated_client.post_json("/api/v1/ask", {"question": ""}),
        authenticated_client.post_json(
            "/api/v1/ask",
            {"question": "q" * (MAX_QUESTION_CHARACTERS + 1)},
        ),
        authenticated_client.post_json(
            "/api/v1/ask",
            {"question": "Question?", "unexpected": True},
        ),
    )

    assert calls == 0
    assert all(response.status_code == 422 for response in responses)
    assert all(response.json()["error"]["code"] == "invalid_input" for response in responses)


async def test_deterministic_lint_runs_once_and_remains_read_only(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    facade_calls: list[tuple[bool, str | None]] = []
    original_lint = application.lint

    async def recording_lint(
        *,
        semantic: bool,
        explicit_model: str | None,
    ) -> LintResult:
        facade_calls.append((semantic, explicit_model))
        return await original_lint(semantic=semantic, explicit_model=explicit_model)

    application.lint = recording_lint  # type: ignore[method-assign]
    expected_review_id = _prepare_pending_review(application)
    before = await application.get_pending_review()
    assert before is not None
    assert before.review_id == expected_review_id

    response = authenticated_client.post_json("/api/v1/lint", {"semantic": False})

    assert response.status_code == 200
    body = response.json()
    assert facade_calls == [(False, None)]
    assert body["deterministic_has_errors"] is False
    assert body["findings"]
    assert {finding["origin"] for finding in body["findings"]} == {"deterministic"}
    assert await application.get_pending_review() == before


async def test_semantic_lint_maps_explicit_model_once_and_keeps_origins_distinct(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    runner_calls: list[tuple[str, tuple[str, ...]]] = []
    facade_calls: list[tuple[bool, str | None]] = []

    async def semantic_runner(
        model: LintAgentModel,
        dependencies: AgentDependencies,
        deterministic_findings: tuple[LintFinding, ...],
    ) -> tuple[list[LintFinding], frozenset[str]]:
        runner_calls.append((str(model), tuple(finding.code for finding in deterministic_findings)))
        dependencies.repository.get("topics/agents")
        dependencies.read_ids.add("topics/agents")
        return (
            [
                LintFinding(
                    origin=FindingOrigin.SEMANTIC,
                    severity=Severity.INFO,
                    code="SEM-GAP",
                    message="Explain how tools support agents.",
                    path="topics/agents.md",
                    evidence_paths=["topics/agents"],
                    remediation="Add one evidence-backed example.",
                )
            ],
            frozenset({"topics/agents"}),
        )

    application.dependencies = ApplicationDependencies(
        environment={},
        semantic_lint_runner=semantic_runner,
    )
    original_lint = application.lint

    async def recording_lint(
        *,
        semantic: bool,
        explicit_model: str | None,
    ) -> LintResult:
        facade_calls.append((semantic, explicit_model))
        return await original_lint(semantic=semantic, explicit_model=explicit_model)

    application.lint = recording_lint  # type: ignore[method-assign]
    before = await application.get_pending_review()

    response = authenticated_client.post_json(
        "/api/v1/lint",
        {"semantic": True, "model": "test:model"},
    )

    assert response.status_code == 200
    findings = response.json()["findings"]
    assert facade_calls == [(True, "test:model")]
    assert runner_calls == [("test:model", ("ORPHAN001", "ORPHAN001"))]
    assert {finding["origin"] for finding in findings} == {
        "deterministic",
        "semantic",
    }
    semantic = next(finding for finding in findings if finding["origin"] == "semantic")
    assert semantic["severity"] == "info"
    assert semantic["code"] == "SEM-GAP"
    assert await application.get_pending_review() == before


async def test_semantic_lint_configuration_failure_is_bounded_and_preserves_review(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    application.dependencies = ApplicationDependencies(environment={})
    before = await application.get_pending_review()

    response = authenticated_client.post_json("/api/v1/lint", {"semantic": True})

    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "configuration_error",
        "message": ("an agent model is required; pass --model MODEL or set BUNDLEWALKER_MODEL"),
        "retryable": False,
        "review_id": None,
        "diagnostic_id": None,
    }
    assert await application.get_pending_review() == before


async def test_model_name_limit_is_checked_before_lint_dispatch(
    application: WorkspaceApplication,
    authenticated_client: AuthenticatedWebClient,
) -> None:
    calls = 0
    original_lint: Callable[..., Awaitable[LintResult]] = application.lint

    async def recording_lint(
        *,
        semantic: bool,
        explicit_model: str | None,
    ) -> LintResult:
        nonlocal calls
        calls += 1
        return await original_lint(semantic=semantic, explicit_model=explicit_model)

    application.lint = recording_lint  # type: ignore[method-assign]

    response = authenticated_client.post_json(
        "/api/v1/lint",
        {"semantic": True, "model": "m" * 256},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"
    assert calls == 0
