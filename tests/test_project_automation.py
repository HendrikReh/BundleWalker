# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
import tomllib
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


def test_sdist_includes_historical_empty_directory_representation() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    force_include = project["tool"]["hatch"]["build"]["targets"]["sdist"]["force-include"]
    assert force_include == {
        "tests/fixtures/historical/empty-directories.json": (
            "tests/fixtures/historical/empty-directories.json"
        )
    }


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


def test_testpypi_verification_retries_bounded_propagation_delay() -> None:
    workflow = _yaml(".github/workflows/publish-testpypi.yml")
    verify = workflow["jobs"]["verify"]
    install_step = next(
        step
        for step in _steps(workflow, "verify")
        if step["name"] == "Install and smoke-test published prerelease"
    )
    script = install_step["run"]
    install_command = (
        "uv pip install --python .testpypi-venv/bin/python --no-deps "
        '--default-index https://test.pypi.org/simple "bundlewalker==${{ inputs.version }}"'
    )

    assert "continue-on-error" not in verify
    assert "continue-on-error" not in install_step
    assert "retry_delays=(5 10 20 40 80)" in script
    assert "for attempt in 1 2 3 4 5 6; do" in script
    assert f"if {install_command}; then" in script
    assert 'if [ "$attempt" -eq 6 ]; then' in script
    assert "exit 1" in script
    assert "break" in script
    assert 'delay="${retry_delays[$((attempt - 1))]}"' in script
    assert 'sleep "$delay"' in script


def test_workspace_lifecycle_policy_and_commands_are_published() -> None:
    policy = (PROJECT_ROOT / "docs/workspace-compatibility.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    user_guide = (PROJECT_ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
    tutorial = (PROJECT_ROOT / "docs/tutorial.md").read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")

    for command in (
        "bundlewalker workspace status",
        "bundlewalker workspace backup",
        "bundlewalker workspace restore",
        "bundlewalker workspace upgrade",
    ):
        assert command in policy
        assert command in user_guide
    for warning in (
        "unencrypted",
        "raw source",
        ".bundlewalker",
        "pending review",
        "new or empty",
    ):
        assert warning in policy.lower()
    assert "docs/workspace-compatibility.md" in readme
    assert "workspace backup" in tutorial.lower()
    assert "pre-upgrade backup" in releases.lower()
    assert "sha-256" in releases.lower()


def test_doctor_diagnostics_and_redacted_support_reports_are_published() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    user_guide = (PROJECT_ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
    design = (
        PROJECT_ROOT / "docs/superpowers/specs/2026-07-19-bundlewalker-doctor-diagnostics-design.md"
    ).read_text(encoding="utf-8")
    implementation_plan = (
        PROJECT_ROOT / "docs/superpowers/plans/2026-07-19-bundlewalker-doctor-diagnostics.md"
    ).read_text(encoding="utf-8")
    support = (PROJECT_ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    security = (PROJECT_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "bundlewalker doctor" in readme
    for phrase in (
        "bundlewalker doctor [PATH] [--report REPORT.json]",
        "Warnings exit `0`",
        "failures exit `1`",
        "schema version `1`",
        "read-only",
        "offline",
        "<REVIEW_ID>",
    ):
        assert phrase in user_guide
    assert "redacted JSON support report" in support
    assert "review the report" in support.lower()
    assert "private vulnerability" in security.lower()
    assert "doctor" in changelog.lower()
    for document in (design, implementation_plan):
        assert "cannot atomically prove" in document
        assert "unrelated replacement" in document
        assert "retains the owner-only partial target" in document
    for document in (readme, user_guide, support, security):
        assert "inspect and remove" in document.lower()
        assert "before retrying" in document.lower()
    assert "owner-only partial support-report target" in changelog


def test_historical_plan_embeds_current_user_guide_byte_for_byte() -> None:
    guide = (PROJECT_ROOT / "docs/user-guide.md").read_bytes()
    plan = (PROJECT_ROOT / "docs/superpowers/plans/2026-07-16-end-user-guide.md").read_bytes()
    start_marker = b"Create `docs/user-guide.md` with exactly:\n\n````markdown\n"
    end_marker = b"\n````\n\n- [ ] **Step 3: Link the guide from the README**"

    assert plan.count(start_marker) == 1
    assert plan.count(end_marker) == 1
    embedded_start = plan.index(start_marker) + len(start_marker)
    embedded_end = plan.index(end_marker, embedded_start)
    embedded_guide = plan[embedded_start:embedded_end] + b"\n"

    assert embedded_guide == guide
