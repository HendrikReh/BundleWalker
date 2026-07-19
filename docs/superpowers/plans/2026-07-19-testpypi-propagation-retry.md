# TestPyPI Propagation Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TestPyPI post-upload verification tolerate bounded simple-index propagation delays without weakening permanent failures or retrying immutable publication.

**Architecture:** Keep retry logic inside the existing TestPyPI verify job and wrap only the exact TestPyPI resolver installation. Encode six attempts and the 5/10/20/40/80-second backoff directly in the workflow, protect the contract with YAML automation tests, and document safe verification-only recovery.

**Tech Stack:** GitHub Actions YAML, Bash, uv, pytest, Ruff, Pyright, Twine.

## Global Constraints

- Retry only TestPyPI resolution of the exact immutable version; build, audit, upload, artifact install, metadata, and CLI smoke failures remain immediate.
- Perform exactly six installation attempts with waits of 5, 10, 20, 40, and 80 seconds after the first five failures.
- Stop immediately after a successful install and exit nonzero immediately after the sixth failure.
- Do not add `continue-on-error`, a general retry framework, an external retry action, or production PyPI behavior.
- Do not dispatch the TestPyPI workflow or attempt to rebuild, overwrite, or republish `0.4.0a2`.
- Preserve the existing exact-version metadata check and both CLI smoke tests.
- Add the change under `Unreleased`; do not rewrite the historical `v0.4.0a2` changelog entry.
- Required supported macOS/Linux CI must pass before merge; Windows remains experimental and non-blocking.

---

### Task 1: Add bounded TestPyPI propagation retry

**Files:**
- Modify: `tests/test_project_automation.py`
- Modify: `.github/workflows/publish-testpypi.yml`
- Modify: `docs/maintainers/releases.md`
- Modify: `CHANGELOG.md`
- Create: `docs/superpowers/plans/2026-07-19-testpypi-propagation-retry.md`

**Interfaces:**
- Consumes: workflow input `${{ inputs.version }}`, the downloaded exact wheel, and the existing `.testpypi-venv` Python 3.13 environment.
- Produces: a finite retry boundary around only `uv pip install --no-deps --default-index https://test.pypi.org/simple "bundlewalker==${{ inputs.version }}"`.

- [ ] **Step 1: Add the failing automation contract**

Add this test immediately after `test_testpypi_workflow_is_manual_oidc_only_and_verifies_publication` in `tests/test_project_automation.py`:

```python
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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_testpypi_verification_retries_bounded_propagation_delay -q
```

Expected: FAIL at `assert "retry_delays=(5 10 20 40 80)" in script` because the current workflow performs one immediate TestPyPI install.

- [ ] **Step 3: Implement the minimal bounded retry loop**

In `.github/workflows/publish-testpypi.yml`, leave wheel installation and uninstallation unchanged. Replace only the immediate TestPyPI install command with this block:

```yaml
          retry_delays=(5 10 20 40 80)
          for attempt in 1 2 3 4 5 6; do
            if uv pip install --python .testpypi-venv/bin/python --no-deps --default-index https://test.pypi.org/simple "bundlewalker==${{ inputs.version }}"; then
              break
            fi
            if [ "$attempt" -eq 6 ]; then
              echo "::error::TestPyPI did not expose bundlewalker==${{ inputs.version }} after 6 attempts."
              exit 1
            fi
            delay="${retry_delays[$((attempt - 1))]}"
            echo "::notice::TestPyPI has not exposed bundlewalker==${{ inputs.version }}; retrying in ${delay}s after attempt ${attempt}/6."
            sleep "$delay"
          done
```

Keep these commands immediately after the loop without changes:

```yaml
          test "$(.testpypi-venv/bin/python -c 'from importlib.metadata import version; print(version("bundlewalker"))')" = "${{ inputs.version }}"
          .testpypi-venv/bin/bundlewalker --help
          .testpypi-venv/bin/bundlewalker-mcp --help
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_testpypi_verification_retries_bounded_propagation_delay -q
```

Expected: PASS with one test passing and pristine output.

- [ ] **Step 5: Document bounded retry and safe recovery**

In `docs/maintainers/releases.md`, add this paragraph after the existing immutable-version warning in the TestPyPI section:

```markdown
The verification job retries only the exact TestPyPI installation up to six times, waiting 5,
10, 20, 40, and 80 seconds after successive propagation failures. Build, upload, artifact,
metadata, and CLI failures remain immediate. If upload succeeded but post-upload verification
exhausted the propagation window, confirm the immutable version is present on TestPyPI and rerun
only the failed verification job; do not dispatch a new build or publication for that version.
```

At the top of `CHANGELOG.md`, place this section before `v0.4.0a2`:

```markdown
## [Unreleased]

### Changed

- Hardened TestPyPI post-upload verification with six bounded exponential installation attempts
  while preserving permanent failures and immutable-version safety.

```

Add this link before the existing changelog reference links:

```markdown
[Unreleased]: https://github.com/HendrikReh/BundleWalker/compare/v0.4.0a2...HEAD
```

- [ ] **Step 6: Run focused and complete verification**

Run:

```bash
uv sync --locked
uv lock --check
uv run pytest tests/test_project_automation.py -q
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
```

Expected: every command exits zero; the workflow is not dispatched.

- [ ] **Step 7: Review and commit the atomic change**

Confirm `git status --short` contains only the five Task 1 files. Stage those exact paths and commit:

```bash
git add \
  .github/workflows/publish-testpypi.yml \
  CHANGELOG.md \
  docs/maintainers/releases.md \
  docs/superpowers/plans/2026-07-19-testpypi-propagation-retry.md \
  tests/test_project_automation.py
git commit -m "ci: retry TestPyPI propagation checks"
```

After task-scoped and whole-branch review, push `codex/testpypi-propagation-retry`, open a ready pull request into `master`, wait for required CI, and merge. Do not create a tag or release and do not dispatch `publish-testpypi.yml`.
