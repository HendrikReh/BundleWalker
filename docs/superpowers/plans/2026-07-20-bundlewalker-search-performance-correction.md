# BundleWalker Search Performance Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make application-level lexical search scan and validate a workspace exactly once while preserving its existing public contract.

**Architecture:** `LexicalRetriever.search()` remains the single owner of repository scanning, lexical scoring, filtering, ranking, and limiting. `WorkspaceApplication.search_concepts()` converts the ranked `ConceptSummary` objects already returned by the retriever directly into `ConceptSummaryResult` objects through one application-layer mapping helper, eliminating its redundant second scan.

**Tech Stack:** Python 3.13/3.14, Pydantic 2, pytest/pytest-asyncio, Ruff, Pyright, uv, GitHub Actions.

## Global Constraints

- Preserve full `OkfRepository.scan()` validation during the remaining search scan.
- Preserve lexical scoring weights, normalization, concept-type filtering, the 1–10 limit, and deterministic tie-breaking.
- Preserve title fallback to the final POSIX component of `concept_id`, description fallback to `""`, tuple tags, and `bundlewalker://concept/` URI quoting with `/` safe.
- Preserve application error translation and transaction recovery.
- Do not add a cache, index, parser shortcut, dependency, schema change, workspace migration, telemetry, or public API change.
- Do not optimize unrelated status, list, read, lint, mutation, or MCP startup paths.
- Do not change package version `0.4.0a2`, release metadata, or public capacity claims in this correction.
- macOS and Linux remain official on Python 3.13 and 3.14; Windows remains experimental.
- Do not add elapsed-time assertions to unit tests. The authoritative supported-platform matrix owns the 2-second Medium acceptance target.

---

## File Map

- Modify `tests/application/test_facade.py`: add the one-scan structural regression and explicit search-contract/error regressions.
- Modify `src/bundlewalker/application/facade.py`: convert retriever summaries directly into public results and centralize summary field mapping.
- Do not modify `src/bundlewalker/retrieval.py`: it already returns the complete ranked `ConceptSummary` values required by the facade.
- Do not modify `src/bundlewalker/okf/repository.py`: repository parsing and validation semantics remain unchanged.
- Do not update `docs/performance-and-capacity.md` or commit benchmark artifacts until a qualifying post-merge matrix exists.

---

### Task 1: Lock down the one-scan search contract

**Files:**

- Modify: `tests/application/test_facade.py:9-31`
- Modify: `tests/application/test_facade.py:300-306`
- Test: `tests/application/test_facade.py`

**Interfaces:**

- Consumes: `WorkspaceApplication.search_concepts(query: str, *, concept_type: str | None = None, limit: int = 10) -> ConceptSearchResult`.
- Consumes: `OkfRepository.scan() -> dict[str, OkfDocument]` for structural observation only.
- Produces: regression coverage requiring one scan and preserving `ConceptSummaryResult` serialization and error behavior.

- [ ] **Step 1: Import the repository type used by the structural spy**

Add this import beside the other OKF imports:

```python
from bundlewalker.okf.repository import OkfRepository
```

- [ ] **Step 2: Replace the narrow search test with a one-scan contract test**

Replace `test_search_concepts_returns_lexical_matches` with:

```python
async def test_search_concepts_scans_once_and_preserves_summary_contract(
    application: WorkspaceApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (application.workspace.wiki_dir / "entities" / "tool guide.md").write_text(
        render_document(
            OkfMetadata(type="Entity", tags=["tools"], timestamp=NOW),
            "# Tool Guide\n\nA guide for agent tools.\n",
        ),
        encoding="utf-8",
    )
    original_scan = OkfRepository.scan
    scan_calls = 0

    def counted_scan(repository: OkfRepository) -> dict[str, OkfDocument]:
        nonlocal scan_calls
        scan_calls += 1
        return original_scan(repository)

    monkeypatch.setattr(OkfRepository, "scan", counted_scan)

    result = await application.search_concepts("guide", concept_type="Entity", limit=1)

    assert scan_calls == 1
    assert [item.model_dump() for item in result.items] == [
        {
            "concept_id": "entities/tool guide",
            "type": "Entity",
            "title": "tool guide",
            "description": "",
            "tags": ("tools",),
            "resource_uri": "bundlewalker://concept/entities/tool%20guide",
        }
    ]
```

