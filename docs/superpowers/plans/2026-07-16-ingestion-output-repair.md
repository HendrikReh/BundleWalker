# Ingestion Output Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route schema-valid but domain-invalid ingestion proposals through PydanticAI's existing repair retries before transaction preparation.

**Architecture:** Strengthen the ingestion instructions so first attempts describe canonical paths and citation pairs correctly. Register a per-run PydanticAI output validator that calls the existing `validate_change_set`, converts bounded `ChangeSetError` messages into `ModelRetry`, and leaves the workflow's final validation unchanged as defense in depth.

**Tech Stack:** Python 3.13, PydanticAI 2.10, Pydantic 2, pytest, Ruff, Pyright

## Global Constraints

- Reuse `validate_change_set` as the single domain-validation authority.
- Keep `prepare_ingestion`'s existing post-run validation unchanged.
- Do not normalize, strip, renumber, or silently repair invalid model output.
- Keep the existing retry count at two repair attempts after the initial output.
- Preserve generic sanitized `AgentRunError` behavior for exhausted retries and provider failures.
- Do not change global `ChangeSet`, `DraftConcept`, or `Citation` Pydantic schemas.
- Do not change query, semantic-lint, or synthesis behavior.
- Never print, stage, or commit `.env` or provider credentials.

## File Structure

- `src/bundlewalker/agents/prompts/ingest.md`: tells the model the exact canonical-path and citation-pairing contract before its first attempt.
- `src/bundlewalker/agents/ingest.py`: owns the ingestion agent and its per-run domain output validator.
- `tests/agents/test_ingest.py`: proves prompt coverage, deterministic repair retries, retry exhaustion, and exception sanitization.

---

### Task 1: Make the ingestion prompt state the deterministic contract

**Files:**
- Modify: `tests/agents/test_ingest.py:45-64`
- Modify: `src/bundlewalker/agents/prompts/ingest.md:10-21`

**Interfaces:**
- Consumes: `create_ingestion_agent(TestModel())` and its loaded instruction text.
- Produces: Explicit first-attempt guidance for extensionless canonical paths and one-to-one citation markers.

- [ ] **Step 1: Add failing prompt-contract assertions**

Extend `test_ingestion_agent_has_the_strict_read_only_contract` after its existing numbered-line
assertion with these exact checks:

```python
    assert "extensionless canonical concept id" in instructions
    assert "never include `.md`" in instructions
    assert "exactly one structured citation" in instructions
    assert "contiguous starting at `1`" in instructions
    assert "do not add a `# citations` section" in instructions
```

- [ ] **Step 2: Run the prompt-contract test and verify it fails**

Run:

```bash
uv run pytest tests/agents/test_ingest.py::test_ingestion_agent_has_the_strict_read_only_contract -v
```

Expected: FAIL on the first new assertion because the current prompt does not describe an
"extensionless canonical concept ID".

- [ ] **Step 3: Add the exact path and citation rules to the prompt**

Replace the existing proposal bullet list in `src/bundlewalker/agents/prompts/ingest.md` with:

```markdown
Your proposal must:

- contain exactly one Source draft whose path equals `numbered_source.concept_id` exactly;
- use an extensionless canonical concept ID for every draft path, matching
  `sources|topics|entities/<lowercase-ascii-slug>`, and never include `.md`;
- contain only Source, Topic, and Entity drafts, and never a Synthesis draft;
- preserve uncertainty instead of overstating a claim;
- surface contradictions explicitly instead of silently choosing a winner;
- support source-derived claims with structured citations to numbered source lines;
- give every `[n]` marker in a draft body exactly one structured citation numbered `n`, and give
  every structured citation a matching body marker;
