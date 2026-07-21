# BundleWalker 0.4.0rc1 Production Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare, publish, and independently verify the immutable BundleWalker `0.4.0rc1` release candidate on production PyPI and GitHub.

**Architecture:** Land a dedicated tag-triggered production workflow and the `0.4.0rc1` package identity through a protected pull request. The workflow derives every downstream identity from the tagged `pyproject.toml`, builds one wheel and one source archive, publishes them through a human-approved OIDC environment, verifies production metadata and installation, and attaches the same bytes to a GitHub prerelease. External configuration and tagging occur only after the reviewed repository state reaches `master`.

**Tech Stack:** Python 3.13/3.14, uv 0.11.28, pytest, Ruff, Pyright, pip-audit, Hatchling, Twine, GitHub Actions, GitHub environments, PyPI trusted publishing, GitHub CLI.

## Global Constraints

- The exact prerelease version is `0.4.0rc1`; the exact annotated Git tag is `v0.4.0rc1`.
- `pyproject.toml` is the only authoritative build/runtime package-version source.
- Production publication uses `.github/workflows/publish-pypi.yml`, GitHub environment `pypi`, and PyPI OIDC only; no password or API token is stored.
- The pending publisher tuple is `HendrikReh/BundleWalker/publish-pypi.yml/pypi`, registered by production-PyPI user `hereh`.
- The wheel and source archive are built once in the tag workflow; publish, verify, and GitHub release jobs download those exact workflow artifacts and never rebuild them.
- The workflow accepts only `0.4.0rcN` with positive `N`, or final `0.4.0`, and requires tag `v${project.version}`.
- Create the tag only after the protected release pull request is merged, and point it at that exact reviewed merge commit.
- Never move, delete, or reuse a pushed tag or published version. A failure after tag push advances to `0.4.0rc2`.
- Required macOS and Linux CI must pass; Windows remains experimental and non-blocking.
- Preserve immutable benchmark evidence and historical documents that intentionally record `0.4.0a2`.
- Preserve license metadata `GPL-3.0-or-later AND CC0-1.0` and the current proof-of-concept statement.
- Do not dispatch TestPyPI, publish final `0.4.0`, or claim the broader public-beta milestone complete.
- The external publication steps stop before tag creation if environment protection or the pending trusted publisher cannot be verified.

---

## File Map

- Create `.github/workflows/publish-pypi.yml`: the sole production build, OIDC publication, production verification, and GitHub release pipeline.
- Modify `tests/test_project_automation.py`: structural contract for the production workflow, its artifact flow, retry boundary, and least-privilege permissions.
- Modify `pyproject.toml`: authoritative version changes from `0.4.0a2` to `0.4.0rc1`; the Alpha classifier intentionally remains until final beta.
- Modify `uv.lock`: only the editable `bundlewalker` package version follows `pyproject.toml`.
- Modify `tests/test_release_metadata.py`: current release identity, documentation contract, and version-derived source-archive root.
- Modify `tests/cli/test_workspace.py`: current installed version shown by `workspace status`.
- Modify `tests/application/test_lifecycle.py`: current installed version in the default lifecycle dependency result.
- Modify `README.md`: identify the production release candidate and provide an exact production installation command while retaining proof-of-concept wording.
- Modify `CHANGELOG.md`: cut the current Unreleased work into `v0.4.0rc1` and add comparison links.
- Modify `docs/maintainers/releases.md`: production workflow, protected environment, pending publisher, tagging, verification, and recovery procedure.
- Modify `docs/superpowers/specs/2026-07-21-bundlewalker-0.4.0rc1-production-release-design.md`: record approved status and correct the existing license split.
- Create `docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md`: this executable plan.

---

### Task 1: Add the tag-gated production publication workflow

**Files:**
- Create: `.github/workflows/publish-pypi.yml`
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: `pyproject.toml` project version, the existing pinned action versions, the locked development environment, and GitHub tag context.
- Produces: build output `version: str`; workflow artifact `python-package-distributions` containing exactly one wheel and one source archive; jobs `build`, `publish`, `verify`, and `github-release`.

- [ ] **Step 1: Write the failing workflow contract test**

Append this test to `tests/test_project_automation.py`:

```python
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
        "uv run twine check dist/*",
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
    assert verify["if"] == (
        "${{ always() && needs.build.result == 'success' && "
        "(needs.publish.result == 'success' || needs.publish.result == 'failure') }}"
    )
    assert verify["permissions"] == {"contents": "read"}
    verify_commands = _run_commands(workflow, "verify")
    assert "retry_delays=(5 10 20 40 80)" in verify_commands
    assert "for attempt in 1 2 3 4 5 6; do" in verify_commands
    assert "--default-index https://pypi.org/simple" in verify_commands
    assert "https://pypi.org/pypi/bundlewalker/${version}/json" in verify_commands
    assert 'item["digests"]["sha256"]' in verify_commands

    release = workflow["jobs"]["github-release"]
    assert release["needs"] == ["build", "verify"]
    assert release["if"] == (
        "${{ always() && needs.build.result == 'success' && "
        "needs.verify.result == 'success' }}"
    )
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
```

Also add focused structural tests that:

- extract the exact release-lane regex from the identity step and accept `0.4.0rc1`, `0.4.0rc2`,
  `0.4.0rc10`, and `0.4.0`, while rejecting `0.4.0rc0`, `0.4.1rc1`, `0.4.0a2`, and `1.0.0`;
- extract the exact release-step prerelease branch and prove RCs are prereleases while final
  `0.4.0` is not;
- require the exact local and production-PyPI two-file counts, expected wheel and sdist names,
  digest equality before the install retry, and artifact name/path in every downstream download;
- require read-only verification after ordinary publish success or failure without
  `continue-on-error`, rebuilding, or republishing;
- require live remote annotated-tag and peeled-commit validation before build and before GitHub
  release creation;
- prove only the exact production-index install loop owns the 5/10/20/40/80-second retry and the
  production-PyPI JSON request has no retry flags;
- require the GitHub release job's exact `always()` condition so authoritative recovery bypasses
  the failed publish ancestor's implicit `success()` guard;
- reject broad failed-job reruns in favor of original-artifact/production-JSON proof followed by
  job-specific verification rerun;
- require Task 4 and Task 5 to fail closed on any reviewer, self-review, wait-timer, protection-rule,
  or branch/tag-policy drift; and
