# BundleWalker Doctor Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline, read-only `bundlewalker doctor [PATH] [--report REPORT.json]` command with stable diagnostics, actionable remediation, safe exit semantics, and an opt-in versioned JSON support report.

**Architecture:** Introduce strict diagnostic contracts and a focused synchronous `DiagnosticsApplication` that coordinates runtime, workspace, model/credential, transaction, MCP, and storage inspectors. Keep transaction classification beside transaction internals, and keep terminal rendering plus exclusive report-file creation in a small CLI adapter so diagnostic policy remains reusable and testable.

**Tech Stack:** Python 3.13/3.14, Pydantic v2, Typer, pytest, standard-library filesystem/import/metadata APIs, Ruff, Pyright, uv, Twine.

## Global Constraints

- Plain `bundlewalker doctor` is offline and byte-for-byte read-only; it never creates, repairs, recovers, deletes, renames, fsyncs, or otherwise mutates workspace state.
- `doctor --report REPORT.json` writes only the explicitly authorized new report file and performs no workspace mutation.
- The report writer refuses every existing target, symlink, directory, and missing parent; it never overwrites a path.
- After any post-creation write, `fchmod`, `fsync`, or close failure, the writer retains the owner-only partial target. Portable macOS and Linux pathname APIs cannot atomically prove that a path still names the created inode, so automatic cleanup could delete an unrelated replacement. The user must inspect and remove the newly created report target when appropriate before retrying.
- Warnings exit `0`; one or more diagnostic failures exit `1`; Typer syntax errors and invalid report targets exit `2`.
- Every run returns exactly the fourteen check codes and categories defined by the approved design, in the approved order.
- Diagnostic contracts never contain environment values, credential data, full model identifiers, source or generated content, review diffs, transaction/review identifiers, filesystem paths, usernames, hostnames, provider payloads, or exception text.
- Model and credential checks recognize only `BUNDLEWALKER_MODEL` and the documented `openai:` to `OPENAI_API_KEY` presence mapping. Unknown providers warn without guessing.
- Python 3.13 and 3.14 pass. macOS and Linux pass. Windows and unknown platforms warn; Windows remains experimental.
- MCP checks inspect availability only; they never start the server, open stdio, read host configuration, or contact a provider.
- Disk space below exactly 1 GiB warns; disk inspection never makes an operation-capacity guarantee.
- Read-only transaction diagnostics reject a manifest larger than exactly 1,048,576 bytes before parsing it.
- No new runtime dependency, version bump, TestPyPI/PyPI publication, tag, GitHub release, telemetry, MCP diagnostic surface, repair mode, performance benchmark, or web UI belongs to this plan.
- Default verification remains offline and credential-free.

---

## File structure

### New files

- `src/bundlewalker/application/diagnostics.py` — diagnostic dependencies, orchestration, safe fixed messages, workspace inspection, and report construction.
- `src/bundlewalker/interfaces/doctor.py` — terminal line rendering and exclusive JSON report-file creation only.
- `tests/application/test_diagnostics.py` — deterministic application and redaction coverage.
- `tests/cli/test_doctor.py` — public CLI, report writer, exit status, and non-mutation coverage.
- `tests/test_transaction_diagnostics.py` — read-only transaction-state classification and topology/content preservation.

### Modified files

- `src/bundlewalker/application/contracts.py` — strict diagnostic and support-report contracts.
- `src/bundlewalker/application/__init__.py` — public application exports.
- `src/bundlewalker/application/errors.py` — bounded diagnostic operation error code.
- `src/bundlewalker/transactions.py` — bounded read-only transaction-state inspector beside private manifest logic.
- `src/bundlewalker/interfaces/cli.py` — register `doctor`, bypass eager discovery, render results, and select exit codes.
- `README.md` — short diagnostic discovery example.
- `docs/user-guide.md` — complete doctor, report, exit, remediation, and privacy reference.
- `docs/superpowers/plans/2026-07-16-end-user-guide.md` — keep the repository's byte-for-byte embedded user-guide contract synchronized.
- `SUPPORT.md` — safe public-issue report guidance.
- `SECURITY.md` — keep suspected vulnerabilities out of public issues even when a report is redacted.
- `CHANGELOG.md` — Unreleased diagnostic capability entry.
- `tests/test_project_automation.py` — documentation/public-command contract.

---

### Task 1: Add strict diagnostic contracts

**Files:**
- Modify: `src/bundlewalker/application/contracts.py`
- Modify: `src/bundlewalker/application/__init__.py`
- Modify: `tests/application/test_contracts.py`

**Interfaces:**
- Consumes: Pydantic v2 `BaseModel`, `ConfigDict`, `Field`, `AwareDatetime`, `field_validator`, and `model_validator`.
- Produces: `DIAGNOSTIC_CHECK_CATALOG`, `DiagnosticCategory`, `DiagnosticSeverity`, `DiagnosticCheck`, `DiagnosticCounts`, `DiagnosticResult`, and `SupportReport`.

- [ ] **Step 1: Write failing contract tests**

Append imports for the new contracts and add helpers/tests with these exact behaviors:

```python
from pydantic import ValidationError

from bundlewalker.application import (
    DIAGNOSTIC_CHECK_CATALOG,
    DiagnosticCategory,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticSeverity,
    SupportReport,
)


def _diagnostic_checks(
    overrides: dict[str, DiagnosticSeverity] | None = None,
) -> tuple[DiagnosticCheck, ...]:
    selected = overrides or {}
    return tuple(
        DiagnosticCheck(
            code=code,
            category=category,
            severity=selected.get(code, DiagnosticSeverity.PASS),
            summary=f"Safe summary for {code}.",
            remediation=(),
        )
        for code, category in DIAGNOSTIC_CHECK_CATALOG
    )


def test_diagnostic_result_requires_exact_catalog_counts_and_overall_severity() -> None:
    checks = _diagnostic_checks(
        {
            "configuration.model": DiagnosticSeverity.WARNING,
            "workspace.permissions": DiagnosticSeverity.FAILURE,
        }
    )

    result = DiagnosticResult(
        overall=DiagnosticSeverity.FAILURE,
        bundlewalker_version="0.4.0a2",
        python_version="3.13.5",
        platform="linux",
        counts=DiagnosticCounts(passed=12, warnings=1, failures=1),
        checks=checks,
    )

    assert tuple(check.code for check in result.checks) == tuple(
        code for code, _category in DIAGNOSTIC_CHECK_CATALOG
    )
    assert result.counts == DiagnosticCounts(passed=12, warnings=1, failures=1)
    assert result.overall is DiagnosticSeverity.FAILURE


@pytest.mark.parametrize(
    ("counts", "overall"),
    [
        (DiagnosticCounts(passed=14, warnings=0, failures=0), DiagnosticSeverity.WARNING),
        (DiagnosticCounts(passed=13, warnings=1, failures=0), DiagnosticSeverity.PASS),
        (DiagnosticCounts(passed=13, warnings=0, failures=1), DiagnosticSeverity.WARNING),
    ],
)
def test_diagnostic_result_rejects_inconsistent_summary(
    counts: DiagnosticCounts,
    overall: DiagnosticSeverity,
) -> None:
    overrides = (
        {"configuration.model": DiagnosticSeverity.WARNING}
        if counts.warnings
        else {"workspace.permissions": DiagnosticSeverity.FAILURE}
        if counts.failures
        else {}
    )

    with pytest.raises(ValidationError):
        DiagnosticResult(
            overall=overall,
            bundlewalker_version="0.4.0a2",
            python_version="3.13.5",
            platform="linux",
            counts=counts,
            checks=_diagnostic_checks(overrides),
        )


def test_diagnostic_result_rejects_missing_reordered_and_wrong_category_checks() -> None:
    checks = list(_diagnostic_checks())
    missing = tuple(checks[:-1])
    reordered = tuple([checks[1], checks[0], *checks[2:]])
    wrong_category = tuple(
        [
            checks[0].model_copy(update={"category": DiagnosticCategory.STORAGE}),
            *checks[1:],
        ]
    )

    for candidate in (missing, reordered, wrong_category):
        with pytest.raises(ValidationError):
            DiagnosticResult(
                overall=DiagnosticSeverity.PASS,
                bundlewalker_version="0.4.0a2",
                python_version="3.13.5",
                platform="linux",
                counts=DiagnosticCounts(passed=len(candidate), warnings=0, failures=0),
                checks=candidate,
            )


def test_support_report_round_trips_and_forbids_extra_fields() -> None:
    result = DiagnosticResult(
        overall=DiagnosticSeverity.PASS,
        bundlewalker_version="0.4.0a2",
        python_version="3.13.5",
        platform="linux",
        counts=DiagnosticCounts(passed=14, warnings=0, failures=0),
        checks=_diagnostic_checks(),
    )
    report = SupportReport(
        generated_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        result=result,
    )

    assert report.schema_version == 1
    assert SupportReport.model_validate_json(report.model_dump_json()) == report
    with pytest.raises(ValidationError):
        SupportReport.model_validate({**report.model_dump(), "workspace_path": "/private"})


@pytest.mark.parametrize("value", ["line\nbreak", "tab\tvalue", "control\x00value"])
def test_diagnostic_text_rejects_control_characters(value: str) -> None:
    with pytest.raises(ValidationError):
        DiagnosticCheck(
            code="runtime.python",
            category=DiagnosticCategory.RUNTIME,
            severity=DiagnosticSeverity.PASS,
            summary=value,
            remediation=(),
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/application/test_contracts.py -q
```

Expected: collection fails because the new diagnostic contracts are not exported.

- [ ] **Step 3: Implement the contract vocabulary and invariants**

Add `AwareDatetime`, `field_validator`, `StrEnum`, and `unicodedata` imports, then add these exact public shapes to `application/contracts.py`:

```python
class DiagnosticSeverity(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAILURE = "failure"


class DiagnosticCategory(StrEnum):
    RUNTIME = "runtime"
    WORKSPACE = "workspace"
    CONFIGURATION = "configuration"
    TRANSACTIONS = "transactions"
    MCP = "mcp"
    STORAGE = "storage"


DIAGNOSTIC_CHECK_CATALOG: tuple[tuple[str, DiagnosticCategory], ...] = (
    ("runtime.bundlewalker", DiagnosticCategory.RUNTIME),
    ("runtime.python", DiagnosticCategory.RUNTIME),
    ("runtime.platform", DiagnosticCategory.RUNTIME),
    ("workspace.discovery", DiagnosticCategory.WORKSPACE),
    ("workspace.configuration", DiagnosticCategory.WORKSPACE),
    ("workspace.compatibility", DiagnosticCategory.WORKSPACE),
    ("workspace.structure", DiagnosticCategory.WORKSPACE),
    ("workspace.permissions", DiagnosticCategory.WORKSPACE),
    ("configuration.model", DiagnosticCategory.CONFIGURATION),
    ("configuration.credential", DiagnosticCategory.CONFIGURATION),
    ("transactions.state", DiagnosticCategory.TRANSACTIONS),
    ("mcp.package", DiagnosticCategory.MCP),
    ("mcp.entrypoint", DiagnosticCategory.MCP),
    ("storage.disk", DiagnosticCategory.STORAGE),
)


def _single_line(value: str) -> str:
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("diagnostic text must be one printable line")
    return value


class DiagnosticCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z]+(?:\.[a-z]+)+$", max_length=80)
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    summary: str = Field(min_length=1, max_length=300)
    remediation: tuple[str, ...] = Field(default=(), max_length=5)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _single_line(value)

    @field_validator("remediation")
    @classmethod
    def validate_remediation(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_single_line(value) for value in values)


class DiagnosticCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failures: int = Field(ge=0)


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    overall: DiagnosticSeverity
    bundlewalker_version: str = Field(min_length=1, max_length=80)
    python_version: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=40)
    counts: DiagnosticCounts
    checks: tuple[DiagnosticCheck, ...]

    @model_validator(mode="after")
    def validate_catalog_and_summary(self) -> Self:
        actual_catalog = tuple((check.code, check.category) for check in self.checks)
        if actual_catalog != DIAGNOSTIC_CHECK_CATALOG:
            raise ValueError("diagnostic checks must match the stable catalog")
        expected = DiagnosticCounts(
            passed=sum(check.severity is DiagnosticSeverity.PASS for check in self.checks),
            warnings=sum(check.severity is DiagnosticSeverity.WARNING for check in self.checks),
            failures=sum(check.severity is DiagnosticSeverity.FAILURE for check in self.checks),
        )
        if self.counts != expected:
            raise ValueError("diagnostic counts do not match checks")
        expected_overall = (
            DiagnosticSeverity.FAILURE
            if expected.failures
            else DiagnosticSeverity.WARNING
            if expected.warnings
            else DiagnosticSeverity.PASS
        )
        if self.overall is not expected_overall:
            raise ValueError("diagnostic overall severity does not match checks")
        return self


class SupportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    generated_at: AwareDatetime
    result: DiagnosticResult
```

Add every public name to `application/__init__.py` imports and `__all__`.

- [ ] **Step 4: Run focused and application contract tests and verify GREEN**

Run:

```bash
uv run pytest tests/application/test_contracts.py -q
uv run ruff check src/bundlewalker/application/contracts.py tests/application/test_contracts.py
uv run pyright src/bundlewalker/application/contracts.py tests/application/test_contracts.py
```

Expected: every command exits `0`; the contract test count increases and no warning appears.

- [ ] **Step 5: Commit the contract boundary**

```bash
git add src/bundlewalker/application/contracts.py src/bundlewalker/application/__init__.py tests/application/test_contracts.py
git commit -m "feat: add diagnostic result contracts"
```

---

### Task 2: Add non-mutating transaction-state inspection

**Files:**
- Modify: `src/bundlewalker/transactions.py`
- Create: `tests/test_transaction_diagnostics.py`

**Interfaces:**
- Consumes: existing private transaction manifest parser and fixed transaction topology names.
- Produces: `TransactionDiagnosticStatus` and `inspect_transaction_state(workspace: Workspace) -> TransactionDiagnosticStatus`.

- [ ] **Step 1: Write the clean and pending read-only tests**

Create `tests/test_transaction_diagnostics.py` with the GPL header, imports, a high-level pending-review fixture, and a snapshot that includes entry kind, link target, mode, and file bytes:

