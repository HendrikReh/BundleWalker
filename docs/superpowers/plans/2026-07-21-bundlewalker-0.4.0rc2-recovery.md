# BundleWalker 0.4.0rc2 Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the production artifact selector, advance every current release identity to `0.4.0rc2`, and publish and independently verify one immutable `v0.4.0rc2` release without altering or rerunning `v0.4.0rc1`.

**Architecture:** Keep the existing tag-triggered, build-once OIDC pipeline. Change only its distribution-file selector so the `uv`-created `dist/.gitignore` is not counted or passed to Twine, prove that behavior with a regression test before editing the workflow, then carry the reviewed rc2 identity through the existing protected release lane. Treat the rc1 tag, failed run `29847165596`, and rc1 plan/spec as immutable historical evidence.

**Tech Stack:** Python 3.13/3.14, pytest, YAML/GitHub Actions, `uv` 0.11.28, Ruff, Pyright, pip-audit, Twine, GitHub CLI/API, PyPI Trusted Publishing/OIDC.

## Global Constraints

- `v0.4.0rc1` stays annotated at `d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1`; never move, delete, recreate, force-push, or reuse it.
- Never rerun rc1 workflow run `29847165596` or any rc1 build, publish, verification, or GitHub-release job.
- The exact new package version is `0.4.0rc2`; the exact new annotated tag is `v0.4.0rc2`.
- Preserve `docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md` and `docs/superpowers/specs/2026-07-21-bundlewalker-0.4.0rc1-production-release-design.md` byte-for-byte.
- The trusted-publisher identity is version-independent and remains exactly project `bundlewalker`, owner `HendrikReh`, repository `BundleWalker`, workflow `publish-pypi.yml`, environment `pypi`. Do not replace it with an rc2-named workflow or environment.
- Production still builds once. Publish, PyPI verification, and GitHub release must reuse the exact retained wheel and source archive; no downstream rebuild is allowed.
- Do not create or push `v0.4.0rc2` until the exact reviewed PR head is merged, `master` is synchronized, rc2 is absent from PyPI and Git, and both trust boundaries pass fresh audits.
- After the rc2 tag push, it is consumed even if the workflow fails. Never move or reuse it; any repository correction advances through review to `0.4.0rc3`.
- Never rerun a failed publish job. Only the original verification job may be rerun for proven index-propagation delay, and only the original GitHub-release job may be rerun for an isolated release-creation failure.
- Any unexpected ref, commit, tag object, version, environment rule, pending/active publisher field, artifact filename/count/digest, deployment, job count/conclusion, or production response stops the release.
- Production `0.4.0` and final-beta claims remain out of scope.

---

## File Map

- Modify `.github/workflows/publish-pypi.yml`: select only wheel and source-distribution files for count, Twine validation, and checksums.
- Modify `tests/test_project_automation.py`: execute the workflow's `find` selector against a fixture containing `dist/.gitignore` and require exactly the wheel and sdist.
- Modify `pyproject.toml` and `uv.lock`: advance the authoritative/editable-project version to `0.4.0rc2`; change no dependency resolution.
- Modify `tests/test_release_metadata.py`, `tests/cli/test_workspace.py`, and `tests/application/test_lifecycle.py`: update only current-version assertions and add rc1-history/rc2-recovery documentation assertions.
- Modify `README.md`: name and install exact current production candidate `0.4.0rc2`.
- Modify `CHANGELOG.md`: add an rc2 recovery entry and links while retaining the rc1 entry and link.
- Modify `docs/maintainers/releases.md`: record the consumed rc1 failure and make the operative procedure rc2-specific while retaining the version-independent publisher tuple and fail-closed recovery rules.
- Do not modify either rc1 plan/spec, the rc1 tag, run `29847165596`, or any benchmark/historical fixture evidence.

---

### Task 1: Reproduce and correct distribution selection test-first

**Files:**

- Modify: `tests/test_project_automation.py`
- Modify: `.github/workflows/publish-pypi.yml`
- Test: `tests/test_project_automation.py`

**Interfaces:**

- Consumes: the `Validate exact artifacts and metadata` shell step.
- Produces: a selector whose result is exactly `dist/bundlewalker-${version}-py3-none-any.whl` and `dist/bundlewalker-${version}.tar.gz`; `dist/.gitignore` is not a distribution artifact.
- Preserves: the existing exact-filename assertions, one-build invariant, Twine check, SHA-256 emission, artifact upload, OIDC permissions, and downstream jobs.

- [ ] **Step 1: Add imports for executing the selector**

Add beside the standard-library imports in `tests/test_project_automation.py`:

```python
import shlex
import subprocess
```

- [ ] **Step 2: Add the failing selector regression**

Add immediately after `test_pypi_workflow_requires_exact_artifacts_in_every_downstream_job`:

