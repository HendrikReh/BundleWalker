# BundleWalker 0.4.0rc3 Stabilization and Public Beta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the four approved dependency-housekeeping updates into production release
candidate `0.4.0rc3`, validate its installed lifecycle on every supported platform, then promote
that exact verified state to the `0.4.0` public beta.

**Architecture:** Use two reviewed, protected release stages. The rc3 stage changes exact locked
dependencies, both PyPI publishing-action pins, current candidate identity, and active candidate
documentation. The final stage begins only after rc3 publication and lifecycle evidence are
complete and changes only first-party version/classifier and active public-beta documentation.
Both stages reuse BundleWalker's build-once, OIDC-backed production workflow and immutable tag
policy.

**Tech Stack:** Python 3.13/3.14, `uv`, pytest, Ruff, Pyright, pip-audit, Twine, YAML/GitHub
Actions, GitHub CLI/API, production PyPI Trusted Publishing, macOS 15, Ubuntu 24.04.

## Global Constraints

- The exact candidate package/tag is `0.4.0rc3`/`v0.4.0rc3`; the exact final package/tag is
  `0.4.0`/`v0.4.0`.
- Preserve every existing tag, GitHub release, PyPI file, historical plan/specification,
  changelog entry, benchmark, and rc1/rc2 evidence record. Never move, delete, recreate,
  force-push, or reuse a release tag.
- Keep declared dependency floors unchanged:
  `pydantic-ai>=2.10.0`, `typer>=0.16.0`, and `ruff>=0.12.0`.
- Resolve exactly PydanticAI `2.16.0`, Typer `0.27.0`, and Ruff `0.15.22` in rc3. Any additional
  lock change must be a demonstrated transitive consequence and called out in review.
- Pin `pypa/gh-action-pypi-publish` in both publishing workflows to
  `ba38be9e461d3875417946c167d0b5f3d385a247 # v1.14.1`.
- Keep rc3 classified Alpha and described as a proof of concept approaching public beta.
- Describe final `0.4.0` exactly as a **public beta** and use
  `Development Status :: 4 - Beta`.
- Do not change application behavior, commands, MCP tools, formats, platform support, or
  provider behavior during either stage.
- Official support remains macOS and Linux on Python 3.13/3.14. Windows remains experimental and
  is not part of the blocking release matrix.
- Do not rerun or record participant-level pilot testing. The maintainer has accepted the
  informal three-user result.
- Final `0.4.0` must contain no third-party dependency, publishing-workflow, or product-code
  change relative to the verified rc3 state. If such a change is required, stop and prepare a
  later release candidate instead.
- Never create a tag before its reviewed pull request is merged, required CI is green, local
  `master` equals `origin/master`, the intended version is absent from Git/PyPI, and the
  maintainer explicitly approves the tag boundary.
- A pushed tag or accepted PyPI version is consumed even if later jobs fail. Follow the existing
  recovery matrix; never republish different bytes under the same version.
- Never approve a protected `pypi` deployment without matching the expected workflow, tag,
  commit, version, environment, artifact names, and digests.
- Stop on any unexpected commit, ref, tag object, package version, dependency drift, workflow
  permission, publisher identity, artifact count/name/digest, job state, or index response.
- Use `apply_patch` for deliberate repository edits. Generated lockfile/build output may be
  produced only by the documented tools.
- Do not merge either release pull request without a fresh explicit user approval.

---

## Stage A — Land the Approved Design and Plan

### Task 1: Review and publish the release design package

**Files:**

- Existing:
  `docs/superpowers/specs/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta-design.md`
- Existing:
  `docs/superpowers/plans/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta.md`

**Produces:** A documentation-only pull request establishing the approved execution contract.

- [ ] **Step 1: Confirm branch scope and formatting**

Run from the design worktree:

```bash
git status --short --branch
git diff master...HEAD --stat
git diff --check master...HEAD
rg -n 'T[B]D|TO[D]O|implement lat[e]r|fill in detail[s]|Similar to Tas[k]|similar to Tas[k]' \
  docs/superpowers/specs/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta-design.md \
  docs/superpowers/plans/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta.md
```

Expected: only the approved design and implementation plan differ from `master`; diff check
passes; the placeholder scan returns no matches.

- [ ] **Step 2: Run documentation contracts**

```bash
uv sync --locked
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
```

Expected: PASS with the existing rc2 identity because this branch changes no active metadata.

- [ ] **Step 3: Push and open the documentation PR**

```bash
git push -u origin codex/beta-dependency-release-design
gh pr create \
  --base master \
  --head codex/beta-dependency-release-design \
  --title "docs: design rc3 stabilization and public beta release" \
  --body-file docs/superpowers/specs/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta-design.md
```

Expected: one ready-for-review pull request containing documentation only.

- [ ] **Step 4: Require green checks and explicit merge approval**

```bash
gh pr checks --watch
gh pr view --json mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: required checks succeed and the PR is mergeable. Present the exact URL and summary to
the maintainer. Do not merge until the maintainer explicitly approves.

- [ ] **Step 5: Merge and synchronize**

After approval:

```bash
gh pr merge --squash --delete-branch
git -C ../.. fetch --prune origin
git -C ../.. pull --ff-only origin master
```

Expected: `master` and `origin/master` identify the same commit. Remove the documentation
worktree only after confirming it is clean:

```bash
git status --short
git -C ../.. worktree remove .worktrees/beta-dependency-release-design
git -C ../.. worktree prune
```

---

## Stage B — Build and Validate 0.4.0rc3

### Task 2: Create an isolated rc3 branch and capture the baseline

**Files:** No production changes yet.

- [ ] **Step 1: Establish a synchronized clean base**

From the primary checkout:

```bash
git fetch --prune origin
git switch master
git pull --ff-only origin master
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
```

Expected: the two revisions match and the worktree is clean.

- [ ] **Step 2: Create the rc3 worktree**

```bash
git worktree add -b codex/bundlewalker-0.4.0rc3 \
  .worktrees/bundlewalker-0.4.0rc3 origin/master