```python
from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.domain import Citation, CitedAnswer, OkfMetadata
from bundlewalker.okf.derived import regenerate_indexes
from bundlewalker.okf.documents import render_document
from bundlewalker.transactions import TransactionDiagnosticStatus, inspect_transaction_state
from bundlewalker.workspace import Workspace, initialize_workspace
from bundlewalker.workflows.ask import AnsweredQuestion, prepare_synthesis

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)


def _workspace_with_review(tmp_path: Path) -> Workspace:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    topic = workspace.wiki_dir / "topics" / "agents.md"
    topic.write_text(
        render_document(
            OkfMetadata(
                type="Topic",
                title="Agents",
                description="Knowledge about agents.",
                timestamp=NOW,
            ),
            "# Agents\n\nAgents can use tools.\n",
        ),
        encoding="utf-8",
    )
    regenerate_indexes(workspace.wiki_dir)
    prepare_synthesis(
        workspace,
        AnsweredQuestion(
            answer=CitedAnswer(
                title="Agent tools",
                body="# Answer\n\nAgents can use tools [1].\n",
                citations=[Citation(number=1, concept_id="topics/agents")],
            ),
            read_ids=frozenset({"topics/agents"}),
        ),
        occurred_at=NOW,
    )
    return workspace


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | str]]:
    snapshot: dict[str, tuple[str, int, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", mode, b"")
        else:
            snapshot[relative] = ("file", mode, path.read_bytes())
    return snapshot


def test_transaction_diagnostics_clean_workspace_creates_no_private_state(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = _tree_snapshot(workspace.root)

    result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.CLEAN
    assert _tree_snapshot(workspace.root) == before
    assert not (workspace.root / ".bundlewalker").exists()


def test_transaction_diagnostics_pending_review_reads_no_review_or_staged_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    before = _tree_snapshot(workspace.root)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        forbidden = {"review.json", "raw-source"}
        assert path.name not in forbidden
        assert "prospective-wiki" not in path.parts
        assert "backup-wiki" not in path.parts
        return original_read_bytes(path)

    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "read_bytes", guarded_read_bytes)
        result = inspect_transaction_state(workspace)

    assert result is TransactionDiagnosticStatus.PENDING
    assert _tree_snapshot(workspace.root) == before
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/test_transaction_diagnostics.py -q
```

Expected: collection fails because the read-only transaction diagnostic API does not exist.

- [ ] **Step 3: Implement clean, pending, interrupted, malformed, and busy classification**

Add `fcntl` to the imports and this public enum near the existing transaction enums:

```python
class TransactionDiagnosticStatus(StrEnum):
    CLEAN = "clean"
    PENDING = "pending"
    INTERRUPTED = "interrupted"
    MALFORMED = "malformed"
    BUSY = "busy"


_MAX_DIAGNOSTIC_MANIFEST_BYTES = 1_048_576
```

Add a public inspector that never calls a recovery API and uses `_load_manifest` only after confirming that the manifest is a real file:

```python
def inspect_transaction_state(workspace: Workspace) -> TransactionDiagnosticStatus:
    """Classify private transaction state without recovering or mutating it."""
    private_root = workspace.root / ".bundlewalker"
    if not private_root.exists() and not private_root.is_symlink():
        return TransactionDiagnosticStatus.CLEAN
    if private_root.is_symlink() or not private_root.is_dir():
        return TransactionDiagnosticStatus.MALFORMED

    lock_path = private_root / "transaction.lock"
    if lock_path.exists() or lock_path.is_symlink():
        if lock_path.is_symlink() or not lock_path.is_file():
            return TransactionDiagnosticStatus.MALFORMED
        try:
            if _transaction_lock_is_busy(lock_path):
                return TransactionDiagnosticStatus.BUSY
        except TransactionError:
            return TransactionDiagnosticStatus.MALFORMED

    transactions_root = private_root / "transactions"
    if not transactions_root.exists() and not transactions_root.is_symlink():
        return TransactionDiagnosticStatus.CLEAN
    if transactions_root.is_symlink() or not transactions_root.is_dir():
        return TransactionDiagnosticStatus.MALFORMED

    try:
        entries = sorted(transactions_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return TransactionDiagnosticStatus.MALFORMED
    if not entries:
        return TransactionDiagnosticStatus.CLEAN

    prepared = 0
    interrupted = 0
    for transaction_dir in entries:
        if transaction_dir.is_symlink() or not transaction_dir.is_dir():
            return TransactionDiagnosticStatus.MALFORMED
        manifest_path = transaction_dir / _MANIFEST_NAME
        if manifest_path.is_symlink() or not manifest_path.is_file():
            return TransactionDiagnosticStatus.MALFORMED
        try:
            if manifest_path.stat().st_size > _MAX_DIAGNOSTIC_MANIFEST_BYTES:
                return TransactionDiagnosticStatus.MALFORMED
            manifest = _load_manifest(workspace, transaction_dir)
        except (OSError, TransactionError, _IncompleteManifestError):
            return TransactionDiagnosticStatus.MALFORMED
        if manifest.phase == "prepared":
            if not _pending_diagnostic_topology_is_regular(transaction_dir):
                return TransactionDiagnosticStatus.MALFORMED
            prepared += 1
        else:
            interrupted += 1

    if prepared == 1 and interrupted == 0:
        return TransactionDiagnosticStatus.PENDING
    if prepared == 0 and interrupted >= 1:
        return TransactionDiagnosticStatus.INTERRUPTED
    return TransactionDiagnosticStatus.MALFORMED


def _pending_diagnostic_topology_is_regular(transaction_dir: Path) -> bool:
    for name in (_IDENTITY_NAME, _REVIEW_NAME):
        path = transaction_dir / name
        if path.is_symlink() or not path.is_file():
            return False
    prospective = transaction_dir / _PROSPECTIVE_NAME
    backup = transaction_dir / _BACKUP_NAME
    return (
        not prospective.is_symlink()
        and prospective.is_dir()
        and not backup.exists()
        and not backup.is_symlink()
    )


def _transaction_lock_is_busy(path: Path) -> bool:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    except OSError as exc:
        raise TransactionError("could not inspect the existing transaction lock") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
```

- [ ] **Step 4: Add failing edge-case tests before broadening implementation**

Add parameterized tests that rewrite only the fixture manifest before taking the snapshot, plus malformed and mixed topology cases:

```python
@pytest.mark.parametrize("phase", ["accepted", "raw-persisted", "swapping", "new-live"])
def test_transaction_diagnostics_classifies_interrupted_phases_without_mutation(
    tmp_path: Path,
    phase: str,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = next((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase"] = phase
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.INTERRUPTED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_symlinked_transaction_storage(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    private = workspace.root / ".bundlewalker"
    private.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (private / "transactions").symlink_to(outside, target_is_directory=True)
    before = _tree_snapshot(tmp_path)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(tmp_path) == before


def test_transaction_diagnostics_rejects_multiple_pending_reviews(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    transactions_root = workspace.root / ".bundlewalker/transactions"
    original = next(transactions_root.iterdir())
    duplicate = transactions_root / ("f" * 32)
    shutil.copytree(original, duplicate)
    manifest_path = duplicate / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["transaction_id"] = "f" * 32
    manifest["prospective_path"] = f".bundlewalker/transactions/{'f' * 32}/prospective-wiki"
    manifest["backup_path"] = f".bundlewalker/transactions/{'f' * 32}/backup-wiki"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_rejects_oversized_manifest_without_parsing(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    manifest_path = next((workspace.root / ".bundlewalker/transactions").glob("*/manifest.json"))
    manifest_path.write_bytes(b"{" + b"x" * 1_048_576 + b"}")
    before = _tree_snapshot(workspace.root)

    assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.MALFORMED
    assert _tree_snapshot(workspace.root) == before


def test_transaction_diagnostics_reports_existing_busy_lock_without_mutation(
    tmp_path: Path,
) -> None:
    workspace = _workspace_with_review(tmp_path)
    lock_path = workspace.root / ".bundlewalker" / "transaction.lock"
    descriptor = os.open(lock_path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = _tree_snapshot(workspace.root)

        assert inspect_transaction_state(workspace) is TransactionDiagnosticStatus.BUSY
        assert _tree_snapshot(workspace.root) == before
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
```

