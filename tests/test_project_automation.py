# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _yaml(relative: str) -> dict[str, Any]:
    content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    loaded = yaml.load(content, Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def _steps(workflow: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], workflow["jobs"][job]["steps"])


def _run_commands(workflow: dict[str, Any], job: str) -> str:
    return "\n".join(step.get("run", "") for step in _steps(workflow, job))


def _assert_actions_are_sha_pinned(workflow: dict[str, Any]) -> None:
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if uses := step.get("uses"):
                assert FULL_SHA.fullmatch(uses), uses


def test_ci_has_required_supported_matrix_and_experimental_windows() -> None:
    workflow = _yaml(".github/workflows/ci.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["UV_VERSION"] == "0.11.28"
    assert workflow["on"]["push"]["branches"] == ["master"]
    assert "pull_request" in workflow["on"]

    supported = workflow["jobs"]["supported"]
    assert supported["strategy"]["fail-fast"] == "false"
    assert supported["strategy"]["matrix"] == {
        "os": ["ubuntu-24.04", "macos-15"],
        "python-version": ["3.13", "3.14"],
    }
    supported_commands = _run_commands(workflow, "supported")
    for command in (
        "uv sync --locked",
        "uv lock --check",
        "uv run pytest -m 'not eval' -q",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run pyright",
    ):
        assert command in supported_commands

    windows = workflow["jobs"]["windows-experimental"]
    assert windows["continue-on-error"] == "true"
    assert windows["strategy"]["matrix"] == {"python-version": ["3.13", "3.14"]}
    assert windows["runs-on"] == "windows-2025"
    assert _run_commands(workflow, "windows-experimental") == supported_commands

    required = workflow["jobs"]["required"]
    assert required["if"] == "always()"
    assert required["needs"] == ["supported"]
    _assert_actions_are_sha_pinned(workflow)