- accept publish failure at completion only when the same run's build, authoritative verification,
  and GitHub release jobs succeeded and a recovered publication warning is recorded.

- [ ] **Step 2: Run the focused test and confirm the missing-workflow failure**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_pypi_workflow_is_tag_gated_oidc_only_and_reuses_exact_artifacts -q
```

Expected: FAIL with `FileNotFoundError` for `.github/workflows/publish-pypi.yml`.

- [ ] **Step 3: Add the complete production workflow**

Create `.github/workflows/publish-pypi.yml` with exactly this content:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

env:
  UV_VERSION: "0.11.28"

jobs:
  build:
    name: Build and verify exact distributions
    runs-on: ubuntu-24.04
    outputs:
      version: ${{ steps.identity.outputs.version }}
    steps:
      - name: Check out tagged revision
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Validate current remote annotated tag
        shell: bash
        run: |
          test "$GITHUB_REF_TYPE" = "tag"
          tag="$GITHUB_REF_NAME"
          remote_refs="$(git ls-remote --exit-code --tags origin "refs/tags/${tag}" "refs/tags/${tag}^{}")"
          tag_oid="$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/${tag}" '$2 == ref { print $1 }')"
          peeled_oid="$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/${tag}^{}" '$2 == ref { print $1 }')"
          test -n "$tag_oid"
          test -n "$peeled_oid"
          test "$peeled_oid" = "$GITHUB_SHA"
      - name: Install uv and Python
        uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
        with:
          version: ${{ env.UV_VERSION }}
          python-version: "3.13"
          enable-cache: true
          cache-suffix: publish-pypi
      - name: Synchronize locked environment
        run: uv sync --locked
      - name: Validate release identity
        id: identity
        shell: bash
        run: |
          version="$(uv run python -c 'import tomllib; from pathlib import Path; print(tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])')"
          uv run python -c 'import re, sys; from packaging.version import Version; value = sys.argv[1]; assert str(Version(value)) == value; assert re.fullmatch(r"0\.4\.0(?:rc[1-9][0-9]*)?", value)' "$version"
          test "$GITHUB_REF_TYPE" = "tag"
          test "$GITHUB_REF_NAME" = "v${version}"
          test "$(uv run python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = "$version"
          printf 'version=%s\n' "$version" >> "$GITHUB_OUTPUT"
      - name: Run offline acceptance gates
        run: |
          uv lock --check
          uv run pytest -m 'not eval' -q
          uv run ruff format --check .
          uv run ruff check .
          uv run pyright
      - name: Export locked third-party requirements
        run: uv export --frozen --no-emit-project --output-file "$RUNNER_TEMP/bundlewalker-audit-requirements.txt" >/dev/null
      - name: Audit locked third-party dependencies
        run: uv run pip-audit --strict --requirement "$RUNNER_TEMP/bundlewalker-audit-requirements.txt" --require-hashes --disable-pip
      - name: Build wheel and source distribution once
        run: uv build --clear --no-sources
      - name: Validate exact artifacts and metadata
        shell: bash
        run: |
          mapfile -t artifacts < <(find dist -maxdepth 1 -type f -print | sort)
          test "${#artifacts[@]}" -eq 2
          test -f "dist/bundlewalker-${{ steps.identity.outputs.version }}-py3-none-any.whl"
          test -f "dist/bundlewalker-${{ steps.identity.outputs.version }}.tar.gz"
          uv run twine check dist/*
          sha256sum "${artifacts[@]}"
      - name: Install and smoke-test built wheel
        shell: bash
        run: |
          uv venv --python "3.13" .release-venv
          uv pip install --python .release-venv/bin/python dist/*.whl
          test "$(.release-venv/bin/python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = "${{ steps.identity.outputs.version }}"
          .release-venv/bin/bundlewalker --help
          .release-venv/bin/bundlewalker-mcp --help
      - name: Upload exact distributions
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: python-package-distributions
          path: dist/
          if-no-files-found: error
          retention-days: 90

  publish:
    name: Publish exact distributions
    needs: [build]
    runs-on: ubuntu-24.04
    environment:
      name: pypi
      url: https://pypi.org/project/bundlewalker/${{ needs.build.outputs.version }}/
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

  verify:
    name: Verify production PyPI installation and checksums
    needs: [build, publish]
    if: ${{ always() && needs.build.result == 'success' && (needs.publish.result == 'success' || needs.publish.result == 'failure') }}
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
      - name: Install and smoke-test published release
        shell: bash
        run: |
          version="${{ needs.build.outputs.version }}"
          curl --fail --silent --show-error --location "https://pypi.org/pypi/bundlewalker/${version}/json" --output "$RUNNER_TEMP/pypi.json"
          uv run --no-project python - "$RUNNER_TEMP/pypi.json" "$version" <<'PY'
          import hashlib
          import json
          import sys
          from pathlib import Path

          payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
          version = sys.argv[2]
          assert payload["info"]["version"] == version
          local = {
              path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in Path("dist").iterdir()
              if path.is_file()
          }
          remote = {item["filename"]: item["digests"]["sha256"] for item in payload["urls"]}
          assert len(payload["urls"]) == 2
          assert len(local) == 2
          assert local == remote, {"local": local, "remote": remote}
          PY
          uv venv --python "3.13" .pypi-venv
          uv pip install --python .pypi-venv/bin/python dist/*.whl
          .pypi-venv/bin/bundlewalker --help
          .pypi-venv/bin/bundlewalker-mcp --help
          uv pip uninstall --python .pypi-venv/bin/python bundlewalker
          retry_delays=(5 10 20 40 80)
          for attempt in 1 2 3 4 5 6; do
            if uv pip install --python .pypi-venv/bin/python --no-deps --default-index https://pypi.org/simple "bundlewalker==${version}"; then
              break
            fi
            if [ "$attempt" -eq 6 ]; then
              echo "::error::Production PyPI did not expose bundlewalker==${version} after 6 attempts."
              exit 1
            fi
            delay="${retry_delays[$((attempt - 1))]}"
            echo "::notice::Production PyPI has not exposed bundlewalker==${version}; retrying in ${delay}s after attempt ${attempt}/6."
            sleep "$delay"
          done
          test "$(.pypi-venv/bin/python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = "$version"
          .pypi-venv/bin/bundlewalker --help
          .pypi-venv/bin/bundlewalker-mcp --help

  github-release:
    name: Create GitHub release from exact distributions
    needs: [build, verify]
    if: ${{ always() && needs.build.result == 'success' && needs.verify.result == 'success' }}
    runs-on: ubuntu-24.04
    permissions:
      contents: write
    steps:
      - name: Check out tagged revision
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          persist-credentials: false
      - name: Revalidate current remote annotated tag
        shell: bash
        run: |
          test "$GITHUB_REF_TYPE" = "tag"
          tag="$GITHUB_REF_NAME"
          remote_refs="$(git ls-remote --exit-code --tags origin "refs/tags/${tag}" "refs/tags/${tag}^{}")"
          tag_oid="$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/${tag}" '$2 == ref { print $1 }')"
          peeled_oid="$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/${tag}^{}" '$2 == ref { print $1 }')"
          test -n "$tag_oid"
          test -n "$peeled_oid"
          test "$peeled_oid" = "$GITHUB_SHA"
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
      - name: Create or complete the GitHub release
        shell: bash
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          version="${{ needs.build.outputs.version }}"
          tag="v${version}"
          test "$GITHUB_REF_NAME" = "$tag"
          test "$(git rev-list -n 1 "$tag")" = "$GITHUB_SHA"
          uv run --no-project python - "$version" <<'PY'
          import re
          import sys
          from pathlib import Path

          version = sys.argv[1]
          changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
          match = re.search(
              rf"^## \[v{re.escape(version)}\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)",
              changelog,
              re.MULTILINE | re.DOTALL,
          )
          assert match is not None
          Path("release-notes.md").write_text(match.group("body").strip() + "\n", encoding="utf-8")
          PY
          expected_prerelease=false
          case "$version" in
            0.4.0rc*) expected_prerelease=true ;;
          esac
          if gh release view "$tag" >/dev/null 2>&1; then
            test "$(gh release view "$tag" --json name --jq .name)" = "BundleWalker ${version}"
            test "$(gh release view "$tag" --json isPrerelease --jq .isPrerelease)" = "$expected_prerelease"
          else
            release_args=("$tag" --verify-tag --title "BundleWalker ${version}" --notes-file release-notes.md)
            if [ "$expected_prerelease" = true ]; then
              release_args+=(--prerelease)
            fi
            gh release create "${release_args[@]}"
          fi
          mkdir -p "$RUNNER_TEMP/existing-assets"
          for path in dist/*; do
            name="$(basename "$path")"
            if gh release view "$tag" --json assets --jq '.assets[].name' | grep -Fxq "$name"; then
              gh release download "$tag" --pattern "$name" --dir "$RUNNER_TEMP/existing-assets"
              cmp --silent "$path" "$RUNNER_TEMP/existing-assets/$name"
            else
              gh release upload "$tag" "$path"
            fi
          done
```