cd .worktrees/bundlewalker-0.4.0rc3
```

Expected: a new isolated branch based exactly on `origin/master`.

- [ ] **Step 3: Capture the baseline gate**

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all commands pass before dependency changes. If not, stop and diagnose the inherited
failure separately.

- [ ] **Step 4: Record existing trust and release state**

```bash
git tag --list 'v0.4.0rc3' 'v0.4.0'
gh api repos/HendrikReh/BundleWalker/environments/pypi/deployment-branch-policies
gh api repos/HendrikReh/BundleWalker/actions/permissions/workflow
gh api repos/HendrikReh/BundleWalker/dependabot/alerts
gh api repos/HendrikReh/BundleWalker/code-scanning/alerts
gh api repos/HendrikReh/BundleWalker/secret-scanning/alerts
RC3_PYPI_STATUS="$(
  curl -sS -o /dev/null -w '%{http_code}' \
    https://pypi.org/pypi/bundlewalker/0.4.0rc3/json
)"
test "$RC3_PYPI_STATUS" = 404 || {
  printf 'Refusing to continue: expected PyPI rc3 absence (404), got %s\\n' \
    "$RC3_PYPI_STATUS" >&2
  exit 1
}
```

Expected: neither planned tag exists; PyPI returns HTTP 404 for rc3; repository security APIs
contain no unresolved release-blocking alert. Treat access-denied as unknown, not as a clean
result.

### Task 3: Lock the approved dependencies and publishing action test-first

**Files:**

- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_project_automation.py`
- Modify: `uv.lock`
- Modify: `.github/workflows/publish-testpypi.yml`
- Modify: `.github/workflows/publish-pypi.yml`
- Preserve dependency declarations in: `pyproject.toml`

**Produces:** Exact tested dependency resolution and identical immutable publisher pins.

- [ ] **Step 1: Add exact lock-resolution assertions**

Add a focused test in `tests/test_release_metadata.py` that parses every `[[package]]` entry:

```python
def test_release_lock_uses_approved_rc3_dependency_versions() -> None:
    locked = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = {package["name"]: package["version"] for package in locked["package"]}

    assert versions["pydantic-ai"] == "2.16.0"
    assert versions["typer"] == "0.27.0"
    assert versions["ruff"] == "0.15.22"

    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pydantic-ai>=2.10.0" in project["project"]["dependencies"]
    assert "typer>=0.16.0" in project["project"]["dependencies"]
    assert "ruff>=0.12.0" in project["dependency-groups"]["dev"]
```

If the repository's TOML structure differs, preserve the same assertions using the actual
dependency-group key rather than weakening the contract.

- [ ] **Step 2: Strengthen both workflow-pin assertions**

In `tests/test_project_automation.py`, require this exact token in both workflow texts:

```python
publisher = (
    "pypa/gh-action-pypi-publish@"
    "ba38be9e461d3875417946c167d0b5f3d385a247 # v1.14.1"
)
assert publisher in testpypi_text
assert publisher in production_text
assert testpypi_text.count(publisher) == 1
assert production_text.count(publisher) == 1
```

Keep all existing OIDC, environment, minimal-permission, tag-gate, and one-build assertions.

- [ ] **Step 3: Prove the contracts fail against rc2**

```bash
uv run pytest \
  tests/test_release_metadata.py::test_release_lock_uses_approved_rc3_dependency_versions \
  tests/test_project_automation.py -q
```

Expected: FAIL only because the three locks and two action pins are still at their approved old
values.

- [ ] **Step 4: Update both immutable workflow pins**

Replace the old `v1.14.0` SHA in both workflows with exactly:

```yaml
uses: pypa/gh-action-pypi-publish@ba38be9e461d3875417946c167d0b5f3d385a247 # v1.14.1
```

Do not change triggers, permissions, environments, job dependencies, build commands, or retry
behavior.

- [ ] **Step 5: Perform the targeted lock upgrade**

```bash
cp uv.lock /tmp/bundlewalker-uv-lock-before-rc3
uv lock \
  --upgrade-package pydantic-ai==2.16.0 \
  --upgrade-package typer==0.27.0 \
  --upgrade-package ruff==0.15.22
uv lock --check
```

Expected: the three selected packages resolve exactly to the approved versions.

- [ ] **Step 6: Audit dependency drift**

```bash
git diff -- pyproject.toml uv.lock
uv tree --locked
```

Expected: declared floors in `pyproject.toml` are unchanged. Compare the lock diff with
`/tmp/bundlewalker-uv-lock-before-rc3`; list every changed direct and transitive package in the PR
description. Revert any unrelated drift by regenerating from the clean lock with the same
targeted command, never by hand-editing package hashes.

- [ ] **Step 7: Run focused compatibility tests**

```bash
uv sync --locked
uv run pytest \
  tests/test_release_metadata.py::test_release_lock_uses_approved_rc3_dependency_versions \
  tests/interfaces/test_mcp_tools.py \
  tests/application/test_facade.py \
  tests/cli \
  tests/test_acceptance.py \
  tests/test_project_automation.py -q
```

Expected: PASS. This directly exercises PydanticAI model/MCP paths and Typer CLI paths under the
new resolution. Ruff itself is exercised in the next step.

- [ ] **Step 8: Verify tooling and commit the dependency slice**

```bash
uv run ruff format --check .
uv run ruff check .
git diff --check
git add uv.lock \
  .github/workflows/publish-testpypi.yml \
  .github/workflows/publish-pypi.yml \
  tests/test_release_metadata.py \
  tests/test_project_automation.py
git commit -m "build: stabilize dependencies for 0.4.0rc3"
```

Expected: one focused commit with no package-version or public-status change yet.

### Task 4: Advance the candidate identity test-first

**Files:**

- Modify: `tests/test_release_metadata.py`
- Modify: `tests/cli/test_workspace.py`
- Modify: `tests/application/test_lifecycle.py`
- Modify: `tests/test_project_automation.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Produces:** Current package/runtime/artifact identity `0.4.0rc3`, while preserving Alpha.

- [ ] **Step 1: Change only active identity tests**

Update or rename the current-version test to require:

```python
def test_development_version_is_third_release_candidate() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0rc3"
    assert bundlewalker.__version__ == "0.4.0rc3"
    assert "Development Status :: 3 - Alpha" in project["project"]["classifiers"]
    assert "Development Status :: 4 - Beta" not in project["project"]["classifiers"]