```python
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
        "bundlewalker-0.4.0rc2-py3-none-any.whl",
        "bundlewalker-0.4.0rc2.tar.gz",
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
        "dist/bundlewalker-0.4.0rc2-py3-none-any.whl",
        "dist/bundlewalker-0.4.0rc2.tar.gz",
    ]
    assert "dist/.gitignore" not in selected
    assert 'uv run twine check "${artifacts[@]}"' in script
```

- [ ] **Step 3: Run the regression and verify the rc1 failure mode**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_pypi_workflow_does_not_count_uv_gitignore_as_distribution -q
```

Expected: FAIL because the current `find dist -maxdepth 1 -type f -print` returns three paths,
including `dist/.gitignore`. Do not weaken the expected two-path assertion.

- [ ] **Step 4: Make the minimal workflow correction**

In `Validate exact artifacts and metadata`, replace only the selector and Twine invocation so the
complete step is:

```yaml
      - name: Validate exact artifacts and metadata
        shell: bash
        run: |
          mapfile -t artifacts < <(find dist -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) -print | sort)
          test "${#artifacts[@]}" -eq 2
          test -f "dist/bundlewalker-${{ steps.identity.outputs.version }}-py3-none-any.whl"
          test -f "dist/bundlewalker-${{ steps.identity.outputs.version }}.tar.gz"
          uv run twine check "${artifacts[@]}"
          sha256sum "${artifacts[@]}"
```

The count remains fail-closed for missing, duplicate, or additional wheel/sdist files. The only
semantic change is that non-distribution files such as `dist/.gitignore` are not members of
`artifacts` and are not passed to Twine or `sha256sum`.

- [ ] **Step 5: Run focused automation tests**

Run:

```bash
uv run pytest \
  tests/test_project_automation.py::test_pypi_workflow_does_not_count_uv_gitignore_as_distribution \
  tests/test_project_automation.py::test_pypi_workflow_requires_exact_artifacts_in_every_downstream_job \
  tests/test_project_automation.py::test_pypi_workflow_is_tag_gated_oidc_only_and_reuses_exact_artifacts \
  -q
```

Expected: PASS. Also require the workflow diff to contain no permission, trigger, action-pin,
environment, job dependency, build, upload, or retry changes:

```bash
git diff -- .github/workflows/publish-pypi.yml tests/test_project_automation.py
```

- [ ] **Step 6: Commit the tested selector correction**

```bash
git add .github/workflows/publish-pypi.yml tests/test_project_automation.py
git commit -m "ci: exclude uv marker from release artifacts"
```

---

### Task 2: Advance current identity and document the immutable recovery

**Files:**

- Modify: `tests/test_release_metadata.py`
- Modify: `tests/cli/test_workspace.py`
- Modify: `tests/application/test_lifecycle.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/maintainers/releases.md`

**Interfaces:**

- Consumes: installed distribution metadata sourced from `pyproject.toml`.
- Produces: current runtime, CLI, README, changelog, lockfile, and maintainer identity `0.4.0rc2`/`v0.4.0rc2`.
- Preserves: the rc1 changelog entry/link, immutable tag/run facts, historical rc1 plan/spec contents, release-lane regex accepting all `0.4.0rcN`, and Alpha classifier until final beta.

- [ ] **Step 1: Change current-version tests before production files**

Make these exact test changes:

```python
# tests/test_release_metadata.py
def test_development_version_is_second_release_candidate() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == "0.4.0rc2"
    assert bundlewalker.__version__ == "0.4.0rc2"
```

Change the sdist root assertion to:

```python
assert (
    "bundlewalker-0.4.0rc2/docs/superpowers/plans/2026-07-19-bundlewalker-0.4.0a2-release.md"
) in packaged_paths
```

Rename `test_first_release_candidate_is_documented_without_final_beta_claim` to
`test_second_release_candidate_documents_rc1_recovery_without_final_beta_claim`, change its current
README/changelog assertions to rc2, and require the immutable rc1 evidence:

```python
assert "current production release candidate is `0.4.0rc2`" in readme
assert 'uv tool install "bundlewalker==0.4.0rc2"' in readme
assert "proof of concept" in readme
assert "## [v0.4.0rc2] - 2026-07-21" in changelog
assert "## [v0.4.0rc1] - 2026-07-21" in changelog
assert (
    "[v0.4.0rc2]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc1...v0.4.0rc2"
) in changelog
assert (
    "[v0.4.0rc1]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0a2...v0.4.0rc1"
) in changelog
for phrase in (
    "publish-pypi.yml",
    "GitHub environment `pypi`",
    "pending trusted publisher",
    "v0.4.0rc1",
    "29847165596",
    "v0.4.0rc2",
    "Never move, delete, or reuse",
    "TestPyPI and production builds are separate",
    "fresh artifacts from its reviewed tag",
    'gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"',
    "Never rerun a failed publish job",
):
    assert phrase in releases
