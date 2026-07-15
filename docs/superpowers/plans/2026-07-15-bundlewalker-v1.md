# BundleWalker v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, provider-neutral `bundlewalker` CLI that initializes, ingests, queries, saves, and lints a review-first OKF personal knowledge workspace.

**Architecture:** The filesystem-native OKF wiki is the durable artifact. PydanticAI agents receive only bounded read tools and return typed proposals; deterministic services own source identity, rendering, citations, prospective linting, diffs, confirmation, crash recovery, and durable writes.

**Tech Stack:** Python 3.13+, Pydantic 2, PydanticAI 2.10+, Typer, PyYAML, markdown-it-py, pytest, pytest-asyncio, Ruff, and Pyright.

## Global Constraints

- Python requirement remains `>=3.13`; use a `src/` package layout and `uv` for dependency locking and commands.
- Accept only regular UTF-8 `.md` and `.txt` source files, with a configurable default maximum of exactly 100,000 Unicode characters.
- Produce only `Source`, `Topic`, `Entity`, and `Synthesis` concepts; consume unknown OKF types and extra frontmatter permissively.
- Every model-derived live `raw/` or `wiki/` mutation requires a complete diff and interactive confirmation.
- Agents may call only `list_concepts`, `search_concepts`, and `read_concept`; they never receive filesystem, shell, network, rename, delete, or write tools.
- `--model` overrides `BUNDLEWALKER_MODEL`; do not persist model identifiers or credentials in a workspace.
- `lint` is deterministic and offline by default; `lint --semantic` is opt-in, advisory, read-only, and does not affect the exit code determined by deterministic findings.
- Default tests must use fake/function models and require no network, credentials, or paid inference.
- V1 has no deletions, renames, batch ingestion, chunking, embeddings, vector database, SQLite catalog, Git automation, web UI, or MCP server.
- Follow the accepted design at `docs/superpowers/specs/2026-07-15-bundlewalker-v1-design.md` whenever a task-level detail is not repeated here.

---

## File map

### Project and package entry points

- `.gitignore`: exclude Python artifacts, `.venv/`, `.bundlewalker/`, `.worktrees/`, visual-companion state, and macOS metadata.
- `.python-version`: pin the local uv interpreter selector to Python 3.13.
- `README.md`: retain the scaffold overview in Task 1 and replace it with complete user documentation in Task 12.
- `pyproject.toml`: runtime/dev dependencies, package discovery, CLI entry point, pytest, Ruff, and Pyright configuration.
- `src/bundlewalker/__init__.py`: package version.
- `src/bundlewalker/__main__.py`: `python -m bundlewalker` entry point.
- `src/bundlewalker/cli.py`: Typer commands, confirmation, output, and exception-to-exit-code mapping.

### Deterministic domain and OKF core

- `src/bundlewalker/errors.py`: typed application exceptions.
- `src/bundlewalker/domain.py`: Pydantic boundary models and enums shared across workflows.
- `src/bundlewalker/okf/documents.py`: frontmatter codec, Markdown link extraction, safe concept paths, and document digests.
- `src/bundlewalker/okf/repository.py`: read-only parsed bundle view and concept summaries.
- `src/bundlewalker/okf/derived.py`: generated indexes, log entries, and tree diffs.
- `src/bundlewalker/okf/lint.py`: deterministic conformance and health findings.
- `src/bundlewalker/retrieval.py`: stable weighted lexical ranking.

### Workspace, proposals, and persistence

- `src/bundlewalker/workspace.py`: configuration, discovery, initialization, source loading, and stable source identity.
- `src/bundlewalker/changes.py`: ChangeSet validation, citation validation, rendering, and prospective-wiki construction.
- `src/bundlewalker/transactions.py`: journaled staging, commit, rollback, discard, and recovery.

### PydanticAI boundary and workflows

- `src/bundlewalker/agents/common.py`: dependencies, read tracking, model resolution, and shared read-only tools.
- `src/bundlewalker/agents/ingest.py`: IngestionAgent prompt and typed runner.
- `src/bundlewalker/agents/query.py`: QueryAgent prompt and typed runner.
- `src/bundlewalker/agents/semantic_lint.py`: SemanticLintAgent prompt and typed runner.
- `src/bundlewalker/agents/prompts/*.md`: versioned role instructions.
- `src/bundlewalker/workflows/ingest.py`: source-to-reviewed-transaction orchestration.
- `src/bundlewalker/workflows/ask.py`: cited query and optional deterministic Synthesis proposal.
- `src/bundlewalker/workflows/lint.py`: deterministic and optional semantic lint orchestration.

### Tests, fixtures, and documentation

- `tests/`: unit, agent-contract, transaction fault-injection, CLI integration, and acceptance tests mirroring package modules.
- `tests/fixtures/`: conformant and malformed OKF bundles plus fixed source documents.
- `evals/cases.yaml`: opt-in quality cases.
- `tests/evals/test_model_quality.py`: explicitly gated live-model evaluations.
- `README.md`: installation, configuration, command examples, workspace layout, safety model, and scope.

---

### Task 1: Package tooling and typed domain contracts

**Files:**
- Modify: `.gitignore`
- Modify: `.python-version`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Delete: `main.py`
- Create: `src/bundlewalker/__init__.py`
- Create: `src/bundlewalker/errors.py`
- Create: `src/bundlewalker/domain.py`
- Create: `tests/test_domain.py`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: no application interfaces.
- Produces: `ConceptType`, `ChangeOperation`, `FindingOrigin`, `Severity`, `OkfMetadata`, `OkfDocument`, `Citation`, `DraftConcept`, `ChangeSet`, `CitedAnswer`, `LintFinding`, and the typed exception hierarchy.