- [ ] **Step 4: Run the focused workflow contract and full automation tests**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_pypi_workflow_is_tag_gated_oidc_only_and_reuses_exact_artifacts -q
uv run pytest tests/test_project_automation.py -q
git diff --check
```

Expected: all selected tests pass and `git diff --check` prints nothing.

- [ ] **Step 5: Commit the production workflow**

Run:

```bash
git add .github/workflows/publish-pypi.yml tests/test_project_automation.py
git commit -m "ci: add protected production publishing"
```

Expected: one commit containing only the workflow and its structural contract test.

---

### Task 2: Prepare the 0.4.0rc1 package and documentation state

**Files:**
- Modify: `pyproject.toml:3`
- Modify: `uv.lock` editable `bundlewalker` record
- Modify: `tests/test_release_metadata.py:608-611, 654`
- Modify: `tests/cli/test_workspace.py:37`
- Modify: `tests/application/test_lifecycle.py:37`
- Modify: `README.md:7-24, 227-228`
- Modify: `CHANGELOG.md:5-24, 99-102`
- Modify: `docs/maintainers/releases.md:8-16, 82-94`

**Interfaces:**
- Consumes: the production workflow from Task 1 and immutable historical evidence still marked `0.4.0a2`.
- Produces: a reviewed source tree whose package metadata, lockfile, current runtime assertions, README, changelog, and release procedure consistently name `0.4.0rc1` and `v0.4.0rc1`.

- [ ] **Step 1: Change current-version tests before changing package metadata**

In `tests/test_release_metadata.py`, replace `test_development_version_is_second_alpha` with:

```python
def test_development_version_is_first_release_candidate() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0rc1"
    assert bundlewalker.__version__ == "0.4.0rc1"
```

In `test_source_distribution_excludes_untracked_superpowers_worker_state`, change only the
version-derived archive root assertion to:

```python
assert (
    "bundlewalker-0.4.0rc1/docs/superpowers/plans/"
    "2026-07-19-bundlewalker-0.4.0a2-release.md"
) in packaged_paths
```

Keep `test_reviewed_benchmark_evidence_has_complete_immutable_provenance` fixed at `0.4.0a2`.

In `tests/cli/test_workspace.py`, change the expected live command output to:

```python
"BundleWalker version: 0.4.0rc1\n"
```

In `tests/application/test_lifecycle.py`, change the default live dependency result to:

```python
installed_version="0.4.0rc1",
```

Do not mechanically replace `0.4.0a2` in synthetic diagnostic, contract, or benchmark fixtures;
those values are fixture payloads rather than assertions about installed package identity.

- [ ] **Step 2: Add the failing release-document contract**

Append this test to `tests/test_release_metadata.py`:

```python
def test_first_release_candidate_is_documented_without_final_beta_claim() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")

    assert "current production release candidate is `0.4.0rc1`" in readme
    assert 'uv tool install "bundlewalker==0.4.0rc1"' in readme
    assert "proof of concept" in readme
    assert "## [v0.4.0rc1] - 2026-07-21" in changelog
    assert (
        "[v0.4.0rc1]: "
        "https://github.com/HendrikReh/BundleWalker/compare/v0.4.0a2...v0.4.0rc1"
    ) in changelog
    for phrase in (
        "publish-pypi.yml",
        "GitHub environment `pypi`",
        "pending trusted publisher",
        "v0.4.0rc1",
        "Never move, delete, or reuse",
        "TestPyPI and production builds are separate",
        "fresh artifacts from its reviewed tag",
        'gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"',
        "Never rerun a failed publish job",
    ):
        assert phrase in releases
    assert "Production `0.4.0` is forbidden" in releases