```

Update active CLI and lifecycle expectations to `0.4.0rc3`. Update current sdist-root,
production-artifact filename, workflow-dispatch, and active lifecycle-policy assertions to rc3.
Do not alter the existing rc2 evidence test or its fixed artifact names, digests, run URL, Python
versions, and byte counts.

- [ ] **Step 2: Observe the red identity tests**

```bash
uv run pytest \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py \
  tests/test_project_automation.py -q
```

Expected: FAIL on active rc2 identity assertions that now expect rc3; historical rc2 evidence
assertions remain green.

- [ ] **Step 3: Update authoritative project identity**

Change in `pyproject.toml`:

```toml
version = "0.4.0rc3"
```

Keep the Alpha classifier and all dependency declarations unchanged, then refresh only the
editable project record:

```bash
uv lock
uv lock --check
git diff -- pyproject.toml uv.lock
```

Expected: `uv.lock` changes BundleWalker's editable version from rc2 to rc3 without changing the
dependency versions established in Task 3.

- [ ] **Step 4: Run the active identity slice**

```bash
uv sync --locked
uv run pytest \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py \
  tests/test_project_automation.py -q
```

Expected: active identity tests pass and historical rc2 evidence tests remain intact.

- [ ] **Step 5: Commit candidate identity**

```bash
git diff --check
git add pyproject.toml uv.lock \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py \
  tests/test_project_automation.py
