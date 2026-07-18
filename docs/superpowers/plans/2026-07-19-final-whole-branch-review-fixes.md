# Final Whole-Branch Review Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make historical workspace fixtures deterministic from tracked/source-distribution files and close every successfully opened workspace-lock descriptor on acquisition failures.

**Architecture:** Keep historical release bytes immutable and describe release-owned empty directories in a tracked sidecar outside every managed fixture. Route historical tests through one test-support materializer that copies file content and recreates only sidecar-declared empty directories. Move lock-descriptor ownership to an outer `finally`, recording successful acquisition so failure paths close once without attempting an unlock they do not own.

**Tech Stack:** Python 3.13, pytest, standard-library JSON/filesystem/fcntl APIs, Hatchling sdist, Ruff, Pyright, uv, Twine, Git

---

### Task 1: Preserve release-owned empty fixture directories

**Files:**
- Create: `tests/fixtures/historical/empty-directories.json`
- Create: `tests/historical_fixtures.py`
- Modify: `tests/test_historical_compatibility.py`
- Modify: `tests/fixtures/historical/provenance.json`
- Modify: `tests/test_project_automation.py`
- Modify: `pyproject.toml`
- Modify: `CONTRIBUTING.md`

**Step 1: Write the failing tests**

Add historical tests that first copy only represented files into an isolated fixture repository, then use one materialization helper for every fixture consumer. Assert the clean `v1`, `v2`, and `v3` workspaces and the `v3-schema2-pending` fixture regain empty `raw/` directories. Add a project-automation assertion that Hatch's sdist force-includes the representation sidecar.

**Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_historical_compatibility.py tests/test_project_automation.py -q
```

Expected: FAIL because the sidecar, helper contract, provenance representation metadata, and explicit sdist inclusion do not exist.

**Step 3: Add the minimal representation and materializer**

Create `empty-directories.json` with schema version `1` and these paths:

```json
{
  "schema_version": 1,
  "empty_directories": [
    "v1-clean/raw",
    "v2-clean/raw",
    "v3-clean/raw",
    "v3-schema2-pending/raw"
  ]
}
```

Implement a test-support repository that validates safe relative manifest paths, copies a named fixture, and creates only empty directories declared beneath that fixture. Its tracked-only simulation copies regular represented files and never copies ambient directories. Update every historical test to materialize through this contract. Add representation-only provenance metadata, never placeholder files within release-owned roots. Explicitly force-include the sidecar in the sdist and document the contributor contract.

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_historical_compatibility.py tests/test_project_automation.py -q
```

Expected: PASS, including backup, restore, pending-review, invalid-format, and provenance behavior from the file-only repository.

### Task 2: Close workspace lock descriptors on every path

**Files:**
- Modify: `tests/test_coordination.py`
- Modify: `src/bundlewalker/coordination.py`

**Step 1: Write the failing descriptor-ownership tests**

Add focused monkeypatch tests for lock-file `fstat` failure, `flock(LOCK_EX)` failure, and non-regular `fstat` metadata. Record the exact lock descriptor and assert it is closed exactly once; assert failed acquisition never issues `LOCK_UN`.

**Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_coordination.py -q
```

Expected: the three new tests FAIL because their opened descriptor remains valid and the recorded close count is zero.

**Step 3: Move descriptor ownership to an outer finally**

Initialize `descriptor` to `None` and `locked` to false before opening. Wrap creation fsync, metadata validation, acquisition, yielding, unlock, and close in one outer `try/finally`. Unlock only when acquisition completed; close whenever open completed. Preserve the public error messages and normal blocking lock semantics.

**Step 4: Verify GREEN**

Run:

```bash
uv run pytest tests/test_coordination.py -q
```

Expected: PASS; all failure descriptors are closed exactly once, no unowned unlock occurs, and the existing normal lock test still passes.

### Task 3: Record evidence, verify, and commit

**Files:**
- Create: `.superpowers/sdd/final-fix-report.md` (local ignored evidence)
- Modify only files listed above if verification exposes a scoped defect

**Step 1: Run focused verification**

Run historical, backup, project-automation, and coordination suites; run a Git-archive or equivalent file-only fixture proof; run Ruff format/check, Pyright, and diff checks.

**Step 2: Run the one allowed full suite and package gate**

Run exactly once:

```bash
uv run pytest -m 'not eval' -q
```

Then build exactly once, inspect the sdist for the sidecar/helper/fixtures, and run Twine:

```bash
uv build
uv run twine check dist/*
```

**Step 3: Record RED/GREEN and decisions**

Write `.superpowers/sdd/final-fix-report.md` with the archive reproduction, test-first failures, passing commands and counts, representation/provenance decisions, sdist contents, and confirmation that no push or release action occurred.

**Step 4: Review and commit**

Review `git diff`, `git diff --check`, and branch-range diff. Stage only the focused fix and create one intentional commit; do not push.
