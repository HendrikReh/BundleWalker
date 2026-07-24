# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
import shlex
import subprocess
import tomllib
from fnmatch import fnmatchcase
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


def _step(workflow: dict[str, Any], job: str, name: str) -> dict[str, Any]:
    return next(step for step in _steps(workflow, job) if step["name"] == name)


def _step_command_sequence(workflow: dict[str, Any], job: str) -> list[tuple[str, str]]:
    return [(str(step["name"]), str(step.get("run", ""))) for step in _steps(workflow, job)]


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
    supported_sequence = _step_command_sequence(workflow, "supported")
    windows_sequence = _step_command_sequence(workflow, "windows-experimental")
    smoke_steps = [
        step for step in supported_sequence if step[0] == "Run benchmark correctness smoke"
    ]
    assert len(smoke_steps) == 1
    assert windows_sequence == [
        step for step in supported_sequence if step[0] != "Run benchmark correctness smoke"
    ]

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


def test_benchmark_workflow_is_scheduled_manual_and_nonblocking() -> None:
    workflow = _yaml(".github/workflows/benchmarks.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["schedule"] == [{"cron": "17 3 * * 2"}]
    assert "workflow_dispatch" in workflow["on"]
    assert "pull_request" not in workflow["on"]
    measure = workflow["jobs"]["measure"]
    assert measure["strategy"]["fail-fast"] == "false"
    assert measure["strategy"]["matrix"] == {
        "os": ["ubuntu-24.04", "macos-15"],
        "python-version": ["3.13", "3.14"],
    }
    commands = _run_commands(workflow, "measure")
    assert "uv sync --locked" in commands
    assert "uv run python -m benchmarks run" in commands
    assert "smoke,small,medium,large,probe" in commands
    assert "suite-1-${{ github.sha }}" in commands
    assert "${{ github.run_id }}.json" in commands
    assert workflow["jobs"]["summarize"]["needs"] == ["measure"]
    _assert_actions_are_sha_pinned(workflow)


def test_normal_ci_runs_benchmark_correctness_without_timing_assertions() -> None:
    workflow = _yaml(".github/workflows/ci.yml")
    commands = _run_commands(workflow, "supported")
    assert (
        "uv run python -m benchmarks run --profiles smoke --correctness-only "
        '--output "$RUNNER_TEMP/benchmark-smoke.json"' in commands
    )
    assert "benchmark baseline" not in commands.casefold()


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
        "pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247"
    )
    assert publish_steps[-1]["with"]["repository-url"] == "https://test.pypi.org/legacy/"
    assert workflow["jobs"]["verify"]["needs"] == ["publish"]
    verify_commands = _run_commands(workflow, "verify")
    assert "--no-deps --default-index https://test.pypi.org/simple" in verify_commands
    _assert_actions_are_sha_pinned(workflow)


def test_publishing_workflows_pin_approved_publisher_action() -> None:
    testpypi_text = (PROJECT_ROOT / ".github/workflows/publish-testpypi.yml").read_text(
        encoding="utf-8"
    )
    production_text = (PROJECT_ROOT / ".github/workflows/publish-pypi.yml").read_text(
        encoding="utf-8"
    )
    publisher = "pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247 # v1.14.1"

    assert publisher in testpypi_text
    assert publisher in production_text
    assert testpypi_text.count(publisher) == 1
    assert production_text.count(publisher) == 1


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