```

- [ ] **Step 3: Run focused tests and observe the old-version/document failures**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_development_version_is_first_release_candidate \
  tests/test_release_metadata.py::test_first_release_candidate_is_documented_without_final_beta_claim \
  tests/cli/test_workspace.py::test_workspace_status_reports_future_format_without_creating_state \
  tests/application/test_lifecycle.py::test_lifecycle_status_inspects_future_format_without_mutation \
  -q
```

Expected: FAIL because `pyproject.toml`, installed metadata, command output, and public documents
still identify `0.4.0a2`.

- [ ] **Step 4: Change the authoritative version and refresh derived metadata**

Set this exact value in `pyproject.toml`:

```toml
version = "0.4.0rc1"
```

Keep this classifier unchanged:

```toml
"Development Status :: 3 - Alpha",
```

Then run:

```bash
uv lock
uv sync --locked
git diff -- pyproject.toml uv.lock
```

Expected: the editable `bundlewalker` record changes to `0.4.0rc1`; no third-party dependency,
constraint, hash, or license metadata changes.

- [ ] **Step 5: Update the README release identity and installation path**

Replace the release paragraph at the top of `README.md` with:

```markdown
Latest stable release: **v3** (Python package `0.3.0`). The current production release candidate is
`0.4.0rc1`, adding the reviewed public-beta foundation while BundleWalker remains a proof of
concept. See the [changelog](CHANGELOG.md) for release history.
```

At the start of `## Quick start`, retain the Python and `uv` requirements and add this block before
the repository-checkout instructions:

````markdown
Install the exact production release candidate as an isolated command-line tool:

```bash
uv tool install "bundlewalker==0.4.0rc1"
bundlewalker --help
bundlewalker-mcp --help
```

Because this is a prerelease, use the exact version shown above. Final `0.4.0` is not published.
The complete walkthrough below uses a locked source checkout so its commands remain reproducible.
````

Change the Release Procedure description in the documentation index to:

```markdown
- The [Release Procedure](docs/maintainers/releases.md) defines maintainer-only build, TestPyPI,
  production PyPI, GitHub release, versioning, and failure handling.
```

- [ ] **Step 6: Cut the release-candidate changelog entry**

Keep an empty `## [Unreleased]` heading, then place the current Added and Changed sections under:

```markdown
## [v0.4.0rc1] - 2026-07-21
```

Add this bullet to its `### Added` section:

```markdown
- Added a tag-gated, human-approved, OIDC-only production-PyPI workflow that builds once,
  verifies exact production filenames and SHA-256 digests, and creates the GitHub prerelease from
  the same artifacts.
```

Replace the comparison-link footer with:

```markdown
[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc1...HEAD
[v0.4.0rc1]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0a2...v0.4.0rc1
[v0.4.0a2]: https://github.com/HendrikReh/BundleWalker/compare/v3...v0.4.0a2
[v3]: https://github.com/HendrikReh/BundleWalker/compare/v2...v3
[v2]: https://github.com/HendrikReh/BundleWalker/compare/v1...v2
[v1]: https://github.com/HendrikReh/BundleWalker/tree/v1
```

- [ ] **Step 7: Replace the future-production placeholder with the exact maintainer procedure**

Replace the opening artifact paragraph with:

```markdown
TestPyPI and production builds are separate.
Production builds fresh artifacts from its reviewed tag: one wheel and one source distribution.
The publish, verification, and GitHub release jobs then reuse those exact production bytes without
rebuilding them.
```

In `docs/maintainers/releases.md`, retain the TestPyPI section and replace
`## Production PyPI and GitHub releases` through the paragraph before `## Failure and rollback`
with:

```markdown
## Production PyPI and GitHub releases

Production publishing uses `publish-pypi.yml`, GitHub environment `pypi`, and a matching PyPI
trusted publisher. The workflow starts only from a pushed `v*` tag, validates that the tag is
exactly `v${project.version}`, and accepts only `0.4.0rcN` or final `0.4.0`. It builds one wheel and
one source archive, publishes those exact files, verifies production filenames and SHA-256
digests, and attaches the same files to the GitHub release.

Before the first production upload, configure GitHub environment `pypi` with required reviewer
`HendrikReh`, self-review permitted, and a tag-only deployment rule `v0.4.0*`. Register the PyPI
pending trusted publisher while signed in as `hereh`:

| Field | Value |
| --- | --- |
| PyPI project | `bundlewalker` |
| GitHub owner | `HendrikReh` |
| GitHub repository | `BundleWalker` |
| Workflow | `publish-pypi.yml` |
| Environment | `pypi` |

For `0.4.0rc1`, merge the protected release pull request first, binding the merge to its recorded
head commit. Immediately before tagging, fetch fresh `origin/master` and tags; require local
`master`, fresh `origin/master`, and PR #12's actual merge OID to agree. Re-read the `pypi`
environment reviewer and tag-only rule, re-open PyPI publishing settings to verify the exact
pending-publisher tuple, and confirm production version `0.4.0rc1` is still unavailable. Only then
create annotated tag `v0.4.0rc1` at that exact merge commit, verify it, and push it once. Inspect
the build evidence before approving the `pypi` deployment. The workflow validates the current
remote annotated tag before building and again before creating GitHub prerelease
`BundleWalker 0.4.0rc1`.

Never move, delete, or reuse a pushed tag or package version. If build or pre-upload validation
fails after tag push, fix through review and advance to `0.4.0rc2`. The read-only verification job
runs after either ordinary success or ordinary failure of the upload action and treats production
PyPI as authoritative:

- If PyPI exposes neither file, verification fails; advance through review to `0.4.0rc2`.
- If PyPI exposes one file or any filename or digest differs, treat the release as unsafe, yank
  the partial version through PyPI, and advance through review to `0.4.0rc2`.
- If PyPI exposes both exact filenames and digests, verification continues even when the upload
  action reported failure. A successful exact-version install then permits the downstream GitHub
  release job to attach the retained workflow artifacts without rebuilding or republishing.

Only the exact production-index installation receives the bounded 5/10/20/40/80-second
propagation retry. Metadata, checksum, artifact, and CLI failures remain immediate. If that
installation alone exhausts its retry after both exact PyPI files were verified, rerun only the
failed verification job and downstream release job. If only GitHub release creation fails, rerun
only that downstream job; it reuses the retained workflow artifact and verifies any existing
same-named asset byte-for-byte. A fully cancelled workflow may not reach verification; inspect
production PyPI manually before any further action and never restart build or publish for a
version whose files may have been accepted.

Production `0.4.0` is forbidden until every public-beta exit gate passes. `0.4.0rc1` certifies the
production clean-install candidate, not final beta readiness. The next gate is a
production-installed workspace lifecycle rehearsal covering inspection, backup, separate-target
restore, upgrade behavior, rollback, and post-operation verification.
```