assert "Production `0.4.0` is forbidden" in releases
```

In `tests/cli/test_workspace.py`, change the expected status line to
`"BundleWalker version: 0.4.0rc2\n"`. In `tests/application/test_lifecycle.py`, change only the
current `installed_version` expectation to `"0.4.0rc2"`.

- [ ] **Step 2: Run current-identity tests and observe failure**

```bash
uv run pytest \
  tests/test_release_metadata.py::test_development_version_is_second_release_candidate \
  tests/test_release_metadata.py::test_second_release_candidate_documents_rc1_recovery_without_final_beta_claim \
  tests/cli/test_workspace.py::test_workspace_status_reports_future_format_without_creating_state \
  tests/application/test_lifecycle.py::test_lifecycle_status_inspects_future_format_without_mutation \
  -q
```

Expected: FAIL on the still-current rc1 metadata/documentation. The failures must not come from a
changed historical rc1 plan or spec.

- [ ] **Step 3: Advance authoritative version and lockfile**

Change only:

```toml
# pyproject.toml
version = "0.4.0rc2"
```

Then regenerate and verify the lock:

```bash
uv lock
uv lock --check
git diff -- pyproject.toml uv.lock
```

Expected: `uv.lock` changes only the editable `bundlewalker` package version from `0.4.0rc1` to
`0.4.0rc2`; no third-party package, hash, source, or dependency changes.

- [ ] **Step 4: Update README and changelog without rewriting history**

In `README.md`, change the current candidate sentence and exact install command to `0.4.0rc2`; keep
the proof-of-concept and final-`0.4.0` caveats.

In `CHANGELOG.md`, retain the entire rc1 section and add directly above it:

```markdown
## [v0.4.0rc2] - 2026-07-21

### Fixed

- Excluded the `uv`-created `dist/.gitignore` marker from production distribution selection so
  exact-artifact validation counts and checks only the wheel and source archive. The immutable
  `v0.4.0rc1` workflow failed at this pre-upload check and was not rerun or published.