- [ ] **Step 1: Write failing domain-model tests**

Create `tests/test_domain.py` with focused tests for permissive metadata, strict producer types, citation-span pairing, operation/base-digest consistency, and duplicate ChangeSet paths:

```python
import pytest
from pydantic import ValidationError

from bundlewalker.domain import (
    ChangeOperation,
    ChangeSet,
    Citation,
    ConceptType,
    DraftConcept,
    OkfMetadata,
)


def draft(path: str, *, operation: ChangeOperation, base_digest: str | None = None) -> DraftConcept:
    return DraftConcept(
        operation=operation,
        path=path,
        type=ConceptType.TOPIC,
        title="Typed agents",
        description="How typed agents constrain knowledge proposals.",
        tags=["agents"],
        body="# Notes\n\nTyped outputs reduce ambiguity.",
        citations=[],
        base_digest=base_digest,
    )


def test_okf_metadata_preserves_unknown_fields() -> None:
    metadata = OkfMetadata.model_validate({"type": "Unknown Type", "owner": "Hendrik"})
    assert metadata.type == "Unknown Type"
    assert metadata.model_extra == {"owner": "Hendrik"}


def test_citation_requires_both_line_bounds() -> None:
    with pytest.raises(ValidationError):
        Citation(number=1, concept_id="sources/a", start_line=3)


def test_create_rejects_base_digest() -> None:
    with pytest.raises(ValidationError):
        draft("topics/agents", operation=ChangeOperation.CREATE, base_digest="a" * 64)


def test_replace_requires_base_digest() -> None:
    with pytest.raises(ValidationError):
        draft("topics/agents", operation=ChangeOperation.REPLACE)


def test_changeset_rejects_duplicate_paths() -> None:
    item = draft("topics/agents", operation=ChangeOperation.CREATE)
    with pytest.raises(ValidationError):
        ChangeSet(summary="Duplicate", source_sha256=None, drafts=[item, item])
```

- [ ] **Step 2: Run the tests and verify the missing-package failure**

Run: `uv run pytest tests/test_domain.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'bundlewalker'`.

- [ ] **Step 3: Configure the package and dependencies**

Replace `pyproject.toml` with project metadata containing these exact dependency groups and entry point:

```toml
[project]
name = "bundlewalker"
version = "0.1.0"
description = "Build a review-first personal knowledge wiki with OKF and PydanticAI."
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "markdown-it-py>=4.0.0",
    "pydantic-ai>=2.10.0",
    "pyyaml>=6.0.0",
    "typer>=0.16.0",
]

[project.scripts]
bundlewalker = "bundlewalker.cli:app"

[dependency-groups]
dev = [
    "pyright>=1.1.400",
    "pytest>=8.4.0",
    "pytest-asyncio>=1.1.0",
    "ruff>=0.12.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
addopts = "-q"
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.13"
typeCheckingMode = "strict"
```

Create `.gitignore` with:

```gitignore
.DS_Store
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.superpowers/
.bundlewalker/
.worktrees/
*.py[cod]
```

Set `.python-version` to `3.13`. Retain the existing README content as the committed early-project overview; Task 12 will replace it with complete user documentation. Delete the obsolete top-level `main.py`, create `src/bundlewalker/__init__.py` with `__version__ = "0.1.0"`, and run `uv lock`.

- [ ] **Step 4: Implement the exception and domain-model public API**

Create `src/bundlewalker/errors.py` with `BundleWalkerError(exit_code=1)`, `UsageError(exit_code=2)`, `ConfigurationError`, `WorkspaceError`, `OkfError`, `ChangeSetError`, `AgentRunError`, and `TransactionError`.

Create `src/bundlewalker/domain.py` using `StrEnum`, `ConfigDict(extra="allow")` for `OkfMetadata`, `ConfigDict(extra="forbid")` for producer models, and model validators equivalent to:

```python
class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1)
    concept_id: str = Field(min_length=1)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_span(self) -> "Citation":
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("citation line bounds must be supplied together")
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError("citation end_line must not precede start_line")
        return self


class DraftConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: ChangeOperation
    path: str = Field(min_length=1)
    type: ConceptType
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    body: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)
    base_digest: str | None = None

    @model_validator(mode="after")
    def validate_operation_digest(self) -> "DraftConcept":
        if self.operation is ChangeOperation.CREATE and self.base_digest is not None:
            raise ValueError("create operations cannot include base_digest")
        if self.operation is ChangeOperation.REPLACE and self.base_digest is None:
            raise ValueError("replace operations require base_digest")
        return self
```

`OkfDocument` must contain `concept_id`, `path: Path`, `metadata`, `body`, `links: tuple[str, ...]`, and a 64-character `digest`. `ChangeSet` must reject duplicate paths. `CitedAnswer` contains `title`, `body`, and citations. `LintFinding` contains origin, severity, code, message, optional path, evidence paths, and optional remediation.

- [ ] **Step 5: Run domain tests and static checks**

Run: `uv run pytest tests/test_domain.py -v && uv run ruff check src tests && uv run pyright`

Expected: all five tests pass; Ruff and Pyright report no errors.

- [ ] **Step 6: Commit the domain foundation**

```bash
git add .gitignore .python-version README.md pyproject.toml uv.lock src/bundlewalker tests/test_domain.py
git commit -m "feat: add typed BundleWalker domain"
```

---

### Task 2: OKF document codec, links, and safe paths