git commit -m "release: advance candidate identity to 0.4.0rc3"
```

### Task 5: Update rc3 documentation, lifecycle identity, and changelog test-first

**Files:**

- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_project_automation.py`
- Modify: `.github/workflows/rehearse-production-lifecycle.yml`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/vscode-copilot-mcp-setup.md` if its active prerequisite names rc2
- Modify: `docs/maintainers/releases.md`
- Modify active compatibility index only if it identifies the current candidate
- Preserve: all files under `docs/maintainers/evidence/` describing rc2
- Preserve: all prior release plans/specifications

**Produces:** Coherent rc3-facing guidance and an unambiguous lifecycle-run identity without a
premature beta claim.

- [ ] **Step 1: Add active-documentation contracts**

Require the active documents to contain exact rc3 installation/dispatch text:

```text
uv tool install "bundlewalker==0.4.0rc3"
gh workflow run rehearse-production-lifecycle.yml --ref master -f version=0.4.0rc3
production-lifecycle-0.4.0rc3-<os>-py<python-version>
```

Require `tests/test_project_automation.py` to assert that
`.github/workflows/rehearse-production-lifecycle.yml` has the exact top-level workflow identity:

```yaml
run-name: production-lifecycle-${{ inputs.version }}
```

This produces the deterministic GitHub run `displayTitle`
`production-lifecycle-0.4.0rc3` for the rc3 dispatch and must remain unchanged during final
promotion.

Require README and user guide still to contain “proof of concept” and not claim the current
release is the final public beta. Require `docs/maintainers/releases.md` to name rc3 as the
operative candidate, identify `v0.4.0rc4` as the next candidate after a package-affecting rc3
failure, and retain the immutable rc1/rc2 recovery facts.

- [ ] **Step 2: Add changelog contracts**

Require:

```markdown
## [Unreleased]
## [v0.4.0rc3] - 2026-07-24
[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc3...HEAD
[v0.4.0rc3]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc2...v0.4.0rc3
```

The rc3 entry must mention the three exact dependency resolutions and the shared v1.14.1
publishing-action pin. Keep the entire rc2 entry/link and earlier history.

- [ ] **Step 3: Observe documentation failures**

```bash
uv run pytest \
  tests/test_release_metadata.py \
  tests/test_project_automation.py -q
```

Expected: FAIL because active guidance still names rc2, the workflow has no rc3 lifecycle
`run-name`, and the rc3 changelog entry does not exist.

- [ ] **Step 4: Update active candidate documentation**

Use deliberate edits, not a repository-wide replacement. Update only current-state sections and
current install/release commands. In particular:

- README: current candidate and exact rc3 installation, still proof of concept.
- User guide: exact rc3 installation/current version, still pre-beta.
- VS Code/Copilot guide: exact rc3 prerequisite only if the line is an active install
  instruction; preserve dated rc2 certification results.
- Release guide: rc3 tag/publish/rehearsal commands and recovery to rc4; preserve old incident and
  evidence sections as historical facts.
- Compatibility documentation: add or update the active candidate pointer without rewriting
  host-certification provenance.
- Lifecycle workflow: add the exact top-level `run-name: production-lifecycle-${{ inputs.version }}`
  contract; do not change its dispatch inputs, jobs, matrix, or artifact contract.
- Changelog: cut the current Unreleased material into the dated rc3 entry and restore an empty
  Unreleased heading.

- [ ] **Step 5: Run focused and link checks**

```bash
uv run pytest \
  tests/test_release_metadata.py \
  tests/test_project_automation.py -q
rg -n '0\\.4\\.0rc2' README.md docs CHANGELOG.md
```

Expected: tests pass. Every remaining rc2 match is intentionally historical evidence,
certification provenance, changelog history, or a prior plan/specification.

- [ ] **Step 6: Commit rc3 documentation**

```bash
git diff --check
git add README.md CHANGELOG.md docs \
  tests/test_release_metadata.py tests/test_project_automation.py
git commit -m "docs: prepare 0.4.0rc3 release candidate"
```

### Task 6: Run the complete rc3 security and artifact gate

**Files:** Verification only; generated `dist/` must not be committed.

- [ ] **Step 1: Run static and behavioral verification**

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all pass.

- [ ] **Step 2: Audit exact third-party requirements**

```bash
RC3_AUDIT_REQ="$(mktemp -t bundlewalker-rc3-audit.XXXXXX)"
uv export --locked --no-dev --no-emit-project --format requirements-txt \
  --output-file "$RC3_AUDIT_REQ"
uv run pip-audit --strict --requirement "$RC3_AUDIT_REQ" \
  --require-hashes --disable-pip
```

Expected: export succeeds and pip-audit reports no known vulnerability. Delete only the exact
temporary file after inspection:

```bash
rm "$RC3_AUDIT_REQ"
```

- [ ] **Step 3: Build and validate exactly two distributions**

```bash
uv build --clear --no-sources
find dist -maxdepth 1 -type f \
  \( -name '*.whl' -o -name '*.tar.gz' \) -print | sort
uv run twine check \
  dist/bundlewalker-0.4.0rc3-py3-none-any.whl \
  dist/bundlewalker-0.4.0rc3.tar.gz
shasum -a 256 \
  dist/bundlewalker-0.4.0rc3-py3-none-any.whl \
  dist/bundlewalker-0.4.0rc3.tar.gz
```

Expected: exactly the named wheel and source archive; Twine passes. Save their SHA-256 values in
the PR description.

- [ ] **Step 4: Smoke-test wheel and sdist independently**

Create two disposable directories:

```bash
RC3_WHEEL_ENV="$(mktemp -d -t bundlewalker-rc3-wheel.XXXXXX)"
RC3_SDIST_ENV="$(mktemp -d -t bundlewalker-rc3-sdist.XXXXXX)"
uv venv --python 3.13 "$RC3_WHEEL_ENV"
uv venv --python 3.13 "$RC3_SDIST_ENV"
uv pip install --python "$RC3_WHEEL_ENV/bin/python" \
  dist/bundlewalker-0.4.0rc3-py3-none-any.whl
uv pip install --python "$RC3_SDIST_ENV/bin/python" \
  dist/bundlewalker-0.4.0rc3.tar.gz
"$RC3_WHEEL_ENV/bin/bundlewalker" --help
"$RC3_WHEEL_ENV/bin/bundlewalker-mcp" --help
"$RC3_SDIST_ENV/bin/bundlewalker" --help
"$RC3_SDIST_ENV/bin/bundlewalker-mcp" --help
```

Expected: both clean installations succeed and both entry points start/help without importing
the source checkout. Remove only these exact disposable directories afterward.

- [ ] **Step 5: Scan release diff and repository trust boundaries**

```bash
git diff origin/master...HEAD --stat
git diff --check origin/master...HEAD
git grep -n -E 'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|pypi-[A-Za-z0-9_-]{20,}'
git grep -n -E '/Users/[^/]+|/Volumes/' -- \
  ':!docs/superpowers/plans/*' ':!docs/superpowers/specs/*'
git status --short
```

Expected: no credential/private-key match, no newly introduced local absolute path in active
project files, no untracked build output intended for commit, and only approved scope in the
branch diff. Inspect matches before classifying them as benign.

- [ ] **Step 6: Confirm the release diff is product-code neutral**

```bash
git diff --name-only origin/master...HEAD
git diff origin/master...HEAD -- src
```

Expected: no `src/` diff. If product code changed, stop; the branch no longer satisfies the
approved design.

### Task 7: Review and merge the rc3 preparation pull request

- [ ] **Step 1: Push and create a ready PR**

```bash
git push -u origin codex/bundlewalker-0.4.0rc3
gh pr create \
  --base master \
  --head codex/bundlewalker-0.4.0rc3 \
  --title "release: prepare BundleWalker 0.4.0rc3" \
  --body-file docs/superpowers/specs/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta-design.md
```

Amend the generated description with:

- the three targeted lock upgrades and every necessary transitive change;
- both publishing-action pins;
- local test/audit/build/smoke commands and outcomes;
- exact artifact names and SHA-256 values;
- confirmation that `src/` is unchanged; and
- known open security/Dependabot state.

- [ ] **Step 2: Obtain independent review and green required CI**

```bash
gh pr checks --watch
gh pr view --json files,commits,mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: supported test matrix, formatting, Ruff, Pyright, build, dependency audit, artifact
smokes, metadata contracts, and CodeQL all pass at the current head.

- [ ] **Step 3: Request explicit merge approval**

Present the PR URL, head SHA, changed dependency/transitive set, checks, and audit conclusion.
Do not merge until the user explicitly approves.

- [ ] **Step 4: Merge and synchronize after approval**

```bash
gh pr merge --squash --delete-branch
git -C ../.. fetch --prune origin
git -C ../.. switch master
git -C ../.. pull --ff-only origin master
git -C ../.. status --short --branch
```

Expected: clean synchronized master containing the reviewed rc3 state.

### Task 8: Create the immutable rc3 tag after a post-merge gate

- [ ] **Step 1: Re-run the complete gate on the merge commit**

From the primary checkout:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --clear --no-sources
uv run twine check \
  dist/bundlewalker-0.4.0rc3-py3-none-any.whl \
  dist/bundlewalker-0.4.0rc3.tar.gz
```

Expected: PASS and the same package contents/digests as the reviewed merge state.

- [ ] **Step 2: Recheck identity, trust, and availability**

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
git tag --list v0.4.0rc3
gh api repos/HendrikReh/BundleWalker/environments/pypi/deployment-branch-policies
RC3_PYPI_STATUS="$(
  curl -sS -o /dev/null -w '%{http_code}' \
    https://pypi.org/pypi/bundlewalker/0.4.0rc3/json
)"
test "$RC3_PYPI_STATUS" = 404 || {
  printf 'Refusing to create tag: expected PyPI rc3 absence (404), got %s\\n' \
    "$RC3_PYPI_STATUS" >&2
  exit 1
}
```

Expected: clean synchronized revisions, no rc3 tag, trusted `pypi` deployment policy intact, and
HTTP 404 from PyPI. Any other result stops the release.

- [ ] **Step 3: Obtain tag-boundary approval**

Report the exact merge SHA and post-merge gate. Do not create the tag until the user explicitly
approves this irreversible boundary.

- [ ] **Step 4: Create and push the annotated tag once**

```bash
git tag -a v0.4.0rc3 -m "BundleWalker 0.4.0rc3"
git show --no-patch --format=fuller v0.4.0rc3
git push origin v0.4.0rc3
```

Expected: annotated tag targets the exact synchronized merge commit and is pushed once.

### Task 9: Publish and independently verify rc3

- [ ] **Step 1: Identify the tag-triggered production run**

```bash
RC3_TAG_SHA="$(git rev-parse 'v0.4.0rc3^{commit}')"
RC3_RUN_IDS="$(
  gh run list --workflow publish-pypi.yml --branch v0.4.0rc3 \
    --limit 20 --json databaseId,headSha,headBranch,status,conclusion,url,event \
  | jq --arg sha "$RC3_TAG_SHA" \
      '[.[] | select(.event == "push" and .headBranch == "v0.4.0rc3" and .headSha == $sha) | .databaseId]'
)"
RC3_RUN_COUNT="$(printf '%s' "$RC3_RUN_IDS" | jq 'length')"
test "$RC3_RUN_COUNT" -eq 1 || {
  printf 'Refusing to inspect publish run: expected exactly one new rc3 tag push at %s; found %s: %s\\n' \
    "$RC3_TAG_SHA" "$RC3_RUN_COUNT" "$RC3_RUN_IDS" >&2
  exit 1
}
RC3_RUN_ID="$(printf '%s' "$RC3_RUN_IDS" | jq -r '.[0]')"
gh run view "$RC3_RUN_ID" --json headSha,status,conclusion,url,event
```

Expected: one run for the exact tag SHA. Watch through the reversible build/verification stages:

```bash
gh run watch "$RC3_RUN_ID" --exit-status
```

If it pauses for the protected `pypi` deployment, inspect the build artifacts, version, SHA,
publisher workflow/environment, and job dependencies before asking the maintainer to approve the
deployment in GitHub. Never approve a mismatched deployment.

- [ ] **Step 2: Download retained workflow artifacts**

```bash
RC3_RUN_ARTIFACTS="$(mktemp -d -t bundlewalker-rc3-run.XXXXXX)"
gh run download "$RC3_RUN_ID" --dir "$RC3_RUN_ARTIFACTS"
find "$RC3_RUN_ARTIFACTS" -type f -print | sort
find "$RC3_RUN_ARTIFACTS" -type f \
  \( -name 'bundlewalker-0.4.0rc3-py3-none-any.whl' \
  -o -name 'bundlewalker-0.4.0rc3.tar.gz' \) \
  -exec shasum -a 256 {} +
```

Expected: exactly one wheel and one sdist with the workflow-recorded digests.

- [ ] **Step 3: Verify production PyPI independently**

```bash
curl -fsS https://pypi.org/pypi/bundlewalker/0.4.0rc3/json \
  | python -m json.tool
python -m pip index versions bundlewalker
```

Inspect JSON filenames, SHA-256 digests, upload times, and yanked status. Expected: exactly the two
verified artifacts, neither yanked.

- [ ] **Step 4: Verify the GitHub prerelease**

```bash
gh release view v0.4.0rc3 \
  --json tagName,targetCommitish,isDraft,isPrerelease,assets,url
```

Expected: non-draft prerelease at `v0.4.0rc3`, targeting the intended commit, with the exact two
distribution artifacts and matching digests.

- [ ] **Step 5: Verify a production-index installation**

```bash
RC3_PYPI_ENV="$(mktemp -d -t bundlewalker-rc3-pypi.XXXXXX)"
uv venv --python 3.13 "$RC3_PYPI_ENV"
uv pip install --python "$RC3_PYPI_ENV/bin/python" \
  --index-url https://pypi.org/simple \
  bundlewalker==0.4.0rc3
"$RC3_PYPI_ENV/bin/bundlewalker" --version
"$RC3_PYPI_ENV/bin/bundlewalker" --help
"$RC3_PYPI_ENV/bin/bundlewalker-mcp" --help
```

Expected: installed version is exactly rc3 and both CLI/MCP entry points work.

### Task 10: Rehearse the production-installed rc3 lifecycle

**Files initially:** Verification only.

- [ ] **Step 1: Dispatch the exact four-job matrix**

```bash
RC3_LIFECYCLE_SHA="$(git rev-parse origin/master)"
RC3_LIFECYCLE_TITLE="production-lifecycle-0.4.0rc3"
RC3_LIFECYCLE_BEFORE_IDS="$(
  gh run list --workflow rehearse-production-lifecycle.yml \
    --limit 100 --json databaseId \
  | jq '[.[].databaseId]'
)"
gh workflow run rehearse-production-lifecycle.yml \
  --ref master -f version=0.4.0rc3
RC3_LIFECYCLE_RUN_ID=""
for attempt in {1..30}; do
  RC3_LIFECYCLE_NEW_IDS="$(
    gh run list --workflow rehearse-production-lifecycle.yml \
      --limit 100 --json databaseId,displayTitle,headSha,status,conclusion,url,event \
    | jq --arg sha "$RC3_LIFECYCLE_SHA" --arg title "$RC3_LIFECYCLE_TITLE" \
        --argjson before "$RC3_LIFECYCLE_BEFORE_IDS" \
        '[.[] as $run | select($run.event == "workflow_dispatch" and $run.headSha == $sha and $run.displayTitle == $title and ($before | index($run.databaseId) | not)) | $run.databaseId]'
  )"
  RC3_LIFECYCLE_RUN_COUNT="$(printf '%s' "$RC3_LIFECYCLE_NEW_IDS" | jq 'length')"
  if test "$RC3_LIFECYCLE_RUN_COUNT" -eq 1; then
    RC3_LIFECYCLE_RUN_ID="$(printf '%s' "$RC3_LIFECYCLE_NEW_IDS" | jq -r '.[0]')"
    break
  fi
  test "$RC3_LIFECYCLE_RUN_COUNT" -eq 0 || {
    printf 'Refusing to inspect lifecycle run: expected one new %s workflow_dispatch run at %s; found %s: %s\\n' \
      "$RC3_LIFECYCLE_TITLE" "$RC3_LIFECYCLE_SHA" "$RC3_LIFECYCLE_RUN_COUNT" "$RC3_LIFECYCLE_NEW_IDS" >&2
    exit 1
  }
  sleep 2
done
test -n "$RC3_LIFECYCLE_RUN_ID" || {
  printf 'Refusing to continue: no newly dispatched %s lifecycle run appeared at %s\\n' \
    "$RC3_LIFECYCLE_TITLE" "$RC3_LIFECYCLE_SHA" >&2
  exit 1
}
gh run view "$RC3_LIFECYCLE_RUN_ID" \
  --json displayTitle,headSha,status,conclusion,url,event
```

Expected: exactly one new manual run at the synchronized `master` commit with display title
`production-lifecycle-0.4.0rc3`; prior and concurrent dispatches are not eligible.

- [ ] **Step 2: Watch and inspect all jobs**

```bash
gh run watch "$RC3_LIFECYCLE_RUN_ID" --exit-status
gh run view "$RC3_LIFECYCLE_RUN_ID" \
  --json jobs,headSha,status,conclusion,url
```

Expected: exactly these supported combinations pass:

- macOS 15 / Python 3.13;
- macOS 15 / Python 3.14;
- Ubuntu 24.04 / Python 3.13;
- Ubuntu 24.04 / Python 3.14.

- [ ] **Step 3: Download and inspect every evidence artifact**

```bash
RC3_LIFECYCLE_ARTIFACTS="$(mktemp -d -t bundlewalker-rc3-lifecycle.XXXXXX)"
gh run download "$RC3_LIFECYCLE_RUN_ID" --dir "$RC3_LIFECYCLE_ARTIFACTS"
find "$RC3_LIFECYCLE_ARTIFACTS" -type f -print | sort
```

Expected artifact names:

```text
production-lifecycle-0.4.0rc3-macos-15-py3.13
production-lifecycle-0.4.0rc3-macos-15-py3.14
production-lifecycle-0.4.0rc3-ubuntu-24.04-py3.13
production-lifecycle-0.4.0rc3-ubuntu-24.04-py3.14
```

For each JSON record, verify exact installed version, platform/Python identity, nine successful
phases, archive/tree identity, bounded output, sanitized paths, and absence of credentials.
Compute and record SHA-256 plus byte count for each evidence file.

### Task 11: Commit durable rc3 lifecycle evidence

**Files:**

- Create: `docs/maintainers/evidence/2026-07-24-production-lifecycle-0.4.0rc3.md`
- Modify: `docs/maintainers/releases.md`
- Modify: active MCP compatibility documentation
- Modify: `CHANGELOG.md`
- Modify: `tests/test_release_metadata.py`

- [ ] **Step 1: Create a fresh evidence branch**

```bash
git fetch --prune origin
git switch master
git pull --ff-only origin master
git worktree add -b codex/0.4.0rc3-lifecycle-evidence \
  .worktrees/0.4.0rc3-lifecycle-evidence origin/master
cd .worktrees/0.4.0rc3-lifecycle-evidence
```

- [ ] **Step 2: Add failing evidence contracts**

Model the existing rc2 evidence test but require rc3's actual:

- workflow run URL and run ID;
- exact tag/commit/package version;
- four artifact names;
- Python and platform identities;
- result `passed`;
- each SHA-256 and byte count;
- nine accepted phases;
- production-PyPI-only installation boundary; and
- links from release and compatibility documentation.

Keep the entire rc2 evidence test unchanged.

- [ ] **Step 3: Observe the expected failure**

```bash
uv run pytest \
  tests/test_release_metadata.py::test_production_lifecycle_evidence_records_inspected_live_gate \
  -q
```

If the existing function name belongs specifically to rc2, add a separate
`test_rc3_production_lifecycle_evidence_records_inspected_live_gate` and run it. Expected: FAIL
because the rc3 evidence document/links are absent.

- [ ] **Step 4: Write the concise evidence record**

Use only non-personal run facts and accepted technical results. Do not record pilot participants.
Link the live GitHub run, list the exact matrix/artifact digests, state that all four jobs passed,
and describe the existing accepted lifecycle contract without copying unbounded logs.

Update the changelog's Unreleased section to note the completed rc3 live gate. Add active links
from release/compatibility docs while preserving all rc2 historical evidence.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/test_release_metadata.py tests/test_project_automation.py -q
git diff --check
git add CHANGELOG.md docs tests/test_release_metadata.py
git commit -m "docs: record 0.4.0rc3 lifecycle evidence"
```

- [ ] **Step 6: Push, review, and merge only after approval**

```bash
git push -u origin codex/0.4.0rc3-lifecycle-evidence
gh pr create \
  --base master \
  --head codex/0.4.0rc3-lifecycle-evidence \
  --title "docs: record 0.4.0rc3 lifecycle evidence" \
  --body "Records the inspected four-job production-installed lifecycle result for immutable BundleWalker 0.4.0rc3."
gh pr checks --watch
```

Present the PR URL, run URL, four job conclusions, and artifact digests. Merge only after explicit
user approval, then synchronize `master`.

### Task 12: Close superseded dependency pull requests

- [ ] **Step 1: Confirm the consolidated state is on master**

```bash
git switch master
git pull --ff-only origin master
git grep -n '2.16.0' uv.lock
git grep -n '0.27.0' uv.lock
git grep -n '0.15.22' uv.lock
git grep -n 'ba38be9e461d3875417946c167d0b5f3d385a247' \
  .github/workflows/publish-testpypi.yml .github/workflows/publish-pypi.yml
```

Expected: all approved updates and rc3 evidence are merged.

- [ ] **Step 2: Close PRs 1, 2, 3, and 8 as superseded**

For each still-open PR, run the command with its exact number substituted:

```bash
gh pr close 1 \
  --comment "Superseded by the consolidated, tested BundleWalker 0.4.0rc3 dependency stabilization and release-candidate validation."
gh pr close 2 \
  --comment "Superseded by the consolidated, tested BundleWalker 0.4.0rc3 dependency stabilization and release-candidate validation."
gh pr close 3 \
  --comment "Superseded by the consolidated, tested BundleWalker 0.4.0rc3 dependency stabilization and release-candidate validation."
gh pr close 8 \
  --comment "Superseded by the consolidated, tested BundleWalker 0.4.0rc3 dependency stabilization and release-candidate validation."
```

Expected: only those four exact stale Dependabot PRs are closed; do not delete unrelated branches
or close any other PR.

---

## Stage C — Promote the Verified Candidate to 0.4.0

### Task 13: Create a final-promotion branch and prove rc3 provenance

- [ ] **Step 1: Create the branch from verified evidence state**

```bash
git fetch --prune origin
git switch master
git pull --ff-only origin master
git worktree add -b codex/bundlewalker-0.4.0 \
  .worktrees/bundlewalker-0.4.0 origin/master
cd .worktrees/bundlewalker-0.4.0
```

- [ ] **Step 2: Verify rc3 provenance and clean baseline**

```bash
git merge-base --is-ancestor v0.4.0rc3 HEAD
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
git status --short --branch
```

Expected: rc3 is an ancestor, lifecycle evidence is present, the full suite passes, and the
branch is clean.

- [ ] **Step 3: Snapshot forbidden-to-change state**

```bash
git show HEAD:uv.lock > /tmp/bundlewalker-rc3-verified-uv.lock
git show HEAD:.github/workflows/publish-pypi.yml \
  > /tmp/bundlewalker-rc3-publish-pypi.yml
git show HEAD:.github/workflows/publish-testpypi.yml \
  > /tmp/bundlewalker-rc3-publish-testpypi.yml
git show HEAD:.github/workflows/rehearse-production-lifecycle.yml \
  > /tmp/bundlewalker-rc3-lifecycle-workflow.yml
```

These snapshots form the final promotion's no-product/no-dependency-change proof.

### Task 14: Change final identity and public-beta documentation test-first

**Files:**

- Modify: `tests/test_release_metadata.py`
- Modify: `tests/cli/test_workspace.py`
- Modify: `tests/application/test_lifecycle.py`
- Modify: `tests/test_project_automation.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `SUPPORT.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/performance-and-capacity.md`
- Modify: `docs/maintainers/releases.md`
- Modify other active current-status docs discovered by the focused status scan
- Preserve: all historical plan/spec/evidence and certification records

- [ ] **Step 1: Add final metadata contracts**

Require:

```python
assert project["project"]["version"] == "0.4.0"
assert bundlewalker.__version__ == "0.4.0"
assert "Development Status :: 4 - Beta" in project["project"]["classifiers"]
assert "Development Status :: 3 - Alpha" not in project["project"]["classifiers"]
```

Update active CLI/lifecycle, sdist-root, production artifact, and release-document tests to
`0.4.0`. Preserve lifecycle workflow input validation for rc versions because the rehearsal
workflow remains a candidate-only gate; do not dispatch it with final `0.4.0`.

- [ ] **Step 2: Add active public-beta documentation contracts**

Require active README, support, user, and performance/capacity documents to say “public beta” and
to avoid describing the current project as a proof of concept or release candidate. Require:

```text
uv tool install "bundlewalker==0.4.0"
```

Require the changelog structure:

```markdown
## [Unreleased]
## [v0.4.0] - 2026-07-24
## [v0.4.0rc3] - 2026-07-24
[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0...HEAD
[v0.4.0]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc3...v0.4.0
```

The final entry describes promotion of the verified candidate, not new behavior.

- [ ] **Step 3: Observe the red final contracts**

```bash
uv run pytest \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py \
  tests/test_project_automation.py -q
```

Expected: FAIL because active identity/status remains rc3/Alpha/pre-beta.

- [ ] **Step 4: Apply final first-party metadata**

Change:

```toml
version = "0.4.0"
```

Replace only the Alpha development-status classifier with:

```toml
"Development Status :: 4 - Beta",
```

Then:

```bash
uv lock
uv lock --check
```

Expected: only BundleWalker's editable lock version changes; every third-party package/version/hash
remains identical to verified rc3.

- [ ] **Step 5: Update active status documentation deliberately**

Change current status and install instructions to final `0.4.0`/“public beta” in README,
SUPPORT, user guide, performance/capacity guide, and maintainer release procedure. Preserve
historical rc1/rc2/rc3 records and statements that were true at their dated boundaries.

Add the final changelog entry and comparison links. Do not claim production stability, Windows
support, new functionality, or a repeated pilot.

- [ ] **Step 6: Run focused tests and status scans**

```bash
uv sync --locked
uv run pytest \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py \
  tests/test_project_automation.py -q
rg -n -i 'proof of concept|approaching (the )?beta|release candidate|0\\.4\\.0rc3' \
  README.md SUPPORT.md docs CHANGELOG.md
```

Expected: tests pass. Every remaining pre-beta/rc3 occurrence is clearly historical,
candidate-workflow policy, immutable evidence, certification provenance, or prior plan/spec.

- [ ] **Step 7: Prove no forbidden promotion drift**

```bash
diff -u /tmp/bundlewalker-rc3-publish-pypi.yml \
  .github/workflows/publish-pypi.yml
diff -u /tmp/bundlewalker-rc3-publish-testpypi.yml \
  .github/workflows/publish-testpypi.yml
diff -u /tmp/bundlewalker-rc3-lifecycle-workflow.yml \
  .github/workflows/rehearse-production-lifecycle.yml
git diff --exit-code -- src .github/workflows
git diff --exit-code v0.4.0rc3 -- src .github/workflows
git diff -- pyproject.toml uv.lock
python - <<'PY'
from pathlib import Path
import tomllib


def third_party(path: Path) -> list[dict[str, object]]:
    lock = tomllib.loads(path.read_text(encoding="utf-8"))
    return [
        package
        for package in lock["package"]
        if package["name"] != "bundlewalker"
    ]


before = third_party(Path("/tmp/bundlewalker-rc3-verified-uv.lock"))
after = third_party(Path("uv.lock"))
assert after == before, "final promotion changed third-party lock state"
PY
```

Expected: workflows and product-code tree are unchanged. The third-party lock is identical; only
the editable BundleWalker version differs. Any other drift stops final promotion.

- [ ] **Step 8: Commit final promotion**

```bash
git diff --check
git add pyproject.toml uv.lock README.md CHANGELOG.md SUPPORT.md docs \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py \
  tests/test_project_automation.py
git commit -m "release: promote BundleWalker 0.4.0 public beta"
```

### Task 15: Run the complete final security and artifact gate

- [ ] **Step 1: Run all local quality gates**

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: PASS.

- [ ] **Step 2: Run strict dependency audit**

```bash
FINAL_AUDIT_REQ="$(mktemp -t bundlewalker-final-audit.XXXXXX)"
uv export --locked --no-dev --no-emit-project --format requirements-txt \
  --output-file "$FINAL_AUDIT_REQ"
uv run pip-audit --strict --requirement "$FINAL_AUDIT_REQ" \
  --require-hashes --disable-pip
```

Expected: no known vulnerability. The exported third-party requirement set must match rc3.

- [ ] **Step 3: Build, validate, and smoke exact final artifacts**

```bash
uv build --clear --no-sources
find dist -maxdepth 1 -type f \
  \( -name '*.whl' -o -name '*.tar.gz' \) -print | sort
uv run twine check \
  dist/bundlewalker-0.4.0-py3-none-any.whl \
  dist/bundlewalker-0.4.0.tar.gz
shasum -a 256 \
  dist/bundlewalker-0.4.0-py3-none-any.whl \
  dist/bundlewalker-0.4.0.tar.gz
```

Install each artifact into its own clean Python 3.13 environment and run:

```bash
bundlewalker --version
bundlewalker --help
bundlewalker-mcp --help
```

Expected: exact final identity and healthy CLI/MCP entry points.

- [ ] **Step 4: Repeat repository/security review**

Run the credential, private-key, local-path, GitHub alert, workflow-permission, dependency-drift,
and `src/` checks from Task 6. Record commands and material findings in the PR description rather
than adding a separate audit report.

### Task 16: Review and merge the final promotion

- [ ] **Step 1: Push and open the final PR**

```bash
git push -u origin codex/bundlewalker-0.4.0
gh pr create \
  --base master \
  --head codex/bundlewalker-0.4.0 \
  --title "release: promote BundleWalker 0.4.0 public beta" \
  --body-file docs/superpowers/specs/2026-07-24-bundlewalker-0.4.0rc3-and-public-beta-design.md
```

The PR summary must state that rc3 publication/lifecycle passed, enumerate the allowed
first-party metadata/docs diff, prove third-party locks/workflows/`src/` are unchanged, and record
the full local audit and artifact digests.

- [ ] **Step 2: Require all remote gates**

```bash
gh pr checks --watch
gh pr view --json files,commits,mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: every required check passes at the current head.

- [ ] **Step 3: Obtain explicit final merge approval**

Present the PR URL, exact head SHA, rc3 provenance, diff proof, and checks. Do not merge until the
user explicitly approves.

- [ ] **Step 4: Merge and synchronize**

```bash
gh pr merge --squash --delete-branch
git -C ../.. fetch --prune origin
git -C ../.. switch master
git -C ../.. pull --ff-only origin master
git -C ../.. status --short --branch
```

Expected: clean synchronized final metadata state.

### Task 17: Tag, publish, and verify the final public beta

- [ ] **Step 1: Run the final post-merge gate**

Repeat the full tests, format/lint/type checks, strict hash audit, exact build, Twine validation,
wheel/sdist installation smokes, secret/path scans, and no-drift proof on the merge commit.

- [ ] **Step 2: Check the irreversible boundary**

```bash
git rev-parse HEAD
git rev-parse origin/master
git status --short --branch
git tag --list v0.4.0
FINAL_PYPI_STATUS="$(
  curl -sS -o /dev/null -w '%{http_code}' \
    https://pypi.org/pypi/bundlewalker/0.4.0/json
)"
test "$FINAL_PYPI_STATUS" = 404 || {
  printf 'Refusing to create final tag: expected PyPI 0.4.0 absence (404), got %s\\n' \
    "$FINAL_PYPI_STATUS" >&2
  exit 1
}
gh api repos/HendrikReh/BundleWalker/environments/pypi/deployment-branch-policies
```

Expected: clean synchronized commit, no final tag, HTTP 404 from PyPI, and intact protected
publisher policy.

- [ ] **Step 3: Obtain explicit final tag approval**

Report exact commit, full gate, artifact names/digests, and trust-boundary result. Wait for
explicit approval.

- [ ] **Step 4: Create and push the final annotated tag once**

```bash
git tag -a v0.4.0 -m "BundleWalker 0.4.0"
git show --no-patch --format=fuller v0.4.0
git push origin v0.4.0
```

- [ ] **Step 5: Monitor and approve the protected production run**

Identify the exact tag-triggered `publish-pypi.yml` run, inspect its build job and retained
artifacts, then ask the maintainer to approve only the matching `pypi` deployment. Watch the run
to completion. Never rerun a failed publish job.

- [ ] **Step 6: Independently verify PyPI and GitHub**

Require:

- PyPI JSON for `0.4.0` lists exactly the expected wheel and sdist with matching SHA-256;
- neither file is yanked;
- the GitHub `v0.4.0` release is non-draft and non-prerelease;
- the GitHub release contains the same two artifacts;
- the tag targets the reviewed merge commit; and
- a clean production-index install reports exact `0.4.0` and passes CLI/MCP smokes.

The final version must not be dispatched through
`rehearse-production-lifecycle.yml`; its accepted lifecycle evidence is the rc3 gate plus the
proof that final promotion changed no product/dependency/workflow behavior.

### Task 18: Clean up and report completion

- [ ] **Step 1: Remove only clean owned worktrees**

```bash
git worktree list
git -C .worktrees/bundlewalker-0.4.0rc3 status --short
git -C .worktrees/0.4.0rc3-lifecycle-evidence status --short
git -C .worktrees/bundlewalker-0.4.0 status --short
```

After each reports clean:

```bash
git worktree remove .worktrees/bundlewalker-0.4.0rc3
git worktree remove .worktrees/0.4.0rc3-lifecycle-evidence
git worktree remove .worktrees/bundlewalker-0.4.0
git worktree prune
```

- [ ] **Step 2: Prune merged local/remote branches safely**

```bash
git fetch --prune origin
git branch --merged master
git branch -r --merged origin/master
```

Delete only the owned merged `codex/` branches that still exist. Never delete `master`, an
unmerged branch, a release tag, or a user-owned unrelated branch.

- [ ] **Step 3: Confirm final repository state**

```bash
git switch master
git pull --ff-only origin master
git status --short --branch
git worktree list
git tag --list 'v0.4.0rc3' 'v0.4.0'
gh release view v0.4.0rc3 --json isDraft,isPrerelease,url
gh release view v0.4.0 --json isDraft,isPrerelease,url
curl -fsS https://pypi.org/pypi/bundlewalker/0.4.0/json \
  | python -m json.tool
```

Expected: clean synchronized master, only intended worktrees, both immutable tags/releases,
rc3 marked prerelease, final marked non-prerelease, and production PyPI serving final `0.4.0`.

- [ ] **Step 4: Deliver the completion summary**

Report:

- rc3 and final PR/tag/release/PyPI URLs;
- merge and tag SHAs;
- exact artifact names and verified digests;
- the four rc3 lifecycle job results and evidence link;
- dependency/security audit conclusion;
- confirmation that final differs from verified rc3 only by approved first-party
  identity/classifier/docs;
- closed superseded Dependabot PRs;
- remaining non-blocking risks, including experimental Windows; and
- final clean/synchronized repository state.
