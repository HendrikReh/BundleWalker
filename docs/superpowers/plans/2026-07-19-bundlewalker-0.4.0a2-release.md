# BundleWalker 0.4.0a2 Alpha Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare, review, publish, and verify the immutable BundleWalker `0.4.0a2` TestPyPI alpha from the current `master` state.

**Architecture:** Treat the package version in `pyproject.toml` as the release identity and derive the editable lock record and installed metadata from it. Land that identity and its user-facing documentation through a protected-branch pull request before creating the matching annotated Git tag, TestPyPI publication, and GitHub prerelease.

**Tech Stack:** Python 3.13/3.14, uv, pytest, Ruff, Pyright, Twine, GitHub Actions, TestPyPI trusted publishing.

## Global Constraints

- The exact prerelease version is `0.4.0a2`; the exact Git tag is `v0.4.0a2`.
- Publish the alpha to TestPyPI only; do not publish to production PyPI.
- `pyproject.toml` is the only authoritative build/runtime package-version source.
- The wheel, source distribution, installed metadata, lockfile, documentation, Git tag, TestPyPI record, and GitHub prerelease must identify the same version.
- Create the tag only after the protected-branch pull request is merged, and point it at that merge commit.
- Do not move or reuse an existing tag or overwrite an existing TestPyPI version.
- Required macOS and Linux CI must pass; Windows remains experimental and non-blocking.

---

### Task 1: Prepare the 0.4.0a2 release state

**Files:**
- Create: `docs/superpowers/plans/2026-07-19-bundlewalker-0.4.0a2-release.md`
- Modify: `pyproject.toml:3`
- Modify: `uv.lock` editable `bundlewalker` package record
- Modify: `README.md:7-9`
- Modify: `CHANGELOG.md`
- Modify: `docs/maintainers/releases.md:67-71`
- Modify: `tests/test_release_metadata.py:136-140`
- Modify: `tests/cli/test_workspace.py:37`
- Modify: `tests/application/test_lifecycle.py:36`

**Interfaces:**
- Consumes: the merged Milestone B1 source at commit `bb199ee19d5f38f0ad519864105f5c3280b10bf0`.
- Produces: a source tree whose authoritative and derived release metadata all resolve to `0.4.0a2` and whose release documentation names tag `v0.4.0a2`.

- [ ] **Step 1: Make the version-specific tests describe the new alpha**

In `tests/test_release_metadata.py`, rename the final test to `test_development_version_is_second_alpha` and require both project and runtime versions to equal `0.4.0a2`.

In `tests/cli/test_workspace.py`, change the workspace-status version line to:

```python
"BundleWalker version: 0.4.0a2\n"
```

In `tests/application/test_lifecycle.py`, update the default-runtime
`CompatibilityResult(installed_version=...)` expectation in
`test_lifecycle_status_inspects_future_format_without_mutation` to `"0.4.0a2"`.

- [ ] **Step 2: Run the focused tests and observe the expected old-version failures**

Run:

```bash
uv run pytest tests/test_release_metadata.py::test_development_version_is_second_alpha tests/cli/test_workspace.py::test_workspace_status_reports_future_format_without_creating_state -q
```

Expected: both tests fail because the installed editable distribution still reports `0.4.0a1`.

- [ ] **Step 3: Change the authoritative version and regenerate the lockfile**

Set the project version in `pyproject.toml` to:

```toml
version = "0.4.0a2"
```

Then run:

```bash
uv lock
uv sync --locked
```

Expected: the editable `bundlewalker` record in `uv.lock` and installed distribution metadata both report `0.4.0a2` without unrelated dependency updates.

- [ ] **Step 4: Update release-facing documentation**

Update `README.md` to identify `v3`/`0.3.0` as the latest stable release and `0.4.0a2` as the current alpha.

Convert the current changelog material since `v3` into a dated `v0.4.0a2` entry for `2026-07-19`. Include the release-foundation work plus Milestone B1 workspace status, verified backup/restore, explicit upgrade and rollback safety, historical compatibility fixtures, and abrupt-termination recovery evidence. Add this exact comparison target:

```markdown
[v0.4.0a2]: https://github.com/HendrikReh/BundleWalker/compare/v3...v0.4.0a2
```

Update the TestPyPI dispatch example in `docs/maintainers/releases.md` to:

```bash
gh workflow run publish-testpypi.yml --ref master -f version=0.4.0a2
```

- [ ] **Step 5: Re-run focused verification**

Run:

```bash
uv run pytest tests/test_release_metadata.py tests/cli/test_workspace.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Run complete release verification and build exact artifacts**

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

Expected: every command exits zero; `dist/` contains exactly `bundlewalker-0.4.0a2-py3-none-any.whl` and `bundlewalker-0.4.0a2.tar.gz`.

- [ ] **Step 7: Commit the reviewed release state**

Stage only the files listed for Task 1 and commit with:

```bash
git commit -m "build: prepare 0.4.0a2 alpha"
```

#### Artifact hygiene follow-up

The source distribution must exclude untracked local worker state under `.superpowers/**`, so a
locally built release artifact matches a clean GitHub checkout. Keep this as an sdist-only Hatch
exclusion: tracked release plans under `docs/superpowers/**` remain included. The focused
regression coverage is `tests/test_release_metadata.py`, and the release build configuration scope
is `pyproject.toml`.

## Post-implementation release procedure

After Task 1 passes task-scoped and whole-branch review:

1. Push `codex/release-0.4.0a2` and open a ready pull request into `master`.
2. Wait for the required check, supported macOS/Linux jobs, artifact smoke tests, dependency audit, and CodeQL to pass; experimental Windows failures do not block the release.
3. Merge the pull request and fast-forward the primary checkout to the resulting `master` merge commit.
4. Create annotated tag `v0.4.0a2` at that exact merge commit and push the tag.
5. Dispatch `publish-testpypi.yml` on `master` with input `version=0.4.0a2`, wait for build, publish, and install verification to pass, and download that workflow's exact distribution artifact.
6. Create a GitHub prerelease named `BundleWalker 0.4.0a2` for `v0.4.0a2`, using the `v0.4.0a2` changelog entry as release notes and attaching the exact workflow-built wheel and source archive.
7. Verify the remote tag, GitHub prerelease, TestPyPI JSON metadata, artifact checksums, and clean synchronized `master` checkout.