**Files:**
- Create: `src/bundlewalker/okf/__init__.py`
- Create: `src/bundlewalker/okf/documents.py`
- Create: `tests/okf/test_documents.py`

**Interfaces:**
- Consumes: `OkfDocument`, `OkfMetadata`, and `OkfError` from Task 1.
- Produces: `parse_document(path, root)`, `render_document(metadata, body)`, `extract_links(markdown)`, `concept_path(root, concept_id)`, and `document_digest(content)`.

- [ ] **Step 1: Write failing codec and path-safety tests**

Create tests that assert a frontmatter/body round trip preserves `owner`, Markdown links are extracted from inline tokens, `index.md` cannot be treated as a concept, `../escape` is rejected, and symlinks escaping the bundle are rejected. The round-trip test must include:

```python
def test_round_trip_preserves_extra_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "wiki"
    path = root / "topics" / "agents.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\ntype: Topic\ntitle: Agents\nowner: Hendrik\n---\n\n# Agents\n\n"
        "See [Pydantic](/entities/pydantic.md).\n",
        encoding="utf-8",
    )
    parsed = parse_document(path, root)
    rendered = render_document(parsed.metadata, parsed.body)
    reparsed_path = root / "topics" / "round-trip.md"
    reparsed_path.write_text(rendered, encoding="utf-8")
    reparsed = parse_document(reparsed_path, root)
    assert reparsed.metadata.model_extra == {"owner": "Hendrik"}
    assert reparsed.links == ("/entities/pydantic.md",)
```

- [ ] **Step 2: Verify the new tests fail**

Run: `uv run pytest tests/okf/test_documents.py -v`

Expected: collection fails because `bundlewalker.okf.documents` does not exist.

- [ ] **Step 3: Implement the codec and safe path resolver**

Implement strict `---` frontmatter splitting, `yaml.safe_load`, UTF-8 reads, `OkfMetadata.model_validate`, deterministic `yaml.safe_dump(sort_keys=False, allow_unicode=True)`, and recursive markdown-it token walking. Use this path contract:

```python
RESERVED_NAMES = frozenset({"index.md", "log.md"})


def concept_path(root: Path, concept_id: str) -> Path:
    relative = PurePosixPath(f"{concept_id}.md")
    if relative.is_absolute() or ".." in relative.parts:
        raise OkfError(f"unsafe concept id: {concept_id}")
    if relative.name.casefold() in RESERVED_NAMES:
        raise OkfError(f"reserved concept path: {concept_id}")
    candidate = root.joinpath(*relative.parts)
    resolved_parent = candidate.parent.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if not resolved_parent.is_relative_to(resolved_root):
        raise OkfError(f"concept escapes bundle: {concept_id}")
    return candidate
```

`parse_document` must reject paths outside `root`, missing or non-mapping frontmatter, empty `type`, reserved filenames, and malformed UTF-8. Compute the digest over exact UTF-8 file bytes.

- [ ] **Step 4: Run codec tests and all deterministic checks**

Run: `uv run pytest tests/okf/test_documents.py -v && uv run ruff check src tests && uv run pyright`

Expected: codec/path tests pass with no lint or type errors.

- [ ] **Step 5: Commit the OKF codec**

```bash
git add src/bundlewalker/okf tests/okf/test_documents.py
git commit -m "feat: parse and render OKF documents"
```

---

### Task 3: Repository, generated navigation, log, and lexical retrieval

**Files:**
- Create: `src/bundlewalker/okf/repository.py`
- Create: `src/bundlewalker/okf/derived.py`
- Create: `src/bundlewalker/retrieval.py`
- Create: `tests/okf/test_repository.py`
- Create: `tests/okf/test_derived.py`
- Create: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: Task 2 document codec.
- Produces: `ConceptSummary`, `OkfRepository.scan/get/list`, `regenerate_indexes`, `prepend_log_entry`, `tree_diff`, and `LexicalRetriever.search`.

- [ ] **Step 1: Write failing repository and retrieval tests**

Build a three-concept fixture in `tmp_path` and assert scanning ignores reserved files, `list("topics")` returns only immediate concepts, missing IDs raise `OkfError`, title hits outrank body-only hits, and equal scores use concept-ID ordering.

```python
def test_title_match_outranks_body_match(repository: OkfRepository) -> None:
    retriever = LexicalRetriever(repository)
    results = retriever.search("typed agents", concept_type=None, limit=10)
    assert [item.concept_id for item in results[:2]] == [
        "topics/typed-agents",
        "topics/python",
    ]
```

- [ ] **Step 2: Write failing derived-file tests**

Assert `regenerate_indexes` creates root/category indexes without frontmatter, includes title and description, uses stable concept-ID order, lists subdirectories separately, and `prepend_log_entry` creates ISO-date headings newest first. Assert `tree_diff(old, new)` returns unified filenames rooted at `wiki/` and stable ordering.

- [ ] **Step 3: Verify all Task 3 tests fail**

Run: `uv run pytest tests/okf/test_repository.py tests/okf/test_derived.py tests/test_retrieval.py -v`

Expected: import failures for the three new modules.

- [ ] **Step 4: Implement repository and derived projections**

`OkfRepository.scan()` must return a dict sorted by concept ID and reject case-folded path collisions. `ConceptSummary` contains ID, type, title, description, and tags. `regenerate_indexes` must rewrite every existing directory index from parsed immediate children and subdirectories. Use an injectable `date: datetime` for log generation.