def test_mcp_host_documentation_is_published() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    user_guide = (PROJECT_ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
    tutorial = (PROJECT_ROOT / "docs/tutorial.md").read_text(encoding="utf-8")
    setup = (PROJECT_ROOT / "docs/vscode-copilot-mcp-setup.md").read_text(encoding="utf-8")
    compatibility = (PROJECT_ROOT / "docs/mcp-compatibility.md").read_text(encoding="utf-8")

    for document in (readme, user_guide, tutorial):
        assert "vscode-copilot-mcp-setup.md" in document
        assert "mcp-compatibility.md" in document

    for phrase in (
        ".vscode/mcp.json",
        "envFile",
        "${input:",
        "Configure Tools",
        "MCP: List Servers",
        "MCP: Browse Resources",
        "Show Output",
    ):
        assert phrase in setup

    for phrase in (
        "Visual Studio Code 1.129.1",
        "GitHub Copilot 0.57.0",
        "BundleWalker 0.4.0rc2",
        "MCP Python SDK 1.28.1",
        "MCP protocol 2025-11-25",
        "macOS",
        "resources",
        "discard",
        "apply",
        "restart",
        "transaction recovery",
    ):
        assert phrase in compatibility

    for tool in (
        "workspace_status",
        "search_concepts",
        "ask",
        "lint",
        "prepare_ingestion",
        "prepare_synthesis",
        "prepare_refresh",
        "get_pending_review",
        "apply_review",
        "discard_review",
    ):
        assert f"`{tool}`" in compatibility


def test_contributor_documentation_keeps_historical_records_immutable() -> None:
    contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "Historical plans and specifications are immutable project records." in contributing
    assert "Do not synchronize them with later edits to active documentation." in contributing
    assert "After every user-guide edit, update the embedded block" not in contributing


def test_pypi_workflow_is_tag_gated_oidc_only_and_reuses_exact_artifacts() -> None:
    path = PROJECT_ROOT / ".github/workflows/publish-pypi.yml"
    workflow_text = path.read_text(encoding="utf-8")
    workflow = _yaml(".github/workflows/publish-pypi.yml")

    assert workflow["on"] == {"push": {"tags": ["v*"]}}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["UV_VERSION"] == "0.11.28"
    assert list(workflow["jobs"]) == ["build", "publish", "verify", "github-release"]

    build = workflow["jobs"]["build"]
    assert build["outputs"] == {"version": "${{ steps.identity.outputs.version }}"}
    build_commands = _run_commands(workflow, "build")
    for required in (
        'test "$GITHUB_REF_TYPE" = "tag"',
        'test "$GITHUB_REF_NAME" = "v${version}"',
        r"0\.4\.0(?:rc[1-9][0-9]*)?",
        "uv sync --locked",
        "uv lock --check",
        "uv run pytest -m 'not eval' -q",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run pyright",
        "uv run pip-audit --strict",
        "uv build --clear --no-sources",
        'uv run twine check "${artifacts[@]}"',
        "bundlewalker --help",
        "bundlewalker-mcp --help",
        "sha256sum",
    ):
        assert required in build_commands
    assert "persist-credentials" in str(_steps(workflow, "build")[0])
    assert _steps(workflow, "build")[0]["with"]["persist-credentials"] == "false"

    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == ["build"]
    assert publish["environment"]["name"] == "pypi"
    assert publish["permissions"] == {"id-token": "write"}
    publish_action = _steps(workflow, "publish")[-1]
    assert publish_action["uses"].startswith("pypa/gh-action-pypi-publish@")
    assert "with" not in publish_action

    verify = workflow["jobs"]["verify"]
    assert verify["needs"] == ["build", "publish"]
    assert verify["permissions"] == {"contents": "read"}
    verify_commands = _run_commands(workflow, "verify")
    assert "retry_delays=(5 10 20 40 80)" in verify_commands
    assert "for attempt in 1 2 3 4 5 6; do" in verify_commands
    assert "--default-index https://pypi.org/simple" in verify_commands
    assert "https://pypi.org/pypi/bundlewalker/${version}/json" in verify_commands
    assert 'item["digests"]["sha256"]' in verify_commands

    release = workflow["jobs"]["github-release"]
    assert release["needs"] == ["build", "verify"]
    assert release["permissions"] == {"contents": "write"}
    release_commands = _run_commands(workflow, "github-release")
    assert "gh release create" in release_commands
    assert "--prerelease" in release_commands
    assert "gh release upload" in release_commands
    assert "gh release download" in release_commands
    assert "cmp --silent" in release_commands

    assert workflow_text.count("uv build --clear --no-sources") == 1
    assert workflow_text.count("pypa/gh-action-pypi-publish@") == 1
    assert "repository-url:" not in workflow_text
    assert "password:" not in workflow_text
    assert "secrets." not in workflow_text
    assert "continue-on-error" not in workflow_text
    for job_name in ("publish", "verify", "github-release"):
        assert any(
            step.get("uses", "").startswith("actions/download-artifact@")
            for step in _steps(workflow, job_name)
        )
    _assert_actions_are_sha_pinned(workflow)


def test_pypi_workflow_uses_its_release_lane_and_prerelease_branches() -> None:
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    identity_script = _step(workflow, "build", "Validate release identity")["run"]
    pattern_match = re.search(
        r'assert re\.fullmatch\(r"(?P<pattern>[^"]+)", value\)', identity_script
    )
    assert pattern_match is not None
    version_pattern = pattern_match.group("pattern")

    for version in ("0.4.0rc1", "0.4.0rc2", "0.4.0rc10", "0.4.0"):
        assert re.fullmatch(version_pattern, version), version
    for version in ("0.4.0rc0", "0.4.1rc1", "0.4.0a2", "1.0.0"):
        assert re.fullmatch(version_pattern, version) is None, version

    release_script = _step(workflow, "github-release", "Create or complete the GitHub release")[
        "run"
    ]
    prerelease_match = re.search(
        r'expected_prerelease=false\s+case "\$version" in\s+'
        r"(?P<pattern>\S+)\) expected_prerelease=true ;;\s+esac",
        release_script,
    )
    assert prerelease_match is not None
    prerelease_pattern = prerelease_match.group("pattern")
    for version in ("0.4.0rc1", "0.4.0rc2", "0.4.0rc10"):
        assert fnmatchcase(version, prerelease_pattern), version
    assert not fnmatchcase("0.4.0", prerelease_pattern)


def test_pypi_workflow_requires_exact_artifacts_in_every_downstream_job() -> None:
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    artifact_script = _step(workflow, "build", "Validate exact artifacts and metadata")["run"]
    assert 'test "${#artifacts[@]}" -eq 2' in artifact_script
    assert (
        'test -f "dist/bundlewalker-${{ steps.identity.outputs.version }}-py3-none-any.whl"'
        in artifact_script
    )
    assert (
        'test -f "dist/bundlewalker-${{ steps.identity.outputs.version }}.tar.gz"'
        in artifact_script
    )
    verify_script = _step(workflow, "verify", "Install and smoke-test published release")["run"]
    assert 'assert len(payload["urls"]) == 2' in verify_script
    assert "assert len(local) == 2" in verify_script
    assert 'assert local == remote, {"local": local, "remote": remote}' in verify_script
    assert verify_script.index("payload = json.loads(Path(sys.argv[1])") < verify_script.index(
        "retry_delays=(5 10 20 40 80)"
    )

    for job_name in ("publish", "verify", "github-release"):
        downloads = [
            step
            for step in _steps(workflow, job_name)
            if step.get("uses", "").startswith("actions/download-artifact@")
        ]
        assert downloads
        assert all(
            step.get("with") == {"name": "python-package-distributions", "path": "dist/"}
            for step in downloads
        )


def test_pypi_workflow_does_not_count_uv_gitignore_as_distribution(
    tmp_path: Path,
) -> None:
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    script = _step(workflow, "build", "Validate exact artifacts and metadata")["run"]
    selector = re.search(
        r"mapfile -t artifacts < <\((?P<command>find dist .+?) \| sort\)",
        script,
    )
    assert selector is not None

    dist = tmp_path / "dist"
    dist.mkdir()
    for name in (
        ".gitignore",
        "bundlewalker-0.4.0rc3-py3-none-any.whl",
        "bundlewalker-0.4.0rc3.tar.gz",
    ):
        (dist / name).touch()

    selected = subprocess.run(
        shlex.split(selector.group("command")),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert sorted(selected) == [
        "dist/bundlewalker-0.4.0rc3-py3-none-any.whl",
        "dist/bundlewalker-0.4.0rc3.tar.gz",
    ]
    assert "dist/.gitignore" not in selected
    assert 'uv run twine check "${artifacts[@]}"' in script


def test_pypi_verification_runs_after_ordinary_publish_failure_read_only() -> None:
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    verify = workflow["jobs"]["verify"]
    assert verify["needs"] == ["build", "publish"]
    assert verify["if"] == (
        "${{ always() && needs.build.result == 'success' && "
        "(needs.publish.result == 'success' || needs.publish.result == 'failure') }}"
    )
    assert verify["permissions"] == {"contents": "read"}
    assert "id-token" not in verify["permissions"]
    verify_commands = _run_commands(workflow, "verify")
    assert "uv build" not in verify_commands
    assert "gh-action-pypi-publish" not in str(_steps(workflow, "verify"))
    assert "continue-on-error" not in str(verify)


def test_pypi_workflow_validates_current_remote_annotated_tag_twice() -> None:
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    expected_remote_query = (
        'git ls-remote --exit-code --tags origin "refs/tags/${tag}" "refs/tags/${tag}^{}"'
    )

    for job_name, step_name in (
        ("build", "Validate current remote annotated tag"),
        ("github-release", "Revalidate current remote annotated tag"),
    ):
        steps = _steps(workflow, job_name)
        assert steps[1]["name"] == step_name
        script = steps[1]["run"]
        assert expected_remote_query in script
        assert 'refs/tags/${tag}"' in script
        assert 'refs/tags/${tag}^{}"' in script
        assert 'test -n "$tag_oid"' in script
        assert 'test -n "$peeled_oid"' in script
        assert 'test "$peeled_oid" = "$GITHUB_SHA"' in script


def test_pypi_verification_retries_only_exact_index_installation() -> None:
    path = PROJECT_ROOT / ".github/workflows/publish-pypi.yml"
    workflow_text = path.read_text(encoding="utf-8")
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    verify_script = _step(workflow, "verify", "Install and smoke-test published release")["run"]

    assert workflow_text.count("retry_delays=(5 10 20 40 80)") == 1
    assert workflow_text.count("for attempt in 1 2 3 4 5 6; do") == 1
    assert (
        "if uv pip install --python .pypi-venv/bin/python --no-deps "
        '--default-index https://pypi.org/simple "bundlewalker==${version}"; then' in verify_script
    )
    json_command = next(
        line.strip()
        for line in verify_script.splitlines()
        if "https://pypi.org/pypi/bundlewalker/${version}/json" in line
    )
    assert "--retry" not in json_command
    assert "--retry-all-errors" not in json_command


def test_pypi_release_runs_after_authoritative_recovery() -> None:
    workflow = _yaml(".github/workflows/publish-pypi.yml")
    release = workflow["jobs"]["github-release"]

    assert release["needs"] == ["build", "verify"]
    assert release["if"] == (
        "${{ always() && needs.build.result == 'success' && needs.verify.result == 'success' }}"
    )
    assert release["permissions"] == {"contents": "write"}
    release_text = str(release)
    assert "pypa/gh-action-pypi-publish@" not in release_text
    assert "uv build" not in release_text


def test_release_recovery_reruns_only_the_original_verification_job() -> None:
    plan = (
        PROJECT_ROOT
        / "docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md"
    ).read_text(encoding="utf-8")
    design = (
        PROJECT_ROOT
        / "docs/superpowers/specs/2026-07-21-bundlewalker-0.4.0rc1-production-release-design.md"
    ).read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")

    for document in (plan, design, releases):
        assert "Re-run failed jobs" not in document
        assert "never rerun a failed publish job" in document.lower()
    for command in (
        'gh run download "$RUN_ID" --name python-package-distributions',
        "https://pypi.org/pypi/bundlewalker/${version}/json",
        'VERIFY_JOB_ID="$(gh run view "$RUN_ID" --json jobs',
        'gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"',
    ):
        assert command in plan
    assert "assert local == remote" in plan


def test_release_plan_fails_closed_on_environment_approval_drift() -> None:
    plan = (
        PROJECT_ROOT
        / "docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md"
    ).read_text(encoding="utf-8")

    for assertion in (
        ".protection_rules | map(.type) | sort",
        '["branch_policy", "required_reviewers"]',
        '[.protection_rules[] | select(.type == "required_reviewers")] | length',
        ".prevent_self_review == false",
        "(.reviewers | map({type, login: .reviewer.login})) == "
        '[{"type":"User","login":"HendrikReh"}]',
        ".deployment_branch_policy.protected_branches == false",
        ".deployment_branch_policy.custom_branch_policies == true",
        ".total_count == 1",
        '(.branch_policies[0].name == "v0.4.0*")',
        '(.branch_policies[0].type == "tag")',
    ):
        assert plan.count(assertion) == 2, assertion
    assert plan.count("| jq -e '") >= 4


def test_release_completion_allows_only_exactly_verified_publish_failure() -> None:
    plan = (
        PROJECT_ROOT
        / "docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md"
    ).read_text(encoding="utf-8")
    design = (
        PROJECT_ROOT
        / "docs/superpowers/specs/2026-07-21-bundlewalker-0.4.0rc1-production-release-design.md"
    ).read_text(encoding="utf-8")

    assert 'gh run watch "$RUN_ID" --exit-status' not in plan
    for job_name in (
        "Build and verify exact distributions",
        "Publish exact distributions",
        "Verify production PyPI installation and checksums",
        "Create GitHub release from exact distributions",
    ):
        assert job_name in plan
    for assertion in (
        'test "$BUILD_CONCLUSION" = success',
        'test "$VERIFY_CONCLUSION" = success',
        'test "$RELEASE_CONCLUSION" = success',
        'case "$PUBLISH_CONCLUSION" in',
        "recovered publication warning",
    ):
        assert assertion in plan
    assert "publish may conclude `failure`" in design
    assert "recovered publication warning" in design


def test_release_plan_reaudits_named_jobs_after_verification_rerun() -> None:
    plan = (
        PROJECT_ROOT
        / "docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md"
    ).read_text(encoding="utf-8")

    assert "successful workflow" not in plan.lower()
    recovery_marker = plan.index("If only exact-version installation exhausts")
    rerun_command = 'gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"'
    rerun = plan.index(rerun_command, recovery_marker)
    assert recovery_marker < rerun
    independent_verification = plan.index(
        "- [ ] **Step 7: Independently verify production PyPI", rerun
    )
    recovery_audit = plan[rerun + len(rerun_command) : independent_verification]
    watch_command = 'gh run watch "$RUN_ID"'
    run_json_command = (
        'RUN_JSON="$(gh run view "$RUN_ID" --json status,conclusion,headBranch,headSha,url,jobs)"'
    )
    build_extraction = 'BUILD_CONCLUSION="$(job_conclusion "Build and verify exact distributions")"'
    watch = recovery_audit.index(watch_command)
    refreshed_run_json = recovery_audit.index(run_json_command, watch + len(watch_command))
    post_watch_audit = recovery_audit[watch + len(watch_command) :]
    post_refresh_audit = recovery_audit[refreshed_run_json + len(run_json_command) :]
    assert watch < refreshed_run_json
    assert 'gh run watch "$RUN_ID" --exit-status' not in recovery_audit
    assert run_json_command in post_watch_audit
    for assertion in (
        build_extraction,
        'PUBLISH_CONCLUSION="$(job_conclusion "Publish exact distributions")"',
        'VERIFY_CONCLUSION="$(job_conclusion "Verify production PyPI installation and checksums")"',
        'RELEASE_CONCLUSION="$(job_conclusion "Create GitHub release from exact distributions")"',
        'test "$BUILD_CONCLUSION" = success',
        'test "$VERIFY_CONCLUSION" = success',
        'test "$RELEASE_CONCLUSION" = success',
        'case "$PUBLISH_CONCLUSION" in',
        "recovered publication warning",
    ):
        assert assertion in post_refresh_audit


def test_production_lifecycle_rehearsal_is_manual_read_only_and_supported_only() -> None:
    workflow = _yaml(".github/workflows/rehearse-production-lifecycle.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["UV_VERSION"] == "0.11.28"
    artifact_version = workflow["env"]["LIFECYCLE_ARTIFACT_VERSION"]
    assert artifact_version == "unvalidated-version"
    assert not re.search(r'[\r\n":<>|*?/\\]', artifact_version)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    version = workflow["on"]["workflow_dispatch"]["inputs"]["version"]
    assert version == {
        "description": "Exact production PyPI release candidate (0.4.0rcN)",
        "required": "true",
        "type": "string",
    }

    rehearse = workflow["jobs"]["rehearse"]
    assert "environment" not in rehearse
    assert rehearse["strategy"] == {
        "fail-fast": "false",
        "matrix": {
            "os": ["ubuntu-24.04", "macos-15"],
            "python-version": ["3.13", "3.14"],
        },
    }
    assert rehearse["runs-on"] == "${{ matrix.os }}"
    commands = _run_commands(workflow, "rehearse")
    for required in (
        r"0\.4\.0rc[1-9][0-9]*",
        "UV_NO_CONFIG=1",
        "unset PYTHONPATH UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_FIND_LINKS UV_CONFIG_FILE",
        "--default-index https://pypi.org/simple",
        '"bundlewalker==${VERSION}"',
        "scripts/rehearse_production_lifecycle.py",
        'cd "$REHEARSAL_ROOT"',
    ):
        assert required in commands
    assert "test.pypi.org" not in commands.lower()
    assert "dist/" not in commands
    assert "uv sync" not in commands

    validate_script = _step(workflow, "rehearse", "Validate exact release candidate")["run"]
    artifact_version_overwrite = (
        'printf \'LIFECYCLE_ARTIFACT_VERSION=%s\\n\' "$VERSION_INPUT" >> "$GITHUB_ENV"'
    )
    assert artifact_version_overwrite in validate_script
    assert validate_script.index("re.fullmatch") < validate_script.index(artifact_version_overwrite)

    run_script = _step(workflow, "rehearse", "Run production-installed rehearsal")["run"]
    activate_installed_commands = 'export PATH="$VENV/bin:$PATH"'
    assert activate_installed_commands in run_script
    assert run_script.index(activate_installed_commands) < run_script.index(
        'cp "$GITHUB_WORKSPACE/scripts/rehearse_production_lifecycle.py"'
    )

    upload = _step(workflow, "rehearse", "Upload lifecycle evidence")
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == "90"
    artifact_name = upload["with"]["name"]
    assert "${{ inputs.version }}" not in artifact_name
    assert artifact_name == (
        "production-lifecycle-${{ env.LIFECYCLE_ARTIFACT_VERSION }}-"
        "${{ matrix.os }}-py${{ matrix.python-version }}"
    )
    assert (
        artifact_name.replace("${{ env.LIFECYCLE_ARTIFACT_VERSION }}", "0.4.0rc3")
        == "production-lifecycle-0.4.0rc3-${{ matrix.os }}-py${{ matrix.python-version }}"
    )
    _assert_actions_are_sha_pinned(workflow)


def test_production_lifecycle_rehearsal_policy_is_published_without_premature_claims() -> None:
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")
    compatibility = (PROJECT_ROOT / "docs/workspace-compatibility.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    for required in (
        "gh workflow run rehearse-production-lifecycle.yml --ref master -f version=0.4.0rc2",
        "production-lifecycle-0.4.0rc2-<os>-py<python-version>",
        "Ubuntu 24.04",
        "macOS 15",
        "Python 3.13",
        "Python 3.14",
        "does not import BundleWalker from the checkout",
        "workflow implementation is not live rehearsal evidence",
    ):
        assert required in releases
    assert "advance to the next release candidate" in releases
    assert "rerun the same immutable release candidate" in releases
    assert "current format `1`" in compatibility
    assert "real migration rehearsal" in compatibility
    assert "production-installed lifecycle rehearsal workflow" in changelog
    assert "0.4.0rc2 lifecycle rehearsal passed" not in changelog
