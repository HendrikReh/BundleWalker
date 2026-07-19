# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from benchmarks.contracts import SampleObservation, ScenarioName
from benchmarks.fixtures import GeneratedFixture

EXPECTED_TOOL_NAMES = (
    "apply_review",
    "ask",
    "discard_review",
    "get_pending_review",
    "lint",
    "prepare_ingestion",
    "prepare_refresh",
    "prepare_synthesis",
    "search_concepts",
    "workspace_status",
)
_MCP_TIMEOUT_SECONDS = 30


async def _run_mcp_startup(fixture: GeneratedFixture) -> SampleObservation:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "bundlewalker.interfaces.mcp",
            "--workspace",
            str(fixture.workspace.root),
        ],
        env={},
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_output:
        with anyio.fail_after(_MCP_TIMEOUT_SECONDS):
            started = time.perf_counter_ns()
            async with (
                stdio_client(parameters, errlog=error_output) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                tool_names = tuple(sorted(tool.name for tool in listed.tools))
                duration = time.perf_counter_ns() - started

        error_output.seek(0)
        if error_output.read() != "":
            raise RuntimeError("MCP benchmark process wrote to stderr")

    if tool_names != EXPECTED_TOOL_NAMES:
        raise AssertionError("MCP benchmark tool discovery changed")
    canonical = json.dumps(tool_names, separators=(",", ":")).encode("ascii")
    return SampleObservation(
        scenario=ScenarioName.MCP_STARTUP,
        profile=fixture.profile.name,
        duration_ns=duration,
        output_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def run_mcp_startup(fixture: GeneratedFixture) -> SampleObservation:
    return anyio.run(_run_mcp_startup, fixture)