In `## Version policy`, replace the TestPyPI-only candidate line with:

```markdown
- Alpha versions are rehearsed on TestPyPI; release candidates are published to production PyPI
  only through the protected production workflow.
```

In `## Failure and rollback`, ensure the tag instruction says:

```markdown
publish an advisory, and issue a fixed version; never move, delete, or reuse its Git tag.
```

- [ ] **Step 8: Run focused version and documentation verification**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_release_versions_are_consistent \
  tests/test_release_metadata.py::test_development_version_is_first_release_candidate \
  tests/test_release_metadata.py::test_first_release_candidate_is_documented_without_final_beta_claim \
  tests/test_release_metadata.py::test_source_distribution_excludes_untracked_superpowers_worker_state \
  tests/cli/test_workspace.py::test_workspace_status_reports_future_format_without_creating_state \
  tests/application/test_lifecycle.py::test_lifecycle_status_inspects_future_format_without_mutation \
  -q
git diff --check
```

Expected: all selected tests pass and whitespace validation prints nothing.

- [ ] **Step 9: Audit intentional historical-version preservation**

Run:

```bash
rg -n '0\.4\.0a2' \
  README.md CHANGELOG.md docs pyproject.toml uv.lock tests benchmarks/evidence
```

Expected current-version occurrences:

- the `v0.4.0a2` historical changelog entry and comparison link;
- TestPyPI's immutable `0.4.0a2` dispatch example;
- dated design and implementation records;
- immutable benchmark evidence, report provenance, and its assertion;
- synthetic test fixture payloads whose date/version are part of their sample data; and
- no `0.4.0a2` in `pyproject.toml`, the editable `uv.lock` record, README current-release prose,
  live workspace output, or default lifecycle result.

- [ ] **Step 10: Commit the release-candidate state**

Run:

```bash
git add pyproject.toml uv.lock README.md CHANGELOG.md docs/maintainers/releases.md \
  tests/test_release_metadata.py tests/cli/test_workspace.py tests/application/test_lifecycle.py
git commit -m "build: prepare 0.4.0rc1 release candidate"
```

Expected: one commit containing only current version, derived lock metadata, current-version tests,
and release-facing documentation.

---

### Task 3: Verify and submit the protected release pull request

**Files:**
- Verify: all files changed by Tasks 1 and 2
- Build output: local ignored `dist/` containing exact candidate artifacts
- Remote artifact: pull request from `codex/release-0.4.0rc1` to `master`

**Interfaces:**
- Consumes: committed workflow and release state from Tasks 1 and 2.
- Produces: a protected, fully green pull request whose head is the reviewed `0.4.0rc1` source state.

- [ ] **Step 1: Run the complete local acceptance gate**

Run:

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

Expected: every command exits zero.

- [ ] **Step 2: Prove the local artifact set and metadata are exact**

Run:

```bash
test "$(find dist -maxdepth 1 -type f -name '*.whl' | wc -l | tr -d ' ')" = 1
test "$(find dist -maxdepth 1 -type f -name '*.tar.gz' | wc -l | tr -d ' ')" = 1
test -f dist/bundlewalker-0.4.0rc1-py3-none-any.whl
test -f dist/bundlewalker-0.4.0rc1.tar.gz
shasum -a 256 dist/bundlewalker-0.4.0rc1-py3-none-any.whl dist/bundlewalker-0.4.0rc1.tar.gz
uv run python -c 'from importlib.metadata import version; assert version("bundlewalker") == "0.4.0rc1"'
```

Expected: exactly the named wheel and source archive exist, two SHA-256 values print, and installed
metadata equals `0.4.0rc1`.

- [ ] **Step 3: Confirm branch scope and clean tracked state**

Run:

```bash
git status --short --branch
git log --oneline --decorate origin/master..HEAD
git diff --stat origin/master...HEAD
git diff --check origin/master...HEAD
```

Expected: the tracked worktree is clean; the range contains the design/plan, workflow, tests,
version metadata, and release documentation only.

- [ ] **Step 4: Push the release branch and open the ready pull request**

Run:

```bash
git push -u origin codex/release-0.4.0rc1
gh pr create \
  --base master \
  --head codex/release-0.4.0rc1 \
  --title "Release BundleWalker 0.4.0rc1 to production PyPI" \
  --body "$(printf '%s\n' \
    '## Summary' \
    '- add a tag-gated, protected, OIDC-only production PyPI workflow' \
    '- prepare the immutable 0.4.0rc1 package and documentation identity' \
    '- verify production installation and publish the same artifacts as a GitHub prerelease' \
    '' \
    '## Safety' \
    '- no tag or package publication occurs in this pull request' \
    '- macOS and Linux remain supported; Windows remains experimental' \
    '- final 0.4.0 and the public-beta completion claim remain gated' \
    '' \
    '## Verification' \
    '- uv run pytest -m '\''not eval'\'' -q' \
    '- uv run ruff format --check .' \
    '- uv run ruff check .' \
    '- uv run pyright' \
    '- uv lock --check' \
    '- pip-audit, uv build, twine check, exact artifact inspection')"
```

Expected: the branch push succeeds and GitHub returns one ready pull-request URL.

- [ ] **Step 5: Wait for every required pull-request check**

Run:

```bash
gh pr checks --watch --fail-fast=false
gh pr view --json mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: supported macOS/Linux, packaging, audit, CodeQL, and the aggregate required check pass;
`mergeStateStatus` is not `BLOCKED` by a required failure. Experimental Windows results remain
visible but non-blocking.

---

### Task 4: Merge and configure both production trust boundaries

**Files:**
- Remote repository state: merged release pull request and GitHub environment `pypi`
- External account state: production-PyPI pending trusted publisher

**Interfaces:**
- Consumes: the fully green pull request from Task 3 and authenticated GitHub/PyPI maintainer sessions.
- Produces: reviewed `master`, a human-approved tag-only GitHub environment, and the exact pending publisher tuple required for first-project OIDC creation.

- [ ] **Step 1: Merge only the verified pull-request head**

Record the pull-request head before merging:

```bash
PR_NUMBER="$(gh pr view --json number --jq .number)"
PR_HEAD="$(gh pr view --json headRefOid --jq .headRefOid)"
test "$PR_HEAD" = "$(git rev-parse HEAD)"
gh pr checks "$PR_NUMBER"
gh pr merge "$PR_NUMBER" --merge --match-head-commit "$PR_HEAD" \
  --subject "Release BundleWalker 0.4.0rc1 to production PyPI"
```

Expected: GitHub merges the exact checked head into protected `master`; no tag exists yet.

- [ ] **Step 2: Synchronize and audit the merge commit**

In the primary checkout, run:

```bash
git switch master
git pull --ff-only origin master
MERGE_COMMIT="$(git rev-parse HEAD)"
test "$MERGE_COMMIT" = "$(git rev-parse origin/master)"
git status --short --branch
git tag --list v0.4.0rc1
git ls-remote --exit-code --tags origin refs/tags/v0.4.0rc1 && exit 1 || test "$?" -eq 2
```

Expected: `master` is clean and synchronized, and `v0.4.0rc1` is absent locally and remotely.

- [ ] **Step 3: Create the protected GitHub `pypi` environment**

Run from an authenticated GitHub CLI session with repository administration permission:

```bash
REVIEWER_ID="$(gh api users/HendrikReh --jq .id)"
jq -n --argjson reviewer_id "$REVIEWER_ID" '{
  wait_timer: 0,
  prevent_self_review: false,
  reviewers: [{type: "User", id: $reviewer_id}],
  deployment_branch_policy: {
    protected_branches: false,
    custom_branch_policies: true
  }
}' | gh api \
  --method PUT \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/HendrikReh/BundleWalker/environments/pypi \
  --input -
gh api \
  --method POST \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/HendrikReh/BundleWalker/environments/pypi/deployment-branch-policies \
  -f name='v0.4.0*' \
  -f type='tag'
```

Expected: GitHub returns environment `pypi` with a required reviewer and one custom tag policy.
Self-review must remain permitted because `HendrikReh` is both the release initiator and required
human approver.

- [ ] **Step 4: Verify environment protection before touching PyPI**

Run:

```bash
ENVIRONMENT_JSON="$(gh api \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/HendrikReh/BundleWalker/environments/pypi)"
printf '%s' "$ENVIRONMENT_JSON" | jq -e '
  (.protection_rules | map(.type) | sort) == ["branch_policy", "required_reviewers"] and
  ([.protection_rules[] | select(.type == "required_reviewers")] | length) == 1 and
  ([.protection_rules[] | select(.type == "required_reviewers")][0] |
    .prevent_self_review == false and
    (.reviewers | map({type, login: .reviewer.login})) == [{"type":"User","login":"HendrikReh"}]
  ) and
  .deployment_branch_policy.protected_branches == false and
  .deployment_branch_policy.custom_branch_policies == true
' >/dev/null
TAG_POLICIES="$(gh api \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/HendrikReh/BundleWalker/environments/pypi/deployment-branch-policies)"
printf '%s' "$TAG_POLICIES" | jq -e '
  .total_count == 1 and
  (.branch_policies | length) == 1 and
  (.branch_policies[0].name == "v0.4.0*") and
  (.branch_policies[0].type == "tag")
' >/dev/null
```

Expected: the required-reviewers rule exists exactly once, names only user `HendrikReh`, and
permits self-review. The only other protection rule is `branch_policy`; no wait timer or custom
protection rule exists. Custom policies are enabled, protected-branch selection is disabled, and
the separate endpoint contains exactly one tag rule `v0.4.0*` with no branch rule. Any drift exits
nonzero and stops the release before registration or tagging.

- [ ] **Step 5: Register the production-PyPI pending trusted publisher**

