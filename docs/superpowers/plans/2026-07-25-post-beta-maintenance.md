# Post-Beta Dependency and Source-Distribution Maintenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the historical `rc3` lock-version blocker from current dependency policy and make
every sdist contain exactly the Git-tracked historical fixture files.

**Architecture:** Current dependency policy will validate declared floors and resolved-package
presence while immutable release records retain exact `rc3` versions. Hatch will explicitly
force-include only the two ignored historical `.bundlewalker` subtrees, and a built-archive test
will compare historical fixture members exactly with `git ls-files`.

**Tech Stack:** Python 3.13/3.14, pytest, Hatchling, uv, TOML, tarfile, Git, Ruff, Pyright,
pip-audit, Twine

## Global Constraints

- Keep package version exactly `0.4.0`.
- Do not change any dependency version or any `uv.lock` record.
- Do not modify `src/`, `.github/workflows/`, active support claims, or historical plans,
  specifications, fixtures, and release records.
- Preserve the exact `0.4.0rc3` dependency resolution in the immutable tag, changelog, accepted
  release documents, and existing release-history assertions.
- Continue excluding `.superpowers/` and `benchmarks/` from sdists.
- Include exactly the Git-tracked files below `tests/fixtures/historical/`; do not package
  untracked fixture data.
- macOS and Linux remain supported; Windows remains experimental.

---

### Task 1: Make historical fixture packaging deterministic

**Files:**
- Modify: `tests/test_release_metadata.py`
- Modify: `tests/test_project_automation.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Git's authoritative tracked-file list below `tests/fixtures/historical/`
- Produces: an sdist whose normalized historical fixture file set equals that tracked-file list

- [ ] **Step 1: Add the failing archive-content regression test**

Add this test near the existing source-distribution tests in `tests/test_release_metadata.py`:

```python
def test_source_distribution_contains_exact_tracked_historical_fixtures(
    tmp_path: Path,
) -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", "tests/fixtures/historical"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = set(tracked.stdout.splitlines())
    assert expected

    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(tmp_path), "--no-sources"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    sdist = next(tmp_path.glob("bundlewalker-*.tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        packaged = {
            PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix()
            for member in archive.getmembers()
            if member.isfile()
        }

    actual = {
        path for path in packaged if path.startswith("tests/fixtures/historical/")
    }
    assert actual == expected
```

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_source_distribution_contains_exact_tracked_historical_fixtures \
  -q
```

Expected: FAIL. The `expected - actual` difference contains the 28 tracked paths below the two
historical `.bundlewalker/` subtrees.

- [ ] **Step 3: Add focused Hatch force-inclusion mappings**

Change the existing table in `pyproject.toml` to:

```toml
[tool.hatch.build.targets.sdist.force-include]
"tests/fixtures/historical/empty-directories.json" = "tests/fixtures/historical/empty-directories.json"
"tests/fixtures/historical/v1-schema1-swapping/.bundlewalker" = "tests/fixtures/historical/v1-schema1-swapping/.bundlewalker"
"tests/fixtures/historical/v3-schema2-pending/.bundlewalker" = "tests/fixtures/historical/v3-schema2-pending/.bundlewalker"
```

- [ ] **Step 4: Update the configuration contract**

Change `test_sdist_includes_historical_empty_directory_representation` in
`tests/test_project_automation.py` to
`test_sdist_force_includes_ignored_historical_fixture_representation` and assert:

```python
assert force_include == {
    "tests/fixtures/historical/empty-directories.json": (
        "tests/fixtures/historical/empty-directories.json"
    ),
    "tests/fixtures/historical/v1-schema1-swapping/.bundlewalker": (
        "tests/fixtures/historical/v1-schema1-swapping/.bundlewalker"
    ),
    "tests/fixtures/historical/v3-schema2-pending/.bundlewalker": (
        "tests/fixtures/historical/v3-schema2-pending/.bundlewalker"
    ),
}
```

- [ ] **Step 5: Record the packaging correction**

Add this bullet below `## [Unreleased]` in `CHANGELOG.md`:

```markdown
- Included all tracked historical `.bundlewalker` fixture data in source distributions while
  excluding untracked fixture files.
```

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_source_distribution_contains_exact_tracked_historical_fixtures \
  tests/test_release_metadata.py::test_source_distribution_excludes_untracked_superpowers_worker_state \
  tests/test_release_metadata.py::test_benchmark_harness_is_not_packaged \
  tests/test_project_automation.py::test_sdist_force_includes_ignored_historical_fixture_representation \
  -q
```

Expected: four tests pass.

- [ ] **Step 7: Verify the added archive members are the intended tracked set**

Run:

```bash
BW_SDIST_CHECK_DIR="$(mktemp -d)"
uv build --sdist --no-sources --out-dir "$BW_SDIST_CHECK_DIR"
BW_HIDDEN_MEMBERS="$(
  tar -tzf "$BW_SDIST_CHECK_DIR"/bundlewalker-0.4.0.tar.gz \
    | rg '/tests/fixtures/historical/.*/\.bundlewalker/' \
    | sort
)"
test "$(printf '%s\n' "$BW_HIDDEN_MEMBERS" | wc -l | tr -d ' ')" = "28"
printf '%s\n' "$BW_HIDDEN_MEMBERS"
```

Expected: 28 file paths, all below `v1-schema1-swapping/.bundlewalker/` or
`v3-schema2-pending/.bundlewalker/`.

- [ ] **Step 8: Commit the packaging fix**

```bash
git add pyproject.toml CHANGELOG.md tests/test_release_metadata.py tests/test_project_automation.py
git commit -m "fix: package complete historical fixtures"
```

---

### Task 2: Separate current dependency policy from historical release evidence

**Files:**
- Modify: `tests/test_release_metadata.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: current `pyproject.toml`, current `uv.lock`, and existing immutable release-history
  assertions