- require citation numbers to be contiguous starting at `1` within each draft;
- do not add a `# Citations` section; deterministic application code renders it;
- use only the read-only list, search, and read tools to inspect existing knowledge;
- use `create` for new concepts and `replace` with the read base digest for existing ones.
```

Leave the untrusted-data framing and the final forbidden-output paragraph unchanged.

- [ ] **Step 4: Run the prompt-contract test and verify it passes**

Run:

```bash
uv run pytest tests/agents/test_ingest.py::test_ingestion_agent_has_the_strict_read_only_contract -v
```

Expected: PASS.

- [ ] **Step 5: Commit the prompt contract**

Run:

```bash
git add src/bundlewalker/agents/prompts/ingest.md tests/agents/test_ingest.py
git diff --cached --check
git commit -m "fix: clarify ingestion output contract"
```

Expected: the staged diff check has no output and the commit succeeds with only the prompt and its
contract test.

---

### Task 2: Retry domain-invalid ingestion output inside PydanticAI

**Files:**
- Modify: `tests/agents/test_ingest.py:19-31,190-243`
- Modify: `src/bundlewalker/agents/ingest.py:6-12,34-66`

**Interfaces:**
- Consumes: `validate_change_set(change_set, context)`, `ChangeValidationContext`,
  `AgentDependencies.read_ids`, `RawSource`, and PydanticAI `ModelRetry`.
- Produces: `run_ingestion_agent(...) -> tuple[ChangeSet, frozenset[str]]`, returning only output
  that passed ingestion-domain validation within the configured retry budget.

- [ ] **Step 1: Add deterministic repair and exhaustion tests**

Add `Citation` to the existing import list from `bundlewalker.domain`:

```python
from bundlewalker.domain import (
    MAX_TITLE_CHARACTERS,
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
)
```

Add these tests before `test_ingestion_runner_drops_sensitive_provider_exception_chains`:

```python
@pytest.mark.parametrize("invalid_kind", ["markdown-suffix", "citation-mismatch"])
async def test_ingestion_runner_retries_domain_invalid_output(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    dependencies = _dependencies(tmp_path)
    input_path = tmp_path / "notes.txt"
    input_path.write_text("Evidence.\n", encoding="utf-8")
    source = load_raw_source(input_path, discover_workspace(dependencies.repository.root))
    citation = Citation(
        number=1,
        concept_id=source.concept_id,
        start_line=1,
        end_line=1,
    )
    valid_draft = DraftConcept(
        operation=ChangeOperation.CREATE,
        path=source.concept_id,
        type=ConceptType.SOURCE,
        title="Notes",
        description="Source evidence.",
        body="# Notes\n\nEvidence [1].\n",
        citations=[citation],
    )
    if invalid_kind == "markdown-suffix":
        invalid_draft = valid_draft.model_copy(
            update={"path": f"{source.concept_id}.md"}
        )
    else:
        invalid_draft = valid_draft.model_copy(update={"body": "# Notes\n\nEvidence.\n"})
    invalid_change_set = ChangeSet(
        summary="Invalid first proposal.",
        source_sha256=source.sha256,
        drafts=[invalid_draft],
    )
    valid_change_set = ChangeSet(
        summary="Repaired proposal.",
        source_sha256=source.sha256,
        drafts=[valid_draft],
    )
    responses = (invalid_change_set, valid_change_set)
    calls = 0

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        response = responses[min(calls, len(responses) - 1)]
        calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=response.model_dump(mode="json"),
                )
            ]
        )

    output, read_ids = await run_ingestion_agent(
        FunctionModel(respond), dependencies, source
    )

    assert calls == 2
    assert output == valid_change_set
    assert read_ids == frozenset()