Implement `tree_diff` using `difflib.unified_diff` over the union of relative text-file paths, with `/dev/null` for creates and deletes. Although v1 ChangeSets cannot delete concepts, the diff helper must show files removed by index regeneration bugs during tests.

- [ ] **Step 5: Implement stable weighted retrieval**

Normalize with Unicode case-folding and whitespace tokenization. Score exact phrase matches before token matches using weights `title=16`, `description=8`, `tags/path=4`, and `body=1`. Return at most `limit` summaries, sort by descending score then concept ID, and reject limits outside `1..10`.

- [ ] **Step 6: Run Task 3 tests and commit**

Run: `uv run pytest tests/okf/test_repository.py tests/okf/test_derived.py tests/test_retrieval.py -v && uv run ruff check src tests && uv run pyright`

Expected: all tests and checks pass.

```bash
git add src/bundlewalker/okf src/bundlewalker/retrieval.py tests
git commit -m "feat: add OKF repository and retrieval"
```

---

### Task 4: Deterministic OKF and workspace linter

**Files:**
- Create: `src/bundlewalker/okf/lint.py`
- Create: `tests/okf/test_lint.py`
- Create: `tests/fixtures/wiki-valid/index.md`
- Create: `tests/fixtures/wiki-valid/log.md`
- Create: `tests/fixtures/wiki-valid/topics/agents.md`

**Interfaces:**
- Consumes: repository, links, derived files, and `LintFinding`.
- Produces: `lint_bundle(wiki_root, workspace_root=None) -> list[LintFinding]` and `has_errors(findings) -> bool`.

- [ ] **Step 1: Write failing conformance and health tests**

Create parameterized tests for missing frontmatter, empty type, malformed reserved indexes, broken internal links as warnings, case collisions as errors, stale/missing index entries as errors, invalid log dates as errors, and orphan concepts as warnings. Use stable finding codes such as `OKF001`, `LINK001`, `INDEX001`, `LOG001`, and `ORPHAN001`.

- [ ] **Step 2: Verify lint tests fail**

Run: `uv run pytest tests/okf/test_lint.py -v`

Expected: import failure for `bundlewalker.okf.lint`.

- [ ] **Step 3: Implement deterministic lint passes**

Each pass returns findings instead of raising so one run reports all detectable problems. Catch individual parse errors as `OKF001`, compare generated index text in memory without writing, resolve bundle-root links beginning `/`, and compute inbound-link counts for orphan warnings. Sort findings by severity (`error`, `warning`, `info`), then code, path, and message.

When `workspace_root` is supplied, additionally validate Source extension fields, resolve workspace-relative `raw_path`, compare `source_sha256` to raw bytes, validate citation marker/reference agreement, and verify cited line ranges against raw-file line counts.

- [ ] **Step 4: Run linter tests and commit**

Run: `uv run pytest tests/okf/test_lint.py -v && uv run pytest -q && uv run ruff check src tests && uv run pyright`

Expected: the full deterministic suite passes.

```bash
git add src/bundlewalker/okf/lint.py tests/okf/test_lint.py tests/fixtures
git commit -m "feat: lint OKF knowledge bundles"
```

---

### Task 5: Workspace configuration, source identity, initialization, and CLI shell

**Files:**
- Create: `src/bundlewalker/workspace.py`
- Create: `src/bundlewalker/cli.py`
- Create: `src/bundlewalker/__main__.py`
- Create: `tests/test_workspace.py`
- Create: `tests/cli/test_init.py`

**Interfaces:**
- Consumes: derived files and deterministic linter.
- Produces: `WorkspaceConfig`, `Workspace`, `RawSource`, `discover_workspace`, `initialize_workspace`, `load_raw_source`, `stable_source_paths`, and Typer `app` with `init`.

- [ ] **Step 1: Write failing workspace and source tests**

Test upward discovery, exact default TOML values, strict `.md`/`.txt` regular-file checks, strict UTF-8, 100,000-character rejection, exact-byte SHA-256 identity, duplicate full-digest detection, and collision-safe digest prefixes.

- [ ] **Step 2: Write failing `init` CLI tests**

Using `typer.testing.CliRunner`, assert `init PATH` creates `bundlewalker.toml`, `conventions.md`, `raw/`, all four concept directories, indexes, and a valid log; deterministic lint returns no errors; a non-empty target exits `2`; and failed initialization removes only paths created by the command.

- [ ] **Step 3: Verify Task 5 tests fail**

Run: `uv run pytest tests/test_workspace.py tests/cli/test_init.py -v`

Expected: import failures for workspace and CLI modules.

- [ ] **Step 4: Implement workspace configuration and source loading**

Use `tomllib` for reads and deterministic string formatting for the four config keys. `discover_workspace` walks parents until `bundlewalker.toml` is found. `load_raw_source` reads bytes first, hashes exact bytes, decodes strict UTF-8, checks character count, counts `splitlines()`, derives an ASCII slug from the filename, and returns:

```python
@dataclass(frozen=True, slots=True)
class RawSource:
    input_path: Path
    content: bytes
    text: str
    sha256: str
    line_count: int
    extension: Literal[".md", ".txt"]
    slug: str
    stored_relative_path: Path
    concept_id: str
```

`stored_relative_path` is `raw/<unique-prefix>-<slug><extension>` and `concept_id` is `sources/<unique-prefix>-<slug>`.

Expose the exact signatures `stable_source_paths(workspace: Workspace, sha256: str, slug: str, extension: Literal[".md", ".txt"]) -> tuple[Path, str]` and `load_raw_source(path: Path, workspace: Workspace) -> RawSource`. The first tuple item is workspace-relative raw path; the second is concept ID.