This single integration-style unit test proves the architectural requirement and the fields most
at risk when removing the second full-document lookup.

- [ ] **Step 3: Add no-match and error-contract regressions**

Add these tests immediately after the structural regression:

```python
async def test_search_concepts_returns_empty_result_for_no_match(
    application: WorkspaceApplication,
) -> None:
    result = await application.search_concepts("term-that-does-not-exist")

    assert result.items == ()


async def test_search_concepts_translates_invalid_limit(
    application: WorkspaceApplication,
) -> None:
    with pytest.raises(ApplicationError) as raised:
        await application.search_concepts("agents", limit=0)

    assert raised.value.code is ApplicationErrorCode.INVALID_INPUT
    assert raised.value.safe_message == "search limit must be between 1 and 10"


async def test_search_concepts_translates_repository_failure(
    application: WorkspaceApplication,
) -> None:
    (application.workspace.wiki_dir / "topics" / "broken.md").write_text(
        "not frontmatter\n",
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError) as raised:
        await application.search_concepts("agents")

    assert raised.value.code is ApplicationErrorCode.OKF_ERROR
    assert raised.value.safe_message == "knowledge bundle operation failed"
```

- [ ] **Step 4: Run the structural regression and verify the intended failure**

Run:

```bash
uv run pytest tests/application/test_facade.py::test_search_concepts_scans_once_and_preserves_summary_contract -q
```

Expected: FAIL at `assert scan_calls == 1` because the current facade calls `scan()` twice. The
serialized result assertion should not be the cause of failure.

- [ ] **Step 5: Run the non-structural contract regressions**

Run:

```bash
uv run pytest \
  tests/application/test_facade.py::test_search_concepts_returns_empty_result_for_no_match \
  tests/application/test_facade.py::test_search_concepts_translates_invalid_limit \
  tests/application/test_facade.py::test_search_concepts_translates_repository_failure \
  -q
```

Expected: PASS. These tests capture existing behavior before the performance correction.

---

### Task 2: Convert ranked repository summaries directly

**Files:**

- Modify: `src/bundlewalker/application/facade.py:39-45`
- Modify: `src/bundlewalker/application/facade.py:159-179`
- Modify: `src/bundlewalker/application/facade.py:365-374`
- Test: `tests/application/test_facade.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**

- Consumes: `ConceptSummary` with `concept_id`, `type`, optional `title`, optional `description`, and tuple `tags`.
- Produces: `_concept_summary_result(summary: ConceptSummary) -> ConceptSummaryResult`.
- Preserves: `_concept_summary(document: OkfDocument) -> ConceptSummaryResult` for list/read callers by delegating through `ConceptSummary.from_document(document)`.

- [ ] **Step 1: Import `ConceptSummary` into the application facade**

Change:

```python
from bundlewalker.okf.repository import OkfRepository
```

to:

```python
from bundlewalker.okf.repository import ConceptSummary, OkfRepository
```

- [ ] **Step 2: Remove the second repository scan from search**

Replace the search result construction:

```python
matches = LexicalRetriever(repository).search(query, concept_type, limit)
documents = repository.scan()
return ConceptSearchResult(
    items=tuple(_concept_summary(documents[item.concept_id]) for item in matches)
)
```

with:

```python
matches = LexicalRetriever(repository).search(query, concept_type, limit)
return ConceptSearchResult(items=tuple(_concept_summary_result(item) for item in matches))
```

- [ ] **Step 3: Centralize public summary field mapping**

Replace the existing `_concept_summary` implementation with:

```python
def _concept_summary(document: OkfDocument) -> ConceptSummaryResult:
    return _concept_summary_result(ConceptSummary.from_document(document))


