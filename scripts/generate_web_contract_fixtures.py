# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generate deterministic JSON examples for frontend web-contract tests."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker.application import (
    AnswerResult,
    ConceptContent,
    ConceptPage,
    ConceptSearchResult,
    ConceptSummaryResult,
    IngestionResult,
    LintResult,
    MutationResult,
    RefreshResult,
    ReviewResult,
    SynthesisResult,
    WorkspaceStatus,
)
from bundlewalker.domain import Citation, CitedAnswer, FindingOrigin, LintFinding, Severity
from bundlewalker.interfaces.web.contracts import (
    WebErrorDetail,
    WebErrorResponse,
    to_web_answer,
    to_web_concept,
    to_web_concept_page,
    to_web_ingestion,
    to_web_lint,
    to_web_mutation,
    to_web_refresh,
    to_web_review,
    to_web_search,
    to_web_synthesis,
    to_web_workspace,
)
from bundlewalker.transactions import ReviewKind, ReviewStatus

OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "frontend"
    / "src"
    / "test"
    / "fixtures"
    / "contracts.json"
)
PRETTIER = Path(__file__).resolve().parents[1] / "frontend" / "node_modules" / ".bin" / "prettier"
REVIEW_ID = "a" * 32


def main() -> None:
    """Write canonical examples with stable ordering and whitespace."""
    if not PRETTIER.is_file():
        raise SystemExit("frontend dependencies are unavailable; run npm ci in frontend first")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(_examples(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        (str(PRETTIER), "--write", str(OUTPUT)),
        check=True,
    )


def _examples() -> dict[str, object]:
    review = _review()
    answer = _answer()
    summary = _summary()
    finding = LintFinding(
        origin=FindingOrigin.DETERMINISTIC,
        severity=Severity.WARNING,
        code="missing-description",
        message="Description is missing.",
        path="topics/agents.md",
        evidence_paths=["topics/agents.md"],
        remediation="Add a description.",
    )
    responses = {
        "workspace": to_web_workspace(
            WorkspaceStatus(
                display_name="knowledge",
                config_version=3,
                concept_counts={"Topic": 1},
                pending_review=None,
            ),
            csrf_token="fixture-csrf-token",
        ),
        "concept_page": to_web_concept_page(ConceptPage(items=(summary,), next_cursor="page-2")),
        "concept": to_web_concept(
            ConceptContent(
                **summary.model_dump(exclude={"resource_uri"}),
                resource_uri=summary.resource_uri,
                markdown="# Agents\n\nAgents can use tools.\n",
                digest="b" * 64,
            )
        ),
        "search": to_web_search(ConceptSearchResult(items=(summary,))),
        "answer": to_web_answer(answer),
        "lint": to_web_lint(LintResult(findings=(finding,), deterministic_has_errors=False)),
        "review": to_web_review(review),
        "ingestion_duplicate": to_web_ingestion(IngestionResult(status="duplicate", review=None)),
        "ingestion_pending": to_web_ingestion(IngestionResult(status="pending", review=review)),
        "synthesis": to_web_synthesis(SynthesisResult(answer=answer, review=review)),
        "refresh_current": to_web_refresh(
            RefreshResult(
                status="current",
                concept_id="syntheses/agents",
                answer=answer,
                review=None,
            )
        ),
        "refresh_pending": to_web_refresh(
            RefreshResult(
                status="pending",
                concept_id="syntheses/agents",
                answer=answer,
                review=review,
            )
        ),
        "mutation": to_web_mutation(MutationResult(review_id=REVIEW_ID, status="applied")),
        "error": WebErrorResponse(
            error=WebErrorDetail(
                code="review_stale",
                message="review is stale",
                retryable=False,
            )
        ),
    }
    return {name: response.model_dump(mode="json") for name, response in responses.items()}


def _review() -> ReviewResult:
    return ReviewResult(
        review_id=REVIEW_ID,
        kind=ReviewKind.INGESTION,
        status=ReviewStatus.PENDING,
        summary="Add agent notes",
        diff="diff --git a/topics/agents.md b/topics/agents.md\n",
        changed_paths=("topics/agents.md",),
        created_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        resource_uri="bundlewalker://review/pending",
    )


def _answer() -> AnswerResult:
    return AnswerResult(
        answer=CitedAnswer(
            title="Agent tools",
            body="Agents can use tools.",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        markdown="# Agent tools\n\nAgents can use tools. [1]\n",
    )


def _summary() -> ConceptSummaryResult:
    return ConceptSummaryResult(
        concept_id="topics/agents",
        type="Topic",
        title="Agents",
        description="How agents work.",
        tags=("agents",),
        resource_uri="bundlewalker://concept/topics/agents",
    )


if __name__ == "__main__":
    main()