- [ ] **Step 5: Implement initialization and CLI exception mapping**

`initialize_workspace` creates defaults, calls `regenerate_indexes`, writes one `Initialization` log entry, and asserts `has_errors(lint_bundle(workspace.wiki_dir, workspace.root))` is false before success. Add a Typer callback that discovers the workspace for non-init commands later. Map `BundleWalkerError.exit_code`, render concise messages, hide tracebacks, and convert Ctrl-C during a future confirmation to exit `0`.

- [ ] **Step 6: Run Task 5 tests and exercise the command**

Run:

```bash
uv run pytest tests/test_workspace.py tests/cli/test_init.py -v
tmpdir=$(mktemp -d)
uv run bundlewalker init "$tmpdir/knowledge"
test -f "$tmpdir/knowledge/wiki/index.md"
```

Expected: tests pass, CLI prints the initialized path, and the index assertion succeeds.

- [ ] **Step 7: Commit the first working CLI**

```bash
git add src/bundlewalker tests pyproject.toml uv.lock
git commit -m "feat: initialize BundleWalker workspaces"
```

---

### Task 6: ChangeSet validation and prospective rendering

**Files:**
- Create: `src/bundlewalker/changes.py`
- Create: `tests/test_changes.py`

**Interfaces:**
- Consumes: `ChangeSet`, `RawSource`, repository, codec, derived files, and linter.
- Produces: `ChangeValidationContext`, `validate_change_set`, `render_draft`, and `build_prospective_wiki`.

- [ ] **Step 1: Write failing validation tests**

Cover path/category mismatch, reserved path, create-over-existing, replace-over-missing, stale base digest, ingestion without exactly one matching Source draft, ingestion creating Synthesis, query-save creating a non-Synthesis, missing/extra citation markers, nonexistent concepts, unread query citations, and source spans outside `1..line_count`.

- [ ] **Step 2: Write failing prospective-render tests**

Assert a replacement preserves unknown existing frontmatter, overwrites known fields, renders normalized numbered citations, updates timestamps with an injected clock, regenerates indexes, adds exactly one log entry, and refuses a prospective wiki with deterministic lint errors.

- [ ] **Step 3: Verify Task 6 tests fail**

Run: `uv run pytest tests/test_changes.py -v`

Expected: import failure for `bundlewalker.changes`.

- [ ] **Step 4: Implement context-aware ChangeSet validation**

Use this exact context boundary:

```python
@dataclass(frozen=True, slots=True)
class ChangeValidationContext:
    mode: Literal["ingest", "synthesis"]
    repository: OkfRepository
    readable_concepts: frozenset[str]
    source: RawSource | None = None
```

Normalize agent paths by removing an optional `.md` suffix, then use `concept_path`. Require types to reside in their plural category. For ingestion, require one Source draft whose path equals `source.concept_id`; allow only Source/Topic/Entity. For synthesis, require one create-only Synthesis draft and no source. Compare citation markers using the exact pattern `\[(\d+)]`, require contiguous numbering starting at 1, and verify each citation against the current or prospective repository.

- [ ] **Step 5: Implement deterministic rendering and prospective construction**

`render_draft` merges unknown existing frontmatter, then sets known fields and Source extensions deterministically. The Source extensions are exactly `resource: urn:bundlewalker:source:sha256:<digest>`, `source_sha256: <digest>`, and workspace-relative `raw_path: raw/<stored-name>`. `build_prospective_wiki` copies the live wiki to a supplied empty destination, renders all drafts, regenerates indexes, prepends one transaction log entry, lints the result with the workspace root, and raises `ChangeSetError` on any error finding.

Use the exact signature `build_prospective_wiki(workspace: Workspace, change_set: ChangeSet, context: ChangeValidationContext, destination: Path, occurred_at: datetime) -> None` so transaction code has one deterministic entry point.

- [ ] **Step 6: Run Task 6 tests and commit**

Run: `uv run pytest tests/test_changes.py -v && uv run pytest -q && uv run ruff check src tests && uv run pyright`

Expected: all checks pass.

```bash
git add src/bundlewalker/changes.py tests/test_changes.py
git commit -m "feat: validate and render knowledge proposals"
```

---

### Task 7: Journaled transaction, unified diff, and crash recovery

**Files:**
- Create: `src/bundlewalker/transactions.py`
- Create: `tests/test_transactions.py`

**Interfaces:**
- Consumes: Workspace, RawSource, `build_prospective_wiki`, `tree_diff`, and linter.
- Produces: `PreparedTransaction`, `prepare_transaction`, `commit_transaction`, `discard_transaction`, and `recover_transactions`.

- [ ] **Step 1: Write failing prepare/commit/discard tests**

Assert preparation writes only under `.bundlewalker/transactions/<id>/`, returns a complete unified diff, and leaves live raw/wiki unchanged. Assert discard removes staging. Assert commit persists exact raw bytes, replaces the wiki, verifies the result, and removes its transaction directory.

- [ ] **Step 2: Write phase-boundary fault-injection tests**

Parameterize crashes after `prepared`, `raw-persisted`, `swapping` before either rename, `swapping` after moving old wiki, `swapping` after moving new wiki, and `new-live`. Build exact filesystem states, call `recover_transactions`, and assert the live wiki is either the complete old tree or complete validated new tree—never a mixed tree.

- [ ] **Step 3: Verify Task 7 tests fail**

Run: `uv run pytest tests/test_transactions.py -v`

Expected: import failure for `bundlewalker.transactions`.

- [ ] **Step 4: Implement manifest and preparation**

