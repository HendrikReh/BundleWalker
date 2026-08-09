# MCP Interface Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable cross-process reviews, an interface-neutral application facade, CLI compatibility, and a full local MCP `stdio` server bound to one BundleWalker workspace.

**Architecture:** Preserve BundleWalker's modular monolith and deterministic knowledge core. Add schema-v2 pending-review persistence and opaque review-ID operations beneath an async `WorkspaceApplication`; route the CLI and a low-level official MCP Python SDK server through that facade. The local web UI is a separate follow-on plan after this MCP milestone is complete.

**Tech Stack:** Python 3.13+, Pydantic 2, PydanticAI, Typer, official MCP Python SDK `mcp>=1.28.1,<2`, pytest/pytest-asyncio, Ruff, strict Pyright.

## Global Constraints

- Preserve the trust boundary: models propose typed changes; deterministic code alone validates paths, citations, complete diffs, review state, and persistence.
- Preparation may write only private `.bundlewalker/` state; it must not mutate live `raw/` or `wiki/` content.
- A workspace has zero or one schema-v2 pending review. Read-only operations remain available while it is pending.
- Pending reviews survive restart. Accepted transactions retain authenticated completion-or-rollback recovery.
- A stale pending review remains inspectable but cannot apply; only explicit discard frees the slot.
- Existing schema-v1 `prepared` transactions retain historical cleanup/recovery behavior and never become durable pending reviews.
- MCP uses local `stdio` only, binds one workspace at startup, and never accepts workspace paths or local source paths in tool calls.
- MCP ingestion accepts one simple `.md` or `.txt` filename and inline Unicode content; the UTF-8 encoding of that content is the immutable accepted source.
- MCP annotations are hints only. Review ID, state, workspace confinement, and digest revalidation enforce authority.
- Only protocol messages reach MCP stdout; diagnostics use stderr or MCP logging.
- Default tests remain offline and require no model credentials.
- Existing CLI commands, prompt behavior, exit codes, duplicate/no-op behavior, and Ctrl-C semantics remain compatible.
- Use `mcp>=1.28.1,<2`; do not adopt the pre-release v2 SDK in this milestone.
- Normal verification is `uv run pytest -m 'not eval' -q`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pyright`, and `git diff --check`.

---

## File Structure

### New production files

- `src/bundlewalker/application/__init__.py` — public application exports.
- `src/bundlewalker/application/contracts.py` — strict serializable request/result models.
- `src/bundlewalker/application/errors.py` — stable application error codes and exception translation.
- `src/bundlewalker/application/facade.py` — async workspace-bound use cases.
- `src/bundlewalker/interfaces/__init__.py` — delivery-adapter package marker.
- `src/bundlewalker/interfaces/cli.py` — Typer adapter migrated through the facade.
- `src/bundlewalker/interfaces/mcp_schemas.py` — MCP request models and static tool metadata.
- `src/bundlewalker/interfaces/mcp_tools.py` — MCP tool dispatch, result, and error mapping.
- `src/bundlewalker/interfaces/mcp.py` — low-level MCP server, resources, and `stdio` entry point.

### New test files

- `tests/application/__init__.py`
- `tests/application/test_contracts.py`
- `tests/application/test_facade.py`
- `tests/interfaces/__init__.py`
- `tests/interfaces/test_mcp_resources.py`
- `tests/interfaces/test_mcp_tools.py`
- `tests/interfaces/test_mcp_stdio.py`
- `tests/cli/test_review.py`

### Modified production files

- `src/bundlewalker/workspace.py` — inline-source normalization.
- `src/bundlewalker/errors.py` — typed review lifecycle errors.
- `src/bundlewalker/transactions.py` — schema-v2 review records, pending preservation, ID-based apply/discard, acceptance recovery.
- `src/bundlewalker/workflows/ingest.py` — pre-model review gate and already-loaded source entry point.
- `src/bundlewalker/workflows/ask.py` — pre-model review gate and review kinds.
- `src/bundlewalker/workflows/lint.py` — preserve pending reviews while recovering accepted commits.
- `src/bundlewalker/cli.py` — compatibility re-export for existing imports and console script.
- `pyproject.toml` and `uv.lock` — MCP dependency and `bundlewalker-mcp` entry point.
- `README.md`, `docs/user-guide.md`, and `CONTRIBUTING.md` — MCP setup, review workflow, and architecture.

### Existing tests modified in place

- `tests/test_workspace.py`
- `tests/test_transactions.py`
- `tests/test_acceptance.py`
- `tests/workflows/test_ingest.py`
- `tests/workflows/test_ask.py`
- `tests/workflows/test_lint.py`
- `tests/cli/test_ingest.py`
- `tests/cli/test_ask.py`
- `tests/cli/test_lint.py`

---

### Task 1: Normalize Inline Sources Without Filesystem Authority

**Files:**
- Modify: `src/bundlewalker/workspace.py:30-220`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Produces: `load_inline_source(source_name: str, content: str, workspace: Workspace) -> RawSource`.
- Preserves: `load_raw_source(path: Path, workspace: Workspace) -> RawSource` and all existing file safety behavior.
- Later tasks consume `load_inline_source` from `WorkspaceApplication.prepare_ingestion`.

- [ ] **Step 1: Write failing inline-source tests**

Add focused tests covering exact UTF-8 bytes, stable identity, simple-name validation, suffix validation, configured character limits, and no filesystem read:

```python
def test_load_inline_source_builds_the_same_identity_from_supplied_utf8(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    source = load_inline_source("Überblick.md", "Grüße\n", workspace)

    assert source.content == "Grüße\n".encode("utf-8")
    assert source.text == "Grüße\n"
    assert source.extension == ".md"
    assert source.slug == "uberblick"
    assert source.line_count == 1
    assert source.sha256 == hashlib.sha256(source.content).hexdigest()
    assert source.input_path == Path("Überblick.md")
    assert source.stored_relative_path.parent == Path("raw")


@pytest.mark.parametrize(
    "name",
    [
        "../notes.md",
        "folder/notes.md",
        r"folder\\notes.md",
        "bad\x7fname.md",
        ".",
        "..",
        "notes.pdf",
    ],
)
def test_load_inline_source_rejects_paths_and_unsupported_names(
    tmp_path: Path,
    name: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    with pytest.raises(WorkspaceError):
        load_inline_source(name, "content\n", workspace)
```

- [ ] **Step 2: Run the focused tests and confirm the missing API failure**

Run: `uv run pytest tests/test_workspace.py -q`

Expected: collection or import failure because `load_inline_source` does not exist.

- [ ] **Step 3: Refactor source construction and add inline validation**

Keep file reads in `load_raw_source`, then route both inputs through one private constructor. Use this exact public shape and validation order:

```python
_INLINE_SOURCE_NAME_MAX = 255


def load_inline_source(source_name: str, content: str, workspace: Workspace) -> RawSource:
    if (
        not source_name
        or len(source_name) > _INLINE_SOURCE_NAME_MAX
        or source_name in {".", ".."}
        or "/" in source_name
        or "\\" in source_name
        or any(unicodedata.category(character) == "Cc" for character in source_name)
    ):
        raise WorkspaceError("inline source name must be one safe filename")
    name = Path(source_name)
    if name.suffix not in {".md", ".txt"}:
        raise WorkspaceError("source extension must be .md or .txt")
    return _raw_source_from_content(name, content.encode("utf-8"), workspace)


def _raw_source_from_content(
    input_path: Path,
    content: bytes,
    workspace: Workspace,
) -> RawSource:
    extension_value = input_path.suffix
    if extension_value not in {".md", ".txt"}:
        raise WorkspaceError("source extension must be .md or .txt")
    extension = cast(Literal[".md", ".txt"], extension_value)
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkspaceError(f"source must contain valid UTF-8: {input_path}") from exc
    if len(text) > workspace.config.max_source_characters:
        raise WorkspaceError(
            "source exceeds the configured limit of "
            f"{workspace.config.max_source_characters} characters"
        )
    digest = hashlib.sha256(content).hexdigest()
    slug = _slugify(input_path.stem)
    stored_path, concept_id = stable_source_paths(
        workspace,
        digest,
        slug,
        extension,
    )
    return RawSource(
        input_path=input_path,
        content=content,
        text=text,
        sha256=digest,
        line_count=len(text.splitlines()),
        extension=extension,
        slug=slug,
        stored_relative_path=stored_path,
        concept_id=concept_id,
    )
```

Change `load_raw_source` to retain its regular-file/symlink/read checks and return `_raw_source_from_content(candidate.resolve(strict=True), content, workspace)`.

- [ ] **Step 4: Run workspace tests**

Run: `uv run pytest tests/test_workspace.py -q`

Expected: all workspace tests pass, including the new inline-source cases.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/workspace.py tests/test_workspace.py
git commit -m "feat: normalize inline ingestion sources"
```

---

### Task 2: Persist Schema-v2 Review Records and Exact Diffs

**Files:**
- Modify: `src/bundlewalker/transactions.py:27-195, 875-1043`
- Modify: `src/bundlewalker/errors.py`
- Modify: `src/bundlewalker/workflows/ingest.py`
- Modify: `src/bundlewalker/workflows/ask.py`
- Test: `tests/test_transactions.py`

**Interfaces:**
- Produces: `ReviewKind`, `ReviewStatus`, and immutable `TransactionReview`.
- Changes: `prepare_transaction(workspace, change_set, context, raw_source, occurred_at, *, kind) -> PreparedTransaction`.
- Persists: `review.json`, whose SHA-256 is stored in schema-v2 `identity.json`.
- Preserves: `PreparedTransaction` fields and schema-v1 read/recovery compatibility.

- [ ] **Step 1: Add a failing persisted-review test**

Extend the transaction test helper so every new preparation passes `kind=ReviewKind.INGESTION`, then add:

```python
def test_prepare_persists_exact_review_record_and_identity(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    review_path = prepared.transaction_dir / "review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    identity = json.loads(
        (prepared.transaction_dir / "identity.json").read_text(encoding="utf-8")
    )

    assert review == {
        "changed_paths": [prepared.change_set.drafts[0].path],
        "created_at": NOW.isoformat(),
        "diff": prepared.diff,
        "kind": "ingestion",
        "schema_version": 1,
        "summary": prepared.summary,
        "transaction_id": prepared.transaction_id,
    }
    assert identity["review_digest"] == hashlib.sha256(review_path.read_bytes()).hexdigest()


```

- [ ] **Step 2: Run the focused tests and observe the signature/schema failures**

Run: `uv run pytest tests/test_transactions.py -q`

Expected: failures because review types, the `kind` parameter, `review.json`, and `review_digest` do not exist.

- [ ] **Step 3: Add typed review state and typed lifecycle errors**

Add to `src/bundlewalker/errors.py`:

```python
class ReviewPendingError(TransactionError):
    def __init__(self, review_id: str) -> None:
        self.review_id = review_id
        super().__init__(f"workspace already has a pending review: {review_id}")


class ReviewNotFoundError(TransactionError):
    pass


class ReviewMismatchError(TransactionError):
    pass


class ReviewStaleError(TransactionError):
    pass
```

Add beside `PreparedTransaction` in `transactions.py`:

```python
class ReviewKind(StrEnum):
    INGESTION = "ingestion"
    SYNTHESIS = "synthesis"
    REFRESH = "refresh"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class TransactionReview:
    review_id: str
    kind: ReviewKind
    status: ReviewStatus
    summary: str
    diff: str
    changed_paths: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _ReviewRecord:
    schema_version: int
    transaction_id: str
    kind: ReviewKind
    summary: str
    diff: str
    changed_paths: tuple[str, ...]
    created_at: datetime
```

Import `StrEnum` and add `_REVIEW_NAME = "review.json"`, `_REVIEW_SCHEMA_VERSION = 1`, and transaction schema version `2`. Extend `_Identity` with `review_digest: str | None` so schema-v1 identities remain readable.

- [ ] **Step 4: Persist and validate the review record**

Add `_write_review` using sorted JSON, UTF-8, mode `0o600`, `O_EXCL | O_NOFOLLOW`, file `fsync`, and directory `fsync`. Add `_load_review` that requires exactly the seven keys shown in the test, validates the UUID-safe ID, enum, ISO timestamp, summary bounds, changed canonical concept IDs, and the recorded digest:

```python
def _review_values(record: _ReviewRecord) -> dict[str, object]:
    return {
        "changed_paths": list(record.changed_paths),
        "created_at": record.created_at.isoformat(),
        "diff": record.diff,
        "kind": record.kind.value,
        "schema_version": record.schema_version,
        "summary": record.summary,
        "transaction_id": record.transaction_id,
    }


def _review_digest(transaction_dir: Path) -> str:
    return _file_digest(transaction_dir / _REVIEW_NAME)
```

In `prepare_transaction`, write the raw payload and prospective tree first, then `review.json`, then schema-v2 `identity.json` containing `review_digest`, then the schema-v2 manifest last. Include `kind` and `occurred_at` in `_ReviewRecord`; derive `changed_paths` from canonical draft paths. If any write fails, retain the existing safe transaction-directory cleanup.

Update all production call sites in the same task: ingestion passes `ReviewKind.INGESTION`, saved
Synthesis passes `ReviewKind.SYNTHESIS`, and refresh passes `ReviewKind.REFRESH`. This keeps the
repository type-correct immediately after the required `kind` parameter is introduced.

Update `_load_manifest` to accept schema versions `1` and `2`, with schema-specific phase validation. Update `_load_identity` to accept missing `review_digest` only for schema-v1 handling. Do not reinterpret a schema-v1 `prepared` record as pending.

- [ ] **Step 5: Run transaction tests**

Run: `uv run pytest tests/test_transactions.py -q`

Expected: the new persistence tests and all updated historical transaction tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/errors.py src/bundlewalker/transactions.py \
  src/bundlewalker/workflows/ingest.py src/bundlewalker/workflows/ask.py \
  tests/test_transactions.py
git commit -m "feat: persist durable transaction reviews"
```

---

### Task 3: Preserve One Pending Review and Report Staleness

**Files:**
- Modify: `src/bundlewalker/transactions.py:99-195, 296-427, 732-824`
- Test: `tests/test_transactions.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Produces: `get_pending_review(workspace: Workspace) -> TransactionReview | None`.
- Produces: `ensure_no_pending_review(workspace: Workspace) -> None`.
- Guarantees: recovery preserves one valid schema-v2 `pending` review and still cleans legacy schema-v1 `prepared` state.

- [ ] **Step 1: Add failing pending, stale, and single-slot tests**

```python
def test_recovery_preserves_schema_v2_pending_review(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)

    recover_transactions(prepared.workspace)
    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.review_id == prepared.transaction_id
    assert loaded.status is ReviewStatus.PENDING
    assert loaded.diff == prepared.diff


def test_pending_review_becomes_stale_after_live_edit(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    (prepared.workspace.wiki_dir / "external.md").write_text("external\n", encoding="utf-8")

    loaded = get_pending_review(prepared.workspace)

    assert loaded is not None
    assert loaded.status is ReviewStatus.STALE


def test_second_preparation_is_rejected_without_removing_first(tmp_path: Path) -> None:
    first, _source = _prepare(tmp_path)

    with pytest.raises(ReviewPendingError) as raised:
        _prepare_in_workspace(first.workspace, tmp_path / "other.txt")

    assert raised.value.review_id == first.transaction_id
    assert get_pending_review(first.workspace).review_id == first.transaction_id


def test_corrupted_review_record_is_not_loadable(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    review_path = prepared.transaction_dir / "review.json"
    review_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(TransactionError, match="review identity"):
        get_pending_review(prepared.workspace)
```

Keep or add the historical acceptance assertion that schema-v1 `prepared` recovery leaves live
knowledge unchanged and removes the legacy transaction directory.

- [ ] **Step 2: Run focused recovery tests**

Run: `uv run pytest tests/test_transactions.py tests/test_acceptance.py -q`

Expected: failures because normal recovery still cleans all prepared state and no single-slot API exists.

- [ ] **Step 3: Split recoverable commits from pending reviews**

Implement the public operations as lock-taking wrappers around private locked helpers:

```python
def get_pending_review(workspace: Workspace) -> TransactionReview | None:
    transactions_root = workspace.root.joinpath(*_TRANSACTIONS_PATH.parts)
    if not transactions_root.exists():
        return None
    with _workspace_transaction_lock(workspace):
        _recover_transactions_locked(workspace, transactions_root)
        return _get_pending_review_locked(workspace, transactions_root)


def ensure_no_pending_review(workspace: Workspace) -> None:
    pending = get_pending_review(workspace)
    if pending is not None:
        raise ReviewPendingError(pending.review_id)
```

In `_recover_transactions_locked`, load each manifest first. Preserve only a valid schema-v2
`pending` record after verifying its identity, review digest, confined paths, raw payload digest,
and prospective tree digest. Send schema-v1 `prepared` and all accepted/later phases through the
existing recovery path. Raise `TransactionError` if more than one valid pending review exists.

Build `TransactionReview.status` by comparing the materialized live wiki digest and every draft
precondition to the persisted base. Return `STALE` instead of raising for a well-formed proposal
whose live preconditions changed; integrity corruption still raises.

- [ ] **Step 4: Enforce the slot under the cross-process lock**

Wrap the body of `prepare_transaction` in `_workspace_transaction_lock`, call
`_recover_transactions_locked`, and call `_get_pending_review_locked` before creating the new
transaction directory:

```python
def prepare_transaction(
    workspace: Workspace,
    change_set: ChangeSet,
    context: ChangeValidationContext,
    raw_source: RawSource | None,
    occurred_at: datetime,
    *,
    kind: ReviewKind,
) -> PreparedTransaction:
    with _workspace_transaction_lock(workspace):
        transactions_root = _ensure_transactions_root(workspace)
        _recover_transactions_locked(workspace, transactions_root)
        existing = _get_pending_review_locked(workspace, transactions_root)
        if existing is not None:
            raise ReviewPendingError(existing.review_id)
        return _prepare_transaction_locked(
            workspace,
            change_set,
            context,
            raw_source,
            occurred_at,
            kind=kind,
            transactions_root=transactions_root,
        )
```

The lock begins only after model output exists; no model call is made while holding it.

- [ ] **Step 5: Run recovery, transaction, and acceptance tests**

Run: `uv run pytest tests/test_transactions.py tests/test_acceptance.py -q`

Expected: all pass, including schema-v1 cleanup and schema-v2 pending preservation.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/transactions.py tests/test_transactions.py tests/test_acceptance.py
git commit -m "feat: preserve one pending workspace review"
```

---

### Task 4: Apply and Discard Reviews by Opaque ID

**Files:**
- Modify: `src/bundlewalker/transactions.py:198-519, 623-760, 1413-1434`
- Test: `tests/test_transactions.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Produces: `apply_pending_review(workspace: Workspace, review_id: str) -> None`.
- Produces: `discard_pending_review(workspace: Workspace, review_id: str) -> None`.
- Preserves: `commit_transaction(PreparedTransaction)` and `discard_transaction(PreparedTransaction)` as compatibility wrappers.
- Adds schema-v2 `accepted` phase before any live raw/wiki mutation.

- [ ] **Step 1: Add failing cross-process apply/discard tests**

```python
def test_loaded_review_can_apply_without_original_handle(tmp_path: Path) -> None:
    prepared, source = _prepare(tmp_path)
    review_id = prepared.transaction_id
    workspace = prepared.workspace
    del prepared

    apply_pending_review(workspace, review_id)

    assert get_pending_review(workspace) is None
    assert (workspace.root / source.stored_relative_path).read_bytes() == source.content


def test_wrong_review_id_cannot_resolve_current_review(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)

    with pytest.raises(ReviewMismatchError):
        discard_pending_review(prepared.workspace, "0" * 32)

    assert get_pending_review(prepared.workspace).review_id == prepared.transaction_id


def test_stale_review_cannot_apply_but_can_discard(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)
    (prepared.workspace.wiki_dir / "external.md").write_text("external\n", encoding="utf-8")

    with pytest.raises(ReviewStaleError):
        apply_pending_review(prepared.workspace, prepared.transaction_id)
    discard_pending_review(prepared.workspace, prepared.transaction_id)

    assert get_pending_review(prepared.workspace) is None
```

Add a phase-injection acceptance test that writes `accepted`, simulates process termination before
raw persistence, calls `recover_transactions`, and asserts the authenticated prospective tree and
raw payload are committed. Add a second test that changes the live base before accepted recovery
and asserts deterministic rollback: the external live tree remains exact, raw is unchanged, and
the accepted transaction is cleaned. Existing raw-persisted, swapping, and new-live recovery cases
must remain.

- [ ] **Step 2: Run the focused tests**

Run: `uv run pytest tests/test_transactions.py tests/test_acceptance.py -q`

Expected: failures because only in-memory handle commit/discard exists and `accepted` is unknown.

- [ ] **Step 3: Refactor commit to persisted manifest identity**

Make `_persist_raw_source` consume only `workspace`, `transaction_dir`, and `_Manifest`; verify the
staged payload directly against `manifest.raw_sha256`. Extract a private commit function that does
not require `RawSource` or `ChangeSet` in memory:

```python
def _accept_and_commit_locked(
    workspace: Workspace,
    transaction_dir: Path,
    manifest: _Manifest,
) -> None:
    if manifest.phase != "pending":
        raise TransactionError(f"transaction is not pending: {manifest.phase}")
    _verify_pending_transaction(workspace, transaction_dir, manifest)
    manifest = replace(manifest, phase="accepted")
    _write_manifest(transaction_dir, manifest)
    _resume_accepted_commit_locked(workspace, transaction_dir, manifest)
```

`_resume_accepted_commit_locked` performs the existing raw-persisted, swapping, and new-live
sequence from persisted manifest and identity data. It must write and fsync `accepted` before
calling `_persist_raw_source`.

- [ ] **Step 4: Add ID-based public functions and compatibility wrappers**

```python
def apply_pending_review(workspace: Workspace, review_id: str) -> None:
    with _workspace_transaction_lock(workspace):
        transaction_dir, manifest = _require_pending_manifest_locked(workspace, review_id)
        review = _load_transaction_review(workspace, transaction_dir, manifest)
        if review.status is ReviewStatus.STALE:
            raise ReviewStaleError(f"pending review is stale: {review_id}")
        _accept_and_commit_locked(workspace, transaction_dir, manifest)


def discard_pending_review(workspace: Workspace, review_id: str) -> None:
    with _workspace_transaction_lock(workspace):
        transaction_dir, manifest = _require_pending_manifest_locked(workspace, review_id)
        if manifest.phase != "pending":
            raise TransactionError(f"only a pending review can be discarded: {manifest.phase}")
        _cleanup_transaction(workspace, transaction_dir)
```

If no pending review exists, raise `ReviewNotFoundError`; if one exists under a different ID, raise
`ReviewMismatchError`. Validate every supplied ID against `^[0-9a-f]{32}$` before inspecting a
transaction directory; malformed or non-current values use the fixed message
`review ID does not match the pending review` and never interpolate uncontrolled input. Make
`commit_transaction` validate the old handle then delegate to the same locked accept/commit
function. Make `discard_transaction` validate the old handle then delegate to the same cleanup
path.

- [ ] **Step 5: Recover accepted-before-mutation transactions**

Teach recovery that schema-v2 `accepted` means the decision is durable. If the authenticated base
and prospective tree are intact, resume the commit. If a concurrent live edit makes application
unsafe before any BundleWalker mutation, leave the live tree exact and safely remove the accepted
transaction as a rollback. Integrity ambiguity or an unauthenticated tree remains a blocking
`TransactionError`.

- [ ] **Step 6: Run transaction and acceptance tests**

Run: `uv run pytest tests/test_transactions.py tests/test_acceptance.py -q`

Expected: all transaction phases and ID-based resolution cases pass.

- [ ] **Step 7: Commit**

```bash
git add src/bundlewalker/transactions.py tests/test_transactions.py tests/test_acceptance.py
git commit -m "feat: resolve reviews by durable identity"
```

---

### Task 5: Gate Write Workflows Before Model Calls

**Files:**
- Modify: `src/bundlewalker/workflows/ingest.py`
- Modify: `src/bundlewalker/workflows/ask.py`
- Modify: `src/bundlewalker/workflows/lint.py`
- Test: `tests/workflows/test_ingest.py`
- Test: `tests/workflows/test_ask.py`
- Test: `tests/workflows/test_lint.py`

**Interfaces:**
- Produces: `prepare_raw_ingestion(workspace, source: RawSource, *, explicit_model, environment, runner, occurred_at) -> IngestionOutcome`.
- Existing `prepare_ingestion` remains a path-loading wrapper.
- Every preparing workflow supplies the correct `ReviewKind`.
- Read-only ask and lint recover accepted commits but preserve pending reviews.

- [ ] **Step 1: Add failing pre-model gate and loaded-source tests**

For ingestion and both synthesis preparation paths, prepare one review, install a runner that raises
if called, then assert the second preparation raises `ReviewPendingError` with zero runner calls.
Also add:

```python
async def test_prepare_raw_ingestion_accepts_an_already_normalized_source(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    source = load_inline_source("notes.txt", "first\nsecond\n", workspace)

    outcome = await prepare_raw_ingestion(
        workspace,
        source,
        explicit_model="test:model",
        environment={},
        runner=_valid_runner,
        occurred_at=NOW,
    )

    assert isinstance(outcome, PreparedIngestion)
    assert get_pending_review(workspace).kind is ReviewKind.INGESTION
```

- [ ] **Step 2: Run workflow tests**

Run: `uv run pytest tests/workflows -q`

Expected: failures because write workflows do not preflight pending state or tag review kind.

- [ ] **Step 3: Split ingestion loading from ingestion orchestration**

Keep `prepare_ingestion` as:

```python
async def prepare_ingestion(
    workspace: Workspace,
    source_path: Path,
    *,
    explicit_model: str | None,
    environment: Mapping[str, str] | None = None,
    runner: IngestionRunner | None = None,
    occurred_at: datetime | None = None,
) -> IngestionOutcome:
    source = load_raw_source(source_path, workspace)
    return await prepare_raw_ingestion(
        workspace,
        source,
        explicit_model=explicit_model,
        environment=environment,
        runner=runner,
        occurred_at=occurred_at,
    )
```

Move the current orchestration into `prepare_raw_ingestion`. After recovery and duplicate detection
but before context/model resolution, call `ensure_no_pending_review(workspace)`. Pass
`kind=ReviewKind.INGESTION` to transaction preparation.

`answer_synthesis_refresh` is always a write-intent workflow, so preflight it before its model call.
Plain `answer_question`, plain lint, and semantic lint must leave a pending review untouched because
they are read-only. Saved-Synthesis preflight occurs in `WorkspaceApplication.prepare_synthesis`
immediately before it calls `answer_question`; the existing standalone `prepare_synthesis` still
rechecks before transaction preparation as defense in depth. Review kinds were already wired in
Task 2 and remain unchanged here.

- [ ] **Step 4: Run workflow tests**

Run: `uv run pytest tests/workflows -q`

Expected: all workflow tests pass; second write preparation never invokes a fake model runner.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/workflows tests/workflows
git commit -m "feat: gate workflows on pending reviews"
```

---

### Task 6: Define Stable Application Contracts and Errors

**Files:**
- Create: `src/bundlewalker/application/__init__.py`
- Create: `src/bundlewalker/application/contracts.py`
- Create: `src/bundlewalker/application/errors.py`
- Create: `tests/application/__init__.py`
- Create: `tests/application/test_contracts.py`

**Interfaces:**
- Produces the exact Pydantic contracts used by CLI, MCP, and the later web plan.
- Produces `ApplicationErrorCode`, `ApplicationError`, and `translate_error`.
- Consumes existing `Citation`, `LintFinding`, transaction review enums, and bounded core errors.

- [ ] **Step 1: Write failing strict-contract and translation tests**

```python
def test_inline_source_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        InlineSource.model_validate(
            {"source_name": "notes.md", "content": "text\n", "path": "/tmp/notes.md"}
        )


def test_review_pending_error_maps_without_parsing_message() -> None:
    mapped = translate_error(ReviewPendingError("a" * 32))

    assert mapped.code is ApplicationErrorCode.REVIEW_PENDING
    assert mapped.review_id == "a" * 32
    assert mapped.retryable is False
    assert "a" * 32 in mapped.safe_message


def test_application_error_redacts_absolute_paths() -> None:
    mapped = translate_error(WorkspaceError("could not read /tmp/private-source.md"))

    assert mapped.safe_message == "workspace operation failed"
    assert "/tmp" not in mapped.safe_message
```

Add model-validation cases for all result discriminators and maximum input lengths.

- [ ] **Step 2: Run application contract tests**

Run: `uv run pytest tests/application/test_contracts.py -q`

Expected: import failure because the application package does not exist.

- [ ] **Step 3: Create strict request/result models**

Use `ConfigDict(extra="forbid")` on every request/result. Define these exact public names in
`contracts.py`:

```python
MAX_QUESTION_CHARACTERS = 20_000
MAX_SEARCH_CHARACTERS = 2_000
MAX_SOURCE_NAME_CHARACTERS = 255
MAX_INLINE_SOURCE_CHARACTERS = 1_000_000
MAX_CONCEPT_PAGE_SIZE = 100


class InlineSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_name: str = Field(min_length=1, max_length=MAX_SOURCE_NAME_CHARACTERS)
    content: str = Field(max_length=MAX_INLINE_SOURCE_CHARACTERS)


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(min_length=32, max_length=32)
    kind: ReviewKind
    status: ReviewStatus
    summary: str
    diff: str
    changed_paths: tuple[str, ...]
    created_at: datetime
    resource_uri: str


class PendingReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(min_length=32, max_length=32)
    kind: ReviewKind
    status: ReviewStatus
    summary: str


class PendingReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review: ReviewResult | None


class MutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str
    status: Literal["applied", "discarded"]


class WorkspaceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str
    config_version: int
    concept_counts: dict[str, int]
    pending_review: PendingReviewSummary | None


class ConceptSummaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    concept_id: str
    type: str
    title: str
    description: str
    tags: tuple[str, ...]
    resource_uri: str


class ConceptContent(ConceptSummaryResult):
    markdown: str
    digest: str


class ConceptPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: tuple[ConceptSummaryResult, ...]
    next_cursor: str | None


class ConceptSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: tuple[ConceptSummaryResult, ...]


class AnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: CitedAnswer
    markdown: str


class LintResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: tuple[LintFinding, ...]
    deterministic_has_errors: bool


class IngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["duplicate", "pending"]
    review: ReviewResult | None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if (self.status == "pending") != (self.review is not None):
            raise ValueError("pending ingestion must contain exactly one review")
        return self


class SynthesisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: AnswerResult
    review: ReviewResult


class RefreshResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["current", "pending"]
    concept_id: str
    answer: AnswerResult
    review: ReviewResult | None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if (self.status == "pending") != (self.review is not None):
            raise ValueError("pending refresh must contain exactly one review")
        return self
```

Import `Self`, `CitedAnswer`, and `LintFinding`. Never expose `Path`, repository, model, runner, or
transaction objects through these result models.

- [ ] **Step 4: Create closed error codes and typed translation**

In `errors.py`, define the closed enum exactly as approved:

```python
class ApplicationErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    CONFIGURATION_ERROR = "configuration_error"
    WORKSPACE_ERROR = "workspace_error"
    CONCEPT_NOT_FOUND = "concept_not_found"
    OKF_ERROR = "okf_error"
    CHANGE_INVALID = "change_invalid"
    MODEL_FAILED = "model_failed"
    REVIEW_PENDING = "review_pending"
    REVIEW_NOT_FOUND = "review_not_found"
    REVIEW_ID_MISMATCH = "review_id_mismatch"
    REVIEW_STALE = "review_stale"
    TRANSACTION_FAILED = "transaction_failed"


@dataclass(frozen=True, slots=True)
class ApplicationError(Exception):
    code: ApplicationErrorCode
    safe_message: str
    retryable: bool = False
    review_id: str | None = None

    def __str__(self) -> str:
        return self.safe_message


def translate_error(error: BundleWalkerError) -> ApplicationError:
    if isinstance(error, ReviewPendingError):
        return ApplicationError(
            ApplicationErrorCode.REVIEW_PENDING,
            str(error),
            review_id=error.review_id,
        )
    if isinstance(error, ReviewNotFoundError):
        return ApplicationError(ApplicationErrorCode.REVIEW_NOT_FOUND, str(error))
    if isinstance(error, ReviewMismatchError):
        return ApplicationError(ApplicationErrorCode.REVIEW_ID_MISMATCH, str(error))
    if isinstance(error, ReviewStaleError):
        return ApplicationError(ApplicationErrorCode.REVIEW_STALE, str(error))
    if isinstance(error, ConfigurationError):
        return ApplicationError(
            ApplicationErrorCode.CONFIGURATION_ERROR,
            _public_message(error, "workspace configuration is invalid"),
        )
    if isinstance(error, UsageError):
        return ApplicationError(
            ApplicationErrorCode.INVALID_INPUT,
            _public_message(error, "invalid input"),
        )
    if isinstance(error, WorkspaceError):
        return ApplicationError(
            ApplicationErrorCode.WORKSPACE_ERROR,
            _public_message(error, "workspace operation failed"),
        )
    if isinstance(error, OkfError):
        return ApplicationError(
            ApplicationErrorCode.OKF_ERROR,
            _public_message(error, "knowledge bundle operation failed"),
        )
    if isinstance(error, ChangeSetError):
        return ApplicationError(
            ApplicationErrorCode.CHANGE_INVALID,
            _public_message(error, "proposed change is invalid"),
        )
    if isinstance(error, AgentRunError):
        return ApplicationError(
            ApplicationErrorCode.MODEL_FAILED,
            _public_message(error, "model-backed operation failed"),
            retryable=True,
        )
    if isinstance(error, TransactionError):
        return ApplicationError(
            ApplicationErrorCode.TRANSACTION_FAILED,
            _public_message(error, "transaction operation failed"),
        )
    return ApplicationError(
        ApplicationErrorCode.WORKSPACE_ERROR,
        "BundleWalker operation failed",
    )


def _public_message(error: BundleWalkerError, fallback: str) -> str:
    message = str(error)
    if (
        not message
        or len(message) > 1_024
        or any(unicodedata.category(character) == "Cc" for character in message)
    ):
        return fallback
    for token in message.split():
        candidate = token.strip("'\"()[]{}<>,;:")
        if (
            Path(candidate).is_absolute()
            or PureWindowsPath(candidate).is_absolute()
            or candidate.startswith(("~/", "file:"))
        ):
            return fallback
    return message
```

Import `Path`, `PureWindowsPath`, and `unicodedata`. Never include exception repr, chained provider
data, source content, absolute paths, or control characters in a public or fallback message.

- [ ] **Step 5: Run contract tests and strict type checking**

Run: `uv run pytest tests/application/test_contracts.py -q && uv run pyright`

Expected: contract tests pass and Pyright reports zero errors.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/application tests/application
git commit -m "feat: define application boundary contracts"
```

---

### Task 7: Implement Read-only Application Use Cases

**Files:**
- Create: `src/bundlewalker/application/facade.py`
- Modify: `src/bundlewalker/application/__init__.py`
- Test: `tests/application/test_facade.py`

**Interfaces:**
- Produces async `WorkspaceApplication.status`, `list_concepts`, `read_concept`, `search_concepts`, `ask`, `lint`, and `get_pending_review`.
- Produces opaque cursor helpers private to the facade.
- Consumes current workflow runner injection points so tests stay offline.

- [ ] **Step 1: Write failing facade tests**

Create a workspace with two concepts and test status counts, 1-item cursor pagination, missing
concept translation, lexical search, fake-runner ask, deterministic lint, and pending-review
inspection. Include:

```python
async def test_list_concepts_uses_opaque_cursor_without_duplicates(
    application: WorkspaceApplication,
) -> None:
    first = await application.list_concepts(limit=1)
    second = await application.list_concepts(cursor=first.next_cursor, limit=1)

    assert len(first.items) == 1
    assert len(second.items) == 1
    assert first.items[0].concept_id != second.items[0].concept_id
    assert first.next_cursor is not None


async def test_read_only_ask_works_while_review_is_pending(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    result = await application_with_pending_review.ask(
        "What do agents use?",
        explicit_model="test:model",
    )

    assert result.answer.body.startswith("# Answer")
    assert (await application_with_pending_review.get_pending_review()) is not None
```

- [ ] **Step 2: Run facade tests**

Run: `uv run pytest tests/application/test_facade.py -q`

Expected: import failure because `WorkspaceApplication` does not exist.

- [ ] **Step 3: Add dependency injection and async facade**

Define the dependency record exactly as below. Keep workflow module imports rather than captured
production function aliases so current monkeypatch-based tests remain effective.

```python
def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ApplicationDependencies:
    environment: Mapping[str, str] | None = None
    ingestion_runner: ingest_workflow.IngestionRunner | None = None
    query_runner: ask_workflow.QueryRunner | None = None
    refresh_runner: ask_workflow.RefreshQueryRunner | None = None
    semantic_lint_runner: lint_workflow.SemanticLintRunner | None = None
    clock: Callable[[], datetime] = _utc_now
```

Create this exact facade surface and concrete read implementations:

```python
class WorkspaceApplication:
    def __init__(
        self,
        workspace: Workspace,
        dependencies: ApplicationDependencies | None = None,
    ) -> None:
        self.workspace = workspace
        self.dependencies = dependencies or ApplicationDependencies()

    async def status(self) -> WorkspaceStatus:
        try:
            recover_transactions(self.workspace)
            documents = OkfRepository(self.workspace.wiki_dir).scan().values()
            counts = Counter(document.metadata.type for document in documents)
            pending = get_pending_review(self.workspace)
            return WorkspaceStatus(
                display_name=self.workspace.root.name,
                config_version=self.workspace.config.version,
                concept_counts=dict(sorted(counts.items())),
                pending_review=_to_review_summary(pending),
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def list_concepts(
        self,
        *,
        cursor: str | None = None,
        limit: int = MAX_CONCEPT_PAGE_SIZE,
    ) -> ConceptPage:
        if not 1 <= limit <= MAX_CONCEPT_PAGE_SIZE:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_INPUT,
                f"concept page limit must be between 1 and {MAX_CONCEPT_PAGE_SIZE}",
            )
        try:
            recover_transactions(self.workspace)
            documents = OkfRepository(self.workspace.wiki_dir).scan()
            ordered_ids = sorted(documents)
            start = _cursor_start(ordered_ids, cursor)
            selected = ordered_ids[start : start + limit]
            next_cursor = (
                _encode_cursor(selected[-1])
                if selected and start + limit < len(ordered_ids)
                else None
            )
            return ConceptPage(
                items=tuple(_concept_summary(documents[concept_id]) for concept_id in selected),
                next_cursor=next_cursor,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def read_concept(self, concept_id: str) -> ConceptContent:
        _validate_public_concept_id(concept_id)
        try:
            recover_transactions(self.workspace)
            documents = OkfRepository(self.workspace.wiki_dir).scan()
            document = documents.get(concept_id)
            if document is None:
                raise ApplicationError(
                    ApplicationErrorCode.CONCEPT_NOT_FOUND,
                    f"concept does not exist: {concept_id}",
                )
            summary = _concept_summary(document)
            markdown = document.path.read_text(encoding="utf-8")
            return ConceptContent(
                **summary.model_dump(),
                markdown=markdown,
                digest=document.digest,
            )
        except ApplicationError:
            raise
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc
        except OSError as exc:
            raise ApplicationError(
                ApplicationErrorCode.OKF_ERROR,
                "concept could not be read",
            ) from exc

    async def search_concepts(
        self,
        query: str,
        *,
        concept_type: str | None = None,
        limit: int = 10,
    ) -> ConceptSearchResult:
        if not query.strip() or len(query) > MAX_SEARCH_CHARACTERS:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_INPUT,
                "search query must be non-empty and within the supported limit",
            )
        try:
            recover_transactions(self.workspace)
            repository = OkfRepository(self.workspace.wiki_dir)
            matches = LexicalRetriever(repository).search(query, concept_type, limit)
            documents = repository.scan()
            return ConceptSearchResult(
                items=tuple(
                    _concept_summary(documents[item.concept_id]) for item in matches
                )
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def ask(self, question: str, *, explicit_model: str | None) -> AnswerResult:
        if len(question) > MAX_QUESTION_CHARACTERS:
            raise ApplicationError(
                ApplicationErrorCode.INVALID_INPUT,
                "question exceeds the supported limit",
            )
        try:
            answered = await ask_workflow.answer_question(
                self.workspace,
                question,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.query_runner,
            )
            rendered = ask_workflow.render_cited_answer(
                answered.answer,
                OkfRepository(self.workspace.wiki_dir),
            )
            return AnswerResult(answer=answered.answer, markdown=rendered)
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def lint(self, *, semantic: bool, explicit_model: str | None) -> LintResult:
        try:
            result = await lint_workflow.run_lint(
                self.workspace,
                semantic=semantic,
                explicit_model=explicit_model,
                environment=self.dependencies.environment,
                runner=self.dependencies.semantic_lint_runner,
            )
            return LintResult(
                findings=result.findings,
                deterministic_has_errors=result.deterministic_has_errors,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    async def get_pending_review(self) -> ReviewResult | None:
        try:
            return _to_review_result(get_pending_review(self.workspace))
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc
```

Define `_concept_summary`, `_to_review_summary`, `_to_review_result`, `_encode_cursor`, and
`_cursor_start`, and `_validate_public_concept_id` as focused private helpers in the same file.
`_validate_public_concept_id` applies the same length, control-character, relative
`PurePosixPath`, `.`/`..`, backslash, and normalized-form rules used by the MCP resource parser and
raises `INVALID_INPUT` with a fixed message. `_to_review_summary` excludes the diff and changed
paths. `_to_review_result(None)` returns `None`; otherwise it maps every persisted field and sets
`resource_uri="bundlewalker://review/pending"`. None of these methods catch
`asyncio.CancelledError`, `KeyboardInterrupt`, or `SystemExit`.

`_concept_summary` maps `concept_id`, metadata type, tags, and
`resource_uri=f"bundlewalker://concept/{quote(document.concept_id, safe='/')}"`; use the final ID
segment when title is absent and the empty string when description is absent. This makes optional
OKF front-matter fields conform to the non-optional public result model without exposing a path.

Cursor encoding is URL-safe base64 of the last concept ID without padding. Decoding restores
padding, rejects invalid UTF-8/IDs as `INVALID_INPUT`, and resumes strictly after that ID. Limit is
1 through 100. `read_concept` returns full rendered Markdown and
`bundlewalker://concept/<quoted-id>`; it never returns the filesystem path.

- [ ] **Step 4: Run facade tests**

Run: `uv run pytest tests/application/test_facade.py -q`

Expected: all read-use-case tests pass with no network access.

- [ ] **Step 5: Run related workflow and retrieval tests**

Run: `uv run pytest tests/test_retrieval.py tests/workflows/test_ask.py tests/workflows/test_lint.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/application tests/application/test_facade.py
git commit -m "feat: add read-only application facade"
```

---

### Task 8: Implement Preparing and Review-resolution Use Cases

**Files:**
- Modify: `src/bundlewalker/application/facade.py`
- Modify: `src/bundlewalker/application/__init__.py`
- Test: `tests/application/test_facade.py`

**Interfaces:**
- Produces async `prepare_file_ingestion`, `prepare_ingestion`, `prepare_synthesis`, `prepare_refresh`, `apply_review`, and `discard_review`.
- MCP consumes only inline `prepare_ingestion`; CLI consumes `prepare_file_ingestion`.
- Duplicate source and unchanged refresh are successful typed outcomes.

- [ ] **Step 1: Add failing write-use-case tests**

```python
async def test_inline_ingestion_returns_persisted_review_without_live_mutation(
    application: WorkspaceApplication,
) -> None:
    before = _tree_bytes(application.workspace.root)

    result = await application.prepare_ingestion(
        InlineSource(source_name="notes.txt", content="source text\n"),
        explicit_model="test:model",
    )

    assert result.status == "pending"
    assert result.review is not None
    assert result.review.diff
    assert _live_tree_bytes(application.workspace.root) == _live_tree_bytes_from(before)


async def test_review_resolves_exactly_once(application_with_pending_review: WorkspaceApplication) -> None:
    pending = await application_with_pending_review.get_pending_review()
    assert pending is not None

    applied = await application_with_pending_review.apply_review(pending.review_id)

    assert applied.status == "applied"
    with pytest.raises(ApplicationError) as raised:
        await application_with_pending_review.apply_review(pending.review_id)
    assert raised.value.code is ApplicationErrorCode.REVIEW_NOT_FOUND
```

Add cases for file ingestion parity, duplicate source, saved synthesis with one model call, current
refresh, stale apply, wrong ID, discard, and pending preflight.

- [ ] **Step 2: Run write facade tests**

Run: `uv run pytest tests/application/test_facade.py -q`

Expected: failures because write facade methods do not exist.

- [ ] **Step 3: Implement write methods through workflows and persisted review loading**

Implement these concrete methods; keep `_ingestion_result`, `_required_review_result`, and the
persisted-review mappings private to the facade:

```python
async def prepare_file_ingestion(
    self,
    source_path: Path,
    *,
    explicit_model: str | None,
) -> IngestionResult:
    try:
        outcome = await ingest_workflow.prepare_ingestion(
            self.workspace,
            source_path,
            explicit_model=explicit_model,
            environment=self.dependencies.environment,
            runner=self.dependencies.ingestion_runner,
            occurred_at=self.dependencies.clock(),
        )
        return _ingestion_result(self.workspace, outcome)
    except BundleWalkerError as exc:
        raise translate_error(exc) from exc

async def prepare_ingestion(
    self,
    source: InlineSource,
    *,
    explicit_model: str | None,
) -> IngestionResult:
    try:
        recover_transactions(self.workspace)
        raw_source = load_inline_source(source.source_name, source.content, self.workspace)
        outcome = await ingest_workflow.prepare_raw_ingestion(
            self.workspace,
            raw_source,
            explicit_model=explicit_model,
            environment=self.dependencies.environment,
            runner=self.dependencies.ingestion_runner,
            occurred_at=self.dependencies.clock(),
        )
        return _ingestion_result(self.workspace, outcome)
    except BundleWalkerError as exc:
        raise translate_error(exc) from exc

async def prepare_synthesis(
    self,
    question: str,
    *,
    explicit_model: str | None,
) -> SynthesisResult:
    try:
        ensure_no_pending_review(self.workspace)
        answered = await ask_workflow.answer_question(
            self.workspace,
            question,
            explicit_model=explicit_model,
            environment=self.dependencies.environment,
            runner=self.dependencies.query_runner,
        )
        ask_workflow.prepare_synthesis(
            self.workspace,
            answered,
            occurred_at=self.dependencies.clock(),
        )
        review = _required_review_result(self.workspace)
        rendered = ask_workflow.render_cited_answer(
            answered.answer,
            OkfRepository(self.workspace.wiki_dir),
        )
        return SynthesisResult(
            answer=AnswerResult(answer=answered.answer, markdown=rendered),
            review=review,
        )
    except BundleWalkerError as exc:
        raise translate_error(exc) from exc

async def prepare_refresh(
    self,
    instruction: str,
    concept_id: str,
    *,
    explicit_model: str | None,
) -> RefreshResult:
    try:
        ensure_no_pending_review(self.workspace)
        refreshed = await ask_workflow.answer_synthesis_refresh(
            self.workspace,
            instruction,
            concept_id,
            explicit_model=explicit_model,
            environment=self.dependencies.environment,
            runner=self.dependencies.refresh_runner,
        )
        rendered = ask_workflow.render_cited_answer(
            refreshed.answer,
            OkfRepository(self.workspace.wiki_dir),
        )
        answer = AnswerResult(answer=refreshed.answer, markdown=rendered)
        outcome = ask_workflow.prepare_synthesis_refresh(
            self.workspace,
            refreshed,
            occurred_at=self.dependencies.clock(),
        )
        if isinstance(outcome, ask_workflow.SynthesisAlreadyCurrent):
            return RefreshResult(
                status="current",
                concept_id=outcome.concept_id,
                answer=answer,
                review=None,
            )
        return RefreshResult(
            status="pending",
            concept_id=refreshed.target.concept_id,
            answer=answer,
            review=_required_review_result(self.workspace),
        )
    except BundleWalkerError as exc:
        raise translate_error(exc) from exc

async def apply_review(self, review_id: str) -> MutationResult:
    try:
        apply_pending_review(self.workspace, review_id)
        return MutationResult(review_id=review_id, status="applied")
    except BundleWalkerError as exc:
        raise translate_error(exc) from exc

async def discard_review(self, review_id: str) -> MutationResult:
    try:
        discard_pending_review(self.workspace, review_id)
        return MutationResult(review_id=review_id, status="discarded")
    except BundleWalkerError as exc:
        raise translate_error(exc) from exc
```

`_ingestion_result` returns `IngestionResult(status="duplicate", review=None)` for
`DuplicateIngestion`; otherwise it returns `status="pending"` with `_required_review_result`.
`_required_review_result` loads persisted state and raises `TransactionError` if workflow
preparation returned without one. Never construct the public diff from the old in-memory handle.

- [ ] **Step 4: Run application and workflow tests**

Run: `uv run pytest tests/application tests/workflows -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/application tests/application/test_facade.py
git commit -m "feat: add reviewed application use cases"
```

---

### Task 9: Migrate the CLI and Add Review Recovery Commands

**Files:**
- Create: `src/bundlewalker/interfaces/__init__.py`
- Create: `src/bundlewalker/interfaces/cli.py`
- Replace: `src/bundlewalker/cli.py`
- Create: `tests/cli/test_review.py`
- Modify: `tests/cli/test_ingest.py`
- Modify: `tests/cli/test_ask.py`
- Modify: `tests/cli/test_lint.py`

**Interfaces:**
- `src/bundlewalker/cli.py` remains an import-compatible re-export of `app` and `main`.
- Existing commands use `WorkspaceApplication`.
- Adds `bundlewalker review show|apply|discard`.

- [ ] **Step 1: Add failing review-command tests and retain current CLI snapshots**

```python
def test_review_show_apply_survives_new_cli_invocation(
    cli_workspace_with_pending_review: tuple[Path, str],
) -> None:
    root, review_id = cli_workspace_with_pending_review

    shown = runner.invoke(app, ["review", "show"])
    applied = runner.invoke(app, ["review", "apply", review_id])

    assert shown.exit_code == 0
    assert review_id in shown.output
    assert "--- wiki/" in shown.output
    assert applied.exit_code == 0
    assert "Changes applied." in applied.output
    assert not list((root / ".bundlewalker" / "transactions").glob("*/manifest.json"))


def test_write_command_reports_existing_review_before_model(
    cli_workspace_with_pending_review: tuple[Path, str],
) -> None:
    _root, review_id = cli_workspace_with_pending_review

    result = runner.invoke(app, ["ask", "question", "--save", "--model", "test:model"])

    assert result.exit_code == 1
    assert review_id in result.output
    assert "bundlewalker review show" in result.output
```

Retain all current CLI tests as compatibility assertions; do not update expected user-facing copy
unless the approved design explicitly adds review recovery guidance.

- [ ] **Step 2: Run CLI tests**

Run: `uv run pytest tests/cli -q`

Expected: review-command tests fail because the group does not exist.

- [ ] **Step 3: Move the adapter and preserve imports**

Create `interfaces/cli.py` from current CLI behavior, route shared operations through a
`WorkspaceApplication`, and leave this exact shim in `src/bundlewalker/cli.py`:

```python
from bundlewalker.interfaces.cli import app, main

__all__ = ["app", "main"]
```

Keep `init` directly on deterministic initialization. For ingest/save/refresh, call the facade to
prepare, print the persisted `ReviewResult`, use the current prompt, then call facade apply/discard.
Plain ask and lint render the corresponding facade result without changing copy or exit behavior.

- [ ] **Step 4: Add the Typer review group**

Register `review_app = typer.Typer(no_args_is_help=True)` under `review`. Implement:

```python
@review_app.command("show")
def review_show(context: typer.Context) -> None:
    application = WorkspaceApplication(current_workspace(context))
    review = asyncio.run(application.get_pending_review())
    if review is None:
        typer.echo("No pending review.")
        return
    _render_review(review)


@review_app.command("apply")
def review_apply(context: typer.Context, review_id: str) -> None:
    application = WorkspaceApplication(current_workspace(context))
    asyncio.run(application.apply_review(review_id))
    typer.echo("Changes applied.")


@review_app.command("discard")
def review_discard(context: typer.Context, review_id: str) -> None:
    application = WorkspaceApplication(current_workspace(context))
    asyncio.run(application.discard_review(review_id))
    typer.echo("No changes applied.")
```

Map `ApplicationErrorCode` to existing CLI exit classes without exposing adapter-independent
internals. `review_pending` output must include the safe ID and the three recovery commands.

- [ ] **Step 5: Run CLI and acceptance tests**

Run: `uv run pytest tests/cli tests/test_acceptance.py -q`

Expected: all old CLI behavior and new recovery commands pass.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/cli.py src/bundlewalker/interfaces tests/cli tests/test_acceptance.py
git commit -m "feat: route CLI through application facade"
```

---

### Task 10: Add the Stable MCP SDK and Static Schemas

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/bundlewalker/interfaces/mcp_schemas.py`
- Create: `tests/interfaces/__init__.py`
- Create: `tests/interfaces/test_mcp_tools.py`

**Interfaces:**
- Adds runtime dependency `mcp>=1.28.1,<2` and script name reserved for Task 14.
- Produces strict MCP input models and static `ToolSpec` metadata for all ten tools.
- No server transport is started in this task.

- [ ] **Step 1: Add failing schema and annotation tests**

```python
def test_mcp_tool_specs_have_unique_names_and_closed_schemas() -> None:
    assert [spec.name for spec in TOOL_SPECS] == [
        "workspace_status",
        "search_concepts",
        "ask",
        "lint",
        "prepare_ingestion",
        "prepare_synthesis",
        "prepare_refresh",
        "get_pending_review",
        "apply_review",
        "discard_review",
    ]
    assert all(
        spec.input_model.model_json_schema()["additionalProperties"] is False
        for spec in TOOL_SPECS
    )


def test_model_backed_tool_annotations_are_open_world() -> None:
    by_name = {spec.name: spec for spec in TOOL_SPECS}
    assert by_name["ask"].annotations.openWorldHint is True
    assert by_name["lint"].annotations.openWorldHint is True
    assert by_name["prepare_ingestion"].annotations.openWorldHint is True
    assert by_name["workspace_status"].annotations.openWorldHint is False
```

- [ ] **Step 2: Add the stable SDK dependency**

Run: `uv add 'mcp>=1.28.1,<2'`

Expected: `pyproject.toml` contains the bounded v1 dependency and `uv.lock` resolves a stable 1.x
release, not a 2.0 pre-release.

- [ ] **Step 3: Create strict input models and `ToolSpec`**

Define `EmptyInput`, `SearchInput`, `AskInput`, `LintInput`, `PrepareIngestionInput`,
`PrepareSynthesisInput`, `PrepareRefreshInput`, and `ReviewIdInput`. Every model uses
`ConfigDict(extra="forbid")`. Import `ConceptType` and `MAX_CONCEPT_ID_CHARACTERS` from
`domain.py`, plus the approved question, search, inline-content, and source-name bounds from
application contracts. Use these exact field sets so no MCP write input can acquire local-path or
workspace-path authority:

```python
MAX_MODEL_NAME_CHARACTERS = 255


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=MAX_SEARCH_CHARACTERS)
    concept_type: ConceptType | None = None
    limit: int = Field(default=10, ge=1, le=10)


class AskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class LintInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic: bool = False
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class PrepareIngestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_name: str = Field(min_length=1, max_length=MAX_SOURCE_NAME_CHARACTERS)
    content: str = Field(max_length=MAX_INLINE_SOURCE_CHARACTERS)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class PrepareSynthesisInput(AskInput):
    pass


class PrepareRefreshInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=MAX_QUESTION_CHARACTERS)
    concept_id: str = Field(min_length=1, max_length=MAX_CONCEPT_ID_CHARACTERS)
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MODEL_NAME_CHARACTERS,
    )


class ReviewIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(pattern=r"^[0-9a-f]{32}$")
```

```python
@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    annotations: ToolAnnotations
```

Populate `TOOL_SPECS` in the exact order tested. Use explicit annotations: read-only/closed-world
for status/search/get; read-only/open-world for ask/lint; non-read-only/non-destructive/open-world
for prepare tools; destructive/closed-world for apply/discard. Do not set task support.
Use `PendingReviewResult` as the output model for `get_pending_review`, so the no-review case still
has an object-root output schema.

Map input/output models exactly as follows: `workspace_status` uses `EmptyInput`/`WorkspaceStatus`;
`search_concepts` uses `SearchInput`/`ConceptSearchResult`; `ask` uses `AskInput`/`AnswerResult`;
`lint` uses `LintInput`/`LintResult`; the three prepare tools use their matching input and
`IngestionResult`, `SynthesisResult`, or `RefreshResult`; `get_pending_review` uses
`EmptyInput`/`PendingReviewResult`; and both review-resolution tools use
`ReviewIdInput`/`MutationResult`.

- [ ] **Step 4: Run schema tests and lock check**

Run: `uv run pytest tests/interfaces/test_mcp_tools.py -q && uv lock --check`

Expected: all schema tests pass and the lock is current.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/bundlewalker/interfaces/mcp_schemas.py tests/interfaces
git commit -m "build: add stable MCP SDK contracts"
```

---

### Task 11: Expose Paginated Concept and Pending-review Resources

**Files:**
- Create: `src/bundlewalker/interfaces/mcp.py`
- Create: `tests/interfaces/test_mcp_resources.py`

**Interfaces:**
- Produces `create_mcp_server(application: WorkspaceApplication) -> Server[None]`.
- Registers dynamic `resources/list`, `resources/templates/list`, and `resources/read` handlers.
- Uses `bundlewalker://concept/{+concept_id}` and `bundlewalker://review/pending`.

- [ ] **Step 1: Write failing in-memory protocol resource tests**

Use the SDK's `create_connected_server_and_client_session` helper:

```python
async def test_mcp_lists_and_reads_concept_resources(application: WorkspaceApplication) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        listed = await session.list_resources()
        uri = next(resource.uri for resource in listed.resources if "topics/agents" in str(resource.uri))
        read = await session.read_resource(uri)

    content = read.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert content.mimeType == "text/markdown"
    assert "# Agents" in content.text


async def test_pending_review_resource_contains_exact_persisted_diff(
    application_with_pending_review: WorkspaceApplication,
) -> None:
    expected = await application_with_pending_review.get_pending_review()
    assert expected is not None
    server = create_mcp_server(application_with_pending_review)

    async with create_connected_server_and_client_session(server) as session:
        read = await session.read_resource(AnyUrl("bundlewalker://review/pending"))

    content = read.contents[0]
    assert isinstance(content, types.TextResourceContents)
    assert expected.diff in content.text
```

Add pagination, invalid URI, missing concept, no-pending-review, and template-list cases.

- [ ] **Step 2: Run MCP resource tests**

Run: `uv run pytest tests/interfaces/test_mcp_resources.py -q`

Expected: import failure because `create_mcp_server` does not exist.

- [ ] **Step 3: Build a low-level server and dynamic handlers**

Create `Server[None]("bundlewalker")`. Register `@server.list_resources()` with the request form so
the incoming cursor reaches `application.list_concepts(cursor=request.params.cursor, limit=100)`.
Return `types.ListResourcesResult` with concept `types.Resource` values, plus the pending resource
on the first page when present. Set `nextCursor` from the application page.

Register this exact template:

```python
types.ResourceTemplate(
    name="bundlewalker-concept",
    title="BundleWalker concept",
    uriTemplate="bundlewalker://concept/{+concept_id}",
    description="Read one OKF concept from the bound BundleWalker workspace.",
    mimeType="text/markdown",
)
```

Use `urlsplit` and `unquote` to parse URIs. Reject any authority other than `concept` or `review`,
any query/fragment, and any review path other than `/pending`. A decoded concept ID is safe only
when it is 1 through `MAX_CONCEPT_ID_CHARACTERS` characters, contains neither `\\` nor Unicode
control characters, is a relative `PurePosixPath`, contains no `.` or `..` component, and equals
its own `PurePosixPath.as_posix()` normalization. Concept reads return
`ReadResourceContents(content=concept.markdown, mime_type="text/markdown")`; pending review reads
return `ReadResourceContents(content=_render_pending_review(review),
mime_type="text/markdown")`. Map `ApplicationError` to a bounded `ValueError` for resource protocol
handling without filesystem paths.

- [ ] **Step 4: Run MCP resource tests**

Run: `uv run pytest tests/interfaces/test_mcp_resources.py -q`

Expected: all dynamic resource, pagination, and error cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/mcp.py tests/interfaces/test_mcp_resources.py
git commit -m "feat: expose BundleWalker MCP resources"
```

---

### Task 12: Implement Read-only MCP Tools with Structured Results

**Files:**
- Create: `src/bundlewalker/interfaces/mcp_tools.py`
- Modify: `src/bundlewalker/interfaces/mcp.py`
- Modify: `tests/interfaces/test_mcp_tools.py`

**Interfaces:**
- Registers `tools/list` and `tools/call` for status, search, ask, lint, and pending-review read.
- Returns both bounded human-readable `TextContent` and validated `structuredContent`.
- Domain failures use `CallToolResult(isError=True)` rather than JSON-RPC protocol errors.

- [ ] **Step 1: Add failing read-tool protocol tests**

```python
async def test_workspace_status_tool_returns_structured_and_text_content(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("workspace_status", {})

    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["display_name"] == application.workspace.root.name
    assert result.content[0].type == "text"


async def test_invalid_search_is_a_tool_execution_error(application: WorkspaceApplication) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool("search_concepts", {"query": "", "limit": 10})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["error"]["code"] == "invalid_input"
```

Add fake-runner ask, deterministic lint, semantic lint, get-pending, unknown tool, and tool output
schema assertions.

- [ ] **Step 2: Run read-tool tests**

Run: `uv run pytest tests/interfaces/test_mcp_tools.py -q`

Expected: failures because tool handlers are not registered.

- [ ] **Step 3: Generate protocol tool definitions from static specs**

Convert each `ToolSpec` to `types.Tool` with `inputSchema`, `outputSchema`, descriptions, and exact
annotations. Register a low-level `@server.list_tools()` returning the ten definitions even before
all dispatch branches are implemented; unknown calls return a bounded error result.

Implement reusable result helpers:

```python
def success_result(model: BaseModel, text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=model.model_dump(mode="json"),
        isError=False,
    )


def error_result(error: ApplicationError) -> types.CallToolResult:
    payload = {
        "error": {
            "code": error.code.value,
            "message": error.safe_message,
            "retryable": error.retryable,
            "review_id": error.review_id,
        }
    }
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=error.safe_message)],
        structuredContent=payload,
        isError=True,
    )
