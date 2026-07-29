# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run deterministic browser smoke tests against the production local web stack."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import uvicorn
from mcp.shared.memory import create_connected_server_and_client_session

from bundlewalker.agents.common import AgentDependencies
from bundlewalker.agents.ingest import AgentModel as IngestionAgentModel
from bundlewalker.agents.query import AgentModel as QueryAgentModel
from bundlewalker.application import (
    ApplicationDependencies,
    SynthesisResult,
    WorkspaceApplication,
)
from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    CitedAnswer,
    ConceptType,
    DraftConcept,
    OkfDocument,
    OkfMetadata,
)
from bundlewalker.interfaces.mcp import create_mcp_server
from bundlewalker.interfaces.web.app import create_web_app
from bundlewalker.interfaces.web.security import BrowserSessionStore
from bundlewalker.interfaces.web.server import bind_loopback_socket
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.workspace import RawSource, Workspace, discover_workspace, initialize_workspace

_NOW = datetime(2026, 7, 25, 12, tzinfo=UTC)
_SMOKE_MODEL = "test:model"


def main(argv: Sequence[str] | None = None) -> None:
    """Run a child command with one temporary authenticated web fixture."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--prepare-mcp-review"]:
        if len(arguments) != 2:
            raise SystemExit("usage: run_web_smoke.py --prepare-mcp-review WORKSPACE")
        review_id = asyncio.run(_prepare_mcp_review(Path(arguments[1])))
        print(review_id)
        return
    if "--" not in arguments:
        raise SystemExit("usage: run_web_smoke.py -- COMMAND [ARG ...]")
    separator = arguments.index("--")
    if separator != 0 or separator + 1 == len(arguments):
        raise SystemExit("usage: run_web_smoke.py -- COMMAND [ARG ...]")
    raise SystemExit(asyncio.run(_run_smoke(arguments[separator + 1 :])))


async def _run_smoke(command: Sequence[str]) -> int:
    with tempfile.TemporaryDirectory(prefix="bundlewalker-web-smoke-") as temporary:
        temporary_root = Path(temporary)
        workspace = _create_workspace(temporary_root / "knowledge")
        application = WorkspaceApplication(workspace, _dependencies())
        listener = bind_loopback_socket()
        sessions: BrowserSessionStore | None = None
        server: uvicorn.Server | None = None
        server_task: asyncio.Task[None] | None = None
        try:
            bootstrap_secret = secrets.token_urlsafe(32)
            sessions = BrowserSessionStore(bootstrap_secret)
            host, port = cast(tuple[str, int], listener.getsockname())
            origin = f"http://{host}:{port}"
            app = create_web_app(
                application,
                expected_host=f"{host}:{port}",
                sessions=sessions,
            )
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host=host,
                    port=port,
                    access_log=False,
                    log_level="warning",
                )
            )
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            await _wait_until_started(server, server_task)

            state_path = temporary_root / "browser-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "bootstrap_url": (f"{origin}/bootstrap?token={bootstrap_secret}"),
                        "origin": origin,
                        "workspace": str(workspace.root),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "BUNDLEWALKER_WEB_SMOKE_STATE": str(state_path),
                "BUNDLEWALKER_PYTHON": sys.executable,
            }
            process = await asyncio.create_subprocess_exec(
                *command,
                env=environment,
                stdin=subprocess.DEVNULL,
            )
            return await process.wait()
        finally:
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                await server_task
            if sessions is not None:
                sessions.clear()
            listener.close()


async def _wait_until_started(
    server: uvicorn.Server,
    server_task: asyncio.Task[None],
) -> None:
    for _ in range(500):
        if server.started:
            return
        if server_task.done():
            await server_task
            raise RuntimeError("web smoke server stopped before startup")
        await asyncio.sleep(0.01)
    raise RuntimeError("web smoke server did not start")


def _create_workspace(root: Path) -> Workspace:
    workspace = initialize_workspace(root, occurred_at=_NOW)
    documents = (
        (
            "topics/agents",
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                tags=["agents"],
                timestamp=_NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        (
            "entities/tools",
            OkfMetadata(
                type="Entity",
                title="Tools",
                description="Tools support agent workflows.",
                tags=["tools"],
                timestamp=_NOW,
            ),
            "# Tools\n\nTools support agent workflows.\n",
        ),
        (
            "syntheses/current-agent-framework",
            OkfMetadata(
                type="Synthesis",
                title="Current Agent Framework",
                description="A maintained decision framework.",
                tags=["agents"],
                timestamp=_NOW,
            ),
            (
                "# Current Agent Framework\n\nAgents can use tools [1].\n\n"
                "# Citations\n\n[1] [Agents](/topics/agents.md)\n"
            ),
        ),
        (
            "syntheses/agent-framework",
            OkfMetadata(
                type="Synthesis",
                title="Agent Framework",
                description="A maintained decision framework.",
                tags=["agents"],
                timestamp=_NOW,
            ),
            (
                "# Agent Framework\n\nAgents can use tools [1].\n\n"
                "# Citations\n\n[1] [Agents](/topics/agents.md)\n"
            ),
        ),
    )
    for concept_id, metadata, body in documents:
        path = workspace.wiki_dir / f"{concept_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(metadata, body), encoding="utf-8")
    regenerate_indexes(workspace.wiki_dir)
    return workspace


def _dependencies() -> ApplicationDependencies:
    return ApplicationDependencies(
        environment={},
        ingestion_runner=_ingestion_runner,
        query_runner=_query_runner,
        refresh_runner=_refresh_runner,
        clock=lambda: _NOW,
    )


async def _query_runner(
    model: QueryAgentModel,
    dependencies: AgentDependencies,
    question: str,
) -> tuple[CitedAnswer, frozenset[str]]:
    if str(model) != _SMOKE_MODEL:
        raise AssertionError("smoke query used an unexpected model")
    dependencies.repository.get("topics/agents")
    dependencies.read_ids.add("topics/agents")
    title = "MCP handoff" if question == "MCP handoff" else "Agent tools"
    return (
        CitedAnswer(
            title=title,
            body=f"# {title}\n\nAgents can use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        ),
        frozenset({"topics/agents"}),
    )


async def _ingestion_runner(
    model: IngestionAgentModel,
    _dependencies: AgentDependencies,
    source: RawSource,
) -> tuple[ChangeSet, frozenset[str]]:
    if str(model) != _SMOKE_MODEL:
        raise AssertionError("smoke ingestion used an unexpected model")
    return (
        ChangeSet(
            summary="Integrated browser notes.",
            source_sha256=source.sha256,
            drafts=[
                DraftConcept(
                    operation=ChangeOperation.CREATE,
                    path=source.concept_id,
                    type=ConceptType.SOURCE,
                    title="Browser notes",
                    description="Notes submitted through the browser smoke.",
                    tags=["notes"],
                    body=("# Browser notes\n\nThe source contains browser evidence [1].\n"),
                    citations=[
                        Citation(
                            number=1,
                            concept_id=source.concept_id,
                            start_line=1,
                            end_line=1,
                        )
                    ],
                )
            ],
        ),
        frozenset(),
    )


async def _refresh_runner(
    model: QueryAgentModel,
    dependencies: AgentDependencies,
    instruction: str,
    target: OkfDocument,
) -> tuple[CitedAnswer, frozenset[str]]:
    if str(model) != _SMOKE_MODEL:
        raise AssertionError("smoke refresh used an unexpected model")
    dependencies.repository.get("topics/agents")
    dependencies.read_ids.add("topics/agents")
    if instruction == "Check current evidence":
        answer = CitedAnswer(
            title="Current Agent Framework",
            body="# Current Agent Framework\n\nAgents can use tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        )
    else:
        answer = CitedAnswer(
            title="Updated Agent Framework",
            body="# Updated Agent Framework\n\nCurrent evidence supports tools [1].\n",
            citations=[Citation(number=1, concept_id="topics/agents")],
        )
    return answer, frozenset({"topics/agents"})


async def _prepare_mcp_review(root: Path) -> str:
    application = WorkspaceApplication(discover_workspace(root), _dependencies())
    server = create_mcp_server(application)
    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "prepare_synthesis",
            {"question": "MCP handoff", "model": _SMOKE_MODEL},
        )
    if result.isError or result.structuredContent is None:
        raise RuntimeError("MCP prepare_synthesis did not return a result")
    prepared = SynthesisResult.model_validate(result.structuredContent)
    return prepared.review.review_id


if __name__ == "__main__":
    main()