async def test_ingestion_runner_sanitizes_exhausted_domain_retries(tmp_path: Path) -> None:
    dependencies = _dependencies(tmp_path)
    input_path = tmp_path / "notes.txt"
    input_path.write_text("Evidence.\n", encoding="utf-8")
    source = load_raw_source(input_path, discover_workspace(dependencies.repository.root))
    invalid_change_set = ChangeSet(
        summary="Invalid proposal.",
        source_sha256=source.sha256,
        drafts=[
            DraftConcept(
                operation=ChangeOperation.CREATE,
                path=f"{source.concept_id}.md",
                type=ConceptType.SOURCE,
                title="Notes",
                description="Source evidence.",
                body="# Notes\n",
            )
        ],
    )
    calls = 0

    def respond(_messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=invalid_change_set.model_dump(mode="json"),
                )
            ]
        )

    with pytest.raises(AgentRunError, match="could not produce a proposal") as caught:
        await run_ingestion_agent(FunctionModel(respond), dependencies, source)

    assert calls == 3
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
```

- [ ] **Step 2: Run the new tests and verify the missing retry behavior**

Run:

```bash
uv run pytest tests/agents/test_ingest.py -k 'domain_invalid or exhausted_domain' -v
```

Expected: three failures. Both parametrized repair cases report `calls == 1`, and the exhaustion
case reports that `AgentRunError` was not raised.

- [ ] **Step 3: Register the per-run domain output validator**

Update the imports at the top of `src/bundlewalker/agents/ingest.py` to include the retry types,
authoritative validator, validation context, and domain error:

```python
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import KnownModelName, Model

from bundlewalker.agents.common import AgentDependencies, frame_untrusted_data, read_tools
from bundlewalker.changes import ChangeValidationContext, validate_change_set
from bundlewalker.domain import ChangeSet
from bundlewalker.errors import AgentRunError, ChangeSetError
from bundlewalker.workspace import RawSource
```

Replace the final prompt/run block of `run_ingestion_agent`, starting with
`prompt = frame_untrusted_data(payload)`, with:

```python
    prompt = frame_untrusted_data(payload)
    agent = create_ingestion_agent(model)

    @agent.output_validator
    def validate_ingestion_output(
        ctx: RunContext[AgentDependencies],
        output: ChangeSet,
    ) -> ChangeSet:
        context = ChangeValidationContext(
            mode="ingest",
            repository=ctx.deps.repository,
            readable_concepts=frozenset(ctx.deps.read_ids),
            source=source,
        )
        try:
            validate_change_set(output, context)
        except ChangeSetError as exc:
            raise ModelRetry(str(exc)) from None
        return output

    try:
        result = await agent.run(prompt, deps=dependencies)
    except Exception:
        pass
    else:
        return result.output, frozenset(dependencies.read_ids)
    raise AgentRunError("ingestion agent could not produce a proposal") from None
```

Do not remove or alter the later `validate_change_set` call in
`src/bundlewalker/workflows/ingest.py`.

- [ ] **Step 4: Run ingestion agent and workflow tests**

Run:

```bash
uv run pytest tests/agents/test_ingest.py tests/workflows/test_ingest.py -v
```

Expected: PASS, including both repair cases, the three-call exhaustion case, provider-exception
sanitization, and workflow defense-in-depth tests.

- [ ] **Step 5: Run the complete offline verification suite**

Run:

```bash
uv run pytest -m 'not eval' -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
```

Expected: 296 non-eval tests pass; Ruff reports all files formatted and no lint errors; Pyright
reports zero errors.

- [ ] **Step 6: Run the live GPT-5.6 Luna quality evaluation**

Load the ignored local environment without printing any values, then run the opt-in evaluation:

```bash
set -a
source .env
set +a
uv run pytest -m eval -v
```

Expected: all four cases pass with `openai:gpt-5.6-luna`, including the three ingestion cases that
previously returned invalid canonical paths or citation pairs. The command uses paid network
inference and must not print or commit `.env`.

- [ ] **Step 7: Commit the repair loop**

Run:

```bash
git add src/bundlewalker/agents/ingest.py tests/agents/test_ingest.py
git diff --cached --check
git diff --cached --name-only
git commit -m "fix: retry invalid ingestion proposals"
```

Expected: staged names contain only `src/bundlewalker/agents/ingest.py` and
`tests/agents/test_ingest.py`; the staged diff check has no output; the commit succeeds.