```

Register `@server.call_tool(validate_input=False)` so BundleWalker, not the SDK's generic validator,
owns input-error envelopes. Parse arguments with the corresponding Pydantic input model; catch
`ValidationError` and return `error_result(ApplicationError(INVALID_INPUT, "invalid tool input"))`.
Dispatch the five read tools to the
facade. Wrap the optional facade value for `get_pending_review` as
`PendingReviewResult(review=await application.get_pending_review())`; never return JSON `null` at
the structured-content root. Render answer text with its validated Markdown/citations, lint text
with one bounded line per finding, and pending review text with ID, summary, and exact diff. Catch
`ApplicationError` and return `error_result`. Catch other `Exception` values only to log the full
trace through the module logger and return a generic `workspace_error` result with message
`BundleWalker operation failed`; do not catch `asyncio.CancelledError` or any other
`BaseException`.

- [ ] **Step 4: Run MCP read-tool tests**

Run: `uv run pytest tests/interfaces/test_mcp_tools.py -q`

Expected: all read-tool, schema, annotation, and domain-error cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/bundlewalker/interfaces/mcp.py src/bundlewalker/interfaces/mcp_tools.py tests/interfaces/test_mcp_tools.py
git commit -m "feat: add read-only MCP tools"
```

---

### Task 13: Add MCP Preparation, Apply, Discard, Progress, and Cancellation