def _concept_summary_result(summary: ConceptSummary) -> ConceptSummaryResult:
    return ConceptSummaryResult(
        concept_id=summary.concept_id,
        type=summary.type,
        title=summary.title or PurePosixPath(summary.concept_id).name,
        description=summary.description or "",
        tags=summary.tags,
        resource_uri=f"bundlewalker://concept/{quote(summary.concept_id, safe='/')}",
    )
```

This avoids duplicating fallback and URI rules between list/read and search while keeping the
application contract out of the repository layer.

- [ ] **Step 4: Run the structural regression and verify it turns green**

Run:

```bash
uv run pytest tests/application/test_facade.py::test_search_concepts_scans_once_and_preserves_summary_contract -q
```

Expected: PASS with exactly one `OkfRepository.scan()` call.

- [ ] **Step 5: Run all facade and retrieval tests**

Run:

```bash
uv run pytest tests/application/test_facade.py tests/test_retrieval.py -q
```

Expected: PASS. Existing ranking, filtering, normalization, tie-breaking, list, and read behavior
must remain green.

- [ ] **Step 6: Format and inspect the focused diff**

Run:

```bash
uv run ruff format tests/application/test_facade.py src/bundlewalker/application/facade.py
git diff --check
git diff -- tests/application/test_facade.py src/bundlewalker/application/facade.py
```

Expected: formatting succeeds, `git diff --check` emits no output, and the diff contains only the
planned tests, import, direct conversion, and mapping helper.

- [ ] **Step 7: Commit the test-driven correction**

Run:

```bash
git add tests/application/test_facade.py src/bundlewalker/application/facade.py
git commit -m "perf: avoid duplicate search scan"
```

Expected: one commit containing both the failing-first regression and its minimal implementation.

---

### Task 3: Verify the complete branch before review

**Files:**

- Verify only: repository-wide source, tests, benchmark smoke, and distribution metadata.
- Do not create or commit benchmark evidence from this task.

**Interfaces:**

- Consumes: the Task 2 commit.
- Produces: a clean branch that satisfies the same supported-platform checks enforced by CI.

- [ ] **Step 1: Verify the lockfile and all offline tests**

Run:

```bash
uv lock --check
uv run pytest -m 'not eval' -q
```

Expected: lockfile check and complete offline test suite PASS.

- [ ] **Step 2: Run the benchmark correctness smoke**

Run:

```bash
benchmark_check_dir="$(mktemp -d /tmp/bundlewalker-search-smoke.XXXXXX)"
uv run python -m benchmarks run \
  --profiles smoke \
  --correctness-only \
  --output "$benchmark_check_dir/evidence.json" \
  --work-root "$benchmark_check_dir/work"
```

Expected: command exits zero and prints the evidence path. This validates benchmark correctness,
not Medium timing.

- [ ] **Step 3: Run formatting, lint, and strict type checking**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
```

Expected: all three commands PASS with no formatting diff, lint finding, type error, or warning.

- [ ] **Step 4: Build and validate distribution metadata**

Run:

```bash
uv build --clear --no-sources
uv run twine check dist/*
```

Expected: wheel and source distribution build successfully and `twine check` reports `PASSED` for
both artifacts. Generated `dist/` content remains untracked.

- [ ] **Step 5: Verify the final branch scope**

Run:

```bash
git status --short --branch
git diff --check master...HEAD
git diff --stat master...HEAD
git log --oneline master..HEAD
```

Expected: source-controlled changes are limited to the approved design, this implementation plan,
the facade tests, and the facade implementation. The worktree is otherwise clean.

---

### Task 4: Run the authoritative post-merge acceptance matrix

**Files:**

- Read only: `.github/workflows/benchmarks.yml`
- Download to a temporary directory: four evidence JSON artifacts and the provisional matrix report.
- Do not update `docs/performance-and-capacity.md` in the correction branch.

