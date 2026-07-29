# BundleWalker 0.5.0 GUI Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare one reviewed `0.5.0` public-beta release commit that makes the
verified local GUI installable through BundleWalker's protected production
release path.

**Architecture:** Treat the release as one coordinated metadata transaction.
`pyproject.toml` owns package identity, `uv.lock` mirrors only the editable
project record, active docs describe the new current release, and publishing
workflows accept only the explicit `0.5.0` family. Historical release evidence
remains immutable.

**Tech Stack:** Python 3.13/3.14, uv/Hatch, pytest, GitHub Actions, React/Vite,
Vitest, Playwright, Markdown.

## Global Constraints

- Target package version is exactly `0.5.0`; the future tag is exactly
  `v0.5.0`.
- Keep `Development Status :: 4 - Beta`.
- macOS and Linux remain supported; Windows remains experimental and
  non-blocking.
- Do not change product code, dependencies, workspace formats, or the private
  frontend `0.0.0` version.
- Do not edit historical specifications, plans, evidence, fixtures, changelog
  entries, tags, releases, or published package versions.
- Do not create or push a tag or publish a package from the release branch.

---

### Task 1: Lock the release contract with failing metadata tests

**Files:**
- Modify: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: active metadata and Markdown files read through `PROJECT_ROOT`
- Produces: behavioral assertions for `0.5.0` identity, active GUI release
  wording, changelog links, and workflow release-family validation

- [ ] **Step 1: Change active version assertions to `0.5.0`**

Update `test_development_version_is_public_beta` and the active README/user
guide assertions to require `0.5.0`. Preserve every assertion that explicitly
tests historical `0.4.0`, `0.4.0rcN`, evidence, or fixture provenance.

- [ ] **Step 2: Change GUI changelog assertions from unreleased to released**

Require an empty `Unreleased` section, a dated `v0.5.0` section containing the
verified GUI and CI/CodeQL language, and comparison links
`v0.5.0...HEAD`/`v0.4.0...v0.5.0`.

- [ ] **Step 3: Add workflow identity assertions**

Require production validation to accept only
`0.5.0(?:rc[1-9][0-9]*)?`, GitHub prerelease detection to use `0.5.0rc*`,
and TestPyPI to use the `0.5.0a*|0.5.0rc*` family.

- [ ] **Step 4: Run the focused module and verify RED**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
```

Expected: failures name stale `0.4.0` identity, unreleased GUI wording, and
hard-coded `0.4.0` workflow guards.

### Task 2: Apply the single release identity

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.github/workflows/publish-pypi.yml`
- Modify: `.github/workflows/publish-testpypi.yml`

**Interfaces:**
- Consumes: Task 1 release assertions
- Produces: canonical package/lock identity and protected `0.5.0` publishing
  validation

- [ ] **Step 1: Set `project.version` to `0.5.0`**

Change only the authoritative project version in `pyproject.toml`; retain the
Beta classifier and dependency set.

- [ ] **Step 2: Regenerate the editable lock record**

Run:

```bash
uv lock
```

Review `uv.lock` and require that only the editable BundleWalker version changes
from `0.4.0` to `0.5.0`.

- [ ] **Step 3: Advance protected workflow guards**

In `publish-pypi.yml`, replace the exact `0.4.0` release-family regex with the
exact `0.5.0` family and replace `0.4.0rc*` prerelease classification with
`0.5.0rc*`. In `publish-testpypi.yml`, replace the accepted alpha/RC family
with `0.5.0a*|0.5.0rc*`.

- [ ] **Step 4: Run the focused workflow/identity assertions**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
```

Expected: version/workflow failures are resolved; documentation failures
remain until Task 3.

### Task 3: Promote the GUI into active release documentation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/maintainers/releases.md`

**Interfaces:**
- Consumes: exact public identity `0.5.0`
- Produces: consistent installation, status, release notes, and maintainer
  transaction instructions

- [ ] **Step 1: Create the dated `v0.5.0` changelog entry**