**Files:**
- Modify: `src/bundlewalker/interfaces/mcp_tools.py`
- Modify: `tests/interfaces/test_mcp_tools.py`

**Interfaces:**
- Implements `prepare_ingestion`, `prepare_synthesis`, `prepare_refresh`, `apply_review`, and `discard_review`.
- Uses inline source content only.
- Sends start/complete progress when the request contains `_meta.progressToken`.
- Lets cancellation propagate; persisted reviews remain discoverable.

- [ ] **Step 1: Add failing two-step write-tool tests**

```python
async def test_prepare_then_apply_uses_two_explicit_tool_calls(
    application: WorkspaceApplication,
) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        prepared = await session.call_tool(
            "prepare_ingestion",
            {"source_name": "notes.txt", "content": "evidence\n", "model": "test:model"},
        )
        assert prepared.structuredContent is not None
        review_id = prepared.structuredContent["review"]["review_id"]
        assert _tree_bytes(application.workspace.raw_dir) == {}
        applied = await session.call_tool("apply_review", {"review_id": review_id})

    assert prepared.isError is False
    assert prepared.structuredContent is not None
    assert prepared.structuredContent["review"]["diff"]
    assert applied.structuredContent is not None
    assert applied.structuredContent["status"] == "applied"


async def test_mcp_ingestion_has_no_path_argument(application: WorkspaceApplication) -> None:
    server = create_mcp_server(application)

    async with create_connected_server_and_client_session(server) as session:
        result = await session.call_tool(
            "prepare_ingestion",
            {"source_name": "notes.txt", "content": "text\n", "path": "/tmp/secret"},
        )

    assert result.isError is True
```