Open [PyPI publishing settings](https://pypi.org/manage/account/publishing/) while signed in as
`hereh`. In **Add a new pending publisher**, enter exactly:

```text
PyPI project name: bundlewalker
GitHub owner: HendrikReh
GitHub repository name: BundleWalker
GitHub workflow name: publish-pypi.yml
GitHub environment name: pypi
```

Submit once. Do not enter or create an API token.

Expected: the account page lists pending project `bundlewalker` with owner `HendrikReh`, repository
`BundleWalker`, workflow `publish-pypi.yml`, and environment `pypi`. If PyPI reports the project
name is already owned by another account or the tuple differs, stop before tagging.

- [ ] **Step 6: Confirm the production version is still unused**

Run:

```bash
status="$(curl --silent --output /dev/null --write-out '%{http_code}' https://pypi.org/pypi/bundlewalker/0.4.0rc1/json)"
test "$status" = 404
```

Expected: HTTP 404. The pending publisher is account configuration, not a package release.

---

### Task 5: Tag, publish, approve, and independently verify 0.4.0rc1

**Files:**
- Immutable Git ref: `v0.4.0rc1`
- Production package: `https://pypi.org/project/bundlewalker/0.4.0rc1/`
- GitHub prerelease: `BundleWalker 0.4.0rc1`

**Interfaces:**
- Consumes: synchronized reviewed `master`, protected environment `pypi`, and verified pending publisher from Task 4.
- Produces: one immutable production-PyPI version, one immutable remote tag, successful build,
  authoritative verification, and GitHub release jobs, a publish job that either succeeds or is
  explicitly recorded as authoritatively recovered, one GitHub prerelease, and independent
  clean-install/checksum evidence.

- [ ] **Step 1: Run the final reversible pre-tag audit**

Run in the clean synchronized primary checkout:

```bash
git fetch origin master --tags
test "$(git branch --show-current)" = master
test -z "$(git status --porcelain)"
PR_MERGE_OID="$(gh pr view 12 --json mergeCommit --jq '.mergeCommit.oid')"
test -n "$PR_MERGE_OID"
test "$(git rev-parse master)" = "$(git rev-parse origin/master)"
test "$(git rev-parse master)" = "$PR_MERGE_OID"
test "$(uv run python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = 0.4.0rc1
test -z "$(git tag --list v0.4.0rc1)"
git ls-remote --exit-code --tags origin refs/tags/v0.4.0rc1 && exit 1 || test "$?" -eq 2
ENVIRONMENT_JSON="$(gh api \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/HendrikReh/BundleWalker/environments/pypi)"
printf '%s' "$ENVIRONMENT_JSON" | jq -e '
  (.protection_rules | map(.type) | sort) == ["branch_policy", "required_reviewers"] and
  ([.protection_rules[] | select(.type == "required_reviewers")] | length) == 1 and
  ([.protection_rules[] | select(.type == "required_reviewers")][0] |
    .prevent_self_review == false and
    (.reviewers | map({type, login: .reviewer.login})) == [{"type":"User","login":"HendrikReh"}]
  ) and
  .deployment_branch_policy.protected_branches == false and
  .deployment_branch_policy.custom_branch_policies == true
' >/dev/null
TAG_POLICIES="$(gh api \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  repos/HendrikReh/BundleWalker/environments/pypi/deployment-branch-policies)"
printf '%s' "$TAG_POLICIES" | jq -e '
  .total_count == 1 and
  (.branch_policies | length) == 1 and
  (.branch_policies[0].name == "v0.4.0*") and
  (.branch_policies[0].type == "tag")
' >/dev/null
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://pypi.org/pypi/bundlewalker/json)" = 404
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://pypi.org/pypi/bundlewalker/0.4.0rc1/json)" = 404
```

Re-open [PyPI publishing settings](https://pypi.org/manage/account/publishing/) while signed in as
`hereh` and require the pending publisher to still show the exact tuple
`bundlewalker/HendrikReh/BundleWalker/publish-pypi.yml/pypi`. Do not create the tag unless the
reviewer, sole tag rule, publisher tuple, project absence, and version absence all remain exact.

Expected: the fetched branch identity, actual PR merge OID, protection, publisher, and absence
checks pass. This is the last point where release cancellation does not consume a version or tag.

- [ ] **Step 2: Create and verify the annotated tag locally**

Run:

```bash
RELEASE_COMMIT="$(git rev-parse HEAD)"
git tag -a v0.4.0rc1 "$RELEASE_COMMIT" -m "BundleWalker 0.4.0rc1"
test "$(git rev-list -n 1 v0.4.0rc1)" = "$RELEASE_COMMIT"
git tag -n99 v0.4.0rc1
git show --no-patch --format=fuller v0.4.0rc1
```

Expected: the annotated tag names the exact reviewed merge commit and message
`BundleWalker 0.4.0rc1`.

- [ ] **Step 3: Push the immutable tag exactly once**

Run:

```bash
git push origin refs/tags/v0.4.0rc1
test "$(git ls-remote origin refs/tags/v0.4.0rc1^{} | cut -f1)" = "$RELEASE_COMMIT"
```

Expected: the push succeeds and the peeled remote annotated tag equals the reviewed merge commit.
From this point onward, never move, delete, or reuse `v0.4.0rc1`.

- [ ] **Step 4: Identify the tag workflow and inspect the reversible build stage**

Run:

```bash
RUN_ID="$(gh run list \
  --workflow publish-pypi.yml \
  --branch v0.4.0rc1 \
  --event push \
  --limit 1 \
  --json databaseId,headSha \
  --jq '.[0] | select(.headSha == "'"$RELEASE_COMMIT"'") | .databaseId')"
test -n "$RUN_ID"
gh run view "$RUN_ID"
gh run view "$RUN_ID" --log --job "$(gh run view "$RUN_ID" --json jobs --jq '.jobs[] | select(.name == "Build and verify exact distributions") | .databaseId')"
```

Expected: the build job passes exact identity, test, audit, artifact-count, Twine, clean-wheel, and
checksum gates; the publish job waits for environment approval. If build fails, do not approve or
publish. Never move, delete, or reuse the tag; prepare `0.4.0rc2` through a new pull request.

- [ ] **Step 5: Approve only the displayed `pypi` deployment for v0.4.0rc1**

Open the workflow run returned by:

```bash
gh run view "$RUN_ID" --web
```

In GitHub, confirm the deployment shows environment `pypi`, tag `v0.4.0rc1`, and the reviewed
commit. Select **Review deployments**, choose `pypi`, and approve it once.

Expected: the OIDC publish job starts. Do not approve if the ref, environment, version, or commit
differs.

- [ ] **Step 6: Wait for the complete immutable pipeline**

Run:

```bash
gh run watch "$RUN_ID"
RUN_JSON="$(gh run view "$RUN_ID" --json status,conclusion,headBranch,headSha,url,jobs)"
test "$(printf '%s' "$RUN_JSON" | jq -r .status)" = completed
test "$(printf '%s' "$RUN_JSON" | jq -r .headBranch)" = v0.4.0rc1
test "$(printf '%s' "$RUN_JSON" | jq -r .headSha)" = "$RELEASE_COMMIT"
job_conclusion() {
  local name="$1"
  printf '%s' "$RUN_JSON" | jq -er --arg name "$name" '
    [.jobs[] | select(.name == $name)] |
    if length == 1 and .[0].conclusion != null then .[0].conclusion
    else error("missing or duplicate completed job: \($name)") end
  '
}
BUILD_CONCLUSION="$(job_conclusion "Build and verify exact distributions")"
PUBLISH_CONCLUSION="$(job_conclusion "Publish exact distributions")"
VERIFY_CONCLUSION="$(job_conclusion "Verify production PyPI installation and checksums")"
RELEASE_CONCLUSION="$(job_conclusion "Create GitHub release from exact distributions")"
test "$BUILD_CONCLUSION" = success
test "$VERIFY_CONCLUSION" = success
test "$RELEASE_CONCLUSION" = success
case "$PUBLISH_CONCLUSION" in
  success) ;;
  failure)
    echo "recovered publication warning: publish failed, but same-run verification and GitHub release succeeded"
    ;;
  *) exit 1 ;;
esac
```

Expected: build, production verification, and GitHub release jobs conclude `success`. The publish
job ordinarily succeeds, but may conclude `failure` when PyPI nevertheless accepted both exact
files; in that case successful authoritative verification and GitHub release completion establish
the safe outcome, and the completion report records a recovered publication warning. No other
publish result is accepted. `headBranch` is `v0.4.0rc1` and `headSha` is the reviewed release
commit.

After ordinary publish success or failure, verification reads production PyPI as the authority. If
neither file exists, advance to `0.4.0rc2`. If one file exists or a filename or digest mismatches,
yank the unsafe partial release through PyPI and advance to `0.4.0rc2`. If both exact files and
digests exist, verification can succeed and the GitHub release job can use the retained artifact
even when the upload action reported failure.

If only exact-version installation exhausts the bounded propagation window, first prove the
complete exact PyPI set against the original run artifact, then rerun only the original
verification job and its dependent release job:

```bash
version=0.4.0rc1
RECOVERY_ROOT="$(mktemp -d)"
gh run download "$RUN_ID" --name python-package-distributions --dir "$RECOVERY_ROOT/dist"
curl --fail --silent --show-error --location \
  "https://pypi.org/pypi/bundlewalker/${version}/json" \
  --output "$RECOVERY_ROOT/pypi.json"
uv run --no-project python - "$RECOVERY_ROOT/pypi.json" "$RECOVERY_ROOT/dist" "$version" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dist = Path(sys.argv[2])
version = sys.argv[3]
expected_names = {
    f"bundlewalker-{version}-py3-none-any.whl",
    f"bundlewalker-{version}.tar.gz",
}
local = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in dist.iterdir()
    if path.is_file()
}
remote = {item["filename"]: item["digests"]["sha256"] for item in payload["urls"]}
assert payload["info"]["version"] == version
assert set(local) == expected_names
assert set(remote) == expected_names
assert local == remote, {"local": local, "remote": remote}
PY
VERIFY_JOB_ID="$(gh run view "$RUN_ID" --json jobs --jq '.jobs[] | select(.name == "Verify production PyPI installation and checksums") | .databaseId')"
test -n "$VERIFY_JOB_ID"
gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"
gh run watch "$RUN_ID"
RUN_JSON="$(gh run view "$RUN_ID" --json status,conclusion,headBranch,headSha,url,jobs)"
test "$(printf '%s' "$RUN_JSON" | jq -r .status)" = completed
test "$(printf '%s' "$RUN_JSON" | jq -r .headBranch)" = v0.4.0rc1
test "$(printf '%s' "$RUN_JSON" | jq -r .headSha)" = "$RELEASE_COMMIT"
job_conclusion() {
  local name="$1"
  printf '%s' "$RUN_JSON" | jq -er --arg name "$name" '
    [.jobs[] | select(.name == $name)] |
    if length == 1 and .[0].conclusion != null then .[0].conclusion
    else error("missing or duplicate completed job: \($name)") end
  '
}
BUILD_CONCLUSION="$(job_conclusion "Build and verify exact distributions")"
PUBLISH_CONCLUSION="$(job_conclusion "Publish exact distributions")"
VERIFY_CONCLUSION="$(job_conclusion "Verify production PyPI installation and checksums")"
RELEASE_CONCLUSION="$(job_conclusion "Create GitHub release from exact distributions")"
test "$BUILD_CONCLUSION" = success
test "$VERIFY_CONCLUSION" = success
test "$RELEASE_CONCLUSION" = success
case "$PUBLISH_CONCLUSION" in
  success) ;;
  failure)
    echo "recovered publication warning: publish failed, but same-run verification and GitHub release succeeded"
    ;;
  *) exit 1 ;;
esac
```

Never rerun a failed publish job. If the GitHub release job alone fails, target only that original
job by database ID. A fully cancelled workflow requires manual production-PyPI inspection before
any further action.

- [ ] **Step 7: Independently verify production PyPI and clean installation**

Run:

```bash
VERIFY_ROOT="$(mktemp -d)"
curl --fail --silent --show-error --location \
  https://pypi.org/pypi/bundlewalker/0.4.0rc1/json \
  --output "$VERIFY_ROOT/pypi.json"
uv venv --python 3.13 "$VERIFY_ROOT/venv"
uv pip install \
  --python "$VERIFY_ROOT/venv/bin/python" \
  --default-index https://pypi.org/simple \
  "bundlewalker==0.4.0rc1"
test "$("$VERIFY_ROOT/venv/bin/python" -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = 0.4.0rc1
"$VERIFY_ROOT/venv/bin/bundlewalker" --help
"$VERIFY_ROOT/venv/bin/bundlewalker-mcp" --help
uv run --no-project python - "$VERIFY_ROOT/pypi.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["info"]["version"] == "0.4.0rc1"
files = {item["filename"] for item in payload["urls"]}
assert files == {
    "bundlewalker-0.4.0rc1-py3-none-any.whl",
    "bundlewalker-0.4.0rc1.tar.gz",
}
assert all(len(item["digests"]["sha256"]) == 64 for item in payload["urls"])
PY
```

Expected: exact production installation succeeds, both command smokes pass, and PyPI exposes only
the expected wheel and source archive.

- [ ] **Step 8: Verify GitHub release assets equal PyPI bytes**

Run:

```bash
gh release view v0.4.0rc1 --json name,isDraft,isPrerelease,tagName,targetCommitish,url,assets
mkdir "$VERIFY_ROOT/github-assets"
gh release download v0.4.0rc1 --dir "$VERIFY_ROOT/github-assets"
uv run --no-project python - "$VERIFY_ROOT/pypi.json" "$VERIFY_ROOT/github-assets" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assets = Path(sys.argv[2])
remote = {item["filename"]: item["digests"]["sha256"] for item in payload["urls"]}
downloaded = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in assets.iterdir()
    if path.is_file()
}
assert downloaded == remote, {"github": downloaded, "pypi": remote}
PY
```

Expected: the release is named `BundleWalker 0.4.0rc1`, is not a draft, is a prerelease, targets
`v0.4.0rc1`, and both downloaded asset digests exactly equal production PyPI.

- [ ] **Step 9: Verify converted publisher and final repository state**

On the production PyPI project publishing page, confirm the pending publisher has converted to a
project-scoped publisher with owner `HendrikReh`, repository `BundleWalker`, workflow
`publish-pypi.yml`, and environment `pypi`. Confirm user `hereh` manages the project.

Then run in the primary checkout:

```bash
git fetch origin master --tags
test "$(git rev-parse master)" = "$(git rev-parse origin/master)"
test "$(git rev-list -n 1 v0.4.0rc1)" = "$(git rev-parse master)"
test -z "$(git status --porcelain)"
gh run view "$RUN_ID" --json conclusion --jq .conclusion
gh release view v0.4.0rc1 --json url --jq .url
```

Expected: synchronized clean `master`, exact immutable tag, successful build, authoritative
verification, and GitHub release jobs, publish either successful or explicitly recorded as
authoritatively recovered, converted trusted publisher, and public GitHub prerelease.

Record the workflow URL, PyPI URL, GitHub release URL, release commit, and both SHA-256 digests in
the completion report. The next task is a separately designed production-installed lifecycle
rehearsal; do not tag or publish final `0.4.0` here.