Define a JSON manifest containing schema version, transaction ID, phase, workspace-relative prospective/backup/raw paths, raw digest, and summary. Write updates through a temporary file plus `os.replace`, then flush and `os.fsync` the file. `prepare_transaction` creates a UUID transaction directory, calls `build_prospective_wiki`, computes `tree_diff`, writes phase `prepared`, and returns:

```python
@dataclass(frozen=True, slots=True)
class PreparedTransaction:
    transaction_id: str
    workspace: Workspace
    transaction_dir: Path
    prospective_wiki: Path
    backup_wiki: Path
    change_set: ChangeSet
    raw_source: RawSource | None
    summary: str
    diff: str
```

Expose `prepare_transaction(workspace: Workspace, change_set: ChangeSet, context: ChangeValidationContext, raw_source: RawSource | None, occurred_at: datetime) -> PreparedTransaction`, `commit_transaction(prepared: PreparedTransaction) -> None`, `discard_transaction(prepared: PreparedTransaction) -> None`, and `recover_transactions(workspace: Workspace) -> None`. Persist each draft path, operation, and base digest in the manifest so pre-commit verification does not depend on process memory.

- [ ] **Step 5: Implement commit and idempotent recovery**

Before commit, revalidate replacement digests. Persist raw bytes with exclusive create and verify existing bytes by full digest. Sync `raw-persisted`, sync `swapping` before renames, rename live to backup, rename prospective to live, sync `new-live`, lint live, then clean up.

Recovery must inspect live/backup/prospective existence in addition to the phase. At `swapping`: restore backup if live is absent; validate live and finish when both live and backup exist; discard staging when live exists and backup does not. At `new-live`: keep valid live or restore backup. Every recovery path must be safe to call twice.

- [ ] **Step 6: Run transaction tests and commit**

Run: `uv run pytest tests/test_transactions.py -v && uv run pytest -q && uv run ruff check src tests && uv run pyright`

Expected: all fault-injection cases and full checks pass.

```bash
git add src/bundlewalker/transactions.py tests/test_transactions.py
git commit -m "feat: add recoverable knowledge transactions"
```

---

### Task 8: Provider-neutral PydanticAI boundary and read-only tools

**Files:**
- Create: `src/bundlewalker/agents/__init__.py`
- Create: `src/bundlewalker/agents/common.py`
- Create: `tests/agents/test_common.py`

**Interfaces:**
- Consumes: Workspace, repository, retrieval, and PydanticAI.
- Produces: `AgentDependencies`, `resolve_model`, `list_concepts`, `search_concepts`, `read_concept`, and `read_tools`.

- [ ] **Step 1: Write failing model-resolution tests**

Assert explicit model wins, environment model is the fallback, and absence raises `ConfigurationError` with both configuration methods named. Do not mutate the real environment; pass a mapping into `resolve_model`.

- [ ] **Step 2: Write failing read-tool tests**

Construct `AgentDependencies`, call tools through a `RunContext`, and assert list/search are bounded, path traversal is rejected, `read_concept` records the ID in `read_ids`, missing IDs return a tool-safe error, and no callable named write/delete/rename exists in `read_tools`.

- [ ] **Step 3: Verify Task 8 tests fail**

Run: `uv run pytest tests/agents/test_common.py -v`

Expected: import failure for `bundlewalker.agents.common`.

- [ ] **Step 4: Implement dependencies and tools**

Use this dependency object:

```python
@dataclass(slots=True)
class AgentDependencies:
    repository: OkfRepository
    retriever: LexicalRetriever
    conventions: str
    root_index: str
    read_ids: set[str] = field(default_factory=set)
```

Tool return values must be JSON-serializable summaries, not Path or model objects. Cap search at ten and concept bodies at 64,000 characters per read. Register exactly the three functions in `read_tools`; tool docstrings describe path and limit constraints so PydanticAI exposes useful schemas.

- [ ] **Step 5: Run Task 8 tests and commit**

Run: `uv run pytest tests/agents/test_common.py -v && uv run ruff check src tests && uv run pyright`

Expected: all tests and checks pass.

```bash
git add src/bundlewalker/agents tests/agents/test_common.py
git commit -m "feat: expose read-only knowledge agent tools"
```

---

### Task 9: IngestionAgent, reviewed ingestion workflow, and CLI command

**Files:**
- Create: `src/bundlewalker/agents/prompts/__init__.py`
- Create: `src/bundlewalker/agents/prompts/ingest.md`
- Create: `src/bundlewalker/agents/ingest.py`
- Create: `src/bundlewalker/workflows/__init__.py`
- Create: `src/bundlewalker/workflows/ingest.py`
- Modify: `src/bundlewalker/cli.py`
- Create: `tests/agents/test_ingest.py`
- Create: `tests/workflows/test_ingest.py`
- Create: `tests/cli/test_ingest.py`

**Interfaces:**
- Consumes: read-only tools, ChangeSet validation, transactions, and model resolution.
- Produces: `create_ingestion_agent`, `run_ingestion_agent`, `DuplicateIngestion`, `PreparedIngestion`, `IngestionOutcome`, `prepare_ingestion`, and CLI `ingest`.

- [ ] **Step 1: Write failing agent-construction tests**

Assert the agent has `deps_type=AgentDependencies`, `output_type=ChangeSet`, retries set to `2`, only the three read tools, and instructions containing the protected-data rule, exact Source cardinality, allowed types, uncertainty/contradiction behavior, and numbered line citations.

- [ ] **Step 2: Write failing workflow and CLI tests**