- [ ] **Step 5: Run transaction, crash-recovery, and type gates**

Run:

```bash
uv run pytest tests/test_transaction_diagnostics.py tests/test_transaction_crash_recovery.py tests/test_transactions.py -q
uv run ruff check src/bundlewalker/transactions.py tests/test_transaction_diagnostics.py
uv run pyright src/bundlewalker/transactions.py tests/test_transaction_diagnostics.py
```

Expected: all commands exit `0`; existing recovery behavior remains unchanged.

- [ ] **Step 6: Commit the read-only transaction seam**

```bash
git add src/bundlewalker/transactions.py tests/test_transaction_diagnostics.py
git commit -m "feat: inspect transaction health without recovery"
```

---

### Task 3: Implement diagnostic orchestration

**Files:**
- Create: `src/bundlewalker/application/diagnostics.py`
- Modify: `src/bundlewalker/application/__init__.py`
- Modify: `src/bundlewalker/application/errors.py`
- Create: `tests/application/test_diagnostics.py`

**Interfaces:**
- Consumes: Task 1 diagnostic contracts; Task 2 `inspect_transaction_state`; `find_workspace_config`, `inspect_workspace`, `discover_workspace`, `safe_configured_parts`, and `open_workspace_directory`.
- Produces: `DiagnosticsDependencies`, `DiagnosticsApplication.run(start: Path | None = None) -> DiagnosticResult`, and `DiagnosticsApplication.support_report(result: DiagnosticResult) -> SupportReport`.

- [ ] **Step 1: Write failing runtime, model, MCP, and disk tests**

Create `tests/application/test_diagnostics.py` with a deterministic dependency factory:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import os
from pathlib import Path

import pytest

from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    DiagnosticCheck,
    DiagnosticResult,
    DiagnosticsApplication,
    DiagnosticsDependencies,
    DiagnosticSeverity,
)
from bundlewalker.transactions import TransactionDiagnosticStatus
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
ONE_GIB = 1024**3


def _dependencies() -> DiagnosticsDependencies:
    return DiagnosticsDependencies(
        environment={"BUNDLEWALKER_MODEL": "openai:private-model", "OPENAI_API_KEY": "secret"},
        bundlewalker_version="0.4.0a2",
        python_version=(3, 13, 5),
        platform_name="Linux",
        clock=lambda: NOW,
        module_available=lambda name: name == "mcp",
        executable_lookup=(
            lambda name: "/private/bin/bundlewalker-mcp"
            if name == "bundlewalker-mcp"
            else None
        ),
        permission_check=lambda _path, _mode: True,
        disk_free=lambda _path: 2 * ONE_GIB,
    )


def _by_code(result: DiagnosticResult) -> dict[str, DiagnosticCheck]:
    return {check.code: check for check in result.checks}


def test_diagnostics_run_returns_full_catalog_and_redacts_environment_values(
    tmp_path: Path,
) -> None:
    private_model = "openai:private-model"
    private_key = "secret-api-key"
    dependencies = replace(
        _dependencies(),
        environment={"BUNDLEWALKER_MODEL": private_model, "OPENAI_API_KEY": private_key}
    )

    result = DiagnosticsApplication(dependencies).run(tmp_path)
    serialized = result.model_dump_json()
    checks = _by_code(result)

    assert len(result.checks) == 14
    assert checks["runtime.python"].severity is DiagnosticSeverity.PASS
    assert checks["runtime.platform"].severity is DiagnosticSeverity.PASS
    assert checks["configuration.model"].severity is DiagnosticSeverity.PASS
    assert checks["configuration.credential"].severity is DiagnosticSeverity.PASS
    assert checks["mcp.package"].severity is DiagnosticSeverity.PASS
    assert checks["mcp.entrypoint"].severity is DiagnosticSeverity.PASS
    assert private_model not in serialized
    assert private_key not in serialized
    assert "/private" not in serialized


def test_diagnostics_warning_policy_for_optional_and_experimental_environment(
    tmp_path: Path,
) -> None:
    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            environment={},
            platform_name="Windows",
            disk_free=lambda _path: ONE_GIB - 1,
        )
    ).run(tmp_path)
    checks = _by_code(result)

    assert checks["runtime.platform"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.model"].severity is DiagnosticSeverity.WARNING
    assert checks["configuration.credential"].severity is DiagnosticSeverity.WARNING
    assert checks["storage.disk"].severity is DiagnosticSeverity.WARNING


def test_diagnostics_unsupported_python_and_missing_mcp_are_failures(tmp_path: Path) -> None:
    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            python_version=(3, 12, 9),
            module_available=lambda _name: False,
            executable_lookup=lambda _name: None,
        )
    ).run(tmp_path)
    checks = _by_code(result)

    assert checks["runtime.python"].severity is DiagnosticSeverity.FAILURE
    assert checks["mcp.package"].severity is DiagnosticSeverity.FAILURE
    assert checks["mcp.entrypoint"].severity is DiagnosticSeverity.FAILURE
    assert result.overall is DiagnosticSeverity.FAILURE


def test_diagnostics_unexpected_defect_uses_bounded_application_error(tmp_path: Path) -> None:
    marker = "private-programming-defect"

    def fail_lookup(_name: str) -> bool:
        raise RuntimeError(marker)

    with pytest.raises(ApplicationError) as raised:
        DiagnosticsApplication(
            replace(_dependencies(), module_available=fail_lookup)
        ).run(tmp_path)

    assert raised.value.code is ApplicationErrorCode.DIAGNOSTIC_FAILED
    assert raised.value.safe_message == "diagnostic operation failed"
    assert marker not in raised.value.safe_message
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/application/test_diagnostics.py -q
```

Expected: collection fails because `DiagnosticsApplication` and `DiagnosticsDependencies` do not exist.

- [ ] **Step 3: Add dependencies, fixed check helpers, and runtime/configuration/MCP/storage checks**

Create `application/diagnostics.py` with the GPL header and these exact public types/defaults:

```python
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker import __version__
from bundlewalker.application.contracts import (
    DiagnosticCategory,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticSeverity,
    SupportReport,
)
from bundlewalker.application.errors import ApplicationError, ApplicationErrorCode
from bundlewalker.transactions import TransactionDiagnosticStatus, inspect_transaction_state
from bundlewalker.workspace import Workspace

ONE_GIB = 1024**3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