Add prepare/restart-load behavior in memory, discard, wrong ID, stale apply, saved synthesis one
model call, unchanged refresh, pending-before-provider, progress callback, cancellation before
persistence, and cancellation immediately after persistence.

- [ ] **Step 2: Run write-tool tests**

Run: `uv run pytest tests/interfaces/test_mcp_tools.py -q`

Expected: write-tool calls return unknown-tool or unimplemented errors.

- [ ] **Step 3: Dispatch all write tools through the facade**

Validate `PrepareIngestionInput` into `InlineSource`; never convert `source_name` into a local path.
Dispatch all five write tools. Preparation text includes the opaque ID, summary, exact complete
diff, and `bundlewalker://review/pending`. Apply/discard require only the exact 32-character ID.

Do not catch `asyncio.CancelledError`. Existing workflow and transaction cleanup handles
cancellation before persistence; after persistence, the durable review remains visible through
`get_pending_review` and the pending resource.

- [ ] **Step 4: Report coarse standard progress without MCP tasks**

In the low-level call handler, read
`server.request_context.meta.progressToken` when `server.request_context.meta` is present. The SDK
decorator passes only the tool name and arguments into the handler, so do not try to read a request
parameter that is absent from that callback signature. For model-backed tools, send `0/1` before
facade dispatch and `1/1` after a successful return:

```python
async def report_progress(
    server: Server[None],
    token: str | int | None,
    progress: float,
    message: str,
) -> None:
    if token is None:
        return
    await server.request_context.session.send_progress_notification(
        progress_token=token,
        progress=progress,
        total=1.0,
        message=message,
    )
```

Do not advertise experimental task support. Apply/discard are synchronous from the protocol's
perspective and rely on transaction recovery if the process disappears.

- [ ] **Step 5: Run all MCP in-memory tests**

Run: `uv run pytest tests/interfaces/test_mcp_resources.py tests/interfaces/test_mcp_tools.py -q`

Expected: all resource and tool tests pass offline.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/interfaces/mcp_tools.py tests/interfaces/test_mcp_tools.py
git commit -m "feat: add reviewed MCP write tools"
```

---

### Task 14: Add the Workspace-bound `stdio` Entry Point and Subprocess Tests

**Files:**
- Modify: `src/bundlewalker/interfaces/mcp.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/interfaces/test_mcp_stdio.py`

**Interfaces:**
- Produces console script `bundlewalker-mcp = bundlewalker.interfaces.mcp:main`.
- Startup accepts optional `--workspace PATH`; default is normal discovery from the process CWD.
- No MCP tool accepts or changes the workspace path.

- [ ] **Step 1: Add failing subprocess transport tests**

```python
async def test_stdio_entrypoint_binds_workspace_without_stdout_noise(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "bundlewalker.interfaces.mcp",
            "--workspace",
            str(workspace.root),
        ],
        env=os.environ.copy(),
    )

    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("workspace_status", {})

    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["display_name"] == workspace.root.name
