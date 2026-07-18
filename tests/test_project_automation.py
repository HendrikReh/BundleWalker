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
    assert required["needs"] == [
        "supported",
        "build",
        "artifact-smoke",
        "sdist-smoke",
        "dependency-audit",
    ]
    _assert_actions_are_sha_pinned(workflow)


def test_ci_builds_once_and_smoke_tests_both_distribution_formats() -> None:
    workflow = _yaml(".github/workflows/ci.yml")

    assert workflow["jobs"]["build"]["needs"] == ["supported"]
    build_commands = _run_commands(workflow, "build")
    assert "uv build --clear --no-sources" in build_commands
    assert "uv run twine check dist/*" in build_commands

    artifact_smoke = workflow["jobs"]["artifact-smoke"]
    assert artifact_smoke["needs"] == ["build"]
    assert artifact_smoke["strategy"]["matrix"] == {
        "os": ["ubuntu-24.04", "macos-15"],
        "python-version": ["3.13", "3.14"],
    }
    assert "dist/*.whl" in _run_commands(workflow, "artifact-smoke")

    sdist_smoke = workflow["jobs"]["sdist-smoke"]
    assert sdist_smoke["needs"] == ["build"]
    assert "dist/*.tar.gz" in _run_commands(workflow, "sdist-smoke")

    required_needs = workflow["jobs"]["required"]["needs"]
    for dependency in ("supported", "build", "artifact-smoke", "sdist-smoke"):
        assert dependency in required_needs
    _assert_actions_are_sha_pinned(workflow)


def test_ci_requires_dependency_audit() -> None:
    workflow = _yaml(".github/workflows/ci.yml")

    audit_commands = _run_commands(workflow, "dependency-audit")
    assert (
        "uv export --frozen --no-emit-project --output-file "
        '"$RUNNER_TEMP/bundlewalker-audit-requirements.txt" >/dev/null' in audit_commands
    )
    assert (
        "uv run pip-audit --strict --requirement "
        '"$RUNNER_TEMP/bundlewalker-audit-requirements.txt" --require-hashes --disable-pip'
        in audit_commands
    )
    assert workflow["jobs"]["required"]["needs"] == [
        "supported",
        "build",
        "artifact-smoke",
        "sdist-smoke",
        "dependency-audit",
    ]


def test_dependabot_updates_uv_and_actions_weekly() -> None:
    config = _yaml(".github/dependabot.yml")

    assert config["version"] == "2"
    assert config["updates"] == [
        {
            "package-ecosystem": "uv",
            "directory": "/",
            "schedule": {
                "interval": "weekly",
                "day": "monday",
                "time": "05:00",
                "timezone": "Europe/Berlin",
            },
            "open-pull-requests-limit": "5",
        },
        {
            "package-ecosystem": "github-actions",
            "directory": "/",
            "schedule": {
                "interval": "weekly",
                "day": "monday",
                "time": "05:30",
                "timezone": "Europe/Berlin",
            },
            "open-pull-requests-limit": "5",
        },
    ]


def test_codeql_scans_python_on_changes_and_schedule() -> None:
    workflow = _yaml(".github/workflows/codeql.yml")

    assert workflow["permissions"] == {
        "contents": "read",
        "security-events": "write",
    }
    assert workflow["on"]["push"]["branches"] == ["master"]
    assert "pull_request" in workflow["on"]
    assert workflow["on"]["schedule"] == [{"cron": "23 4 * * 1"}]
    assert workflow["jobs"]["analyze"]["strategy"]["matrix"] == {"language": ["python"]}
    _assert_actions_are_sha_pinned(workflow)


def test_testpypi_workflow_is_manual_oidc_only_and_verifies_publication() -> None:
    workflow = _yaml(".github/workflows/publish-testpypi.yml")

    workflow_dispatch = workflow["on"]["workflow_dispatch"]
    assert workflow_dispatch["inputs"]["version"]["required"] == "true"
    assert workflow_dispatch["inputs"]["version"]["type"] == "string"
    assert workflow["permissions"] == {"contents": "read"}
    build = workflow["jobs"]["build"]
    assert build["if"] == "github.ref == 'refs/heads/master'"
    build_commands = _run_commands(workflow, "build")
    assert "uv build --clear --no-sources" in build_commands
    assert "uv run twine check dist/*" in build_commands
    build_run_steps = [step["run"] for step in _steps(workflow, "build") if "run" in step]
    assert (
        "uv export --frozen --no-emit-project --output-file "
        '"$RUNNER_TEMP/bundlewalker-audit-requirements.txt" >/dev/null' in build_run_steps
    )
    assert (
        "uv run pip-audit --strict --requirement "
        '"$RUNNER_TEMP/bundlewalker-audit-requirements.txt" --require-hashes --disable-pip'
        in build_run_steps
    )

    publish = workflow["jobs"]["publish"]
    assert publish["if"] == "github.ref == 'refs/heads/master'"
    assert publish["needs"] == ["build"]
    assert publish["environment"]["name"] == "testpypi"
    assert publish["permissions"] == {"id-token": "write"}
    publish_steps = _steps(workflow, "publish")
    assert publish_steps[-1]["uses"].startswith(
        "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b"
    )
    assert publish_steps[-1]["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    assert workflow["jobs"]["verify"]["needs"] == ["publish"]
    verify_commands = _run_commands(workflow, "verify")
    assert "--no-deps --default-index https://test.pypi.org/simple" in verify_commands
    _assert_actions_are_sha_pinned(workflow)