- Produces: a policy test that accepts compatible new resolutions without changing declared floors

- [ ] **Step 1: Capture the existing RED evidence from both dependency PRs**

Run:

```bash
gh run view 30135051360 --repo HendrikReh/BundleWalker --log \
  | rg -m 1 "AssertionError: assert '2.17.0' == '2.16.0'"
gh run view 30135057405 --repo HendrikReh/BundleWalker --log \
  | rg -m 1 "AssertionError: assert '0.16.0' == '0.15.22'"
```

Expected: both commands find the obsolete exact-version assertion that failed supported CI.

- [ ] **Step 2: Replace the obsolete current-lock test**

Replace `test_release_lock_uses_approved_rc3_dependency_versions` in
`tests/test_release_metadata.py` with:

```python
def test_current_dependency_policy_declares_supported_floors() -> None:
    locked = tomllib.loads((PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_names = {package["name"] for package in locked["package"]}
    assert {"pydantic-ai", "typer", "ruff"} <= locked_names

    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pydantic-ai>=2.10.0" in project["project"]["dependencies"]
    assert "typer>=0.16.0" in project["project"]["dependencies"]
    assert "ruff>=0.12.0" in project["dependency-groups"]["dev"]
```

Do not change the later `test_public_beta_documents_preserve_release_candidate_history` assertions
that require the `rc3` changelog to name `pydantic-ai` `2.16.0`, Typer `0.27.0`, and Ruff
`0.15.22`.

- [ ] **Step 3: Record the release-policy test correction**

Add this second bullet below `## [Unreleased]` in `CHANGELOG.md`:

```markdown
- Separated current dependency-floor validation from the immutable `0.4.0rc3` lock-resolution
  evidence so compatible post-release dependency updates can pass CI.
```

- [ ] **Step 4: Run focused policy and history tests**

Run:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_current_dependency_policy_declares_supported_floors \
  tests/test_release_metadata.py::test_public_beta_documents_preserve_release_candidate_history \
  -q
```

Expected: two tests pass.

- [ ] **Step 5: Commit the dependency-policy correction**

```bash
git add CHANGELOG.md tests/test_release_metadata.py
git commit -m "test: decouple current lock from rc3 evidence"
```

- [ ] **Step 6: Prove the corrected policy against both actual Dependabot locks**

Run:

```bash
for branch in \
  origin/dependabot/uv/pydantic-ai-2.13.0 \
  origin/dependabot/uv/ruff-0.15.22
do
  BW_POLICY_DIR="$(mktemp -d)"
  git archive HEAD | tar -x -C "$BW_POLICY_DIR"
  git archive "$branch" uv.lock | tar -x -C "$BW_POLICY_DIR"
  (
    cd "$BW_POLICY_DIR"
    uv sync --locked
    uv run pytest \
      tests/test_release_metadata.py::test_current_dependency_policy_declares_supported_floors \
      tests/test_release_metadata.py::test_public_beta_documents_preserve_release_candidate_history \
      -q
  )
done
```

Expected: both two-test runs pass. No repository file is modified.

---

### Task 3: Verify the complete maintenance boundary

**Files:**
- Verify only: all changed files and built distributions

**Interfaces:**
- Consumes: commits from Tasks 1 and 2
- Produces: review-ready evidence that the focused maintenance change is safe

- [ ] **Step 1: Verify locked state and the complete non-evaluation suite**

Run:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
```

Expected: locked sync/check pass and all selected tests pass.

- [ ] **Step 2: Verify formatting, linting, and typing**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all commands exit zero with no errors.

- [ ] **Step 3: Audit the unchanged locked dependency graph**

Run:

```bash
BW_AUDIT_REQUIREMENTS="$(mktemp)"
uv export --frozen --no-emit-project \
  --output-file "$BW_AUDIT_REQUIREMENTS" >/dev/null
uv run pip-audit --strict --requirement "$BW_AUDIT_REQUIREMENTS" \
  --require-hashes --disable-pip
```