Leave `Unreleased` empty, move all existing post-`0.4.0` bullets under
`## [v0.5.0] - 2026-07-29`, remove “GUI remains unreleased,” and add the two
new comparison links without altering historical entries.

- [ ] **Step 2: Update active user installation and status copy**

In README and user guide, use exact `bundlewalker==0.5.0`, state that the web
cockpit ships in the standard public-beta installation, and remove only the
active statements that it is unreleased or absent from `0.4.0`.

- [ ] **Step 3: Add the current maintainer release lane**

Update active production-workflow text to the `0.5.0` family and
`v0.5.0*` environment policy. Add a focused prepared-`0.5.0` section that
requires reviewed merge, exact tag identity, protected OIDC publication,
artifact reuse, and installed `bundlewalker-web` smoke. Preserve historical
`0.4.0` recovery sections.

- [ ] **Step 4: Run focused release metadata tests**

Run:

```bash
uv run pytest tests/test_release_metadata.py -q
```

Expected: PASS.

### Task 4: Verify and commit the release preparation

**Files:**
- Verify: all files changed by Tasks 1-3

**Interfaces:**
- Consumes: coordinated release tree
- Produces: one locally verified release-preparation commit suitable for PR

- [ ] **Step 1: Run the complete Python and static gate**

```bash
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

- [ ] **Step 2: Run the complete frontend gate**

```bash
npm --prefix frontend ci
npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run test:a11y
uv run python scripts/generate_web_contract_fixtures.py
npm --prefix frontend run build
git diff --exit-code -- frontend/src/test/fixtures/contracts.json
git diff --exit-code -- src/bundlewalker/interfaces/web/static
npm --prefix frontend audit --audit-level=high
uv run python scripts/run_web_smoke.py -- npm --prefix frontend run test:e2e
```

- [ ] **Step 3: Build and inspect exact release archives**

```bash
uv build --clear --no-sources
uv run twine check dist/bundlewalker-0.5.0-py3-none-any.whl \
  dist/bundlewalker-0.5.0.tar.gz
```

Require exactly those two release files and validate that both contain the
packaged HTML, Vite manifest, hashed JavaScript, and hashed CSS assets.

- [ ] **Step 4: Review the release diff**

Confirm there is no product-code, dependency, historical-evidence, or
frontend-version change. Confirm the worktree contains only intentional
release identity, workflow, active documentation, tests, design, and plan
changes.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/publish-pypi.yml \
  .github/workflows/publish-testpypi.yml \
  CHANGELOG.md README.md docs/user-guide.md docs/maintainers/releases.md \
  docs/superpowers/specs/2026-07-28-bundlewalker-0.5.0-gui-release-design.md \
  docs/superpowers/plans/2026-07-28-bundlewalker-0.5.0-gui-release.md \
  pyproject.toml uv.lock tests/test_release_metadata.py
git commit -m "release: prepare BundleWalker 0.5.0"
```

### Task 5: Prove the exact commit remotely before any tag

**Files:**
- No repository changes expected

**Interfaces:**
- Consumes: committed release branch SHA
- Produces: reviewed, exact-head CI/CodeQL evidence and a mergeable release PR

- [ ] **Step 1: Push the release branch and open a pull request**

The PR must state the exact version, GUI scope, supported-platform boundary,
local verification, and explicit no-tag/no-publication boundary.

- [ ] **Step 2: Require exact-head checks**

Require supported macOS/Linux Python 3.13/3.14 jobs, frontend/browser,
dependency audit, distribution build/install smokes, aggregate Required job,
and CodeQL to pass. Experimental Windows failures remain non-blocking.

- [ ] **Step 3: Resolve review findings through new commits**

Do not dismiss a genuine release or security issue. Re-run proportional local
gates and require exact-head remote checks after any correction.

- [ ] **Step 4: Stop at the immutable boundary**

The release branch is ready to merge only after all required review and CI
evidence is green. Do not create `v0.5.0` or publish before the reviewed
release commit reaches `master` and the merged-state audit passes.