```

Add deterministic lint and resource-read subprocess smoke tests. Also create a pending review with
the transaction fixture, inspect it through one subprocess MCP session, close that process, and
inspect the same review ID and exact diff through a second subprocess session before discarding it
in the parent. This proves restart preservation without credentials. Do not invoke model-backed
tools in subprocess tests; those are covered with injected fake runners in memory.

- [ ] **Step 2: Run stdio tests**

Run: `uv run pytest tests/interfaces/test_mcp_stdio.py -q`

Expected: failure because module execution and console entry point are not implemented.

- [ ] **Step 3: Implement startup parsing and `stdio` serving**

Use `argparse` so help/errors go to the correct streams. Resolve the workspace once:

```python
async def serve_stdio(application: WorkspaceApplication) -> None:
    server = create_mcp_server(application)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(
                    prompts_changed=False,
                    resources_changed=False,
                    tools_changed=False,
                ),
                experimental_capabilities={},
            ),
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bundlewalker-mcp")
    parser.add_argument("--workspace", type=Path)
    arguments = parser.parse_args(argv)
    workspace = discover_workspace(arguments.workspace)
    asyncio.run(serve_stdio(WorkspaceApplication(workspace)))


if __name__ == "__main__":
    main()
```

Catch bounded startup `BundleWalkerError` before the protocol loop, print only `Error: <safe
message>` to stderr, and exit with its current exit code. After the loop starts, never print to
stdout.

- [ ] **Step 4: Register the console script and refresh the lock**

Add under `[project.scripts]`:

```toml
bundlewalker = "bundlewalker.cli:app"
bundlewalker-mcp = "bundlewalker.interfaces.mcp:main"
```

Run: `uv lock`

Expected: lock refresh succeeds without selecting MCP 2.x.

- [ ] **Step 5: Run all interface tests and live help**

Run: `uv run pytest tests/interfaces -q`

Run: `uv run bundlewalker-mcp --help`

Expected: all tests pass; help lists only `--workspace` and standard help.

- [ ] **Step 6: Commit**

```bash
git add src/bundlewalker/interfaces/mcp.py pyproject.toml uv.lock tests/interfaces/test_mcp_stdio.py
git commit -m "feat: add workspace-bound MCP stdio server"
```

---

### Task 15: Document MCP Setup and Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `CONTRIBUTING.md`
- Modify: `docs/superpowers/plans/2026-07-16-end-user-guide.md` embedded user-guide block
- Test: full repository

**Interfaces:**
- Documents only shipped commands and tool/resource contracts.
- Removes MCP server from the README's v1 non-goal list and keeps hosted/remote service out of scope.
- Preserves the repository's user-guide embedding synchronization contract.

- [ ] **Step 1: Capture live help and tool metadata before writing prose**

Run:

```bash
uv run bundlewalker --help
uv run bundlewalker review --help
uv run bundlewalker-mcp --help
uv run python - <<'PY'
from bundlewalker.interfaces.mcp_schemas import TOOL_SPECS
for spec in TOOL_SPECS:
    print(spec.name, spec.annotations.model_dump(exclude_none=True))
