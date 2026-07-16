# Synthesis Orphan Lint Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop deterministic lint from reporting create-only saved Syntheses as orphans while preserving `ORPHAN001` for every other concept type.

**Architecture:** Keep link resolution and inbound counting unchanged. Apply a narrow type-aware exclusion at the point where `_lint_orphans` converts zero inbound counts into findings, using the canonical `ConceptType.SYNTHESIS` value while leaving permissively consumed extension types covered.

**Tech Stack:** Python 3.13, Pydantic domain models, pytest, Ruff, Pyright, Typer CLI

---

### Task 1: Add the type-aware orphan rule

**Files:**
- Modify: `tests/okf/test_lint.py:330`
- Modify: `src/bundlewalker/okf/lint.py:15-24,398-412`

**Step 1: Write the failing regression test**

Add this test immediately after the existing orphan-warning test:

```python
def test_synthesis_without_inbound_links_is_not_an_orphan(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    _write_concept(
        root,
        "syntheses/terminal-answer",
        {
            "type": "Synthesis",
            "title": "Terminal answer",
            "description": "A saved cited answer.",
        },
        "\n# Terminal answer\n\n[Agents](/topics/agents.md)\n",
    )
    _write_concept(
        root,
        "topics/unreferenced",
        {
            "type": "Topic",
            "title": "Unreferenced",
            "description": "No inbound links.",
        },
        "\n# Unreferenced\n\n[Agents](/topics/agents.md)\n",
    )
    regenerate_indexes(root)

    findings = _findings_with_code(lint_bundle(root), "ORPHAN001")

    assert [(finding.path, finding.severity) for finding in findings] == [
        ("topics/unreferenced.md", Severity.WARNING)
    ]
```

The outgoing link makes both new concepts part of the graph. Their only relevant difference is
the canonical OKF type, proving that the expected exemption is type-specific.

**Step 2: Run the test to verify RED**

Run:

```bash
uv run pytest tests/okf/test_lint.py::test_synthesis_without_inbound_links_is_not_an_orphan -v
```

Expected: FAIL because the actual findings also contain
`syntheses/terminal-answer.md` with `ORPHAN001`.

**Step 3: Implement the minimal rule**

Add `ConceptType` to the imports from `bundlewalker.domain`, then narrow the list-comprehension
condition:

```python
        for document in documents
        if inbound_counts[document.concept_id] == 0
        and document.metadata.type != ConceptType.SYNTHESIS.value
```

Do not modify inbound counting, index handling, link validation, severities, or CLI behavior.

**Step 4: Run focused verification to verify GREEN**

Run:

```bash
uv run pytest tests/okf/test_lint.py::test_synthesis_without_inbound_links_is_not_an_orphan -v
uv run pytest tests/okf/test_lint.py tests/workflows/test_lint.py tests/cli/test_lint.py -q
```

Expected: the new regression test passes and all deterministic/semantic lint integration tests
remain green.

**Step 5: Run the complete offline release gate**

Run:

```bash
git diff --check
uv run pytest -m 'not eval' -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
```

Expected: the diff check is silent; all offline tests pass; Ruff reports every file formatted and
no lint errors; Pyright reports zero errors.

**Step 6: Verify the original pilot symptom**

Run from `/Volumes/OWC Envoy Ultra/Development/okf-knowledgebase`:

```bash
uv run --project "../BundleWalker" bundlewalker lint
```

Expected: `No lint findings.` The command must not modify the pilot workspace.

**Step 7: Commit the implementation**

```bash
git add src/bundlewalker/okf/lint.py tests/okf/test_lint.py
git commit -m "fix: allow terminal synthesis concepts"
```