Inject an async fake runner returning a valid ChangeSet. Assert duplicate digest returns a typed no-op before model invocation; a valid proposal returns `PreparedTransaction`; declining confirmation calls discard and exits `0`; accepting prints the diff, commits raw/wiki/index/log together, and exits `0`; invalid output exits `1` and leaves live trees byte-identical.

- [ ] **Step 3: Verify Task 9 tests fail**

Run: `uv run pytest tests/agents/test_ingest.py tests/workflows/test_ingest.py tests/cli/test_ingest.py -v`

Expected: import failures for ingestion agent/workflow.

- [ ] **Step 4: Implement the ingestion prompt and agent wrapper**

Load `ingest.md` with `importlib.resources`. Create `Agent(model, deps_type=AgentDependencies, output_type=ChangeSet, tools=read_tools, retries=2)`. `run_ingestion_agent` injects `conventions` and `root_index` as explicitly delimited untrusted data, numbers source lines as `000001 | text`, runs the agent, and returns `result.output` plus the mutated dependency `read_ids`.

- [ ] **Step 5: Implement reviewed ingestion orchestration**

`prepare_ingestion` must recover first, load and deduplicate the source, build repository/dependencies, call the injected runner, validate with mode `ingest`, and call `prepare_transaction`. Return this discriminated result:

```python
@dataclass(frozen=True, slots=True)
class DuplicateIngestion:
    status: Literal["duplicate"] = "duplicate"


@dataclass(frozen=True, slots=True)
class PreparedIngestion:
    transaction: PreparedTransaction
    status: Literal["prepared"] = "prepared"


type IngestionOutcome = DuplicateIngestion | PreparedIngestion
```

The CLI resolves the model only after duplicate detection, prints summary and unified diff, calls `typer.confirm("Apply these changes?")`, then commits or discards. Catch `KeyboardInterrupt` around confirmation only and report `No changes applied.` with exit `0`.

- [ ] **Step 6: Run ingestion tests and manual fake-model smoke test**

Run: `uv run pytest tests/agents/test_ingest.py tests/workflows/test_ingest.py tests/cli/test_ingest.py -v && uv run pytest -q && uv run ruff check src tests && uv run pyright`

Expected: all tests and checks pass with no provider calls.

- [ ] **Step 7: Commit ingestion**

```bash
git add src/bundlewalker tests
git commit -m "feat: ingest sources through reviewed proposals"
```

---

### Task 10: QueryAgent, cited answers, optional Synthesis, and `ask`

**Files:**
- Create: `src/bundlewalker/agents/prompts/query.md`
- Create: `src/bundlewalker/agents/query.py`
- Create: `src/bundlewalker/workflows/ask.py`
- Modify: `src/bundlewalker/cli.py`
- Create: `tests/agents/test_query.py`
- Create: `tests/workflows/test_ask.py`
- Create: `tests/cli/test_ask.py`

**Interfaces:**
- Consumes: `CitedAnswer`, read tracking, ChangeSet validation, and transactions.
- Produces: `create_query_agent`, `run_query_agent`, `answer_question`, `prepare_synthesis`, and CLI `ask`.

- [ ] **Step 1: Write failing query-agent contract tests**

Use `FunctionModel` for a two-turn response: first call `read_concept`, then return structured `CitedAnswer`. Assert cited IDs exist in `deps.read_ids`. Add rejection tests for nonexistent and unread citations, empty questions, and model output with citation markers missing structured citations.

- [ ] **Step 2: Write failing `ask` and save tests**

Assert plain `ask` prints answer/citations and performs no filesystem writes. For `--save`, assert one create-only Synthesis draft is built deterministically from the answer, a collision-safe slug is chosen, no second runner call occurs, the same diff/confirmation path is used, and rejection leaves the workspace unchanged.

- [ ] **Step 3: Verify Task 10 tests fail**

Run: `uv run pytest tests/agents/test_query.py tests/workflows/test_ask.py tests/cli/test_ask.py -v`

Expected: import failures for query modules.

- [ ] **Step 4: Implement QueryAgent and citation verification**

Create the query agent with `CitedAnswer`, shared tools, and retries `2`. `run_query_agent` injects conventions, root index, and the question as separately delimited untrusted data. It validates that citation numbering matches answer markers, every concept exists, and every cited ID is in `deps.read_ids`; otherwise raise `AgentRunError`.

- [ ] **Step 5: Implement deterministic Synthesis conversion**

`prepare_synthesis` converts the validated answer directly into a `ChangeSet` with one `Synthesis` create. Derive an ASCII slug from the title; when occupied, append `-2`, `-3`, and upward until free. Preserve answer body verbatim, render citations through the standard renderer, validate mode `synthesis`, and prepare the transaction without invoking a model.

- [ ] **Step 6: Run ask tests and commit**

Run: `uv run pytest tests/agents/test_query.py tests/workflows/test_ask.py tests/cli/test_ask.py -v && uv run pytest -q && uv run ruff check src tests && uv run pyright`

Expected: all tests and checks pass.

```bash
git add src/bundlewalker tests
git commit -m "feat: answer and save cited knowledge queries"
```

---

### Task 11: Deterministic and semantic lint workflows and CLI

**Files:**
- Create: `src/bundlewalker/agents/prompts/semantic-lint.md`
- Create: `src/bundlewalker/agents/semantic_lint.py`
- Create: `src/bundlewalker/workflows/lint.py`
- Modify: `src/bundlewalker/cli.py`
- Create: `tests/agents/test_semantic_lint.py`
- Create: `tests/workflows/test_lint.py`
- Create: `tests/cli/test_lint.py`