**Interfaces:**

- Consumes: the exact reviewed correction after it is merged to `master`.
- Produces: supported-platform evidence determining whether the Medium B3 gate qualifies.

- [ ] **Step 1: Dispatch the workflow against updated `master`**

Run from a clean, synchronized `master` checkout:

```bash
git fetch origin master
gh workflow run benchmarks.yml --ref master
matrix_run_id="$(gh run list \
  --workflow benchmarks.yml \
  --branch master \
  --event workflow_dispatch \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')"
gh run watch "$matrix_run_id" --exit-status
```

Expected: all four measurement jobs and the summary job complete successfully. Workflow success
means evidence was produced; it does not by itself mean every timing target passed.

- [ ] **Step 2: Prove the workflow measured the exact merged commit**

Run:

```bash
test "$(gh run view "$matrix_run_id" --json headSha --jq .headSha)" = \
  "$(git rev-parse origin/master)"
```

Expected: exit zero. Reject evidence from any other source commit.

- [ ] **Step 3: Download the four exact evidence artifacts**

Run:

```bash
matrix_evidence_dir="$(mktemp -d /tmp/bundlewalker-b3-search.XXXXXX)"
gh run download "$matrix_run_id" --name benchmark-evidence-Linux-py3.13 --dir "$matrix_evidence_dir"
gh run download "$matrix_run_id" --name benchmark-evidence-Linux-py3.14 --dir "$matrix_evidence_dir"
gh run download "$matrix_run_id" --name benchmark-evidence-macOS-py3.13 --dir "$matrix_evidence_dir"
gh run download "$matrix_run_id" --name benchmark-evidence-macOS-py3.14 --dir "$matrix_evidence_dir"
find "$matrix_evidence_dir" -maxdepth 1 -type f -name '*.json' -print
```

Expected: exactly four JSON files, one for each supported OS/Python combination.

- [ ] **Step 4: Validate the Medium gate in every evidence record**

Run:

```bash
for evidence_file in "$matrix_evidence_dir"/*.json; do
  jq -e '
    .correctness_only == false and
    .git_commit != "" and
    ([.scenarios[] | select(.profile == "medium")] | length == 11) and
    ([.scenarios[] | select(.profile == "medium")] | all(.disposition == "pass"))
  ' "$evidence_file"
done
```

Expected: all four `jq` invocations print `true` and exit zero. This requires both present and
absent Medium search scenarios, plus every other Medium scenario, to pass their reference targets.

- [ ] **Step 5: Render and inspect the complete provisional matrix report**

Run:

```bash
uv run python -m benchmarks report \
  --evidence "$matrix_evidence_dir" \
  --output "$matrix_evidence_dir/report.md" \
  --provisional \
  --require-matrix
sed -n '1,260p' "$matrix_evidence_dir/report.md"
```

Expected: report generation exits zero, identifies all four environments and the exact run, and
lists Medium as a complete successful candidate measurement. The report remains provisional until
the separate Phase 2 evidence/documentation change is reviewed and merged.

- [ ] **Step 6: Decide the next B3 action from evidence, not estimates**

If every Step 4 check passes, prepare the separate Phase 2 evidence change that commits reviewed
JSON/checksums and updates the public capacity documentation. If any check fails, do not publish a
capacity claim; compare fresh profiles with the diagnostic run and return to design review before
expanding into parser or indexing work.

---

## Completion Criteria

- Search performs exactly one complete repository scan per successful application request.
- Public search fields, ordering, fallbacks, URI quoting, empty results, and error translation are unchanged.
- Focused and complete offline tests pass.
- Ruff formatting/lint, Pyright, lockfile, benchmark correctness smoke, build, and metadata validation pass.
- The correction is reviewed and merged before performance evidence is generated.
- The authoritative four-environment matrix shows every Medium scenario passing before B3 evidence publication begins.