```

Replace the first two comparison links with:

```markdown
[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc2...HEAD
[v0.4.0rc2]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0rc1...v0.4.0rc2
```

Leave the existing `[v0.4.0rc1]` link immediately after them unchanged.

- [ ] **Step 5: Make the maintainer runbook operative for rc2**

In `docs/maintainers/releases.md`, preserve the general production workflow and recovery rules,
but replace the rc1-specific operative paragraph with these two paragraphs:

```markdown
`v0.4.0rc1` is consumed and immutable at commit
`d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1`. Production workflow run `29847165596` failed once in
the reversible build stage because `uv build --clear` created `dist/.gitignore` and the validation
step counted every regular file. It produced no retained workflow artifact, deployment approval,
OIDC upload, PyPI version, or GitHub release. Never rerun that workflow or move, delete, or reuse
the rc1 tag.

For `0.4.0rc2`, merge the protected recovery pull request first, binding the merge to its recorded
head commit. Immediately before tagging, fetch fresh `origin/master` and tags; require local
`master`, fresh `origin/master`, and the pull request's actual merge OID to agree. Re-read the
`pypi` environment reviewer and tag-only rule, and verify the still-pending trusted-publisher tuple
`bundlewalker/HendrikReh/BundleWalker/publish-pypi.yml/pypi`; this tuple is keyed by workflow and
environment, not package version. Confirm production `0.4.0rc2` is unavailable. Only then create
annotated tag `v0.4.0rc2` at that exact merge commit, verify it, and push it once. Inspect the
build evidence before approving only the exact `pypi` deployment for that tag and commit.
```

Update later current-candidate references from rc1 to rc2, including the clean-install
certification sentence. Do not change the publisher table, tag policy `v0.4.0*`, historical rc1
facts, or the rule that final `0.4.0` is forbidden.

- [ ] **Step 6: Prove current identity and historical immutability**

```bash
uv sync --locked
uv run pytest \
  tests/test_release_metadata.py \
  tests/cli/test_workspace.py::test_workspace_status_reports_future_format_without_creating_state \
  tests/application/test_lifecycle.py::test_lifecycle_status_inspects_future_format_without_mutation \
  tests/test_project_automation.py \
  -q
test "$(git rev-parse 'v0.4.0rc1^{}')" = d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1
git diff --exit-code v0.4.0rc1 -- \
  docs/superpowers/plans/2026-07-21-bundlewalker-0.4.0rc1-production-release.md \
  docs/superpowers/specs/2026-07-21-bundlewalker-0.4.0rc1-production-release-design.md
git grep -n -E '0\.4\.0rc1|v0\.4\.0rc1|0\.4\.0rc2|v0\.4\.0rc2'
```

Expected: tests PASS; rc1 tag and historical plan/spec match the tagged bytes. Review every grep
hit: rc2 owns current metadata/runtime/install/runbook references; rc1 remains only in changelog
history, failure evidence, release-lane test examples, and historical plan/spec material.

- [ ] **Step 7: Commit the rc2 identity and recovery documentation**

```bash
git add \
  pyproject.toml uv.lock README.md CHANGELOG.md docs/maintainers/releases.md \
  tests/test_release_metadata.py tests/cli/test_workspace.py \
  tests/application/test_lifecycle.py
git commit -m "build: prepare 0.4.0rc2 recovery candidate"
```

---

### Task 3: Run the complete reversible gate and review the exact PR head

**Files:**

- Verify: entire repository and built distributions
- Remote artifact: pull request from `codex/release-0.4.0rc2` to `master`

**Interfaces:**

- Consumes: Tasks 1-2 commits.
- Produces: a clean, pushed, fully green, reviewed PR head whose OID is recorded for exact-head merge.

- [ ] **Step 1: Run the full local quality gate**

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
uv run python - <<'PY'
from pathlib import Path

dist = Path("dist")
expected = {
    "bundlewalker-0.4.0rc2-py3-none-any.whl",
    "bundlewalker-0.4.0rc2.tar.gz",
}
selected = {
    path.name
    for path in dist.iterdir()
    if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
}
unexpected = {path.name for path in dist.iterdir() if path.is_file()} - expected - {".gitignore"}
assert selected == expected, selected
assert not unexpected, unexpected
PY
uv run twine check \
  dist/bundlewalker-0.4.0rc2-py3-none-any.whl \
  dist/bundlewalker-0.4.0rc2.tar.gz
SMOKE_ROOT="$(mktemp -d)"
uv venv --python 3.13 "$SMOKE_ROOT/venv"
uv pip install --python "$SMOKE_ROOT/venv/bin/python" \
  dist/bundlewalker-0.4.0rc2-py3-none-any.whl
test "$("$SMOKE_ROOT/venv/bin/python" -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = 0.4.0rc2
"$SMOKE_ROOT/venv/bin/bundlewalker" --help
"$SMOKE_ROOT/venv/bin/bundlewalker-mcp" --help
git diff --check
test -z "$(git status --porcelain)"
```

Expected: every command exits zero; the only files under `dist/` are the two exact distributions
and optional `.gitignore`; the clean wheel reports rc2 and both entry points work. If `git status`
is not clean, commit only intended tracked changes and repeat the entire gate.

- [ ] **Step 2: Push the recovery branch and open the PR**

```bash
test "$(git branch --show-current)" = codex/release-0.4.0rc2
git push -u origin codex/release-0.4.0rc2
gh pr create \
  --base master \
  --head codex/release-0.4.0rc2 \
  --title "Recover BundleWalker production release as 0.4.0rc2" \
  --body "$(printf '%s\n' \
    '## Summary' \
    '- exclude the uv-created dist/.gitignore from exact distribution selection' \
    '- advance current package and documentation identity to immutable 0.4.0rc2' \
    '- preserve v0.4.0rc1 and failed run 29847165596 without rerun' \
    '' \
    '## Verification' \
    '- uv run pytest -m '\''not eval'\'' -q' \
    '- Ruff format/lint, Pyright, pip-audit, uv lock --check' \
    '- exact rc2 wheel/sdist selection, Twine, and clean-wheel CLI smokes')"
```

- [ ] **Step 3: Bind review and checks to one immutable PR head**

Use the `code-review` skill to review `origin/master...$PR_HEAD`, with special attention to artifact
selection, current-versus-historical identity, workflow permissions, and release fail-closed
behavior. Record the OID before review and require it to remain unchanged afterward:

```bash
PR_NUMBER="$(gh pr view --json number --jq .number)"
PR_HEAD="$(gh pr view "$PR_NUMBER" --json headRefOid --jq .headRefOid)"
test "$PR_HEAD" = "$(git rev-parse HEAD)"
git diff --check origin/master..."$PR_HEAD"
git diff --stat origin/master..."$PR_HEAD"
gh pr diff "$PR_NUMBER"
gh pr checks "$PR_NUMBER" --watch --fail-fast=false
gh pr checks "$PR_NUMBER" --required
test "$(gh pr view "$PR_NUMBER" --json headRefOid --jq .headRefOid)" = "$PR_HEAD"
gh pr view "$PR_NUMBER" --json mergeStateStatus,reviewDecision,statusCheckRollup,url
```

Expected: review has no unresolved correctness or security findings; every required check is
successful; the reviewed head still equals local `HEAD`. Any new commit invalidates the review and
requires the full local gate, pushed checks, and exact-head review again.

---

### Task 4: Merge the exact head and re-audit both trust boundaries

**Files:**

- Remote repository state: exact recovery PR merged to `master`
- External state: existing GitHub `pypi` environment and existing PyPI pending publisher

**Interfaces:**

- Consumes: unchanged reviewed `PR_HEAD` from Task 3.
- Produces: synchronized clean `master`, verified untouched rc1 evidence, unused rc2 identity, and exact pre-tag trust configuration.

- [ ] **Step 1: Merge only the reviewed head**

```bash
test "$(gh pr view "$PR_NUMBER" --json headRefOid --jq .headRefOid)" = "$PR_HEAD"
gh pr checks "$PR_NUMBER" --required
gh pr merge "$PR_NUMBER" --merge --match-head-commit "$PR_HEAD" \
  --subject "Recover BundleWalker production release as 0.4.0rc2"
PR_MERGE_OID="$(gh pr view "$PR_NUMBER" --json mergeCommit --jq '.mergeCommit.oid')"
test -n "$PR_MERGE_OID"
```

- [ ] **Step 2: Synchronize the primary checkout and prove rc1 remains immutable**

Run in `/Volumes/OWC Envoy Ultra/Development/BundleWalker` and stop if it is dirty:

```bash
git switch master
test -z "$(git status --porcelain)"
git pull --ff-only origin master
git fetch origin --tags
RELEASE_COMMIT="$(git rev-parse HEAD)"
test "$RELEASE_COMMIT" = "$PR_MERGE_OID"
test "$RELEASE_COMMIT" = "$(git rev-parse origin/master)"
test "$(uv run python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = 0.4.0rc2
test "$(git rev-parse 'v0.4.0rc1^{}')" = d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1
test "$(git ls-remote origin 'refs/tags/v0.4.0rc1^{}' | cut -f1)" = d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1
RC1_RUN="$(gh run view 29847165596 --json status,conclusion,attempt,headBranch,headSha)"
printf '%s' "$RC1_RUN" | jq -e '
  .status == "completed" and .conclusion == "failure" and .attempt == 1 and
  .headBranch == "v0.4.0rc1" and
  .headSha == "d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1"
' >/dev/null
test "$(gh api repos/HendrikReh/BundleWalker/actions/runs/29847165596/artifacts --jq .total_count)" = 0
test "$(gh api repos/HendrikReh/BundleWalker/actions/runs/29847165596/pending_deployments --jq length)" = 0
if gh release view v0.4.0rc1 >/dev/null 2>&1; then exit 1; fi
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://pypi.org/pypi/bundlewalker/0.4.0rc1/json)" = 404
```

Expected: rc1 is still the original annotated tag and one failed attempt with no artifact,
deployment, PyPI version, or GitHub release. Do not issue any `gh run rerun` command for it.

- [ ] **Step 3: Prove rc2 is unused before trust review**

```bash
test -z "$(git tag --list v0.4.0rc2)"
git ls-remote --exit-code --tags origin refs/tags/v0.4.0rc2 && exit 1 || test "$?" -eq 2
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://pypi.org/pypi/bundlewalker/json)" = 404
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://pypi.org/pypi/bundlewalker/0.4.0rc2/json)" = 404
```

Expected: no rc2 Git ref or PyPI version exists and the project remains uncreated.

- [ ] **Step 4: Re-audit the GitHub environment exactly**

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

Expected: only the required reviewer `HendrikReh` (self-review permitted) and the single tag-only
policy `v0.4.0*` exist. Drift stops the release; do not silently repair configuration in this task.

- [ ] **Step 5: Re-audit the version-independent pending publisher**

In a fresh authenticated `hereh` session, open the PyPI pending-publisher settings and require one
row with exactly:

```text
project:      bundlewalker
repository:   HendrikReh/BundleWalker
workflow:     publish-pypi.yml
environment:  pypi
```

Require no `(Any)` field, API token, duplicate publisher, or already-active project publisher.
This is the existing rc1-era tuple: it is intentionally not renamed for rc2. If any field or state
differs, stop before tagging and record the mismatch.

---

### Task 5: Create the immutable rc2 tag and approve only its exact deployment

**Files:**

- Immutable Git ref: `v0.4.0rc2`
- Workflow run: exact tag-push run for `RELEASE_COMMIT`

**Interfaces:**

- Consumes: Task 4's synchronized commit and fresh trust audits.
- Produces: one pushed annotated tag, one successful retained two-file build artifact, and one explicitly approved exact `pypi` deployment.

- [ ] **Step 1: Repeat the last reversible audit**

Immediately before tag creation, repeat Task 4 Steps 2-5 and additionally require:

```bash
test "$(git branch --show-current)" = master
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = "$RELEASE_COMMIT"
test "$RELEASE_COMMIT" = "$(git rev-parse origin/master)"
test "$RELEASE_COMMIT" = "$PR_MERGE_OID"
```

Expected: every assertion and the authenticated pending-publisher read-back pass in the same
release session. This is the final cancellation point that does not consume rc2.

- [ ] **Step 2: Create, inspect, and push the annotated tag once**

```bash
git tag -a v0.4.0rc2 "$RELEASE_COMMIT" -m "BundleWalker 0.4.0rc2"
test "$(git rev-list -n 1 v0.4.0rc2)" = "$RELEASE_COMMIT"
test "$(git cat-file -t v0.4.0rc2)" = tag
test "$(git for-each-ref refs/tags/v0.4.0rc2 --format='%(contents:subject)')" = "BundleWalker 0.4.0rc2"
git show --no-patch --format=fuller v0.4.0rc2
git push origin refs/tags/v0.4.0rc2
test "$(git ls-remote origin 'refs/tags/v0.4.0rc2^{}' | cut -f1)" = "$RELEASE_COMMIT"
```

Expected: one annotated remote tag peels to the exact reviewed merge. From this line onward rc2 is
immutable and consumed; never delete, move, force-push, or recreate it.

- [ ] **Step 3: Resolve exactly one tag workflow run and verify the build before approval**

```bash
RUN_ID="$(gh run list \
  --workflow publish-pypi.yml \
  --branch v0.4.0rc2 \
  --event push \
  --limit 10 \
  --json databaseId,headSha,headBranch,event \
  --jq '[.[] | select(.headSha == "'"$RELEASE_COMMIT"'" and .headBranch == "v0.4.0rc2" and .event == "push")] | if length == 1 then .[0].databaseId else empty end')"
test -n "$RUN_ID"
RUN_JSON="$(gh run view "$RUN_ID" --json attempt,event,headBranch,headSha,jobs,url)"
printf '%s' "$RUN_JSON" | jq -e --arg sha "$RELEASE_COMMIT" '
  .attempt == 1 and .event == "push" and .headBranch == "v0.4.0rc2" and .headSha == $sha
' >/dev/null
BUILD_JOB_ID="$(printf '%s' "$RUN_JSON" | jq -er '
  [.jobs[] | select(.name == "Build and verify exact distributions")] |
  if length == 1 then .[0].databaseId else error("missing or duplicate build job") end
')"
gh run watch "$RUN_ID" --compact
RUN_JSON="$(gh run view "$RUN_ID" --json attempt,event,headBranch,headSha,jobs,url)"
test "$(printf '%s' "$RUN_JSON" | jq -r --argjson id "$BUILD_JOB_ID" '.jobs[] | select(.databaseId == $id) | .conclusion')" = success
gh run view "$RUN_ID" --log --job "$BUILD_JOB_ID"
BUILD_ROOT="$(mktemp -d)"
gh run download "$RUN_ID" --name python-package-distributions --dir "$BUILD_ROOT/dist"
uv run --no-project python - "$BUILD_ROOT/dist" <<'PY'
import sys
from pathlib import Path

dist = Path(sys.argv[1])
assert {path.name for path in dist.iterdir() if path.is_file()} == {
    "bundlewalker-0.4.0rc2-py3-none-any.whl",
    "bundlewalker-0.4.0rc2.tar.gz",
}
PY
```

If `gh run watch` remains pending for approval, interrupt it after the build has completed and use
the refreshed `RUN_JSON`; do not approve merely to make the watch return. Expected: attempt 1,
exact tag/commit, one successful build job, one retained artifact containing exactly two files,
and logs showing the marker-exclusion regression, tests, audit, Twine, SHA-256, and wheel smoke all
passed. Any build or artifact failure stops; do not approve and do not rerun.

- [ ] **Step 4: Re-audit exact run, ref, tag, trust, and absence immediately before approval**

Repeat the GitHub environment audit and authenticated pending-publisher read-back from Task 4, then:

```bash
test "$(git ls-remote origin 'refs/tags/v0.4.0rc2^{}' | cut -f1)" = "$RELEASE_COMMIT"
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://pypi.org/pypi/bundlewalker/0.4.0rc2/json)" = 404
PENDING="$(gh api repos/HendrikReh/BundleWalker/actions/runs/"$RUN_ID"/pending_deployments)"
printf '%s' "$PENDING" | jq -e '
  length == 1 and .[0].environment.name == "pypi" and .[0].current_user_can_approve == true
' >/dev/null
ENVIRONMENT_ID="$(printf '%s' "$PENDING" | jq -er '.[0].environment.id')"
RUN_IDENTITY="$(gh run view "$RUN_ID" --json attempt,headBranch,headSha)"
printf '%s' "$RUN_IDENTITY" | jq -e --arg sha "$RELEASE_COMMIT" '
  .attempt == 1 and .headBranch == "v0.4.0rc2" and .headSha == $sha
' >/dev/null
```

Expected: exactly one approvable deployment, environment `pypi`, exact run attempt/tag/commit,
unchanged publisher/environment, unchanged remote tag, and rc2 still absent from PyPI.

- [ ] **Step 5: Approve that deployment exactly once**

```bash
jq -n --argjson environment_id "$ENVIRONMENT_ID" '{
  environment_ids: [$environment_id],
  state: "approved",
  comment: "Approve exact v0.4.0rc2 deployment after artifact and trust-boundary audit"
}' | gh api \
  --method POST \
  repos/HendrikReh/BundleWalker/actions/runs/"$RUN_ID"/pending_deployments \
  --input -
```

Expected: only this run's sole `pypi` deployment is approved. Never approve by a stale browser tab,
different run ID, branch, tag, commit, environment, or second submission.

---

### Task 6: Verify publication, byte identity, publisher conversion, and final state

**Files:**

- Production package: `https://pypi.org/project/bundlewalker/0.4.0rc2/`
- GitHub prerelease: `BundleWalker 0.4.0rc2`
- Operational evidence: `.superpowers/sdd/0.4.0rc2-release-report.md` (ignored worker state)

**Interfaces:**

- Consumes: exact run/artifact from Task 5.
- Produces: authoritative PyPI metadata and installation evidence, byte-identical GitHub assets, converted trusted publisher, and final immutable-repository evidence.

- [ ] **Step 1: Audit named jobs after workflow completion**

```bash
gh run watch "$RUN_ID"
RUN_JSON="$(gh run view "$RUN_ID" --json status,conclusion,attempt,headBranch,headSha,url,jobs)"
printf '%s' "$RUN_JSON" | jq -e --arg sha "$RELEASE_COMMIT" '
  .status == "completed" and .attempt == 1 and
  .headBranch == "v0.4.0rc2" and .headSha == $sha
' >/dev/null
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
    echo "recovered publication warning: upload action failed but exact same-run PyPI verification and GitHub release succeeded"
    ;;
  *) exit 1 ;;
esac
```

Do not infer completion from the overall run conclusion alone. Build, authoritative verification,
and GitHub release must succeed. A publish failure is acceptable only when this same run's exact
PyPI set and GitHub release succeeded; record the warning. No cancelled, skipped, duplicate, or
missing named job is accepted.

- [ ] **Step 2: Apply fail-closed recovery rules if the run is not complete**

- If build/pre-upload validation failed: do not approve/rerun; rc2 remains consumed and the next
  repository correction is rc3.
- If PyPI has neither exact file: never rerun publish; diagnose and advance to rc3.
- If PyPI has one file, extra files, a wrong filename, or a digest mismatch: treat rc2 as unsafe,
  yank it through PyPI, record an advisory, and advance through review to rc3.
- If only exact-version index installation exhausted the bounded propagation window, first prove
  both PyPI files equal the original run artifact, then rerun only the original verification job
  (and its dependent release job):

```bash
RECOVERY_ROOT="$(mktemp -d)"
gh run download "$RUN_ID" --name python-package-distributions --dir "$RECOVERY_ROOT/dist"
curl --fail --silent --show-error --location \
  https://pypi.org/pypi/bundlewalker/0.4.0rc2/json \
  --output "$RECOVERY_ROOT/pypi.json"
uv run --no-project python - "$RECOVERY_ROOT/pypi.json" "$RECOVERY_ROOT/dist" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dist = Path(sys.argv[2])
expected = {
    "bundlewalker-0.4.0rc2-py3-none-any.whl",
    "bundlewalker-0.4.0rc2.tar.gz",
}
local = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in dist.iterdir() if path.is_file()}
remote = {item["filename"]: item["digests"]["sha256"] for item in payload["urls"]}
assert payload["info"]["version"] == "0.4.0rc2"
assert set(local) == expected
assert set(remote) == expected
assert local == remote, {"local": local, "remote": remote}
PY
VERIFY_JOB_ID="$(gh run view "$RUN_ID" --json jobs --jq '[.jobs[] | select(.name == "Verify production PyPI installation and checksums")] | if length == 1 then .[0].databaseId else empty end')"
test -n "$VERIFY_JOB_ID"
gh run rerun "$RUN_ID" --job "$VERIFY_JOB_ID"
```

After that exceptional rerun, repeat Task 6 Step 1 from a fresh `RUN_JSON`. Never run `gh run
rerun` for the publish job. If only GitHub release creation fails, verify PyPI and the original
artifact first, then target only that original GitHub-release job database ID.

- [ ] **Step 3: Independently verify production filenames, digests, and clean index install**

```bash
VERIFY_ROOT="$(mktemp -d)"
gh run download "$RUN_ID" --name python-package-distributions --dir "$VERIFY_ROOT/run-dist"
curl --fail --silent --show-error --location \
  https://pypi.org/pypi/bundlewalker/0.4.0rc2/json \
  --output "$VERIFY_ROOT/pypi.json"
uv run --no-project python - "$VERIFY_ROOT/pypi.json" "$VERIFY_ROOT/run-dist" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
dist = Path(sys.argv[2])
expected = {
    "bundlewalker-0.4.0rc2-py3-none-any.whl",
    "bundlewalker-0.4.0rc2.tar.gz",
}
run = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in dist.iterdir() if path.is_file()}
pypi = {item["filename"]: item["digests"]["sha256"] for item in payload["urls"]}
assert payload["info"]["version"] == "0.4.0rc2"
assert set(run) == expected
assert set(pypi) == expected
assert run == pypi, {"run": run, "pypi": pypi}
print(json.dumps(pypi, indent=2, sort_keys=True))
PY
uv venv --python 3.13 "$VERIFY_ROOT/index-venv"
uv pip install --python "$VERIFY_ROOT/index-venv/bin/python" \
  --no-deps --default-index https://pypi.org/simple "bundlewalker==0.4.0rc2"
test "$("$VERIFY_ROOT/index-venv/bin/python" -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = 0.4.0rc2
"$VERIFY_ROOT/index-venv/bin/bundlewalker" --help
"$VERIFY_ROOT/index-venv/bin/bundlewalker-mcp" --help
```

Expected: PyPI exposes exactly the wheel and source archive, both SHA-256 values equal the original
run artifact, an exact clean production-index install reports rc2, and both CLIs succeed.

- [ ] **Step 4: Verify GitHub prerelease metadata and asset bytes**

```bash
RELEASE_JSON="$(gh release view v0.4.0rc2 --json name,isDraft,isPrerelease,tagName,targetCommitish,url,assets)"
printf '%s' "$RELEASE_JSON" | jq -e '
  .name == "BundleWalker 0.4.0rc2" and
  .isDraft == false and .isPrerelease == true and
  .tagName == "v0.4.0rc2" and
  ([.assets[].name] | sort) == [
    "bundlewalker-0.4.0rc2-py3-none-any.whl",
    "bundlewalker-0.4.0rc2.tar.gz"
  ]
' >/dev/null
RELEASE_TARGET="$(printf '%s' "$RELEASE_JSON" | jq -er .targetCommitish)"
test "$(git rev-parse "${RELEASE_TARGET}^{commit}")" = "$RELEASE_COMMIT"
mkdir "$VERIFY_ROOT/github-assets"
gh release download v0.4.0rc2 --dir "$VERIFY_ROOT/github-assets"
uv run --no-project python - "$VERIFY_ROOT/pypi.json" "$VERIFY_ROOT/github-assets" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assets = Path(sys.argv[2])
pypi = {item["filename"]: item["digests"]["sha256"] for item in payload["urls"]}
github = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in assets.iterdir() if path.is_file()}
assert github == pypi, {"github": github, "pypi": pypi}
PY
```

Expected: one non-draft prerelease named `BundleWalker 0.4.0rc2`, exact tag, exactly two assets,
and GitHub bytes identical to PyPI. Also require `targetCommitish` to resolve to `RELEASE_COMMIT`;
stop if GitHub reports an unrelated target.

- [ ] **Step 5: Verify publisher conversion and final immutable repository state**

In a fresh authenticated PyPI session, open project publishing settings and require that the
pending row has disappeared and exactly one project-scoped publisher exists with owner
`HendrikReh`, repository `BundleWalker`, workflow `publish-pypi.yml`, and environment `pypi`.
Confirm `hereh` manages `bundlewalker`; reject `(Any)`, duplicates, or changed fields.

Then run:

```bash
git fetch origin master --tags
test "$(git rev-parse master)" = "$(git rev-parse origin/master)"
test "$(git rev-list -n 1 v0.4.0rc2)" = "$RELEASE_COMMIT"
test "$(git ls-remote origin 'refs/tags/v0.4.0rc2^{}' | cut -f1)" = "$RELEASE_COMMIT"
test "$(git rev-list -n 1 v0.4.0rc1)" = d3a18370e2fdc7cfe2f79728731c82ba63aa0cf1
test -z "$(git status --porcelain)"
gh run view "$RUN_ID" --json url --jq .url
gh release view v0.4.0rc2 --json url --jq .url
```

- [ ] **Step 6: Record completion evidence**

Write `.superpowers/sdd/0.4.0rc2-release-report.md` with: PR URL/number and reviewed head OID;
merge/release commit; rc1 immutable tag and failed-run audit; rc2 annotated tag object and peeled
commit; workflow ID/URL/attempt and all four named job conclusions; approval environment ID;
PyPI URL and exact filenames/SHA-256 digests; clean-install/CLI results; GitHub release URL and
matching digests; converted publisher tuple; final clean `master`/`origin/master` state; and any
explicitly accepted recovered-publication warning. Do not claim completion if any required field is
missing, and do not tag or publish final `0.4.0` in this recovery.