**Interfaces:**
- Consumes: deterministic lint, model resolution, and read-only tools.
- Produces: `create_semantic_lint_agent`, `run_semantic_lint_agent`, `LintRun`, `run_lint`, and CLI `lint`.

- [ ] **Step 1: Write failing lint workflow tests**

Assert plain lint never resolves a model, reports sorted deterministic findings, exits `1` only for deterministic errors, and never writes. Assert `--semantic` requires a model, invokes a fake runner after deterministic lint, marks returned findings `origin=semantic`, verifies evidence paths were read, leaves exit status based only on deterministic errors, and leaves every workspace byte unchanged.

- [ ] **Step 2: Verify Task 11 tests fail**

Run: `uv run pytest tests/agents/test_semantic_lint.py tests/workflows/test_lint.py tests/cli/test_lint.py -v`

Expected: import failures for semantic lint/workflow modules.

- [ ] **Step 3: Implement the semantic agent and workflow**

Create the agent with `output_type=list[LintFinding]`, retries `2`, and the three shared tools. Inject conventions, root index, and deterministic lint signals as separately delimited untrusted data. Instructions constrain codes to `SEM-CONTRADICTION`, `SEM-STALE`, `SEM-UNSUPPORTED`, `SEM-MISSING`, and `SEM-GAP`; require evidence paths; forbid remediation writes. Reject any evidence path absent from `deps.read_ids`.

`run_lint` always runs deterministic lint first and runs the semantic agent only when requested and deterministic parsing left a usable repository. Merge and sort findings but return a separate `deterministic_has_errors` boolean for CLI exit mapping.

```python
@dataclass(frozen=True, slots=True)
class LintRun:
    findings: tuple[LintFinding, ...]
    deterministic_has_errors: bool
```

- [ ] **Step 4: Run lint tests and commit**

Run: `uv run pytest tests/agents/test_semantic_lint.py tests/workflows/test_lint.py tests/cli/test_lint.py -v && uv run pytest -q && uv run ruff check src tests && uv run pyright`

Expected: all tests and checks pass; no test performs network inference.

```bash
git add src/bundlewalker tests
git commit -m "feat: add deterministic and semantic wiki lint"
```

---

### Task 12: Acceptance coverage, opt-in evaluations, and user documentation

**Files:**
- Create: `tests/test_acceptance.py`
- Create: `evals/cases.yaml`
- Create: `tests/evals/test_model_quality.py`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: all v1 commands and workflows.
- Produces: executable acceptance proof, explicitly gated live-model quality evaluation, and user-facing documentation.

- [ ] **Step 1: Write the end-to-end offline acceptance test**

Use a temporary workspace and injected fake runners to execute this exact sequence: init; lint clean; ingest preview decline and assert byte-identical workspace; ingest accept and assert raw/source/topic/index/log; duplicate ingest and assert runner not called; ask with read citation; ask without save and assert no writes; ask save decline; ask save accept without a second model call; semantic lint and assert no writes; inject a `swapping` transaction state and assert the next command recovers first.

- [ ] **Step 2: Add explicitly gated quality cases**

Create `evals/cases.yaml` with four small cases: faithful source summary, cross-source topic update, contradiction preservation, and cited answer. `tests/evals/test_model_quality.py` must use:

```python
MODEL = os.getenv("BUNDLEWALKER_EVAL_MODEL")
pytestmark = pytest.mark.skipif(
    not MODEL,
    reason="set BUNDLEWALKER_EVAL_MODEL to run live model evaluations",
)
```

Each case creates an isolated workspace, runs the real PydanticAI agent with the explicit model, and asserts structural invariants plus case-specific expected phrases/citations. Mark the tests `@pytest.mark.eval`; the environment guard skips them in ordinary offline runs.

- [ ] **Step 3: Rewrite README with the complete v1 workflow**

Document `uv sync`, model configuration, `init`, text-only `ingest`, diff confirmation, `ask`, `ask --save`, deterministic/semantic `lint`, workspace layout, `conventions.md`, provider credential responsibility, exit codes, Git recommendation without automation, source-size limit, and explicit v1 exclusions. Include one copy-paste session using `BUNDLEWALKER_MODEL` without naming a mandatory provider.

- [ ] **Step 4: Run the full offline release gate**

Run:

```bash
uv lock --check
uv run pytest -m "not eval" -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run pyright
uv run bundlewalker --help
uv run bundlewalker init --help
uv run bundlewalker ingest --help
uv run bundlewalker ask --help
uv run bundlewalker lint --help
```

Expected: all commands exit `0`; tests report no failures; all four subcommands appear in top-level help.

- [ ] **Step 5: Run one opt-in evaluation only when credentials are intentionally configured**

Run: `BUNDLEWALKER_EVAL_MODEL='<pydantic-ai-model-string>' uv run pytest -m eval -v`

Expected: four evaluation cases run and report their selected model. If no model credentials are available, record the evaluation as intentionally skipped and do not weaken offline acceptance.

- [ ] **Step 6: Commit the release-ready vertical slice**

```bash
git add README.md pyproject.toml uv.lock evals tests
git commit -m "test: verify BundleWalker v1 acceptance"
```

---

## Final verification and handoff

After Task 12, rerun the complete offline release gate from a clean shell, inspect `git status --short`, and confirm no `.bundlewalker/`, `.superpowers/`, credential, raw personal source, or generated temporary transaction file is staged. Compare the implementation against every numbered acceptance criterion in the design spec and record any intentionally skipped live-model evaluation in the final handoff.