Expected: no known vulnerabilities.

- [ ] **Step 4: Build and validate both distributions**

Run:

```bash
uv build --clear --no-sources
uv run twine check dist/*
```

Expected: one `0.4.0` wheel and one `0.4.0` sdist; Twine reports both `PASSED`.

- [ ] **Step 5: Smoke-test clean wheel and sdist installations**

Run:

```bash
BW_ARTIFACT_SMOKE_DIR="$(mktemp -d)"
uv venv --python 3.13 "$BW_ARTIFACT_SMOKE_DIR/wheel"
uv pip install --python "$BW_ARTIFACT_SMOKE_DIR/wheel/bin/python" \
  dist/bundlewalker-0.4.0-py3-none-any.whl
"$BW_ARTIFACT_SMOKE_DIR/wheel/bin/bundlewalker" --help >/dev/null
"$BW_ARTIFACT_SMOKE_DIR/wheel/bin/bundlewalker-mcp" --help >/dev/null

uv venv --python 3.13 "$BW_ARTIFACT_SMOKE_DIR/sdist"
uv pip install --python "$BW_ARTIFACT_SMOKE_DIR/sdist/bin/python" \
  dist/bundlewalker-0.4.0.tar.gz
"$BW_ARTIFACT_SMOKE_DIR/sdist/bin/bundlewalker" --help >/dev/null
"$BW_ARTIFACT_SMOKE_DIR/sdist/bin/bundlewalker-mcp" --help >/dev/null
```

Expected: both isolated installs and all four entry-point probes pass.

- [ ] **Step 6: Verify repository-layout-independent archive contents**

Verify the behavior once from the linked implementation worktree and once from a fresh normal Git
clone, whose `.git` entry is a directory:

```bash
uv run pytest \
  tests/test_release_metadata.py::test_source_distribution_contains_exact_tracked_historical_fixtures \
  -q

BW_NORMAL_CLONE_DIR="$(mktemp -d)"
git clone --quiet --local \
  --branch codex/post-beta-maintenance \
  "$(git rev-parse --show-toplevel)" \
  "$BW_NORMAL_CLONE_DIR/repository"
(
  cd "$BW_NORMAL_CLONE_DIR/repository"
  uv sync --locked
  uv run pytest \
    tests/test_release_metadata.py::test_source_distribution_contains_exact_tracked_historical_fixtures \
    -q
)
```

Expected: the archive-content regression passes in both repository layouts.

- [ ] **Step 7: Verify the exact change boundary**

Run:

```bash
git diff --check master...HEAD
git diff --name-only master...HEAD
git diff --exit-code master...HEAD -- uv.lock src .github/workflows
git status --short --branch
```

Expected:

- changed files are limited to the approved specification, this plan, `CHANGELOG.md`,
  `pyproject.toml`, `tests/test_release_metadata.py`, and `tests/test_project_automation.py`;
- `uv.lock`, `src/`, and workflows have no diff; and
- the worktree is clean.

- [ ] **Step 8: Review the complete diff**

Run:

```bash
git diff --stat master...HEAD
git diff master...HEAD -- \
  CHANGELOG.md \
  pyproject.toml \
  tests/test_release_metadata.py \
  tests/test_project_automation.py
```

Expected: only the approved maintenance changes appear, with no dependency, version, product, or
workflow drift.

- [ ] **Step 9: Push and open the maintenance pull request**

Run:

```bash
git push -u origin codex/post-beta-maintenance
gh pr create \
  --repo HendrikReh/BundleWalker \
  --base master \
  --head codex/post-beta-maintenance \
  --draft \
  --title "fix: harden post-beta dependency and sdist maintenance" \
  --body '## Summary

- separate current dependency-floor validation from immutable `0.4.0rc3` resolution evidence
- include exactly the Git-tracked historical fixture files in normal-checkout and linked-worktree sdists
- add archive-content regression coverage and document both fixes under `Unreleased`

## Root cause

The current lock test asserted the exact versions approved for `0.4.0rc3`, so compatible
post-release Dependabot resolutions failed supported CI. Exact rc3 versions remain preserved by
the annotated tag, changelog, accepted release records, and release-history tests.

Hatch respected the repository-wide `.bundlewalker/` ignore rule in a normal checkout, omitting 28
tracked historical fixture files from sdists. Targeted force-inclusion mappings now restore those
files without admitting arbitrary untracked fixture data.

## Validation

- full non-evaluation pytest suite
- Ruff formatting and linting
- Pyright
- strict hash-locked dependency audit
- wheel and sdist build plus Twine checks
- clean Python 3.13 wheel/sdist CLI and MCP smokes
- exact archive-versus-`git ls-files` comparison in linked and normal repository layouts
- corrected policy test against both open Dependabot lockfiles

Package version, dependency records, runtime source, workflows, and support policy are unchanged.'
```

Expected: a draft PR targeting `master` with the exact scope and evidence above.