PY
```

Expected: current help and all ten tools print successfully. Use this output as the documentation
authority; do not infer syntax from the design document.

- [ ] **Step 2: Update README and user guide**

Document:

- configuring a local MCP host to run `uv run --project PROJECT_ROOT bundlewalker-mcp --workspace WORKSPACE`;
- the workspace-bound/no-path security model;
- concept and pending-review resources;
- all ten tools, which ones may call a provider, and which mutate private or live state;
- the explicit prepare → inspect → apply/discard flow;
- inline `.md`/`.txt` source names and UTF-8 content;
- restart behavior, stale reviews, and CLI `review show|apply|discard` recovery; and
- the fact that the default suite remains offline.

Update `CONTRIBUTING.md` architecture and test-layer tables. Update the embedded canonical user
guide in `docs/superpowers/plans/2026-07-16-end-user-guide.md` byte-for-byte, including its final
newline.

- [ ] **Step 3: Verify documentation links and embedded synchronization**

Run the repository's existing embedded-user-guide equality check or its owning documentation test.
Also run a local Markdown-link check that resolves every relative link from its containing file.

Expected: no missing local links and exact embedded user-guide equality.

- [ ] **Step 4: Run the complete offline suite**

Run: `uv run pytest -m 'not eval' -q`

Expected: all tests pass with no credentials and no network access.

- [ ] **Step 5: Run formatting, lint, typing, and diff checks**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
git diff --check
```