@dataclass(frozen=True, slots=True)
class DiagnosticsDependencies:
    environment: Mapping[str, str] | None = None
    bundlewalker_version: str = __version__
    python_version: tuple[int, int, int] = (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    platform_name: str = platform.system()
    clock: Callable[[], datetime] = _utc_now
    module_available: Callable[[str], bool] = _module_available
    executable_lookup: Callable[[str], str | None] = shutil.which
    permission_check: Callable[[Path, int], bool] = os.access
    disk_free: Callable[[Path], int] = _disk_free
    transaction_inspector: Callable[[Workspace], TransactionDiagnosticStatus] = inspect_transaction_state
```

Implement helpers that only accept fixed strings:

```python
def _check(
    code: str,
    category: DiagnosticCategory,
    severity: DiagnosticSeverity,
    summary: str,
    *remediation: str,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        code=code,
        category=category,
        severity=severity,
        summary=summary,
        remediation=remediation,
    )


def _normalized_platform(name: str) -> str:
    normalized = name.strip().casefold()
    if normalized == "darwin":
        return "macos"
    if normalized in {"linux", "windows"}:
        return normalized
    return "other"


def _result(
    bundlewalker_version: str,
    python_version: tuple[int, int, int],
    platform_name: str,
    checks: tuple[DiagnosticCheck, ...],
) -> DiagnosticResult:
    counts = DiagnosticCounts(
        passed=sum(check.severity is DiagnosticSeverity.PASS for check in checks),
        warnings=sum(check.severity is DiagnosticSeverity.WARNING for check in checks),
        failures=sum(check.severity is DiagnosticSeverity.FAILURE for check in checks),
    )
    overall = (
        DiagnosticSeverity.FAILURE
        if counts.failures
        else DiagnosticSeverity.WARNING
        if counts.warnings
        else DiagnosticSeverity.PASS
    )
    return DiagnosticResult(
        overall=overall,
        bundlewalker_version=bundlewalker_version,
        python_version=".".join(str(value) for value in python_version),
        platform=_normalized_platform(platform_name),
        counts=counts,
        checks=checks,
    )
```

`DiagnosticsApplication.run()` must append exactly one check for each catalog code in catalog order. Use fixed summaries/remediations from the design. Do not interpolate environment values, executable paths, workspace paths, exception messages, or transaction IDs. `support_report()` is exactly:

```python
class DiagnosticsApplication:
    def __init__(self, dependencies: DiagnosticsDependencies | None = None) -> None:
        self.dependencies = dependencies or DiagnosticsDependencies()

    def run(self, start: Path | None = None) -> DiagnosticResult:
        try:
            return self._run(start)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError(
                ApplicationErrorCode.DIAGNOSTIC_FAILED,
                "diagnostic operation failed",
            ) from exc

    def _run(self, start: Path | None = None) -> DiagnosticResult:
        environment = (
            os.environ if self.dependencies.environment is None else self.dependencies.environment
        )
        workspace_checks, workspace = _workspace_checks(start, self.dependencies)
        model_check, credential_check = _configuration_checks(environment)
        checks = (
            _bundlewalker_check(self.dependencies.bundlewalker_version),
            _python_check(self.dependencies.python_version),
            _platform_check(self.dependencies.platform_name),
            *workspace_checks,
            model_check,
            credential_check,
            _transaction_check(workspace, self.dependencies.transaction_inspector),
            _mcp_package_check(self.dependencies.module_available),
            _mcp_entrypoint_check(self.dependencies.executable_lookup),
            _storage_check(start, workspace, self.dependencies.disk_free),
        )
        return _result(
            self.dependencies.bundlewalker_version,
            self.dependencies.python_version,
            self.dependencies.platform_name,
            checks,
        )

    def support_report(self, result: DiagnosticResult) -> SupportReport:
        return SupportReport(generated_at=self.dependencies.clock(), result=result)
```

Define the named helpers in the same file with the argument and return types demonstrated by the
calls above. `_workspace_checks` returns the five ordered workspace checks plus `Workspace | None`;
`_configuration_checks` returns the model and credential checks; every other helper returns one
`DiagnosticCheck`. The immediately following workspace/check-policy step defines their complete
branch and message behavior.

Export `DiagnosticsApplication` and `DiagnosticsDependencies` from `application/__init__.py`.
Add `DIAGNOSTIC_FAILED = "diagnostic_failed"` to `ApplicationErrorCode`. It is an operational
failure, not one of `_exit_for_application_error`'s exit-`2` usage codes, so the existing CLI error
adapter returns exit `1` without a traceback.

- [ ] **Step 4: Write failing workspace and transaction mapping tests**

Add tests for a real initialized workspace, missing workspace, invalid current configuration, future format, permission denial, each `TransactionDiagnosticStatus`, and a private-path exception. The core assertions are:

```python
def test_diagnostics_current_workspace_passes_workspace_checks(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    result = DiagnosticsApplication(_dependencies()).run(workspace.root)
    checks = _by_code(result)

    for code in (
        "workspace.discovery",
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert checks[code].severity is DiagnosticSeverity.PASS


def test_diagnostics_missing_workspace_fails_discovery_and_marks_dependents_skipped(
    tmp_path: Path,
) -> None:
    result = DiagnosticsApplication(_dependencies()).run(tmp_path)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.FAILURE
    for code in (
        "workspace.configuration",
        "workspace.compatibility",
        "workspace.structure",
        "workspace.permissions",
        "transactions.state",
    ):
        assert checks[code].severity is DiagnosticSeverity.WARNING


def test_diagnostics_invalid_current_configuration_is_bounded(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    (workspace.root / "bundlewalker.toml").write_text("version = 1\n", encoding="utf-8")

    result = DiagnosticsApplication(_dependencies()).run(workspace.root)
    serialized = result.model_dump_json()

    assert _by_code(result)["workspace.configuration"].severity is DiagnosticSeverity.FAILURE
    assert str(workspace.root) not in serialized
    assert "Traceback" not in serialized


def test_diagnostics_future_workspace_reports_compatibility_without_current_parse(
    tmp_path: Path,
) -> None:
    root = tmp_path / "future"
    root.mkdir()
    (root / "bundlewalker.toml").write_text(
        "version = 2\nfuture_path = 'private'\n",
        encoding="utf-8",
    )

    result = DiagnosticsApplication(_dependencies()).run(root)
    checks = _by_code(result)

    assert checks["workspace.discovery"].severity is DiagnosticSeverity.PASS
    assert checks["workspace.configuration"].severity is DiagnosticSeverity.WARNING
    assert checks["workspace.compatibility"].severity is DiagnosticSeverity.FAILURE


def test_diagnostics_write_permission_denial_is_failure_without_probe_file(
    tmp_path: Path,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = sorted(path.relative_to(workspace.root) for path in workspace.root.rglob("*"))
    dependencies = replace(
        _dependencies(),
        permission_check=lambda _path, mode: mode != os.W_OK,
    )

    result = DiagnosticsApplication(dependencies).run(workspace.root)

    assert _by_code(result)["workspace.permissions"].severity is DiagnosticSeverity.FAILURE
    assert sorted(path.relative_to(workspace.root) for path in workspace.root.rglob("*")) == before


@pytest.mark.parametrize(
    ("state", "severity"),
    [
        (TransactionDiagnosticStatus.CLEAN, DiagnosticSeverity.PASS),
        (TransactionDiagnosticStatus.PENDING, DiagnosticSeverity.WARNING),
        (TransactionDiagnosticStatus.BUSY, DiagnosticSeverity.WARNING),
        (TransactionDiagnosticStatus.INTERRUPTED, DiagnosticSeverity.FAILURE),
        (TransactionDiagnosticStatus.MALFORMED, DiagnosticSeverity.FAILURE),
    ],
)
def test_diagnostics_maps_transaction_state_without_identifiers(
    tmp_path: Path,
    state: TransactionDiagnosticStatus,
    severity: DiagnosticSeverity,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    result = DiagnosticsApplication(
        replace(_dependencies(), transaction_inspector=lambda _workspace: state)
    ).run(workspace.root)

    check = _by_code(result)["transactions.state"]
    assert check.severity is severity
    assert "<REVIEW_ID>" in " ".join(check.remediation) if state is TransactionDiagnosticStatus.PENDING else True


def test_diagnostics_redacts_expected_inspector_failures(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "private-workspace", occurred_at=NOW)
    markers = {
        "private-model-marker",
        "private-key-marker",
        "private-executable-marker",
        "private-permission-marker",
        "private-disk-marker",
        "private-transaction-marker",
        "private-host-marker",
    }

    def fail_transaction(_workspace: object) -> TransactionDiagnosticStatus:
        raise OSError("private-transaction-marker")

    def fail_permission(_path: Path, _mode: int) -> bool:
        raise OSError("private-permission-marker")

    def fail_disk(_path: Path) -> int:
        raise OSError("private-disk-marker")

    result = DiagnosticsApplication(
        replace(
            _dependencies(),
            environment={
                "BUNDLEWALKER_MODEL": "openai:private-model-marker",
                "OPENAI_API_KEY": "private-key-marker",
            },
            platform_name="private-host-marker",
            executable_lookup=lambda _name: "/private-executable-marker/bin",
            permission_check=fail_permission,
            disk_free=fail_disk,
            transaction_inspector=fail_transaction,
        )
    ).run(workspace.root)
    serialized = result.model_dump_json()

    assert _by_code(result)["transactions.state"].severity is DiagnosticSeverity.FAILURE
    assert all(marker not in serialized for marker in markers)
    assert str(workspace.root) not in serialized
```

- [ ] **Step 5: Implement workspace inspection and bounded exception handling**

Use existing read-only APIs in this order:

1. `find_workspace_config(start)` for discovery.
2. `inspect_workspace(start)` for format compatibility before full current-format parsing.
3. `discover_workspace(start)` only when compatibility is current.
4. `safe_configured_parts` plus anchored directory opening for configured directories.
5. `lstat`, `is_symlink`, and kind checks for configuration/conventions files.
6. injected `permission_check(path, os.R_OK)` and `permission_check(path, os.W_OK)` without a probe write.
7. injected transaction inspector only for a current, structurally valid workspace.

Use these fixed dependent-check semantics:

```python
_SKIPPED_CONFIGURATION = "Workspace configuration was not checked because discovery failed."
_SKIPPED_COMPATIBILITY = "Workspace compatibility was not checked because configuration is unavailable."
_SKIPPED_STRUCTURE = "Workspace structure was not checked because a usable workspace is unavailable."
_SKIPPED_PERMISSIONS = "Workspace permissions were not checked because a usable workspace is unavailable."
_SKIPPED_TRANSACTIONS = "Transaction state was not checked because a usable workspace is unavailable."
```

Catch only expected `BundleWalkerError`, `OSError`, and lookup failures at inspector boundaries. Map them to fixed summaries; never call `str(error)` in a diagnostic value. For future or unsupported formats, do not call current-format `discover_workspace`; emit a configuration prerequisite warning and a compatibility failure with the fixed `bundlewalker workspace status PATH` or `bundlewalker workspace upgrade PATH` remediation.

- [ ] **Step 6: Run application, lifecycle, and redaction gates**

Run:

```bash
uv run pytest tests/application/test_diagnostics.py tests/application/test_contracts.py tests/application/test_lifecycle.py -q
uv run ruff format --check src/bundlewalker/application tests/application
uv run ruff check src/bundlewalker/application tests/application
uv run pyright src/bundlewalker/application tests/application
```

Expected: all commands exit `0`; no output contains warning text from Pyright or Ruff.

- [ ] **Step 7: Commit the diagnostic application service**

```bash
git add src/bundlewalker/application/diagnostics.py src/bundlewalker/application/__init__.py src/bundlewalker/application/errors.py tests/application/test_diagnostics.py
git commit -m "feat: add offline diagnostic application"
```

---

### Task 4: Add the doctor CLI and exclusive JSON report writer

**Files:**
- Create: `src/bundlewalker/interfaces/doctor.py`
- Modify: `src/bundlewalker/interfaces/cli.py`
- Create: `tests/cli/test_doctor.py`

**Interfaces:**
- Consumes: Task 3 `DiagnosticsApplication`, `DiagnosticResult`, and `SupportReport`.
- Produces: `render_diagnostic_lines(result: DiagnosticResult) -> tuple[str, ...]`, `write_support_report(report: SupportReport, destination: Path) -> None`, and the public `bundlewalker doctor [PATH] [--report REPORT.json]` command.

- [ ] **Step 1: Write failing renderer and report-writer tests**

Create `tests/cli/test_doctor.py` with helpers that construct the full contract catalog, then add:

```python
from collections.abc import Mapping
from datetime import UTC, datetime
import os
from pathlib import Path
import stat

import pytest
from typer.testing import CliRunner

from bundlewalker.application import (
    DIAGNOSTIC_CHECK_CATALOG,
    DiagnosticCheck,
    DiagnosticCounts,
    DiagnosticResult,
    DiagnosticSeverity,
    SupportReport,
)
from bundlewalker.cli import app
from bundlewalker.interfaces.doctor import (
    SupportReportTargetError,
    SupportReportWriteError,
    render_diagnostic_lines,
    write_support_report,
)
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
runner = CliRunner()


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, bytes | str]]:
    snapshot: dict[str, tuple[str, int, bytes | str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", mode, os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("directory", mode, b"")
        else:
            snapshot[relative] = ("file", mode, path.read_bytes())
    return snapshot


def _result(
    overrides: Mapping[str, tuple[DiagnosticSeverity, tuple[str, ...]]],
) -> DiagnosticResult:
    checks = tuple(
        DiagnosticCheck(
            code=code,
            category=category,
            severity=overrides.get(code, (DiagnosticSeverity.PASS, ()))[0],
            summary=f"Safe summary for {code}.",
            remediation=overrides.get(code, (DiagnosticSeverity.PASS, ()))[1],
        )
        for code, category in DIAGNOSTIC_CHECK_CATALOG
    )
    counts = DiagnosticCounts(
        passed=sum(check.severity is DiagnosticSeverity.PASS for check in checks),
        warnings=sum(check.severity is DiagnosticSeverity.WARNING for check in checks),
        failures=sum(check.severity is DiagnosticSeverity.FAILURE for check in checks),
    )
    overall = (
        DiagnosticSeverity.FAILURE
        if counts.failures
        else DiagnosticSeverity.WARNING
        if counts.warnings
        else DiagnosticSeverity.PASS
    )
    return DiagnosticResult(
        overall=overall,
        bundlewalker_version="0.4.0a2",
        python_version="3.13.5",
        platform="linux",
        counts=counts,
        checks=checks,
    )


def test_renderer_uses_stable_tokens_order_remediation_and_summary() -> None:
    result = _result(
        {
            "configuration.model": (
                DiagnosticSeverity.WARNING,
                ("Set BUNDLEWALKER_MODEL before model-backed commands.",),
            ),
            "workspace.discovery": (
                DiagnosticSeverity.FAILURE,
                ("Run `bundlewalker init PATH` or pass an existing workspace.",),
            ),
        }
    )

    lines = render_diagnostic_lines(result)

    assert lines[0].startswith("PASS runtime.bundlewalker — ")
    assert any(line.startswith("WARN configuration.model — ") for line in lines)
    assert any(line.startswith("FAIL workspace.discovery — ") for line in lines)
    assert "  Next: Set BUNDLEWALKER_MODEL before model-backed commands." in lines
    assert lines[-1] == "Doctor: 12 passed, 1 warning, 1 failure."


def test_report_writer_creates_owner_only_json_and_refuses_existing_target(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "support.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    write_support_report(report, destination)

    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert SupportReport.model_validate_json(destination.read_text(encoding="utf-8")) == report
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    original = destination.read_bytes()
    with pytest.raises(SupportReportTargetError):
        write_support_report(report, destination)
    assert destination.read_bytes() == original


def test_report_writer_refuses_symlink_directory_and_missing_parent(tmp_path: Path) -> None:
    report = SupportReport(generated_at=NOW, result=_result({}))
    existing = tmp_path / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    linked = tmp_path / "linked.json"
    linked.symlink_to(existing)

    for destination in (linked, tmp_path, tmp_path / "missing" / "report.json"):
        with pytest.raises(SupportReportTargetError):
            write_support_report(report, destination)
    assert existing.read_text(encoding="utf-8") == "keep"


def test_report_writer_retains_its_owner_only_partial_file_on_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "partial.json"
    report = SupportReport(generated_at=NOW, result=_result({}))

    def fail_write(_descriptor: int, _content: bytes | memoryview) -> int:
        raise OSError("private write failure")

    monkeypatch.setattr(os, "write", fail_write)

    with pytest.raises(SupportReportWriteError):
        write_support_report(report, destination)
    assert destination.exists()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/cli/test_doctor.py -q
```

Expected: collection fails because the doctor interface module does not exist.

- [ ] **Step 3: Implement deterministic rendering and exclusive report creation**

Create `interfaces/doctor.py` with two private exception classes exposed to the CLI and an exclusive writer:

```python
class SupportReportTargetError(Exception):
    pass


class SupportReportWriteError(Exception):
    pass


_TOKENS = {
    DiagnosticSeverity.PASS: "PASS",
    DiagnosticSeverity.WARNING: "WARN",
    DiagnosticSeverity.FAILURE: "FAIL",
}


def render_diagnostic_lines(result: DiagnosticResult) -> tuple[str, ...]:
    lines: list[str] = []
    for check in result.checks:
        lines.append(f"{_TOKENS[check.severity]} {check.code} — {check.summary}")
        lines.extend(f"  Next: {instruction}" for instruction in check.remediation)
    counts = result.counts
    lines.append(
        "Doctor: "
        f"{counts.passed} {_noun(counts.passed, 'passed', 'passed')}, "
        f"{counts.warnings} {_noun(counts.warnings, 'warning', 'warnings')}, "
        f"{counts.failures} {_noun(counts.failures, 'failure', 'failures')}."
    )
    return tuple(lines)


def _noun(value: int, singular: str, plural: str) -> str:
    return singular if value == 1 else plural
```

Implement `write_support_report` with `os.open(destination, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)`, a complete `os.write` loop over `(report.model_dump_json(indent=2) + "\n").encode("utf-8")`, `os.fsync`, and descriptor close. Convert `FileExistsError`, `FileNotFoundError`, `NotADirectoryError`, and an existing non-regular target to `SupportReportTargetError` without exception text. Convert other `OSError` values to `SupportReportWriteError`. After creation, retain the owner-only partial target on write, `fchmod`, `fsync`, or close failure. Portable macOS and Linux pathname APIs cannot atomically prove that the destination still names the created inode, and automatic cleanup could delete an unrelated replacement; do not unlink it. Tell the user to inspect and remove the newly created report target when appropriate before retrying.

- [ ] **Step 4: Write failing public CLI tests**

Add tests using Typer's `CliRunner`:

```python
def test_doctor_runs_outside_workspace_and_returns_failure_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "FAIL workspace.discovery" in result.stdout
    assert "Doctor:" in result.stdout
    assert "Traceback" not in result.output
    assert not (tmp_path / ".bundlewalker").exists()


def test_doctor_warning_only_workspace_exits_zero_and_does_not_mutate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    monkeypatch.delenv("BUNDLEWALKER_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = _tree_snapshot(workspace.root)

    result = runner.invoke(app, ["doctor", str(workspace.root)])

    assert result.exit_code == 0
    assert "WARN configuration.model" in result.stdout
    assert "0 failures" in result.stdout
    assert _tree_snapshot(workspace.root) == before


def test_doctor_writes_only_explicit_report_and_never_echoes_private_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = initialize_workspace(tmp_path / "private-workspace", occurred_at=NOW)
    report = tmp_path / "support.json"
    secret = "private-api-secret"
    model = "openai:private-model"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("BUNDLEWALKER_MODEL", model)
    before = _tree_snapshot(workspace.root)

    result = runner.invoke(
        app,
        ["doctor", str(workspace.root), "--report", str(report)],
    )

    assert result.exit_code == 0
    payload = report.read_text(encoding="utf-8")
    combined = result.output + payload
    assert SupportReport.model_validate_json(payload).schema_version == 1
    assert secret not in combined
    assert model not in combined
    assert str(workspace.root) not in combined
    assert str(report) not in combined
    assert _tree_snapshot(workspace.root) == before
```

Add CLI tests for an existing report target returning `2`, a valid-target write failure returning `1`, and `--help` showing `PATH` plus `--report`.

- [ ] **Step 5: Register the doctor command and exit policy**

In `interfaces/cli.py`:

1. Add `"doctor"` to the callback's discovery-bypass set.
2. Import the diagnostic application/contracts and doctor interface helpers.
3. Add a top-level command with this signature:

```python
@app.command("doctor")
def doctor_command(
    path: Path | None = typer.Argument(None),  # noqa: B008
    report: Path | None = typer.Option(None, "--report", metavar="REPORT.json"),  # noqa: B008
) -> None:
    """Diagnose local BundleWalker health without repairing workspace state."""
```

Run `DiagnosticsApplication().run(path)`, echo every `render_diagnostic_lines` line, and, when requested, call `write_support_report(application.support_report(result), report)`. Print only `Support report written.` after success; never print the destination. Convert `SupportReportTargetError` to `Error: support report target must be a new file` with exit `2`. Convert `SupportReportWriteError` to `Error: support report could not be written` with exit `1`. After any successful report handling, raise `typer.Exit(1)` only when `result.counts.failures > 0`.

- [ ] **Step 6: Run CLI, interface, and full focused gates**

Run:

```bash
uv run pytest tests/cli/test_doctor.py tests/cli tests/interfaces -q
uv run bundlewalker doctor --help
uv run ruff format --check src/bundlewalker/interfaces tests/cli
uv run ruff check src/bundlewalker/interfaces tests/cli
uv run pyright src/bundlewalker/interfaces tests/cli
```

Expected: all commands exit `0`; help shows optional `PATH` and `--report REPORT.json`.

- [ ] **Step 7: Commit the public doctor interface**

```bash
git add src/bundlewalker/interfaces/doctor.py src/bundlewalker/interfaces/cli.py tests/cli/test_doctor.py
git commit -m "feat: add doctor command and support reports"
```

---

### Task 5: Publish the diagnostics and support contract

**Files:**
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/superpowers/plans/2026-07-16-end-user-guide.md`
- Modify: `SUPPORT.md`
- Modify: `SECURITY.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: the Task 4 public command, exact exit behavior, report schema version, stable privacy boundary, and literal `<REVIEW_ID>` remediation token.
- Produces: discoverable user/support documentation and a regression test tying public docs to the shipped command.

- [ ] **Step 1: Write the failing public-documentation contract**

Add this test after the workspace lifecycle documentation contract:

```python
def test_doctor_diagnostics_and_redacted_support_reports_are_published() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    user_guide = (PROJECT_ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
    support = (PROJECT_ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    security = (PROJECT_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "bundlewalker doctor" in readme
    for phrase in (
        "bundlewalker doctor [PATH] [--report REPORT.json]",
        "Warnings exit `0`",
        "failures exit `1`",
        "schema version `1`",
        "read-only",
        "offline",
        "<REVIEW_ID>",
    ):
        assert phrase in user_guide
    assert "redacted JSON support report" in support
    assert "review the report" in support.lower()
    assert "private vulnerability" in security.lower()
    assert "doctor" in changelog.lower()
```

- [ ] **Step 2: Run the documentation contract and verify RED**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_doctor_diagnostics_and_redacted_support_reports_are_published -q
```

Expected: FAIL because the README does not yet mention `bundlewalker doctor`.

- [ ] **Step 3: Add concise README discovery and changelog copy**

In the quick-start command block, place this offline command before lint:

```bash
uv run --project "$PROJECT_ROOT" bundlewalker doctor
```

Explain immediately afterward:

```markdown
`doctor` is an offline, read-only health check. It reports installation, workspace, configuration,
transaction, MCP, and storage status without repairing state or contacting a model provider.
```

Under `CHANGELOG.md` → `Unreleased` → `Added`, add:

```markdown
- Added the offline, read-only `bundlewalker doctor` health check with stable remediation,
  automation-friendly exit behavior, and explicit redacted JSON support reports.
```

Create an `Added` subsection before the existing `Changed` subsection if it is absent.

- [ ] **Step 4: Add the complete user-guide contract**

Add a `doctor` subsection before `workspace` in the CLI reference with this exact signature:

```text
bundlewalker doctor [PATH] [--report REPORT.json]
```

Document:

- fixed `PASS`, `WARN`, and `FAIL` lines plus the fourteen stable codes;
- warnings exit `0`, failures exit `1`, and invalid report targets exit `2`;
- discovery from any directory and optional `PATH`;
- strict offline/read-only behavior and the one explicit report-file write;
- report schema version `1`, new-file-only behavior, and no destination echo;
- the complete exclusion list for credentials, model values, content, paths, host identity,
  review/transaction IDs, and exception/provider payloads;
- `review show`, `review apply <REVIEW_ID>`, and `review discard <REVIEW_ID>` remediation;
- OpenAI presence-only mapping and unknown-provider warning behavior;
- Windows experimental status and the 1-GiB advisory threshold; and
- the statement that users must review even a redacted report before sharing it.

Use this example:

```bash
bundlewalker doctor /path/to/workspace
bundlewalker doctor /path/to/workspace --report bundlewalker-support.json
```

Do not claim provider authentication, network reachability, repair, operation-specific capacity,
or zero disclosure risk.

- [ ] **Step 5: Update support and security policy**

Add to `SUPPORT.md` after the issue-information paragraph:

```markdown
You may create an opt-in redacted JSON support report with
`bundlewalker doctor PATH --report bundlewalker-support.json`. Review the report before attaching
it to a public issue. The report omits credentials, model values, workspace content, filesystem
paths, host identity, and transaction or review identifiers, but it is still your responsibility
to confirm that the diagnostic context is appropriate to share.
```

Add to `SECURITY.md` after private-reporting guidance:

```markdown
Do not attach a doctor support report to a public issue when the report concerns a suspected
security vulnerability. Use private vulnerability reporting and review every diagnostic artifact
before sharing it.
```

- [ ] **Step 6: Synchronize the historical embedded user-guide contract**

The test `test_historical_plan_embeds_current_user_guide_byte_for_byte` intentionally requires the
current `docs/user-guide.md` bytes inside `docs/superpowers/plans/2026-07-16-end-user-guide.md`.
Apply the same doctor subsection and any table-of-contents addition inside the fenced embedded
guide between these exact markers:

```text
Create `docs/user-guide.md` with exactly:

````markdown
```

and:

```text
````

- [ ] **Step 3: Link the guide from the README**
```

Do not modify prose outside that embedded guide block.

- [ ] **Step 7: Run documentation and repository automation tests**

Run:

```bash
uv run pytest tests/test_project_automation.py tests/test_release_metadata.py -q
git diff --check
```

Expected: both test files pass, including the byte-for-byte embedded-guide assertion; the diff check prints nothing.

- [ ] **Step 8: Run the complete final verification gate**

Run from the worktree root:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --clear --no-sources
uv run twine check dist/*
git diff --check
```

Expected: every command exits `0`. The pull request's existing wheel and source-distribution smoke
jobs remain the authoritative clean-install entry-point verification on all supported Python and
operating-system combinations.

- [ ] **Step 9: Commit the public contract**

```bash
git add README.md CHANGELOG.md SECURITY.md SUPPORT.md docs/user-guide.md docs/superpowers/plans/2026-07-16-end-user-guide.md tests/test_project_automation.py
git commit -m "docs: publish doctor diagnostics guidance"
```

---

## Final review and integration

After Task 5:

1. Confirm `git status --short` is clean except for ignored worker-state and build artifacts.
2. Review every commit against `docs/superpowers/specs/2026-07-19-bundlewalker-doctor-diagnostics-design.md`.
3. Run a task-scoped review after each task and one whole-branch review from base commit `e5590c514b432c8e208da132abc3efdf4f3797df` to final `HEAD`.
4. Fix every Critical or Important finding and re-run the relevant review.
5. Independently rerun the complete final verification gate after the last code or documentation change.
6. Push `codex/doctor-diagnostics`, open a ready pull request into `master`, and wait for the required macOS/Linux, packaging, dependency-audit, and CodeQL checks.
7. Experimental Windows failures remain visible and non-blocking.
8. Merge only the reviewed head SHA after the aggregate required check passes.
9. Synchronize the primary `master` checkout after merge.
10. Do not create a tag, release, package version, TestPyPI workflow dispatch, or PyPI publication.
