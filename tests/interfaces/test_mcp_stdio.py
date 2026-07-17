from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import anyio
import pytest
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import AnyUrl

from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import discard_pending_review, get_pending_review
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 17, 12, tzinfo=UTC)
PROJECT_ROOT = Path(__file__).parents[2]
STDIO_TIMEOUT_SECONDS = 15


def _captured_text(stream: TextIO) -> str:
    stream.seek(0)
    return stream.read()


def _workspace(tmp_path: Path) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    concept_path = workspace.wiki_dir / "topics" / "agents.md"
    concept_path.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                tags=["agents"],
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    return workspace


def _parameters(
    *,
    workspace: Workspace | None = None,
    cwd: Path | None = None,
) -> StdioServerParameters:
    arguments = ["-m", "bundlewalker.interfaces.mcp"]
    if workspace is not None:
        arguments.extend(["--workspace", str(workspace.root)])
    return StdioServerParameters(
        command=sys.executable,
        args=arguments,
        env=os.environ.copy(),
        cwd=cwd,
    )


def _console_parameters(workspace: Workspace) -> StdioServerParameters:
    return StdioServerParameters(
        command="uv",
        args=[
            "run",
            "--project",
            str(PROJECT_ROOT),
            "bundlewalker-mcp",
            "--workspace",
            str(workspace.root),
        ],
        env=os.environ.copy(),
        cwd=PROJECT_ROOT,
    )


@pytest.fixture
def workspace_with_pending_review(tmp_path: Path) -> tuple[Workspace, str, str]:
    workspace = _workspace(tmp_path)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Agent tools",
                body="# Answer\n\nAgents can use tools [1].\n",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    pending = get_pending_review(workspace)
    assert pending is not None
    return workspace, pending.review_id, pending.diff


async def _inspect_pending_review(
    parameters: StdioServerParameters,
) -> tuple[dict[str, Any], str]:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_output:
        with anyio.fail_after(STDIO_TIMEOUT_SECONDS):
            async with (
                stdio_client(parameters, errlog=error_output) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("get_pending_review", {})
                resource = await session.read_resource(AnyUrl("bundlewalker://review/pending"))

        assert _captured_text(error_output) == ""
    assert result.isError is False
    assert result.structuredContent is not None
    content = resource.contents[0]
    assert isinstance(content, types.TextResourceContents)
    return result.structuredContent, content.text


async def test_registered_console_entrypoint_binds_workspace_without_protocol_noise(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_output:
        with anyio.fail_after(STDIO_TIMEOUT_SECONDS):
            async with (
                stdio_client(_console_parameters(workspace), errlog=error_output) as (read, write),
                ClientSession(read, write) as session,
            ):
                initialized = await session.initialize()
                result = await session.call_tool("workspace_status", {})

        assert _captured_text(error_output) == ""
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["display_name"] == workspace.root.name
    assert initialized.capabilities.resources is not None
    assert initialized.capabilities.resources.subscribe is False
    assert initialized.capabilities.resources.listChanged is False
    assert initialized.capabilities.tools is not None
    assert initialized.capabilities.tools.listChanged is False
    assert initialized.capabilities.prompts is None
    assert initialized.capabilities.experimental == {}
    assert initialized.capabilities.tasks is None


async def test_stdio_entrypoint_discovers_workspace_from_process_cwd(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    nested = workspace.root / "nested" / "directory"
    nested.mkdir(parents=True)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_output:
        with anyio.fail_after(STDIO_TIMEOUT_SECONDS):
            async with (
                stdio_client(_parameters(cwd=nested), errlog=error_output) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("workspace_status", {})

        assert _captured_text(error_output) == ""

    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["display_name"] == workspace.root.name


async def test_stdio_entrypoint_supports_deterministic_lint_and_resource_read(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_output:
        with anyio.fail_after(STDIO_TIMEOUT_SECONDS):
            async with (
                stdio_client(_parameters(workspace=workspace), errlog=error_output) as (
                    read,
                    write,
                ),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                linted = await session.call_tool("lint", {"semantic": False})
                resource = await session.read_resource(
                    AnyUrl("bundlewalker://concept/topics/agents")
                )

        assert _captured_text(error_output) == ""

    assert linted.isError is False
    assert linted.structuredContent is not None
    assert linted.structuredContent["deterministic_has_errors"] is False
    content = resource.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.mimeType == "text/markdown"
    assert "# Agents" in content.text


async def test_pending_review_survives_two_stdio_process_restarts(
    workspace_with_pending_review: tuple[Workspace, str, str],
) -> None:
    workspace, review_id, expected_diff = workspace_with_pending_review
    parameters = _parameters(workspace=workspace)

    first_result, first_resource = await _inspect_pending_review(parameters)
    second_result, second_resource = await _inspect_pending_review(parameters)

    for result, resource in (
        (first_result, first_resource),
        (second_result, second_resource),
    ):
        assert result["review"]["review_id"] == review_id
        assert result["review"]["diff"] == expected_diff
        assert expected_diff in resource

    discard_pending_review(workspace, review_id)
    assert get_pending_review(workspace) is None


def test_module_help_and_argparse_errors_use_standard_streams() -> None:
    helped = subprocess.run(
        [sys.executable, "-m", "bundlewalker.interfaces.mcp", "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    invalid = subprocess.run(
        [sys.executable, "-m", "bundlewalker.interfaces.mcp", "--unknown"],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert helped.returncode == 0
    assert helped.stderr == ""
    assert "usage: bundlewalker-mcp" in helped.stdout
    assert "--workspace WORKSPACE" in helped.stdout
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    assert "usage: bundlewalker-mcp" in invalid.stderr
    assert "unrecognized arguments: --unknown" in invalid.stderr


def test_startup_workspace_failure_is_bounded_and_uses_domain_exit_code(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "private" / "missing"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bundlewalker.interfaces.mcp",
            "--workspace",
            str(missing),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Error: workspace operation failed\n"
    assert str(tmp_path) not in result.stderr


def test_console_script_is_registered() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"]["bundlewalker-mcp"] == ("bundlewalker.interfaces.mcp:main")


def test_mcp_runtime_dependencies_are_direct_and_bounded() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert "jsonschema>=4.26,<5" in dependencies
    assert "mcp>=1.28.1,<2" in dependencies

    lock = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in lock["package"]}
    assert packages["mcp"]["version"] == "1.28.1"
    assert packages["jsonschema"]["version"].startswith("4.")