Expected: every command exits zero with no warnings or errors.

- [ ] **Step 6: Review scope and commit**

Run: `git status --short && git diff --stat && git diff`

Confirm the diff contains no credentials, private source content, remote transport, web server,
plugin framework, or MCP v2 pre-release.

```bash
git add README.md docs/user-guide.md CONTRIBUTING.md \
  docs/superpowers/plans/2026-07-16-end-user-guide.md
git commit -m "docs: add local MCP server guide"
```

---

## Completion Criteria

- Existing CLI behavior is compatible and all CLI commands route shared operations through the application facade.
- `bundlewalker review show|apply|discard` recovers durable pending reviews.
- Schema-v2 pending reviews survive restart; schema-v1 recovery remains safe.
- One workspace can never persist two pending reviews.
- Apply records acceptance before live mutation and remains recoverable at every phase.
- `bundlewalker-mcp` runs locally over `stdio`, binds one workspace, and emits no non-protocol stdout.
- Concept resources are paginated and pending review exposes the exact persisted complete diff.
- All ten MCP tools have strict input/output schemas, correct annotations, and structured results.
- MCP ingestion has no local-path or workspace-path field.
- Prepare and apply/discard are separate MCP calls.
- Default tests are offline, formatting/lint/type checks pass, and documentation matches live behavior.
- The local web UI remains unimplemented and receives its own plan after this milestone.
