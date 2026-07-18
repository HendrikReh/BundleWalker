# Public Beta Milestone A: Build and Release Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the supported-platform CI, package metadata, policy documents, artifact
verification, security automation, and trusted TestPyPI publication required by Milestone A of the
BundleWalker public-beta roadmap.

**Architecture:** Keep application behavior unchanged while adding repository-level release
infrastructure around the existing Hatchling package and uv lockfile. Treat `pyproject.toml` as
the single authoritative build/runtime version source, verify workflows with executable
repository-policy tests, build one
wheel and source archive per run, and promote those exact artifacts through an OIDC-bound
TestPyPI environment.

**Tech Stack:** Python 3.13 and 3.14, uv 0.11.28, Hatchling, pytest, Ruff, Pyright, Twine,
pip-audit, GitHub Actions, CodeQL, Dependabot, TestPyPI Trusted Publishing, Markdown, Git

## Global Constraints

- Keep BundleWalker local, single-user, and review-first; do not change CLI, MCP, workflow,
  transaction, workspace, model-provider, or OKF behavior.
- Official support is macOS 15 and Ubuntu 24.04 on Python 3.13 and 3.14.
- Windows Server 2025 on Python 3.13 and 3.14 is experimental and non-blocking.
- Keep the Ruff and Pyright language target at Python 3.13, the minimum supported version.
- Keep the complete default test suite offline with `-m 'not eval'`.
- Use uv 0.11.28 in automation and `uv sync --locked` before running project commands.
- Pin every third-party GitHub Action to a full commit SHA and retain a version comment.
- Give workflows only the permissions required by their jobs.
- Use TestPyPI Trusted Publishing with GitHub environment `testpypi` and no stored API token.
- Publish `0.4.0a1` only to TestPyPI; do not create `v0.4.0` or publish to production PyPI.
- Keep `pyproject.toml` as the only authoritative build/runtime package-version declaration;
  derive `bundlewalker.__version__` from installed distribution metadata. Tests and release
  documentation may assert or display the expected release identity.
- Keep the PEP 639 SPDX expression as the license metadata authority; do not add a deprecated
  license Trove classifier.
- Keep the `Development Status :: 3 - Alpha` classifier until the public-beta exit gate passes.
- Do not claim Windows support or add a Windows package classifier.
- Do not add automatic telemetry, crash uploads, credentials, or source contents to automation.
- Preserve the historical `v1`, `v2`, and `v3` tags and releases unchanged.
- Preserve the untracked `2026-07-17T19-22-38.740+02-00-openclaw-backup.tar.gz` without reading,
  staging, modifying, moving, deleting, or archiving it.
- Stop publication if a required CI, artifact, audit, version, or metadata check fails.

---

## File map

- Modify `pyproject.toml`: complete public metadata, add Twine and pip-audit development tools,
  and later set the TestPyPI alpha version.
- Modify `src/bundlewalker/__init__.py`: derive the runtime version from installed metadata.
- Modify `uv.lock`: lock the added development tools and the `0.4.0a1` editable package.
- Modify `tests/test_release_metadata.py`: verify the single version source, public metadata, and
  policy-document navigation.
- Create `tests/test_project_automation.py`: executable structural contracts for CI, security,
  dependency-update, and trusted-publishing configuration.
- Create `.github/workflows/ci.yml`: supported and experimental test matrices, artifact build and
  install checks, dependency audit, and one aggregate required check.
- Create `.github/workflows/codeql.yml`: scheduled and change-triggered Python source analysis.
- Create `.github/workflows/publish-testpypi.yml`: manual, OIDC-only TestPyPI publication and
  post-publication installation verification.
- Create `.github/dependabot.yml`: weekly uv and GitHub Actions update proposals.
- Create `SECURITY.md`: supported-version and private vulnerability-reporting policy.
- Create `SUPPORT.md`: supported scope, issue-routing, and best-effort support boundary.
- Create `docs/maintainers/releases.md`: exact build, TestPyPI, version, and future production
  release procedure.
- Modify `README.md`: policy navigation, platform support, development-version, and maintainer
  release links.
- Modify `CONTRIBUTING.md`: beta-roadmap boundary, supported matrix, policy links, and CI commands.
- Modify `CHANGELOG.md`: record the unreleased Milestone A foundation.
- Configure GitHub after merge: `testpypi` environment, vulnerability alerts, private reporting,
  automated security fixes, and protected `master` with required `Required` CI status.

### Task 1: Complete Package Metadata and Establish One Version Source

**Files:**
- Modify: `pyproject.toml:1-31`
- Modify: `src/bundlewalker/__init__.py:1-4`
- Modify: `tests/test_release_metadata.py:1-45`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: existing static `project.version = "0.3.0"` and
  `importlib.metadata.version("bundlewalker")` from the installed editable distribution.
- Produces: `bundlewalker.__version__: str` derived from distribution metadata; complete
  `[project]` discovery metadata; generic release-version consistency tests used by every later
  version bump.

- [ ] **Step 1: Replace the hard-coded release test with failing generic metadata contracts**

In `tests/test_release_metadata.py`, replace `test_v3_release_versions_are_consistent` with:

```python
def test_release_versions_are_consistent() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    editable_package = next(
        package
        for package in lock["package"]
        if package["name"] == "bundlewalker" and package.get("source") == {"editable": "."}
    )

    expected = project["project"]["version"]
    assert bundlewalker.__version__ == expected
    assert distribution_version("bundlewalker") == expected
    assert editable_package["version"] == expected


def test_public_package_metadata_is_complete() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["authors"] == [{"name": "Hendrik Reh"}]
    assert project["maintainers"] == [{"name": "Hendrik Reh"}]
    assert project["keywords"] == [
        "knowledge-base",
        "markdown",
        "mcp",
        "okf",
        "pydantic-ai",
    ]
    assert project["classifiers"] == [
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Operating System :: MacOS",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Documentation",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ]
    assert project["urls"] == {
        "Homepage": "https://github.com/HendrikReh/BundleWalker",
        "Documentation": "https://github.com/HendrikReh/BundleWalker#documentation",
        "Repository": "https://github.com/HendrikReh/BundleWalker",
        "Issues": "https://github.com/HendrikReh/BundleWalker/issues",
        "Changelog": "https://github.com/HendrikReh/BundleWalker/blob/master/CHANGELOG.md",
    }
```

- [ ] **Step 2: Run the focused tests and verify the metadata contract fails**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_release_versions_are_consistent tests/test_release_metadata.py::test_public_package_metadata_is_complete -v
```

Expected: `test_release_versions_are_consistent` passes against `0.3.0`, while
`test_public_package_metadata_is_complete` fails with a missing `authors` key.

- [ ] **Step 3: Add the exact public package metadata**

Replace the current `[project]` metadata through the dependency list with this complete block:

```toml
[project]
name = "bundlewalker"
version = "0.3.0"
description = "Build a review-first personal knowledge wiki with OKF and PydanticAI."
readme = "README.md"
license = "GPL-3.0-or-later AND CC0-1.0"
license-files = ["LICENSE", "LICENSES/CC0-1.0.txt", "LICENSE-SCOPE.md"]
requires-python = ">=3.13"
authors = [{ name = "Hendrik Reh" }]
maintainers = [{ name = "Hendrik Reh" }]
keywords = [
    "knowledge-base",
    "markdown",
    "mcp",
    "okf",
    "pydantic-ai",
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "Operating System :: MacOS",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Topic :: Documentation",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
dependencies = [
    "jsonschema>=4.26,<5",
    "markdown-it-py>=4.0.0",
    "mcp>=1.28.1,<2",
    "pydantic-ai>=2.10.0",
    "pyyaml>=6.0.0",
    "typer>=0.16.0",
]

[project.urls]
Homepage = "https://github.com/HendrikReh/BundleWalker"
Documentation = "https://github.com/HendrikReh/BundleWalker#documentation"
Repository = "https://github.com/HendrikReh/BundleWalker"
Issues = "https://github.com/HendrikReh/BundleWalker/issues"
Changelog = "https://github.com/HendrikReh/BundleWalker/blob/master/CHANGELOG.md"
```

Keep `[project.scripts]` after `[project.urls]`.

- [ ] **Step 4: Make installed metadata the runtime-version adapter**

Replace `src/bundlewalker/__init__.py` with exactly:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from importlib.metadata import version

__version__ = version("bundlewalker")
```

The authoritative build/runtime version remains only in `pyproject.toml`. Editable development
installs, wheels, and source distributions all expose the same installed metadata through this
adapter.

- [ ] **Step 5: Refresh the editable metadata and run focused verification**

Run:

```bash
uv lock
uv sync --locked
uv run pytest tests/test_release_metadata.py -q
uv run python -c 'import bundlewalker; print(bundlewalker.__version__)'
git diff --check
```

Expected: the release-metadata tests pass, the command prints `0.3.0`, and `git diff --check` is
silent. `uv.lock` changes only if uv refreshes the editable project record; no third-party
dependency version changes are expected in this task.

- [ ] **Step 6: Commit the metadata boundary**

```bash
git add pyproject.toml src/bundlewalker/__init__.py tests/test_release_metadata.py uv.lock
git commit -m "build: complete package metadata"
```

### Task 2: Publish Security and Support Boundaries

**Files:**
- Create: `SECURITY.md`
- Create: `SUPPORT.md`
- Modify: `README.md:7-11,176-190`
- Modify: `CONTRIBUTING.md:1-25,145-190`
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: local-first privacy boundary, official macOS/Linux support decision, experimental
  Windows decision, GitHub Issues, and GitHub private vulnerability reporting.
- Produces: public security and support policies; README and contributor navigation; executable
  checks that keep the policy files linked.

- [ ] **Step 1: Add a failing policy-document navigation test**

Append to `tests/test_release_metadata.py`:

```python
def test_public_policy_documents_exist_and_are_linked() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    security = (PROJECT_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    support = (PROJECT_ROOT / "SUPPORT.md").read_text(encoding="utf-8")

    assert "[Security](SECURITY.md)" in readme
    assert "[Support](SUPPORT.md)" in readme
    assert "[Security Policy](SECURITY.md)" in contributing
    assert "[Support Policy](SUPPORT.md)" in contributing
    assert "security/advisories/new" in security
    assert "Do not report vulnerabilities in a public issue." in security
    assert "macOS and Linux" in support
    assert "Windows is experimental" in support
    assert "no guaranteed response time" in support
```

- [ ] **Step 2: Run the policy test and verify it fails**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_public_policy_documents_exist_and_are_linked -v
```

Expected: FAIL with `FileNotFoundError` for `SECURITY.md`.

- [ ] **Step 3: Create the security policy**

Create `SECURITY.md` with exactly:

```markdown
# Security Policy

## Supported versions

Before BundleWalker 1.0, security fixes are provided for the latest published version only.
Older releases remain available as historical artifacts but do not receive security updates.

| Version | Security support |
| --- | --- |
| Latest published version | Supported |
| Older versions | Not supported |

## Report a vulnerability

Do not report vulnerabilities in a public issue.

Use [GitHub private vulnerability reporting](https://github.com/HendrikReh/BundleWalker/security/advisories/new)
to report suspected credential exposure, path traversal, review bypass, unsafe transaction or
recovery behavior, MCP workspace-boundary violations, dependency vulnerabilities, or another
security-sensitive defect.

Include the affected BundleWalker version, operating system, impact, reproduction steps, and the
smallest safe diagnostic evidence. Do not include real credentials, private source material, or a
user knowledge base. If private reporting is temporarily unavailable, open a public issue asking
the maintainer to establish private contact without disclosing vulnerability details.

Reports are handled on a best-effort basis. The maintainer will validate impact, coordinate a fix
and disclosure when possible, and credit reporters who request attribution.

## Security boundaries

BundleWalker is a local application, but configured model-provider calls may send documented
workflow context to the selected provider. The local MCP server is a foreground `stdio` process
bound to one workspace at startup. BundleWalker does not provide a hosted service, remote MCP
transport, automatic telemetry, or remote crash reporting.

Security reports and support bundles must not contain credentials, raw source content, generated
knowledge content, or unnecessary absolute paths by default.
```

- [ ] **Step 4: Create the support policy**

Create `SUPPORT.md` with exactly:

```markdown
# BundleWalker Support

BundleWalker is moving from proof of concept toward a public beta for technical solo users.
Support is community-based and has no guaranteed response time or service-level agreement.

## Supported scope

- macOS and Linux are the officially supported operating systems.
- Python 3.13 and 3.14 are supported when their required CI jobs pass.
- Windows is experimental and may fail because some filesystem and locking behavior is
  POSIX-specific.
- The supported product surface is the local CLI and workspace-bound MCP `stdio` server.
- Current ingestion accepts one regular UTF-8 Markdown or text file at a time.

Hosted operation, remote MCP transport, multi-user synchronization, a web UI, embeddings, vector
databases, additional source formats, and automatic Git operations are outside the first beta.

## Ask for help or report a bug

Search [existing issues](https://github.com/HendrikReh/BundleWalker/issues) first. If the problem
is new, open an issue with the BundleWalker version, operating system, Python version, installation
method, command or MCP host, expected behavior, actual behavior, and a minimal reproduction.

Remove credentials, private source material, generated knowledge, and unnecessary absolute paths
from logs or diagnostics before posting them.

Security-sensitive reports do not belong in public issues. Follow the
[Security Policy](SECURITY.md) instead.

## Maintenance policy

Before 1.0, only the latest published version receives fixes. Compatibility commitments are
documented per release, and breaking changes must be called out in the changelog and migration
guidance.
```

- [ ] **Step 5: Add policy navigation and the roadmap boundary**

In the README navigation, use:

```markdown
[Tutorial](docs/tutorial.md) · [User Guide](docs/user-guide.md) ·
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) ·
[Security](SECURITY.md) · [Support](SUPPORT.md) · [License](LICENSE-SCOPE.md)
```

Under README `Documentation`, add:

```markdown
- The [Security Policy](SECURITY.md) provides private vulnerability-reporting and supported-version
  guidance.
- The [Support Policy](SUPPORT.md) defines supported platforms, issue reporting, and the
  best-effort maintenance boundary.
```

In `CONTRIBUTING.md`, link the approved
`docs/superpowers/specs/2026-07-18-bundlewalker-public-beta-roadmap-design.md` from `Project
boundaries`. Add this paragraph under `Security and compatibility`:

```markdown
Use the [Security Policy](SECURITY.md) for private vulnerability reports and the
[Support Policy](SUPPORT.md) for public bug-report scope. Never disclose a suspected
vulnerability, credential, or private workspace in a public issue.
```

- [ ] **Step 6: Verify and commit the policy boundary**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
git diff --check
```

Expected: all release-metadata tests pass and the whitespace check is silent.

Commit:

```bash
git add SECURITY.md SUPPORT.md README.md CONTRIBUTING.md tests/test_release_metadata.py
git commit -m "docs: define security and support policies"
```

### Task 3: Add Supported and Experimental CI Matrices

**Files:**
- Create: `tests/test_project_automation.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: existing offline verification commands and uv lockfile.
- Produces: required macOS/Linux evidence for Python 3.13 and 3.14; non-blocking Windows evidence;
  structural workflow tests; aggregate `Required` job used by branch protection.

- [ ] **Step 1: Create the failing CI workflow contract**

Create `tests/test_project_automation.py` with exactly:

```python
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
```

- [ ] **Step 2: Run the contract and verify the workflow is absent**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_ci_has_required_supported_matrix_and_experimental_windows -v
```

Expected: FAIL with `FileNotFoundError` for `.github/workflows/ci.yml`.

- [ ] **Step 3: Create the CI workflow**

Create `.github/workflows/ci.yml` with exactly:

```yaml
name: CI

on:
  push:
    branches: [master]
  pull_request:

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

env:
  UV_VERSION: "0.11.28"

jobs:
  supported:
    name: Supported (${{ matrix.os }}, Python ${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-15]
        python-version: ["3.13", "3.14"]
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: ${{ matrix.python-version }}
          enable-cache: true
          cache-suffix: ${{ matrix.os }}-py${{ matrix.python-version }}
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Verify lockfile
        run: uv lock --check
      - name: Run offline tests
        run: uv run pytest -m 'not eval' -q
      - name: Check formatting
        run: uv run ruff format --check .
      - name: Lint
        run: uv run ruff check .
      - name: Type-check
        run: uv run pyright

  windows-experimental:
    name: Experimental Windows (Python ${{ matrix.python-version }})
    continue-on-error: true
    runs-on: windows-2025
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.13", "3.14"]
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: ${{ matrix.python-version }}
          enable-cache: true
          cache-suffix: windows-2025-py${{ matrix.python-version }}
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Verify lockfile
        run: uv lock --check
      - name: Run offline tests
        run: uv run pytest -m 'not eval' -q
      - name: Check formatting
        run: uv run ruff format --check .
      - name: Lint
        run: uv run ruff check .
      - name: Type-check
        run: uv run pyright

  required:
    name: Required
    if: always()
    needs: [supported]
    runs-on: ubuntu-24.04
    steps:
      - name: Require supported jobs
        shell: bash
        run: |
          test "${{ needs.supported.result }}" = "success"
```

- [ ] **Step 4: Run structural and local verification**

Run:

```bash
uv run pytest tests/test_project_automation.py -q
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Expected: all commands exit `0`. The local run proves repository behavior; GitHub-hosted platform
evidence is collected after the workflow reaches the remote.

- [ ] **Step 5: Commit the platform matrix**

```bash
git add .github/workflows/ci.yml tests/test_project_automation.py
git commit -m "ci: add supported platform matrix"
```

### Task 4: Build Once and Smoke-Test Both Distribution Formats

**Files:**
- Modify: `pyproject.toml:dependency-groups`
- Modify: `uv.lock`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: `supported` CI job and Hatchling package configuration.
- Produces: one `python-package-distributions` artifact containing a wheel and source archive;
  wheel installation evidence on all four supported matrix entries; source-archive installation
  evidence on Ubuntu/Python 3.13.

- [ ] **Step 1: Add a failing artifact-pipeline contract**

Append to `tests/test_project_automation.py`:

```python
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
```

- [ ] **Step 2: Run the artifact contract and verify it fails**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_ci_builds_once_and_smoke_tests_both_distribution_formats -v
```

Expected: FAIL with a missing `build` job.

- [ ] **Step 3: Add Twine to the locked development tools**

Run:

```bash
uv add --group dev 'twine>=6,<7'
```

Expected: `pyproject.toml` gains the bounded Twine requirement and `uv.lock` adds Twine plus its
transitive dependencies without changing runtime dependency ranges.

- [ ] **Step 4: Add the build and artifact-smoke jobs**

Insert these jobs before `required` in `.github/workflows/ci.yml`:

```yaml
  build:
    name: Build distribution
    needs: [supported]
    runs-on: ubuntu-24.04
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
          enable-cache: true
          cache-suffix: build
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Build wheel and source distribution
        run: uv build --clear --no-sources
      - name: Validate distribution metadata
        run: uv run twine check dist/*
      - name: Upload exact distributions
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: python-package-distributions
          path: dist/
          if-no-files-found: error
          retention-days: 14

  artifact-smoke:
    name: Artifact smoke (${{ matrix.os }}, Python ${{ matrix.python-version }})
    needs: [build]
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-15]
        python-version: ["3.13", "3.14"]
    steps:
      - name: Download exact distributions
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        with:
          name: python-package-distributions
          path: dist/
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: ${{ matrix.python-version }}
      - name: Install wheel without repository checkout
        shell: bash
        run: |
          uv venv --python "${{ matrix.python-version }}" .artifact-venv
          uv pip install --python .artifact-venv/bin/python dist/*.whl
          .artifact-venv/bin/bundlewalker --help
          .artifact-venv/bin/bundlewalker-mcp --help
          .artifact-venv/bin/python -c 'from importlib.metadata import version; print(version("bundlewalker"))'

  sdist-smoke:
    name: Source distribution smoke
    needs: [build]
    runs-on: ubuntu-24.04
    steps:
      - name: Download exact distributions
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        with:
          name: python-package-distributions
          path: dist/
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
      - name: Build and install from source distribution
        shell: bash
        run: |
          uv venv --python "3.13" .sdist-venv
          uv pip install --python .sdist-venv/bin/python dist/*.tar.gz
          .sdist-venv/bin/bundlewalker --help
          .sdist-venv/bin/bundlewalker-mcp --help
```

Replace the `required` job with:

```yaml
  required:
    name: Required
    if: always()
    needs: [supported, build, artifact-smoke, sdist-smoke]
    runs-on: ubuntu-24.04
    steps:
      - name: Require supported jobs
        shell: bash
        run: |
          test "${{ needs.supported.result }}" = "success"
          test "${{ needs.build.result }}" = "success"
          test "${{ needs.artifact-smoke.result }}" = "success"
          test "${{ needs.sdist-smoke.result }}" = "success"
```

- [ ] **Step 5: Exercise the same package path locally**

Run:

```bash
PACKAGE_TMP="$(mktemp -d)"
uv sync --locked
uv build --clear --no-sources --out-dir "$PACKAGE_TMP/dist"
uv run twine check "$PACKAGE_TMP"/dist/*
uv venv --python 3.13 "$PACKAGE_TMP/wheel-venv"
uv pip install --python "$PACKAGE_TMP/wheel-venv/bin/python" "$PACKAGE_TMP"/dist/*.whl
"$PACKAGE_TMP/wheel-venv/bin/bundlewalker" --help
"$PACKAGE_TMP/wheel-venv/bin/bundlewalker-mcp" --help
```

Expected: the wheel and source archive build, Twine reports both distributions `PASSED`, and both
installed console scripts exit `0`.

- [ ] **Step 6: Verify and commit artifact automation**

Run:

```bash
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
uv lock --check
git diff --check
```

Expected: all commands exit `0`.

Commit:

```bash
git add pyproject.toml uv.lock .github/workflows/ci.yml tests/test_project_automation.py
git commit -m "ci: verify package artifacts"
```

### Task 5: Add Dependency and Source Security Automation

**Files:**
- Create: `.github/dependabot.yml`
- Create: `.github/workflows/codeql.yml`
- Modify: `pyproject.toml:dependency-groups`
- Modify: `uv.lock`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: locked runtime and development environment; GitHub uv and Actions ecosystems.
- Produces: required dependency audit, weekly dependency-update proposals, scheduled CodeQL
  analysis, and structural tests preventing unpinned actions or disabled scanners.

- [ ] **Step 1: Add failing security-automation contracts**

Append to `tests/test_project_automation.py`:

```python
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
```

- [ ] **Step 2: Run the new contracts and verify all three fail**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_ci_requires_dependency_audit tests/test_project_automation.py::test_dependabot_updates_uv_and_actions_weekly tests/test_project_automation.py::test_codeql_scans_python_on_changes_and_schedule -v
```

Expected: FAIL because the dependency-audit job and both configuration files are absent.

- [ ] **Step 3: Lock pip-audit as a development tool**

Run:

```bash
uv add --group dev 'pip-audit>=2.9,<3'
uv sync --locked
AUDIT_REQ="$(mktemp)"
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
```

Expected: the requirement and lock entries are added, the frozen lock export preserves hashes,
and pip-audit exits `0` with no known vulnerabilities. If it reports a vulnerability or cannot
complete its advisory query, stop and open a focused remediation task; do not suppress, ignore,
or allow-fail the required audit.

- [ ] **Step 4: Add the required dependency-audit job**

Insert before `required` in `.github/workflows/ci.yml`:

```yaml
  dependency-audit:
    name: Dependency audit
    needs: [supported]
    runs-on: ubuntu-24.04
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
          enable-cache: true
          cache-suffix: dependency-audit
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Export locked third-party requirements
        run: uv export --frozen --no-emit-project --output-file "$RUNNER_TEMP/bundlewalker-audit-requirements.txt" >/dev/null
      - name: Audit locked third-party dependencies
        run: uv run pip-audit --strict --requirement "$RUNNER_TEMP/bundlewalker-audit-requirements.txt" --require-hashes --disable-pip
```

Add `dependency-audit` to `required.needs` and add:

```yaml
          test "${{ needs.dependency-audit.result }}" = "success"
```

to the aggregate job's shell script.

- [ ] **Step 5: Configure weekly uv and Actions updates**

Create `.github/dependabot.yml` with exactly:

```yaml
version: 2
updates:
  - package-ecosystem: uv
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "05:00"
      timezone: Europe/Berlin
    open-pull-requests-limit: 5
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "05:30"
      timezone: Europe/Berlin
    open-pull-requests-limit: 5
```

- [ ] **Step 6: Configure Python CodeQL**

Create `.github/workflows/codeql.yml` with exactly:

```yaml
name: CodeQL

on:
  push:
    branches: [master]
  pull_request:
  schedule:
    - cron: "23 4 * * 1"

permissions:
  contents: read
  security-events: write

jobs:
  analyze:
    name: Analyze (Python)
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        language: [python]
    steps:
      - name: Check out repository
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Initialize CodeQL
        uses: github/codeql-action/init@7188fc363630916deb702c7fdcf4e481b751f97a # v4.37.1
        with:
          languages: ${{ matrix.language }}
      - name: Analyze
        uses: github/codeql-action/analyze@7188fc363630916deb702c7fdcf4e481b751f97a # v4.37.1
```

- [ ] **Step 7: Verify and commit security automation**

Run:

```bash
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
AUDIT_REQ="$(mktemp)"
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
uv lock --check
git diff --check
```

Expected: all tests and the audit pass, the lockfile is current, and the whitespace check is
silent.

Commit:

```bash
git add .github/dependabot.yml .github/workflows/codeql.yml .github/workflows/ci.yml pyproject.toml tests/test_project_automation.py uv.lock
git commit -m "ci: add security automation"
```

### Task 6: Add OIDC-Only TestPyPI Publishing and Maintainer Guidance

**Files:**
- Create: `.github/workflows/publish-testpypi.yml`
- Create: `docs/maintainers/releases.md`
- Modify: `tests/test_project_automation.py`
- Modify: `README.md:176-210`
- Modify: `CONTRIBUTING.md:145-190`

**Interfaces:**
- Consumes: verified package build, `testpypi` GitHub environment, TestPyPI pending trusted
  publisher, and manual `version` workflow input.
- Produces: a master-only, secretless manual publication workflow that re-audits frozen locked
  dependencies, builds once, uploads exact artifacts, publishes attestations through
  `pypa/gh-action-pypi-publish`, and installs the published version from TestPyPI.

- [ ] **Step 1: Add a failing trusted-publishing workflow contract**

Append to `tests/test_project_automation.py`:

```python
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
```

- [ ] **Step 2: Run the publishing contract and verify the workflow is absent**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_testpypi_workflow_is_manual_oidc_only_and_verifies_publication -v
```

Expected: FAIL with `FileNotFoundError` for `.github/workflows/publish-testpypi.yml`. During later
maintenance, removing a master guard, the frozen hashed audit, or either dependency edge must make
the same contract fail at its corresponding assertion.

- [ ] **Step 3: Create the TestPyPI workflow**

Create `.github/workflows/publish-testpypi.yml` with exactly:

```yaml
name: Publish to TestPyPI

on:
  workflow_dispatch:
    inputs:
      version:
        description: Exact PEP 440 prerelease version already declared in pyproject.toml
        required: true
        type: string

permissions:
  contents: read

env:
  UV_VERSION: "0.11.28"

jobs:
  build:
    name: Build exact distributions
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-24.04
    steps:
      - name: Check out selected revision
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
          enable-cache: true
          cache-suffix: publish-testpypi
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Verify requested prerelease version
        shell: bash
        run: |
          actual="$(uv run python -c 'from importlib.metadata import version; print(version("bundlewalker"))')"
          test "$actual" = "${{ inputs.version }}"
          case "$actual" in
            0.4.0a*|0.4.0rc*) ;;
            *) exit 1 ;;
          esac
      - name: Run offline acceptance gates
        run: |
          uv run pytest -m 'not eval' -q
          uv run ruff format --check .
          uv run ruff check .
          uv run pyright
          uv lock --check
      - name: Export locked third-party requirements
        run: uv export --frozen --no-emit-project --output-file "$RUNNER_TEMP/bundlewalker-audit-requirements.txt" >/dev/null
      - name: Audit locked third-party dependencies
        run: uv run pip-audit --strict --requirement "$RUNNER_TEMP/bundlewalker-audit-requirements.txt" --require-hashes --disable-pip
      - name: Build wheel and source distribution
        run: uv build --clear --no-sources
      - name: Validate distribution metadata
        run: uv run twine check dist/*
      - name: Upload exact distributions
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: python-package-distributions
          path: dist/
          if-no-files-found: error
          retention-days: 30

  publish:
    name: Publish exact distributions
    if: github.ref == 'refs/heads/master'
    needs: [build]
    runs-on: ubuntu-24.04
    environment:
      name: testpypi
      url: https://test.pypi.org/p/bundlewalker
    permissions:
      id-token: write
    steps:
      - name: Download exact distributions
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        with:
          name: python-package-distributions
          path: dist/
      - name: Publish with short-lived OIDC credentials
        uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b # v1.14.0
        with:
          repository-url: https://test.pypi.org/legacy/

  verify:
    name: Verify TestPyPI installation
    needs: [publish]
    runs-on: ubuntu-24.04
    permissions:
      contents: read
    steps:
      - name: Download exact distributions
        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1
        with:
          name: python-package-distributions
          path: dist/
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
      - name: Install and smoke-test published prerelease
        shell: bash
        run: |
          uv venv --python "3.13" .testpypi-venv
          uv pip install --python .testpypi-venv/bin/python dist/*.whl
          uv pip uninstall --python .testpypi-venv/bin/python bundlewalker
          uv pip install --python .testpypi-venv/bin/python --no-deps --default-index https://test.pypi.org/simple "bundlewalker==${{ inputs.version }}"
          test "$(.testpypi-venv/bin/python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = "${{ inputs.version }}"
          .testpypi-venv/bin/bundlewalker --help
          .testpypi-venv/bin/bundlewalker-mcp --help
```

- [ ] **Step 4: Create the maintainer release guide**

Create `docs/maintainers/releases.md` with these exact sections and contracts:

````markdown
# BundleWalker Release Procedure

BundleWalker builds one wheel and one source distribution for each publication. The same verified
artifacts are promoted; they are never rebuilt between indexes or release attachments.

## Version policy

- `pyproject.toml` is the only authoritative build/runtime package-version source.
- `bundlewalker.__version__` reads installed distribution metadata.
- Historical `v1`, `v2`, and `v3` tags remain unchanged.
- New tags match package versions, for example `v0.4.0` and `v0.4.1`.
- Alpha or release-candidate versions may be published to TestPyPI.
- Production `0.4.0` is forbidden until every public-beta exit gate passes.

## Local release verification

Run from a clean checkout:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
AUDIT_REQ="$(mktemp)"
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
```

The commands must all exit zero. The `dist/` directory must contain exactly one
`bundlewalker-*.whl` and one `bundlewalker-*.tar.gz` for the declared version.

## TestPyPI

TestPyPI publishing uses the GitHub workflow `publish-testpypi.yml`, GitHub environment
`testpypi`, and a matching TestPyPI trusted publisher. It does not use an API-token secret.
The workflow's build and publish jobs run only from `master`.

Dispatch it with the exact version already present on `master`:

```bash
gh workflow run publish-testpypi.yml --ref master -f version=0.4.0a1
```

The build, publish, and TestPyPI installation jobs must all pass. TestPyPI versions are immutable;
increment the prerelease version instead of attempting to overwrite a failed publication.

## Production PyPI and GitHub releases

Production publication is a later milestone. Before enabling it, add a separate `pypi` environment
with required human approval, configure its trusted publisher, require a package-aligned tag, and
attach the exact workflow-built wheel and source archive to the GitHub release.

Never delete or replace historical releases to correct a later license, documentation, or
compatibility decision. Publish a new version and document the difference.

## Failure and rollback

Do not retry by rebuilding the same version. Diagnose the failed job, fix the repository, increment
the prerelease or patch version, and run the complete verification again. If a production release
is later found unsafe, stop new installations through the package index's supported yank mechanism,
publish an advisory, and issue a fixed version; do not move or reuse its Git tag.
````

Use ordinary Markdown fences in the file; the outer four-backtick block here exists only to quote
its embedded shell blocks.

- [ ] **Step 5: Link the maintainer procedure**

Add this bullet under README `Documentation`:

```markdown
- The [Release Procedure](docs/maintainers/releases.md) defines maintainer-only build,
  TestPyPI, versioning, and failure handling.
```

Add this sentence under `Development` in `CONTRIBUTING.md`:

```markdown
Maintainers must follow the [Release Procedure](docs/maintainers/releases.md); contributors must
not create tags or publish package artifacts from feature branches.
```

- [ ] **Step 6: Verify and commit trusted-publishing configuration**

Run:

```bash
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
git diff --check
```

Expected: the workflow and metadata policy tests pass and the whitespace check is silent.

Commit:

```bash
git add .github/workflows/publish-testpypi.yml CONTRIBUTING.md README.md docs/maintainers/releases.md tests/test_project_automation.py
git commit -m "ci: add trusted TestPyPI publishing"
```

### Task 7: Prepare the 0.4.0a1 Foundation Artifact

**Files:**
- Modify: `pyproject.toml:3`
- Modify: `uv.lock`
- Modify: `tests/test_release_metadata.py`
- Modify: `README.md:1-10`
- Modify: `CHANGELOG.md:3-6`

**Interfaces:**
- Consumes: single pyproject version source and TestPyPI workflow's exact `version` input.
- Produces: an internally consistent `0.4.0a1` package state ready for TestPyPI only.

- [ ] **Step 1: Add the failing foundation-alpha version contract**

Append to `tests/test_release_metadata.py`:

```python
def test_development_version_is_foundation_alpha() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0a1"
    assert bundlewalker.__version__ == "0.4.0a1"
```

- [ ] **Step 2: Run the version test and verify it fails**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_development_version_is_foundation_alpha -v
```

Expected: FAIL because both values still report `0.3.0`.

- [ ] **Step 3: Bump only the authoritative version declaration**

Change `pyproject.toml`:

```toml
version = "0.4.0a1"
```

Run:

```bash
uv lock
uv sync --locked
```

Expected: only BundleWalker's editable record changes to `0.4.0a1`; runtime
`bundlewalker.__version__` follows automatically after synchronization.

- [ ] **Step 4: Record development and changelog status**

Replace the README release sentence with:

```markdown
Latest tagged release: **v3** (Python package `0.3.0`). The current development version is
`0.4.0a1` for the public-beta release-foundation rehearsal. See the
[changelog](CHANGELOG.md) for release history.
```

Under `CHANGELOG.md` `[Unreleased]`, add:

```markdown
### Added

- Added required macOS/Linux CI for Python 3.13 and 3.14 plus visible experimental Windows jobs.
- Added verified wheel and source-distribution builds, artifact installation smoke tests,
  dependency auditing, CodeQL, and Dependabot.
- Added public security and support policies, complete package metadata, and an OIDC-only
  TestPyPI publishing rehearsal.

### Changed

- Adopted package-aligned versioning beginning with development version `0.4.0a1`.
- Made installed distribution metadata the runtime package-version source.
```

- [ ] **Step 5: Run complete local release-foundation verification**

Run:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
AUDIT_REQ="$(mktemp)"
uv export --frozen --no-emit-project --output-file "$AUDIT_REQ" >/dev/null
uv run pip-audit --strict --requirement "$AUDIT_REQ" --require-hashes --disable-pip
uv lock --check
PACKAGE_TMP="$(mktemp -d)"
uv build --clear --no-sources --out-dir "$PACKAGE_TMP/dist"
uv run twine check "$PACKAGE_TMP"/dist/*
test "$(find "$PACKAGE_TMP/dist" -maxdepth 1 -name 'bundlewalker-0.4.0a1-*.whl' | wc -l | tr -d ' ')" = "1"
test "$(find "$PACKAGE_TMP/dist" -maxdepth 1 -name 'bundlewalker-0.4.0a1.tar.gz' | wc -l | tr -d ' ')" = "1"
git diff --check
```

Expected:  all offline, format, lint, type, audit, lock, build, metadata, artifact-count, and
whitespace checks pass.

- [ ] **Step 6: Commit the foundation alpha**

```bash
git add CHANGELOG.md README.md pyproject.toml tests/test_release_metadata.py uv.lock
git commit -m "build: prepare 0.4.0a1 foundation alpha"
```

Do not create a tag or GitHub release.

### Task 8: Activate and Verify the Remote Release Foundation

**Files:**
- Remote configuration: GitHub environment, security settings, branch protection
- External configuration: TestPyPI pending trusted publisher
- Remote artifact: TestPyPI `bundlewalker==0.4.0a1`

**Interfaces:**
- Consumes: Tasks 1-7 merged to `origin/master`; authenticated `gh`, GitHub, and TestPyPI
  accounts; successful `CI` and `CodeQL` workflows on master.
- Produces: verified TestPyPI publication, enabled repository security services, protected master,
  and objective Milestone A exit evidence.

- [ ] **Step 1: Verify the implementation is integrated before changing remote settings**

Run:

```bash
gh auth status
test "$(git branch --show-current)" = "master"
test -z "$(git status --porcelain --untracked-files=no)"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)"
gh run list --workflow ci.yml --branch master --limit 1 --json conclusion --jq '.[0].conclusion' | rg '^success$'
gh run list --workflow codeql.yml --branch master --limit 1 --json conclusion --jq '.[0].conclusion' | rg '^success$'
gh api repos/HendrikReh/BundleWalker/commits/master/check-runs --jq '.check_runs[].name' | rg '^Required$'
```

Expected: authentication is valid, local `master` exactly matches `origin/master`, both workflows
conclude `success`, and the `Required` check exists. The known backup archive may remain untracked
because the clean check deliberately excludes untracked files.

- [ ] **Step 2: Create the GitHub environment and enable repository security services**

Run:

```bash
gh api --method PUT repos/HendrikReh/BundleWalker/environments/testpypi
gh api --method PUT repos/HendrikReh/BundleWalker/vulnerability-alerts
gh api --method PUT repos/HendrikReh/BundleWalker/automated-security-fixes
gh api --method PUT repos/HendrikReh/BundleWalker/private-vulnerability-reporting
gh api repos/HendrikReh/BundleWalker/private-vulnerability-reporting --jq .enabled
```

Expected: each PUT succeeds; the final command prints `true`. Do not create repository secrets for
PyPI or TestPyPI.

- [ ] **Step 3: Register the pending TestPyPI trusted publisher**

Sign in to `https://test.pypi.org/manage/account/publishing/` and add a pending GitHub publisher
with exactly:

```text
PyPI project name: bundlewalker
GitHub owner: HendrikReh
GitHub repository name: BundleWalker
Workflow name: publish-testpypi.yml
Environment name: testpypi
```

Expected: TestPyPI lists the pending publisher. If the `bundlewalker` name has been claimed by
another account, stop before publication and return to the user for a package-name decision.

- [ ] **Step 4: Dispatch and watch the exact TestPyPI alpha**

Run:

```bash
gh workflow run publish-testpypi.yml --ref master -f version=0.4.0a1
RUN_ID="$(gh run list --workflow publish-testpypi.yml --branch master --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$RUN_ID" --exit-status
```

Expected: `Build exact distributions`, `Publish exact distributions`, and
`Verify TestPyPI installation` all pass. A failed or partially uploaded version is immutable:
diagnose it and prepare `0.4.0a2` in a new reviewed change instead of overwriting `0.4.0a1`.

- [ ] **Step 5: Protect master with the aggregate supported-platform check**

Run:

```bash
gh api --method PUT repos/HendrikReh/BundleWalker/branches/master/protection --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Required"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
JSON
```

Expected: the API returns branch-protection JSON with strict `Required` status checks, admin
enforcement, conversation resolution, and force-push/deletion disabled. Future implementation
changes must reach master through a branch whose `Required` check succeeds.

- [ ] **Step 6: Capture final Milestone A evidence**

Run:

```bash
gh api repos/HendrikReh/BundleWalker/branches/master/protection --jq '{strict: .required_status_checks.strict, contexts: [.required_status_checks.contexts[].context], enforce_admins: .enforce_admins.enabled, conversations: .required_conversation_resolution.enabled, force_pushes: .allow_force_pushes.enabled, deletions: .allow_deletions.enabled}'
gh api repos/HendrikReh/BundleWalker/private-vulnerability-reporting --jq .enabled
gh run view "$RUN_ID" --json conclusion,url --jq '{conclusion, url}'
curl --fail --silent --show-error https://test.pypi.org/pypi/bundlewalker/0.4.0a1/json |
  uv run python -c 'import json,sys; data=json.load(sys.stdin); assert data["info"]["version"] == "0.4.0a1"; print(data["info"]["version"])'
git status --short --branch
```

Expected:

- branch protection reports `strict: true`, `contexts: ["Required"]`,
  `enforce_admins: true`, `conversations: true`, `force_pushes: false`, and
  `deletions: false`;
- private vulnerability reporting prints `true`;
- the TestPyPI workflow conclusion is `success`;
- the TestPyPI JSON check prints `0.4.0a1`; and
- the local branch matches `origin/master` with only the known untracked backup archive.

Milestone A is complete only when every item above is fresh evidence. Production PyPI, a
`v0.4.0` tag, GitHub release artifacts, workspace migrations, `bundlewalker doctor`, MCP host
certification, benchmarks, and beta-user validation belong to later plans.

## Planning references

- [GitHub-hosted runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [GitHub Actions: Building and testing Python](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)
- [GitHub Dependabot supported ecosystems](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories)
- [Astral `setup-uv` action](https://github.com/astral-sh/setup-uv)
- [PyPA trusted publishing workflow guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [PyPI pending trusted publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
