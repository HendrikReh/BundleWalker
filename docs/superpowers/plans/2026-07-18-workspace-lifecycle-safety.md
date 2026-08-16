# Workspace Lifecycle Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit workspace compatibility boundary, historical release fixtures, verified
portable backups, non-destructive restore, future migration orchestration, rollback evidence, and
abrupt-termination recovery coverage for public-beta Milestone B1.

**Architecture:** Preserve the modular monolith. Extract the existing cross-process lock into a
focused coordination module, expose a transaction-owned quiescent-workspace guard, implement
compatibility and archive rules in core services, and deliver them through an adapter-neutral
lifecycle application facade plus a `bundlewalker workspace` CLI group. Backup and future upgrade
hold the same lock as reviewed mutations; restore verifies into a temporary sibling before atomic
publication.

**Tech Stack:** Python 3.13 and 3.14, standard-library `fcntl`, `hashlib`, `json`, `os`, `shutil`,
`tomllib`, `zipfile`, Pydantic 2, Typer, pytest, Ruff, Pyright, uv, GitHub Actions, Markdown, Git

## Global Constraints

- Workspace format `1` remains the only current readable and writable durable format; do not
  introduce workspace format `2`.
- Transaction manifest schema `2` and durable review schema `1` remain the current internal
  producers; preserve authenticated schema-1 recovery behavior.
- Normal discovery, read, lint, review, and mutation commands never migrate implicitly.
- A portable backup contains only `bundlewalker.toml` and its configured conventions, raw, and
  wiki paths; exclude `.bundlewalker/`, `.git/`, unrelated files, and prior archives.
- Backup must hold BundleWalker's cross-process lock, run authenticated recovery, and reject every
  remaining pending or stale review.
- Restore accepts only a missing or empty non-symlink target and never overwrites a workspace.
- Backups are unencrypted ZIP archives; create them with owner-only permissions where POSIX modes
  are available and document that exact raw source bytes may be sensitive.
- Archive schema is `1`, manifest size is at most 32 MiB, combined directory/file count is at most
  100,000, and each relative path is at most 4,096 Unicode characters.
- Treat SHA-256 and streamed uncompressed bytes as identity; never trust ZIP CRC or compressed size
  as identity.
- The portable contract covers relative paths and file bytes, not ownership, ACLs, extended
  attributes, timestamps, or original mode bits.
- Restore and backup must fail closed on every observed symlink, special-file, containment,
  identity, size, digest, mutation-race, space, verification, and publication error.
- A future real migration must create and verify a backup before mutation, hold the workspace lock,
  and supply migration-specific recovery and verification. Production registers no migration in
  this plan.
- Keep BundleWalker local, single-user, review-first, and free of automatic telemetry, uploads,
  Git operations, database state, background daemons, or alternate mutation paths.
- Official support remains Ubuntu 24.04 and macOS 15 on Python 3.13 and 3.14. Windows Server 2025
  remains experimental and non-blocking.
- Use only existing project/runtime dependencies; all archive and filesystem work uses the Python
  standard library.
- Keep `pyproject.toml` at `0.4.0a1`; do not publish, tag, or create a GitHub release in this plan.
- Preserve the untracked `2026-07-17T19-22-38.740+02-00-openclaw-backup.tar.gz` without reading,
  staging, modifying, moving, deleting, or archiving it.

---

## File map

- Create `src/bundlewalker/coordination.py`: descriptor-safe workspace directory opening and the
  shared cross-process lock extracted from `transactions.py`.
- Modify `src/bundlewalker/transactions.py`: consume the shared lock and expose
  `QuiescentWorkspace` plus `quiescent_workspace(...)` without changing the phase machine.
- Modify `src/bundlewalker/workspace.py`: factor read-only config discovery/parsing and apply a
  bounded 1 MiB configuration parser used by compatibility and archive verification.
- Create `src/bundlewalker/compatibility.py`: workspace status, migration-step contracts, path
  planning, and current-format policy.
- Create `src/bundlewalker/backups.py`: strict manifest contracts, archive verification, locked
  backup creation, restore staging, and restore publication.
- Create `src/bundlewalker/upgrades.py`: backup-first explicit upgrade orchestration without a
  compatibility/backup import cycle.
- Modify `src/bundlewalker/errors.py`: add typed compatibility, backup, restore, and migration
  failures.
- Create `src/bundlewalker/application/lifecycle.py`: synchronous adapter-neutral lifecycle use
  cases and injectable clock/version/migration dependencies.
- Modify `src/bundlewalker/application/contracts.py`: serializable lifecycle result records.
- Modify `src/bundlewalker/application/errors.py`: stable lifecycle error categories and redacted
  translation, including pre-upgrade backup identity after migration failure.
- Modify `src/bundlewalker/application/__init__.py`: export the lifecycle contracts and facade.
- Modify `src/bundlewalker/interfaces/cli.py`: add the `workspace` Typer group and stable output.
- Create `tests/test_coordination.py`, `tests/test_compatibility.py`, `tests/test_backups.py`,
  `tests/test_historical_compatibility.py`, `tests/test_upgrades.py`,
  `tests/test_transaction_crash_recovery.py`,
  `tests/application/test_lifecycle.py`, and `tests/cli/test_workspace.py`.
- Modify `tests/test_transactions.py`, `tests/application/test_contracts.py`, and
  `tests/test_project_automation.py` for the new public seams and documentation contracts.
- Create immutable fixture trees and provenance under `tests/fixtures/historical/`.
- Create `docs/workspace-compatibility.md` and modify `README.md`, `docs/user-guide.md`,
  `docs/tutorial.md`, and `docs/maintainers/releases.md`.

## Design coverage

| Approved design area | Implementation and evidence |
| --- | --- |
| Shared lock and quiescent guard | Task 1 |
| Compatibility policy and bounded config inspection | Task 2 |
| Immutable v1/v2/v3 and transaction fixtures | Task 3 |
| Strict manifest and streaming adversarial verification | Task 4 |
| Quiescent, scoped, race-detecting backup creation | Task 5 |
| Verified non-destructive restore | Task 6 |
| Backup-first explicit upgrade and rollback artifact | Task 7 |
| Adapter-neutral lifecycle API, errors, and CLI | Task 8 |
| Abrupt process-exit recovery across durable phases | Task 9 |
| Public policy, user procedures, release evidence, and full gate | Task 10 |

### Task 1: Extract Shared Coordination and Add the Quiescent Guard

**Files:**
- Create: `src/bundlewalker/coordination.py`
- Modify: `src/bundlewalker/transactions.py:1-65,455-481,1140-1176,2047-2087`
- Create: `tests/test_coordination.py`
- Modify: `tests/test_transactions.py:305-667,1991-2026`

**Interfaces:**
- Consumes: the current `_open_workspace_directory(...)` and
  `_workspace_transaction_lock(...)` implementations and all existing transaction tests.
- Produces: `open_workspace_directory(workspace, parts, *, label, create_from=None)`,
  `workspace_lock(workspace)`, `QuiescentWorkspace(workspace)`, and
  `quiescent_workspace(workspace)`; Tasks 5 and 7 require the quiescent token.

- [ ] **Step 1: Write failing coordination and quiescence tests**

Create `tests/test_coordination.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import stat
from pathlib import Path

from bundlewalker.coordination import workspace_lock
from bundlewalker.workspace import initialize_workspace


def test_workspace_lock_creates_one_regular_private_lock(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    with workspace_lock(workspace):
        lock = workspace.root / ".bundlewalker" / "transaction.lock"
        metadata = lock.stat(follow_symlinks=False)
        assert stat.S_ISREG(metadata.st_mode)
        assert metadata.st_mode & 0o077 == 0

    assert lock.is_file()
```

Append to `tests/test_transactions.py`:

```python
def test_quiescent_workspace_yields_only_after_recovery(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    with transactions.quiescent_workspace(workspace) as quiescent:
        assert quiescent.workspace == workspace
        assert (workspace.root / ".bundlewalker/transaction.lock").is_file()


def test_quiescent_workspace_preserves_and_rejects_pending_review(tmp_path: Path) -> None:
    prepared, _source = _prepare(tmp_path)

    with pytest.raises(ReviewPendingError) as raised:
        with transactions.quiescent_workspace(prepared.workspace):
            pytest.fail("pending review must prevent a quiescent snapshot")

    assert raised.value.review_id == prepared.transaction_id
    assert prepared.transaction_dir.is_dir()
    pending = get_pending_review(prepared.workspace)
    assert pending is not None
    assert pending.review_id == prepared.transaction_id
```

Add `ReviewPendingError` and `get_pending_review` to the existing imports in that test file.

- [ ] **Step 2: Run the focused tests and verify the missing seam fails**

Run:

```bash
uv run pytest tests/test_coordination.py tests/test_transactions.py::test_quiescent_workspace_yields_only_after_recovery tests/test_transactions.py::test_quiescent_workspace_preserves_and_rejects_pending_review -v
```

Expected: collection fails because `bundlewalker.coordination` and
`transactions.quiescent_workspace` do not exist.

- [ ] **Step 3: Extract the exact coordination implementation**

Create `src/bundlewalker/coordination.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager, suppress

from bundlewalker.errors import TransactionError
from bundlewalker.workspace import Workspace

LOCK_NAME = "transaction.lock"


@contextmanager
def open_workspace_directory(
    workspace: Workspace,
    parts: tuple[str, ...],
    *,
    label: str,
    create_from: int | None = None,
) -> Generator[int]:
    if any(not part or part in {".", ".."} or "/" in part for part in parts):
        raise TransactionError(f"{label} is not a safe workspace-relative directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    traversed: list[str] = []
    try:
        current = os.open(workspace.root, flags)
        descriptors.append(current)
        for index, part in enumerate(parts):
            traversed.append(part)
            try:
                child = os.open(part, flags, dir_fd=current)
            except FileNotFoundError:
                if create_from is None or index < create_from:
                    raise
                with suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=current)
                os.fsync(current)
                child = os.open(part, flags, dir_fd=current)
            descriptors.append(child)
            current = child
    except OSError as exc:
        location = "/".join(traversed) or "."
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)
        raise TransactionError(
            f"{label} contains a symlink or non-directory: {location}"
        ) from exc
    try:
        yield current
    finally:
        for descriptor in reversed(descriptors):
            with suppress(OSError):
                os.close(descriptor)


@contextmanager
def workspace_lock(workspace: Workspace) -> Generator[None]:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    with open_workspace_directory(
        workspace,
        (".bundlewalker",),
        label="transaction lock parent",
        create_from=0,
    ) as parent_descriptor:
        try:
            try:
                descriptor = os.open(
                    LOCK_NAME,
                    flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                os.fsync(parent_descriptor)
            except FileExistsError:
                descriptor = os.open(LOCK_NAME, flags, dir_fd=parent_descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise TransactionError("workspace transaction lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise TransactionError("could not acquire workspace transaction lock") from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
```

In `transactions.py`, import:

```python
from bundlewalker.coordination import open_workspace_directory, workspace_lock
```

Replace every `_open_workspace_directory(...)` call with `open_workspace_directory(...)`, every
`_workspace_transaction_lock(...)` call with `workspace_lock(...)`, remove `_LOCK_NAME`, and remove
the two extracted function bodies. Do not change their callers or error text.

- [ ] **Step 4: Add the quiescent token and guard**

Add beside `PreparedTransaction`:

```python
@dataclass(frozen=True, slots=True)
class QuiescentWorkspace:
    """Proof that recovery and review checks passed while the workspace lock is held."""

    workspace: Workspace
```

Add after `ensure_no_pending_review(...)`:

```python
@contextmanager
def quiescent_workspace(workspace: Workspace) -> Generator[QuiescentWorkspace]:
    """Recover and retain the workspace lock while no durable review remains."""
    transactions_root = workspace.root.joinpath(*_TRANSACTIONS_PATH.parts)
    with workspace_lock(workspace):
        if transactions_root.exists() or transactions_root.is_symlink():
            _recover_transactions_locked(workspace, transactions_root)
            pending = _get_pending_review_locked(workspace, transactions_root)
            if pending is not None:
                raise ReviewPendingError(pending.review_id)
        yield QuiescentWorkspace(workspace)
```

Remove now-unused `fcntl` from `transactions.py`; keep `stat` because transaction path validation
still uses it.

- [ ] **Step 5: Run extraction characterization and the full transaction suite**

Run:

```bash
uv run pytest tests/test_coordination.py tests/test_transactions.py tests/test_acceptance.py -q
uv run ruff format --check src/bundlewalker/coordination.py src/bundlewalker/transactions.py tests/test_coordination.py tests/test_transactions.py
uv run ruff check src/bundlewalker/coordination.py src/bundlewalker/transactions.py tests/test_coordination.py tests/test_transactions.py
uv run pyright src/bundlewalker/coordination.py src/bundlewalker/transactions.py tests/test_coordination.py tests/test_transactions.py
```

Expected: all tests and static checks pass with unchanged transaction behavior.

- [ ] **Step 6: Commit the coordination seam**

```bash
git add src/bundlewalker/coordination.py src/bundlewalker/transactions.py tests/test_coordination.py tests/test_transactions.py
git commit -m "refactor: share workspace coordination lock"
```

### Task 2: Add Read-only Compatibility Inspection and Migration Planning Contracts

**Files:**
- Modify: `src/bundlewalker/workspace.py:18-55,73-92,244-295`
- Create: `src/bundlewalker/compatibility.py`
- Modify: `src/bundlewalker/errors.py:1-55`
- Modify: `tests/test_workspace.py:1-120`
- Create: `tests/test_compatibility.py`

**Interfaces:**
- Consumes: `WorkspaceConfig`, workspace discovery, `QuiescentWorkspace`, package version
  `0.4.0a1`, and the exact format decisions from the approved design.
- Produces: `MAX_WORKSPACE_CONFIG_BYTES`, `find_workspace_config(...)`,
  `parse_workspace_config(...)`, `read_workspace_format_version(...)`, `CompatibilityStatus`, `WorkspaceCompatibility`,
  `MigrationStep`, `migration_path(...)`, and `inspect_workspace(...)`; archive verification,
  upgrade orchestration, application status, and historical tests consume these names.

- [ ] **Step 1: Write failing bounded-parser and compatibility tests**

Append to `tests/test_workspace.py`:

```python
def test_workspace_configuration_has_a_bounded_parser(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_bytes(b"#" * (workspace_module.MAX_WORKSPACE_CONFIG_BYTES + 1))

    with pytest.raises(ConfigurationError, match="supported size"):
        discover_workspace(root)
```

Create `tests/test_compatibility.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

import pytest

from bundlewalker.compatibility import (
    CompatibilityStatus,
    MigrationStep,
    inspect_workspace,
    migration_path,
)
from bundlewalker.errors import ConfigurationError
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.workspace import Workspace, initialize_workspace


def _write_version(root: Path, version: object) -> None:
    root.mkdir()
    (root / "bundlewalker.toml").write_text(
        f"version = {version}\n"
        'wiki_dir = "wiki"\n'
        'raw_dir = "raw"\n'
        'conventions_file = "conventions.md"\n'
        "max_source_characters = 100000\n",
        encoding="utf-8",
    )


def test_current_workspace_is_readable_writable_and_not_upgradeable(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    result = inspect_workspace(workspace.root)

    assert result.root == workspace.root
    assert result.workspace_format_version == 1
    assert result.status is CompatibilityStatus.CURRENT
    assert result.readable is True
    assert result.writable is True
    assert result.upgrade_available is False


@pytest.mark.parametrize(
    ("version", "status"),
    [(0, CompatibilityStatus.UNSUPPORTED), (2, CompatibilityStatus.TOO_NEW)],
)
def test_noncurrent_well_formed_versions_are_inspection_only(
    tmp_path: Path,
    version: int,
    status: CompatibilityStatus,
) -> None:
    root = tmp_path / f"format-{version}"
    _write_version(root, version)

    result = inspect_workspace(root)

    assert result.workspace_format_version == version
    assert result.status is status
    assert result.readable is False
    assert result.writable is False
    assert result.upgrade_available is False


@pytest.mark.parametrize("content", ["version = '1'\n", "not toml", "wiki_dir = 'wiki'\n"])
def test_malformed_or_missing_version_is_a_configuration_error(
    tmp_path: Path,
    content: str,
) -> None:
    root = tmp_path / "invalid"
    root.mkdir()
    (root / "bundlewalker.toml").write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError):
        inspect_workspace(root)


def test_migration_path_requires_a_complete_contiguous_chain() -> None:
    def apply(_quiescent: QuiescentWorkspace) -> None:
        return None

    def verify(_workspace: Workspace) -> None:
        return None

    steps = {
        1: MigrationStep(1, 2, apply, verify),
        2: MigrationStep(2, 3, apply, verify),
    }

    assert migration_path(1, target_version=3, migrations=steps) == (
        steps[1],
        steps[2],
    )
    assert migration_path(1, target_version=4, migrations=steps) is None
    assert migration_path(3, target_version=3, migrations=steps) == ()
    assert migration_path(4, target_version=3, migrations=steps) is None


def test_upgradeable_status_uses_an_injected_complete_registry(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge")

    def apply(_quiescent: QuiescentWorkspace) -> None:
        return None

    def verify(_workspace: Workspace) -> None:
        return None

    step = MigrationStep(1, 2, apply, verify)
    result = inspect_workspace(
        workspace.root,
        target_version=2,
        migrations={1: step},
    )

    assert result.status is CompatibilityStatus.UPGRADEABLE
    assert result.readable is False
    assert result.writable is False
    assert result.upgrade_available is True
```

Import `ConfigurationError` in `tests/test_workspace.py`.

- [ ] **Step 2: Run the focused tests and verify the new contracts are absent**

Run:

```bash
uv run pytest tests/test_workspace.py::test_workspace_configuration_has_a_bounded_parser tests/test_compatibility.py -v
```

Expected: collection fails because the new workspace constant and compatibility module do not
exist.

- [ ] **Step 3: Factor bounded configuration discovery and parsing**

In `workspace.py`, add:

```python
MAX_WORKSPACE_CONFIG_BYTES = 1_048_576


def find_workspace_config(start: Path | None = None) -> Path:
    candidate = (start or Path.cwd()).expanduser().resolve(strict=False)
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        config_path = directory / CONFIG_FILENAME
        if config_path.is_file() and not config_path.is_symlink():
            return config_path
    raise WorkspaceError(f"could not find {CONFIG_FILENAME} from {candidate}")


def parse_workspace_config(text: str, *, source: str = CONFIG_FILENAME) -> WorkspaceConfig:
    try:
        values = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"could not read workspace configuration: {source}") from exc
    expected = {
        "version",
        "wiki_dir",
        "raw_dir",
        "conventions_file",
        "max_source_characters",
    }
    if set(values) != expected:
        raise ConfigurationError(f"workspace configuration has unexpected keys: {source}")
    version = values["version"]
    max_characters = values["max_source_characters"]
    if type(version) is not int or version != 1:
        raise ConfigurationError("workspace configuration version must be 1")
    if type(max_characters) is not int or max_characters < 1:
        raise ConfigurationError("max_source_characters must be a positive integer")
    path_values: dict[str, str] = {}
    for key in ("wiki_dir", "raw_dir", "conventions_file"):
        normalized = normalize_workspace_config_path(values[key])
        if normalized is None:
            raise ConfigurationError(f"{key} must be a safe workspace-relative path")
        path_values[key] = normalized
    return WorkspaceConfig(
        version=version,
        wiki_dir=path_values["wiki_dir"],
        raw_dir=path_values["raw_dir"],
        conventions_file=path_values["conventions_file"],
        max_source_characters=max_characters,
    )


def load_workspace_config(path: Path) -> WorkspaceConfig:
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f"could not read workspace configuration: {path}") from exc
    if len(content) > MAX_WORKSPACE_CONFIG_BYTES:
        raise ConfigurationError("workspace configuration exceeds the supported size")
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ConfigurationError(f"could not read workspace configuration: {path}") from exc
    return parse_workspace_config(text, source=str(path))
```

Replace `discover_workspace(...)` with:

```python
def discover_workspace(start: Path | None = None) -> Workspace:
    config_path = find_workspace_config(start)
    return Workspace(root=config_path.parent, config=load_workspace_config(config_path))
```

Remove `_load_config(...)`, replace its two initialization callers with
`load_workspace_config(...)`, and keep exact configuration validation behavior for format `1`.

- [ ] **Step 4: Add typed compatibility and migration planning**

Add to `errors.py`:

```python
class WorkspaceCompatibilityError(ConfigurationError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"workspace is not current: {status}")
```

Create `src/bundlewalker/compatibility.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from bundlewalker.errors import ConfigurationError
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.workspace import (
    MAX_WORKSPACE_CONFIG_BYTES,
    Workspace,
    discover_workspace,
    find_workspace_config,
)

CURRENT_WORKSPACE_FORMAT = 1
MINIMUM_WORKSPACE_FORMAT = 1


class CompatibilityStatus(StrEnum):
    CURRENT = "current"
    UPGRADEABLE = "upgradeable"
    TOO_NEW = "too_new"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MigrationStep:
    source_version: int
    target_version: int
    apply: Callable[[QuiescentWorkspace], None]
    verify: Callable[[Workspace], None]


@dataclass(frozen=True, slots=True)
class WorkspaceCompatibility:
    root: Path
    config_path: Path
    workspace_format_version: int
    status: CompatibilityStatus
    readable: bool
    writable: bool
    upgrade_available: bool


def migration_path(
    source_version: int,
    *,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
) -> tuple[MigrationStep, ...] | None:
    if source_version > target_version:
        return None
    if source_version == target_version:
        return ()
    registered = migrations or {}
    current = source_version
    path: list[MigrationStep] = []
    seen: set[int] = set()
    while current < target_version:
        if current in seen:
            return None
        seen.add(current)
        step = registered.get(current)
        if (
            step is None
            or step.source_version != current
            or step.target_version <= current
            or step.target_version > target_version
        ):
            return None
        path.append(step)
        current = step.target_version
    return tuple(path) if current == target_version else None


def inspect_workspace(
    start: Path | None = None,
    *,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
) -> WorkspaceCompatibility:
    config_path = find_workspace_config(start)
    version = read_workspace_format_version(config_path)
    root = config_path.parent
    if version > target_version:
        return WorkspaceCompatibility(
            root, config_path, version, CompatibilityStatus.TOO_NEW, False, False, False
        )
    if version < MINIMUM_WORKSPACE_FORMAT:
        return WorkspaceCompatibility(
            root, config_path, version, CompatibilityStatus.UNSUPPORTED, False, False, False
        )
    path = migration_path(
        version,
        target_version=target_version,
        migrations=migrations,
    )
    if version < target_version:
        status = CompatibilityStatus.UPGRADEABLE if path is not None else CompatibilityStatus.UNSUPPORTED
        return WorkspaceCompatibility(
            root,
            config_path,
            version,
            status,
            False,
            False,
            path is not None,
        )
    discover_workspace(root)
    return WorkspaceCompatibility(
        root, config_path, version, CompatibilityStatus.CURRENT, True, True, False
    )


def read_workspace_format_version(config_path: Path) -> int:
    try:
        content = config_path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(
            f"could not read workspace configuration: {config_path}"
        ) from exc
    if len(content) > MAX_WORKSPACE_CONFIG_BYTES:
        raise ConfigurationError("workspace configuration exceeds the supported size")
    try:
        parsed = tomllib.loads(content.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(
            f"could not read workspace configuration: {config_path}"
        ) from exc
    values = cast(dict[str, object], parsed)
    version = values.get("version")
    if type(version) is not int:
        raise ConfigurationError("workspace configuration version must be an integer")
    return version
```

Format this module; Ruff will wrap the `status = ...` expression.

- [ ] **Step 5: Run compatibility and existing workspace tests**

Run:

```bash
uv run pytest tests/test_workspace.py tests/test_compatibility.py tests/test_changes.py tests/okf/test_lint.py -q
uv run ruff format --check src/bundlewalker/workspace.py src/bundlewalker/compatibility.py tests/test_workspace.py tests/test_compatibility.py
uv run ruff check src/bundlewalker/workspace.py src/bundlewalker/compatibility.py tests/test_workspace.py tests/test_compatibility.py
uv run pyright src/bundlewalker/workspace.py src/bundlewalker/compatibility.py tests/test_workspace.py tests/test_compatibility.py
```

Expected: all tests pass, current format remains exactly `1`, and format inspection performs no
workspace mutation.

- [ ] **Step 6: Commit the compatibility boundary**

```bash
git add src/bundlewalker/workspace.py src/bundlewalker/compatibility.py src/bundlewalker/errors.py tests/test_workspace.py tests/test_compatibility.py
git commit -m "feat: define workspace compatibility boundary"
```

### Task 3: Preserve Historical Release Fixtures

**Files:**
- Create: `tests/fixtures/historical/v1-clean/`
- Create: `tests/fixtures/historical/v2-clean/`
- Create: `tests/fixtures/historical/v3-clean/`
- Create: `tests/fixtures/historical/v1-schema1-swapping/`
- Create: `tests/fixtures/historical/v3-schema2-pending/`
- Create: `tests/fixtures/historical/invalid-malformed/`
- Create: `tests/fixtures/historical/invalid-format-zero/`
- Create: `tests/fixtures/historical/future-format/`
- Create: `tests/fixtures/historical/provenance.json`
- Create: `tests/test_historical_compatibility.py`

**Interfaces:**
- Consumes: immutable tags `v1` (`be165ac283ba7511592771fd876c89b12ef4ff1a`), `v2`
  (`12ef119ac3b2ba84cff7ca9aee0fbf14b239d975`), and `v3`
  (`ab079a16a98cc31c46f77db73c941328c886075b`), plus Task 2 compatibility inspection.
- Produces: static historical byte fixtures used by Tasks 5, 6, 9, and final CI; tests never
  regenerate them with current code.

- [ ] **Step 1: Add failing historical compatibility tests**

Create `tests/test_historical_compatibility.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bundlewalker.compatibility import CompatibilityStatus, inspect_workspace
from bundlewalker.errors import ConfigurationError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import get_pending_review, recover_transactions
from bundlewalker.workspace import discover_workspace

FIXTURES = Path(__file__).parent / "fixtures" / "historical"


@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_clean_workspace_remains_current_and_readable(
    tmp_path: Path,
    release: str,
) -> None:
    root = tmp_path / release
    shutil.copytree(FIXTURES / f"{release}-clean", root)

    compatibility = inspect_workspace(root)
    workspace = discover_workspace(root)
    documents = OkfRepository(workspace.wiki_dir).scan()

    assert compatibility.status is CompatibilityStatus.CURRENT
    assert compatibility.workspace_format_version == 1
    assert "sources/index" not in documents
    assert (workspace.wiki_dir / "index.md").is_file()


def test_v1_interrupted_schema1_transaction_recovers_exact_base(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    shutil.copytree(FIXTURES / "v1-schema1-swapping", root)
    expected = (root / "expected-base.sha256").read_text(encoding="utf-8").strip()
    (root / "expected-base.sha256").unlink()
    workspace = discover_workspace(root)

    recover_transactions(workspace)

    assert _tree_digest(workspace.wiki_dir) == expected
    assert not any((root / ".bundlewalker/transactions").iterdir())


def test_v3_pending_review_remains_pending(tmp_path: Path) -> None:
    root = tmp_path / "pending"
    shutil.copytree(FIXTURES / "v3-schema2-pending", root)
    workspace = discover_workspace(root)

    pending = get_pending_review(workspace)

    assert pending is not None
    assert pending.kind.value == "ingestion"
    assert pending.status.value == "pending"


def test_static_provenance_pins_release_commits() -> None:
    provenance = json.loads((FIXTURES / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["v1"]["commit"] == "be165ac283ba7511592771fd876c89b12ef4ff1a"
    assert provenance["v2"]["commit"] == "12ef119ac3b2ba84cff7ca9aee0fbf14b239d975"
    assert provenance["v3"]["commit"] == "ab079a16a98cc31c46f77db73c941328c886075b"
    assert {provenance[release]["expected_compatibility"] for release in ("v1", "v2", "v3")} == {"current"}
    assert provenance["fixtures"]["v1-schema1-swapping"] == "recovers_base"
    assert provenance["fixtures"]["v3-schema2-pending"] == "pending_review"


@pytest.mark.parametrize(
    ("name", "status"),
    [
        ("invalid-format-zero", CompatibilityStatus.UNSUPPORTED),
        ("future-format", CompatibilityStatus.TOO_NEW),
    ],
)
def test_well_formed_incompatible_fixtures_are_inspection_only(
    name: str,
    status: CompatibilityStatus,
) -> None:
    assert inspect_workspace(FIXTURES / name).status is status


def test_malformed_fixture_is_a_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        inspect_workspace(FIXTURES / "invalid-malformed")


def _tree_digest(root: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        if path.is_dir():
            digest.update(b"D" + len(relative).to_bytes(8, "big") + relative)
        elif path.is_file() and not path.is_symlink():
            content = path.read_bytes()
            digest.update(b"F" + len(relative).to_bytes(8, "big") + relative)
            digest.update(len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()
```

- [ ] **Step 2: Run the tests and verify every fixture is absent**

Run:

```bash
uv run pytest tests/test_historical_compatibility.py -v
```

Expected: tests fail with missing fixture paths.

- [ ] **Step 3: Generate clean fixtures with each release's own code**

Use a temporary directory outside the repository; never checkout a tag over the working branch:

```bash
fixture_worktrees="$(mktemp -d)"
git worktree add --detach "$fixture_worktrees/v1" v1
git worktree add --detach "$fixture_worktrees/v2" v2
git worktree add --detach "$fixture_worktrees/v3" v3
for release in v1 v2 v3; do
  (
    cd "$fixture_worktrees/$release"
    uv sync --locked
  )
done
```

Run this exact loop so each fixture is initialized by the installed code from its own release
worktree:

```bash
for release in v1 v2 v3; do
  FIXTURE_OUTPUT="/Volumes/OWC Envoy Ultra/Development/BundleWalker/tests/fixtures/historical/$release-clean" \
  uv run --directory "$fixture_worktrees/$release" python - <<'PY'
import os
from datetime import UTC, datetime
from pathlib import Path
from bundlewalker.workspace import initialize_workspace

initialize_workspace(
    Path(os.environ["FIXTURE_OUTPUT"]),
    occurred_at=datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
)
PY
done
```

Running the tag's installed module rather than current code is the provenance guarantee. Keep all
three worktrees until Step 7 completes.

- [ ] **Step 4: Generate the v1 schema-1 swapping fixture with v1 code**

Run this exact program from the detached v1 worktree. It uses the v1 public transaction API,
changes only the persisted phase field, and reproduces the durable topology immediately after the
live wiki has moved to `backup-wiki`:

```bash
FIXTURE_OUTPUT="/Volumes/OWC Envoy Ultra/Development/BundleWalker/tests/fixtures/historical/v1-schema1-swapping" \
uv run --directory "$fixture_worktrees/v1" python - <<'PY'
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import prepare_transaction
from bundlewalker.workspace import initialize_workspace, load_raw_source

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
root = Path(os.environ["FIXTURE_OUTPUT"])
workspace = initialize_workspace(root, occurred_at=NOW)
input_path = root.parent / "v1-source-notes.txt"
input_path.write_bytes(b"first line\r\nsecond line\n")
source = load_raw_source(input_path, workspace)
draft = DraftConcept(
    operation=ChangeOperation.CREATE,
    path=source.concept_id,
    type=ConceptType.SOURCE,
    title="Source notes",
    description="Knowledge about Source notes.",
    tags=["test"],
    body="# Source notes\n\nA grounded claim [1].\n",
    citations=[
        Citation(
            number=1,
            concept_id=source.concept_id,
            start_line=1,
            end_line=2,
        )
    ],
    base_digest=None,
)
change_set = ChangeSet(
    summary="Integrated source notes.",
    source_sha256=source.sha256,
    drafts=[draft],
)
context = ChangeValidationContext(
    mode="ingest",
    repository=OkfRepository(workspace.wiki_dir),
    readable_concepts=frozenset(),
    source=source,
)
prepared = prepare_transaction(workspace, change_set, context, source, NOW)

digest = hashlib.sha256()
for path in sorted(
    workspace.wiki_dir.rglob("*"),
    key=lambda item: item.relative_to(workspace.wiki_dir).as_posix(),
):
    relative = path.relative_to(workspace.wiki_dir).as_posix().encode()
    if path.is_dir():
        digest.update(b"D" + len(relative).to_bytes(8, "big") + relative)
    elif path.is_file() and not path.is_symlink():
        content = path.read_bytes()
        digest.update(b"F" + len(relative).to_bytes(8, "big") + relative)
        digest.update(len(content).to_bytes(8, "big") + content)
(root / "expected-base.sha256").write_text(digest.hexdigest() + "\n", encoding="utf-8")

manifest_path = prepared.transaction_dir / "manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest["schema_version"] == 1
assert manifest["phase"] == "prepared"
manifest["phase"] = "swapping"
manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
raw_destination = root / source.stored_relative_path
raw_destination.parent.mkdir(parents=True, exist_ok=True)
raw_destination.write_bytes(source.content)
workspace.wiki_dir.rename(prepared.backup_wiki)
input_path.unlink()
PY
```

Run after generation:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

root = Path("tests/fixtures/historical/v1-schema1-swapping")
transactions = list((root / ".bundlewalker/transactions").iterdir())
assert len(transactions) == 1
manifest = json.loads((transactions[0] / "manifest.json").read_text(encoding="utf-8"))
assert manifest["schema_version"] == 1
assert manifest["phase"] == "swapping"
assert not (root / "wiki").exists()
assert (transactions[0] / "backup-wiki").is_dir()
PY
```

Expected: all assertions pass. The wildcard must resolve to exactly one transaction directory.

- [ ] **Step 5: Generate the v3 schema-2 pending-review fixture with v3 code**

Run the complete v3-owned generator below. It leaves the authenticated schema-2 review in the
`prepared` phase and removes only the source input outside the fixture:

```bash
FIXTURE_OUTPUT="/Volumes/OWC Envoy Ultra/Development/BundleWalker/tests/fixtures/historical/v3-schema2-pending" \
uv run --directory "$fixture_worktrees/v3" python - <<'PY'
import os
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import ReviewKind, prepare_transaction
from bundlewalker.workspace import initialize_workspace, load_raw_source

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
root = Path(os.environ["FIXTURE_OUTPUT"])
workspace = initialize_workspace(root, occurred_at=NOW)
input_path = root.parent / "v3-source-notes.txt"
input_path.write_bytes(b"first line\r\nsecond line\n")
source = load_raw_source(input_path, workspace)
draft = DraftConcept(
    operation=ChangeOperation.CREATE,
    path=source.concept_id,
    type=ConceptType.SOURCE,
    title="Source notes",
    description="Knowledge about Source notes.",
    tags=["test"],
    body="# Source notes\n\nA grounded claim [1].\n",
    citations=[
        Citation(
            number=1,
            concept_id=source.concept_id,
            start_line=1,
            end_line=2,
        )
    ],
    base_digest=None,
)
change_set = ChangeSet(
    summary="Integrated source notes.",
    source_sha256=source.sha256,
    drafts=[draft],
)
context = ChangeValidationContext(
    mode="ingest",
    repository=OkfRepository(workspace.wiki_dir),
    readable_concepts=frozenset(),
    source=source,
)
prepare_transaction(
    workspace,
    change_set,
    context,
    source,
    NOW,
    kind=ReviewKind.INGESTION,
)
input_path.unlink()
PY
```

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

root = Path("tests/fixtures/historical/v3-schema2-pending")
transactions = list((root / ".bundlewalker/transactions").iterdir())
assert len(transactions) == 1
manifest = json.loads((transactions[0] / "manifest.json").read_text(encoding="utf-8"))
review = json.loads((transactions[0] / "review.json").read_text(encoding="utf-8"))
assert manifest["schema_version"] == 2
assert manifest["phase"] == "prepared"
assert review["schema_version"] == 1
PY
```

Expected: all assertions pass and exactly one `review.json` exists.

- [ ] **Step 6: Add invalid fixtures and exact provenance**

Create minimal invalid directories containing only these configuration bytes:

`invalid-malformed/bundlewalker.toml`:

```toml
version = [
```

`invalid-format-zero/bundlewalker.toml`:

```toml
version = 0
```

`future-format/bundlewalker.toml`:

```toml
version = 2
future_managed_path = "future-data"
```

Create `tests/fixtures/historical/provenance.json`:

```json
{
  "v1": {
    "tag": "v1",
    "commit": "be165ac283ba7511592771fd876c89b12ef4ff1a",
    "package_version": "0.1.0",
    "workspace_format": 1,
    "transaction_schema": 1,
    "expected_compatibility": "current"
  },
  "v2": {
    "tag": "v2",
    "commit": "12ef119ac3b2ba84cff7ca9aee0fbf14b239d975",
    "package_version": "0.2.0",
    "workspace_format": 1,
    "transaction_schema": 2,
    "review_schema": 1,
    "expected_compatibility": "current"
  },
  "v3": {
    "tag": "v3",
    "commit": "ab079a16a98cc31c46f77db73c941328c886075b",
    "package_version": "0.3.0",
    "workspace_format": 1,
    "transaction_schema": 2,
    "review_schema": 1,
    "expected_compatibility": "current"
  },
  "fixtures": {
    "v1-schema1-swapping": "recovers_base",
    "v3-schema2-pending": "pending_review",
    "invalid-malformed": "configuration_error",
    "invalid-format-zero": "unsupported",
    "future-format": "too_new"
  }
}
```

- [ ] **Step 7: Run historical tests and ensure fixtures contain no environments or caches**

Run:

```bash
uv run pytest tests/test_historical_compatibility.py tests/test_transactions.py -q
test -z "$(find tests/fixtures/historical -name .venv -o -name __pycache__ -o -name '*.pyc' -print -quit)"
git diff --check
git worktree remove "$fixture_worktrees/v1"
git worktree remove "$fixture_worktrees/v2"
git worktree remove "$fixture_worktrees/v3"
rmdir "$fixture_worktrees"
```

Expected: all tests pass and the fixture tree contains only intended workspace/provenance bytes.

- [ ] **Step 8: Commit the immutable fixture evidence**

```bash
git add tests/fixtures/historical tests/test_historical_compatibility.py
git commit -m "test: preserve historical workspace fixtures"
```

### Task 4: Implement the Strict Backup Manifest and Archive Verifier

**Files:**
- Create: `src/bundlewalker/backups.py`
- Modify: `src/bundlewalker/errors.py`
- Create: `tests/test_backups.py`

**Interfaces:**
- Consumes: Task 2 `parse_workspace_config(...)`, current format constants, configured path rules,
  and the approved ZIP schema.
- Produces: `BackupFileRecord`, `BackupManifest`, `VerifiedBackup`, and
  `verify_backup_archive(path)`; Tasks 5, 6, 7, and 8 use the same verifier.

- [ ] **Step 1: Write a valid-archive helper and failing verifier tests**

Create `tests/test_backups.py` with these foundations:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.backups import (
    ARCHIVE_FORMAT,
    ARCHIVE_SCHEMA_VERSION,
    BackupManifest,
    VerifiedBackup,
    verify_backup_archive,
)
from bundlewalker.errors import BackupVerificationError
from bundlewalker.workspace import DEFAULT_CONFIG_TEXT

CREATED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _valid_payload() -> dict[str, bytes]:
    return {
        "bundlewalker.toml": DEFAULT_CONFIG_TEXT.encode(),
        "conventions.md": b"# Conventions\n",
        "wiki/index.md": b"# Index\n",
        "wiki/log.md": b"# Log\n",
        "wiki/sources/index.md": b"# Sources\n",
        "wiki/topics/index.md": b"# Topics\n",
        "wiki/entities/index.md": b"# Entities\n",
        "wiki/syntheses/index.md": b"# Syntheses\n",
    }


def _write_archive(
    path: Path,
    *,
    payload: dict[str, bytes] | None = None,
    manifest_updates: dict[str, object] | None = None,
    extra_members: tuple[tuple[str, bytes], ...] = (),
) -> None:
    files = payload or _valid_payload()
    directories = sorted(
        {
            "raw",
            "wiki",
            "wiki/sources",
            "wiki/topics",
            "wiki/entities",
            "wiki/syntheses",
        }
    )
    manifest: dict[str, object] = {
        "archive_format": ARCHIVE_FORMAT,
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "created_at": CREATED_AT.isoformat(),
        "bundlewalker_version": "0.4.0a1",
        "workspace_format_version": 1,
        "directories": directories,
        "files": [
            {
                "path": name,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in sorted(files.items())
        ],
    }
    manifest.update(manifest_updates or {})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr(
            "bundlewalker-backup.json",
            json.dumps(manifest, sort_keys=True).encode(),
        )
        for directory in directories:
            archive.writestr(f"workspace/{directory}/", b"")
        for name, content in sorted(files.items()):
            archive.writestr(f"workspace/{name}", content)
        for name, content in extra_members:
            archive.writestr(name, content)


def test_verify_accepts_exact_current_archive(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    _write_archive(archive)

    verified = verify_backup_archive(archive)

    assert isinstance(verified, VerifiedBackup)
    assert verified.archive_path == archive.resolve()
    assert verified.archive_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert verified.manifest.workspace_format_version == 1
    assert verified.file_count == len(_valid_payload())
    assert verified.byte_count == sum(map(len, _valid_payload().values()))


@pytest.mark.parametrize(
    "updates",
    [
        {"archive_format": "other"},
        {"schema_version": 2},
        {"workspace_format_version": 2},
        {"unknown": True},
        {"directories": ["wiki", "wiki"]},
    ],
)
def test_verify_rejects_invalid_manifest(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    archive = tmp_path / "invalid.zip"
    _write_archive(archive, manifest_updates=updates)

    with pytest.raises(BackupVerificationError, match="manifest"):
        verify_backup_archive(archive)


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "workspace/../escape",
        "workspace\\escape",
        "C:/escape",
        "workspace//double",
    ],
)
def test_verify_rejects_unsafe_or_unexpected_member(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "unsafe.zip"
    _write_archive(archive, extra_members=((name, b"unsafe"),))

    with pytest.raises(BackupVerificationError):
        verify_backup_archive(archive)


def test_verify_rejects_duplicate_zip_member(tmp_path: Path) -> None:
    archive = tmp_path / "duplicate.zip"
    _write_archive(
        archive,
        extra_members=(("workspace/wiki/index.md", b"duplicate"),),
    )

    with pytest.raises(BackupVerificationError, match="duplicate"):
        verify_backup_archive(archive)


def test_verify_rejects_digest_and_size_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "changed.zip"
    manifest_files = [
        {
            "path": name,
            "size": len(content),
            "sha256": ("0" * 64 if name == "wiki/index.md" else hashlib.sha256(content).hexdigest()),
        }
        for name, content in sorted(_valid_payload().items())
    ]
    _write_archive(archive, manifest_updates={"files": manifest_files})

    with pytest.raises(BackupVerificationError, match="digest"):
        verify_backup_archive(archive)


def test_verify_rejects_symlink_attributes(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    _write_archive(archive)
    replacement = tmp_path / "replacement.zip"
    with (
        zipfile.ZipFile(archive) as source,
        zipfile.ZipFile(replacement, "w") as target,
    ):
        for info in source.infolist():
            content = source.read(info)
            if info.filename == "workspace/wiki/index.md":
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            target.writestr(info, content)
    os.replace(replacement, archive)

    with pytest.raises(BackupVerificationError, match="symlink|special"):
        verify_backup_archive(archive)
```

- [ ] **Step 2: Run focused tests and verify the archive module is absent**

Run:

```bash
uv run pytest tests/test_backups.py -v
```

Expected: collection fails because `bundlewalker.backups` and the typed verification error do not
exist.

- [ ] **Step 3: Add strict manifest models and typed errors**

Add to `errors.py`:

```python
class BackupError(BundleWalkerError):
    pass


class BackupVerificationError(BackupError):
    pass
```

Create `src/bundlewalker/backups.py` with the module header, imports, constants, and models below:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bundlewalker.compatibility import CURRENT_WORKSPACE_FORMAT
from bundlewalker.errors import BackupVerificationError, BundleWalkerError
from bundlewalker.workspace import (
    CONFIG_FILENAME,
    MAX_WORKSPACE_CONFIG_BYTES,
    WorkspaceConfig,
    parse_workspace_config,
)

ARCHIVE_FORMAT = "bundlewalker-workspace-backup"
ARCHIVE_SCHEMA_VERSION = 1
MANIFEST_NAME = "bundlewalker-backup.json"
PAYLOAD_PREFIX = "workspace/"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_BACKUP_ENTRIES = 100_000
MAX_BACKUP_PATH_CHARACTERS = 4_096
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class BackupFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str = Field(min_length=1, max_length=MAX_BACKUP_PATH_CHARACTERS)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_path(self) -> Self:
        if _canonical_relative_path(self.path) != self.path:
            raise ValueError("backup file path is not canonical")
        return self


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    archive_format: Literal["bundlewalker-workspace-backup"]
    schema_version: Literal[1]
    created_at: datetime
    bundlewalker_version: str = Field(min_length=1, max_length=128)
    workspace_format_version: int
    directories: tuple[str, ...] = Field(max_length=MAX_BACKUP_ENTRIES)
    files: tuple[BackupFileRecord, ...] = Field(max_length=MAX_BACKUP_ENTRIES)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("backup timestamp must include a timezone")
        if self.workspace_format_version != CURRENT_WORKSPACE_FORMAT:
            raise ValueError("unsupported backup workspace format")
        if len(self.directories) + len(self.files) > MAX_BACKUP_ENTRIES:
            raise ValueError("backup contains too many entries")
        canonical_directories = tuple(_canonical_relative_path(path) for path in self.directories)
        if canonical_directories != self.directories:
            raise ValueError("backup directory paths must be canonical and sorted")
        if tuple(sorted(self.directories)) != self.directories:
            raise ValueError("backup directory paths must be canonical and sorted")
        file_paths = tuple(record.path for record in self.files)
        if tuple(sorted(file_paths)) != file_paths:
            raise ValueError("backup file paths must be canonical and sorted")
        if len(set(self.directories)) != len(self.directories):
            raise ValueError("backup contains duplicate directory paths")
        if len(set(file_paths)) != len(file_paths):
            raise ValueError("backup contains duplicate file paths")
        if set(self.directories) & set(file_paths):
            raise ValueError("backup path is both a file and a directory")
        all_paths = (*self.directories, *file_paths)
        if any(
            PurePosixPath(file_path) in PurePosixPath(other).parents
            for file_path in file_paths
            for other in all_paths
            if other != file_path
        ):
            raise ValueError("backup file path is an ancestor of another entry")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    archive_path: Path
    archive_sha256: str
    manifest: BackupManifest

    @property
    def file_count(self) -> int:
        return len(self.manifest.files)

    @property
    def byte_count(self) -> int:
        return sum(record.size for record in self.manifest.files)
```

- [ ] **Step 4: Implement canonical paths and strict archive verification**

Add these production helpers to `backups.py`:

```python
def verify_backup_archive(path: Path) -> VerifiedBackup:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_file():
        raise BackupVerificationError("backup archive must be a regular file")
    try:
        archive_path = candidate.resolve(strict=True)
        archive_sha256 = _file_sha256(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise BackupVerificationError("backup contains duplicate ZIP members")
            if names.count(MANIFEST_NAME) != 1:
                raise BackupVerificationError("backup must contain exactly one manifest")
            info_by_name = {info.filename: info for info in infos}
            manifest_info = info_by_name[MANIFEST_NAME]
            manifest_content = _read_member(archive, manifest_info, MAX_MANIFEST_BYTES)
            try:
                manifest = BackupManifest.model_validate_json(manifest_content, strict=True)
            except ValidationError as exc:
                raise BackupVerificationError("backup manifest is invalid") from exc
            _validate_member_metadata(infos)
            if manifest_info.is_dir():
                raise BackupVerificationError("backup manifest must be a regular file")
            expected_names = {MANIFEST_NAME}
            expected_names.update(f"{PAYLOAD_PREFIX}{path}/" for path in manifest.directories)
            expected_names.update(f"{PAYLOAD_PREFIX}{record.path}" for record in manifest.files)
            if set(names) != expected_names:
                raise BackupVerificationError("backup members do not match its manifest")
            if any(
                not info_by_name[f"{PAYLOAD_PREFIX}{path}/"].is_dir()
                for path in manifest.directories
            ):
                raise BackupVerificationError("backup directory member has the wrong type")
            if any(
                info_by_name[f"{PAYLOAD_PREFIX}{record.path}"].is_dir()
                for record in manifest.files
            ):
                raise BackupVerificationError("backup file member has the wrong type")
            records = {record.path: record for record in manifest.files}
            config_record = records.get(CONFIG_FILENAME)
            if config_record is None:
                raise BackupVerificationError("backup does not contain bundlewalker.toml")
            if config_record.size > MAX_WORKSPACE_CONFIG_BYTES:
                raise BackupVerificationError("backup workspace configuration is too large")
            config_content: bytes | None = None
            for record in manifest.files:
                member = info_by_name[f"{PAYLOAD_PREFIX}{record.path}"]
                content = _verify_member(
                    archive,
                    member,
                    record,
                    capture=record.path == CONFIG_FILENAME,
                )
                if content is not None:
                    config_content = content
            if config_content is None:
                raise BackupVerificationError("backup workspace configuration is unavailable")
            try:
                config = parse_workspace_config(
                    config_content.decode("utf-8", errors="strict"),
                    source=f"{archive_path}:{CONFIG_FILENAME}",
                )
            except (BundleWalkerError, UnicodeDecodeError) as exc:
                raise BackupVerificationError("backup workspace configuration is invalid") from exc
            _validate_managed_payload(manifest, config)
    except zipfile.BadZipFile as exc:
        raise BackupVerificationError("backup archive is not a valid ZIP") from exc
    except OSError as exc:
        raise BackupVerificationError("backup archive could not be read") from exc
    return VerifiedBackup(archive_path, archive_sha256, manifest)


def _canonical_relative_path(value: str) -> str:
    if (
        not value
        or len(value) > MAX_BACKUP_PATH_CHARACTERS
        or "\\" in value
        or "\x00" in value
        or value.endswith("/")
    ):
        raise ValueError("backup path is unsafe")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or any(part in {"", ".", ".."} for part in path.parts)
        or (path.parts and path.parts[0].endswith(":"))
        or path.as_posix() != value
    ):
        raise ValueError("backup path is unsafe")
    return value


def _validate_member_metadata(infos: list[zipfile.ZipInfo]) -> None:
    if len(infos) - 1 > MAX_BACKUP_ENTRIES:
        raise BackupVerificationError("backup contains too many entries")
    for info in infos:
        if info.flag_bits & 0x1:
            raise BackupVerificationError("encrypted backup members are unsupported")
        if info.filename != MANIFEST_NAME:
            raw_name = info.filename.removeprefix(PAYLOAD_PREFIX).removesuffix("/")
            try:
                _canonical_relative_path(raw_name)
            except ValueError as exc:
                raise BackupVerificationError("backup contains an unsafe member path") from exc
            if not info.filename.startswith(PAYLOAD_PREFIX):
                raise BackupVerificationError("backup contains a member outside workspace/")
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise BackupVerificationError("backup contains a symlink or special file")


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limit: int,
) -> bytes:
    if info.file_size > limit:
        raise BackupVerificationError("backup member exceeds its supported size")
    with archive.open(info) as member:
        content = member.read(limit + 1)
        if len(content) > limit or member.read(1):
            raise BackupVerificationError("backup member exceeds its declared size")
    return content


def _verify_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    record: BackupFileRecord,
    *,
    capture: bool,
) -> bytes | None:
    if info.file_size != record.size:
        raise BackupVerificationError(f"backup size mismatch: {record.path}")
    digest = hashlib.sha256()
    count = 0
    captured = bytearray() if capture else None
    with archive.open(info) as member:
        while chunk := member.read(1024 * 1024):
            count += len(chunk)
            if count > record.size:
                raise BackupVerificationError(f"backup size mismatch: {record.path}")
            digest.update(chunk)
            if captured is not None:
                captured.extend(chunk)
    if count != record.size:
        raise BackupVerificationError(f"backup size mismatch: {record.path}")
    if digest.hexdigest() != record.sha256:
        raise BackupVerificationError(f"backup digest mismatch: {record.path}")
    return bytes(captured) if captured is not None else None


def _validate_managed_payload(manifest: BackupManifest, config: WorkspaceConfig) -> None:
    files = {record.path for record in manifest.files}
    directories = set(manifest.directories)
    required_files = {CONFIG_FILENAME, config.conventions_file}
    required_directories = {config.raw_dir, config.wiki_dir}
    if not required_files <= files or not required_directories <= directories:
        raise BackupVerificationError("backup is missing a configured managed path")
    reserved = PurePosixPath(".bundlewalker")
    managed_roots = (
        PurePosixPath(config.conventions_file),
        PurePosixPath(config.raw_dir),
        PurePosixPath(config.wiki_dir),
    )
    if any(root == reserved or reserved in root.parents for root in managed_roots):
        raise BackupVerificationError("backup configuration overlaps reserved internal state")
    for value in files:
        path = PurePosixPath(value)
        if path == PurePosixPath(CONFIG_FILENAME) or path == managed_roots[0]:
            continue
        if not any(root in path.parents for root in managed_roots[1:]):
            raise BackupVerificationError("backup contains an unmanaged file")
    for value in directories:
        path = PurePosixPath(value)
        if not any(
            path == root or root in path.parents or path in root.parents
            for root in managed_roots
        ):
            raise BackupVerificationError("backup contains an unmanaged directory")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
```

Only the bounded configuration payload is retained in memory; every other payload member is
hashed and counted incrementally.

- [ ] **Step 5: Add remaining adversarial cases**

Extend `tests/test_backups.py` with explicit cases for missing/duplicate manifest, encrypted flag,
special-file mode, NUL and dot segments, unsorted/overlapping manifest paths, manifest larger than
32 MiB, 100,001 entries, 4,097-character path, missing configured roots, configuration larger than
1 MiB, declared size smaller/larger than streamed bytes, CRC-independent SHA mismatch, and future
workspace format. Each case calls `verify_backup_archive(...)` and asserts
`BackupVerificationError` without extracting any member.

Use small monkeypatched `ZipInfo`/stream fakes for the count and oversized-stream cases rather than
creating gigabytes of test data. The exact assertion pattern is:

```python
with pytest.raises(BackupVerificationError):
    verify_backup_archive(archive)
assert list(tmp_path.iterdir()) == [archive]
```

- [ ] **Step 6: Run verifier tests and static checks**

Run:

```bash
uv run pytest tests/test_backups.py -q
uv run ruff format --check src/bundlewalker/backups.py tests/test_backups.py
uv run ruff check src/bundlewalker/backups.py tests/test_backups.py
uv run pyright src/bundlewalker/backups.py tests/test_backups.py
```

Expected: every valid archive passes and every adversarial archive fails before extraction.

- [ ] **Step 7: Commit the archive verifier**

```bash
git add src/bundlewalker/backups.py src/bundlewalker/errors.py tests/test_backups.py
git commit -m "feat: verify workspace backup archives"
```

### Task 5: Create Quiescent Verified Backups

**Files:**
- Modify: `src/bundlewalker/backups.py`
- Modify: `tests/test_backups.py`
- Modify: `tests/test_historical_compatibility.py`

**Interfaces:**
- Consumes: `quiescent_workspace(...)`, `QuiescentWorkspace`, Task 2 current compatibility, and
  Task 4 manifest/verifier.
- Produces: `create_workspace_backup(workspace, output, *, clock, bundlewalker_version)` and
  `create_quiescent_backup(quiescent, output, *, clock, bundlewalker_version)`; Task 7 reuses the
  latter without releasing the upgrade lock.

- [ ] **Step 1: Write failing backup-creation and scope tests**

Append to `tests/test_backups.py`:

```python
from bundlewalker.backups import create_workspace_backup
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.errors import BackupError, ReviewPendingError
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import PreparedTransaction, ReviewKind, prepare_transaction
from bundlewalker.workspace import Workspace, discover_workspace, initialize_workspace, load_raw_source


def _prepared_review(tmp_path: Path) -> PreparedTransaction:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    source_path = tmp_path / "Source Notes.txt"
    source_path.write_bytes(b"first line\r\nsecond line\n")
    source = load_raw_source(source_path, workspace)
    draft = DraftConcept(
        operation=ChangeOperation.CREATE,
        path=source.concept_id,
        type=ConceptType.SOURCE,
        title="Source notes",
        description="Knowledge about Source notes.",
        tags=["test"],
        body="# Source notes\n\nA grounded claim [1].\n",
        citations=[
            Citation(
                number=1,
                concept_id=source.concept_id,
                start_line=1,
                end_line=2,
            )
        ],
        base_digest=None,
    )
    change_set = ChangeSet(
        summary="Integrated source notes.",
        source_sha256=source.sha256,
        drafts=[draft],
    )
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    return prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        CREATED_AT,
        kind=ReviewKind.INGESTION,
    )


def _managed_tree_bytes(workspace: Workspace) -> dict[str, bytes]:
    roots = (
        workspace.root / "bundlewalker.toml",
        workspace.conventions_file,
        workspace.raw_dir,
        workspace.wiki_dir,
    )
    files: dict[str, bytes] = {}
    for root in roots:
        candidates = (root,) if root.is_file() else tuple(sorted(root.rglob("*")))
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                files[candidate.relative_to(workspace.root).as_posix()] = candidate.read_bytes()
    return files


def test_create_backup_is_verified_and_contains_only_managed_bytes(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    unrelated = workspace.root / "private-note.txt"
    unrelated.write_text("outside managed scope\n", encoding="utf-8")
    git_marker = workspace.root / ".git" / "config"
    git_marker.parent.mkdir()
    git_marker.write_text("private git config\n", encoding="utf-8")
    output = tmp_path / "knowledge.zip"

    verified = create_workspace_backup(
        workspace,
        output,
        clock=lambda: CREATED_AT,
        bundlewalker_version="0.4.0a1",
    )

    assert verified == verify_backup_archive(output)
    archived = {record.path for record in verified.manifest.files}
    assert "bundlewalker.toml" in archived
    assert "conventions.md" in archived
    assert "private-note.txt" not in archived
    assert not any(path.startswith(".git") for path in archived)
    assert not any(path.startswith(".bundlewalker") for path in archived)
    assert stat.S_IMODE(output.stat().st_mode) & 0o077 == 0


def test_create_backup_preserves_custom_paths_and_empty_directories(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    configured = workspace.root / "configured"
    configured.mkdir()
    workspace.wiki_dir.rename(configured / "wiki")
    workspace.raw_dir.rename(configured / "raw")
    workspace.conventions_file.rename(configured / "conventions.md")
    (workspace.root / "bundlewalker.toml").write_text(
        "version = 1\n"
        'wiki_dir = "configured/wiki"\n'
        'raw_dir = "configured/raw"\n'
        'conventions_file = "configured/conventions.md"\n'
        "max_source_characters = 100000\n",
        encoding="utf-8",
    )
    workspace = discover_workspace(workspace.root)

    verified = create_workspace_backup(workspace, tmp_path / "custom.zip")

    assert "configured/raw" in verified.manifest.directories
    assert "configured/conventions.md" in {
        record.path for record in verified.manifest.files
    }


def test_create_backup_refuses_existing_or_internal_output(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=CREATED_AT)
    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"keep")

    with pytest.raises(BackupError):
        create_workspace_backup(workspace, existing)
    with pytest.raises(BackupError):
        create_workspace_backup(workspace, workspace.root / "inside.zip")

    assert existing.read_bytes() == b"keep"
    assert not (workspace.root / "inside.zip").exists()


def test_create_backup_refuses_pending_review_without_discarding_it(tmp_path: Path) -> None:
    prepared = _prepared_review(tmp_path)

    with pytest.raises(ReviewPendingError):
        create_workspace_backup(prepared.workspace, tmp_path / "blocked.zip")

    assert prepared.transaction_dir.is_dir()
    assert not (tmp_path / "blocked.zip").exists()
```

Keep `_prepared_review(...)` local to `tests/test_backups.py`; test modules do not import each
other.

- [ ] **Step 2: Run creation tests and verify the public function is absent**

Run:

```bash
uv run pytest tests/test_backups.py -k 'create_backup' -v
```

Expected: collection fails because `create_workspace_backup` does not exist.

- [ ] **Step 3: Implement managed traversal and race-detecting reads**

Add `import os`, `import shutil`, and `UTC` to the existing datetime import in `backups.py`, then
add these internal records and helpers:

```python
from collections.abc import Callable
from contextlib import suppress
from tempfile import mkstemp

from bundlewalker import __version__
from bundlewalker.errors import BackupError, BundleWalkerError
from bundlewalker.transactions import QuiescentWorkspace, quiescent_workspace
from bundlewalker.workspace import Workspace


@dataclass(frozen=True, slots=True)
class _ManagedEntry:
    relative: str
    absolute: Path
    is_directory: bool


def _managed_entries(workspace: Workspace) -> tuple[_ManagedEntry, ...]:
    file_roots = (
        PurePosixPath(CONFIG_FILENAME),
        PurePosixPath(workspace.config.conventions_file),
    )
    directory_roots = (
        PurePosixPath(workspace.config.raw_dir),
        PurePosixPath(workspace.config.wiki_dir),
    )
    roots = (*file_roots, *directory_roots)
    reserved = PurePosixPath(".bundlewalker")
    if any(path == reserved or reserved in path.parents for path in roots):
        raise BackupError("configured managed path overlaps reserved internal state")
    entries: dict[str, _ManagedEntry] = {}

    def add(candidate: Path) -> None:
        relative = candidate.relative_to(workspace.root).as_posix()
        _canonical_relative_path(relative)
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise BackupError(f"managed path is a symlink: {relative}")
        if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
            raise BackupError(f"managed path is not a regular file or directory: {relative}")
        incoming = _ManagedEntry(relative, candidate, stat.S_ISDIR(metadata.st_mode))
        existing = entries.get(relative)
        if existing is not None and existing.is_directory != incoming.is_directory:
            raise BackupError(f"managed path changes type: {relative}")
        entries[relative] = incoming

    for relative_root in roots:
        for parent in reversed(relative_root.parents):
            if parent != PurePosixPath("."):
                add(workspace.root.joinpath(*parent.parts))
        absolute_root = workspace.root.joinpath(*relative_root.parts)
        candidates = (absolute_root, *sorted(absolute_root.rglob("*")))
        for candidate in candidates:
            add(candidate)
    return tuple(entries[path] for path in sorted(entries))


def _stream_stable_file(
    archive: zipfile.ZipFile,
    entry: _ManagedEntry,
) -> BackupFileRecord:
    path_before = entry.absolute.lstat()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(entry.absolute, flags)
    digest = hashlib.sha256()
    count = 0
    try:
        descriptor_before = os.fstat(descriptor)
        if not stat.S_ISREG(descriptor_before.st_mode):
            raise BackupError("managed backup entry is not a regular file")
        info = zipfile.ZipInfo(f"{PAYLOAD_PREFIX}{entry.relative}")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o600) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        with archive.open(info, "w", force_zip64=True) as destination:
            while chunk := os.read(descriptor, 1024 * 1024):
                count += len(chunk)
                digest.update(chunk)
                destination.write(chunk)
        descriptor_after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path_after = entry.absolute.lstat()
    identity = ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    snapshots = (path_before, descriptor_before, descriptor_after, path_after)
    if any(
        getattr(snapshot, name) != getattr(path_before, name)
        for snapshot in snapshots[1:]
        for name in identity
    ):
        raise BackupError("managed backup entry changed while it was read")
    if count != descriptor_after.st_size:
        raise BackupError("managed backup entry size changed while it was read")
    return BackupFileRecord(path=entry.relative, size=count, sha256=digest.hexdigest())
```

The explicit parent loop makes nested configured paths restorable: for
`configured/wiki`, the manifest contains both `configured` and `configured/wiki`. Catch `OSError`
from `_managed_entries(...)` and `_stream_stable_file(...)` at their public caller and
translate it to `BackupError("workspace backup could not read managed data")`.

- [ ] **Step 4: Implement locked archive creation and atomic publication**

Add:

```python
def create_workspace_backup(
    workspace: Workspace,
    output: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    bundlewalker_version: str = __version__,
) -> VerifiedBackup:
    with quiescent_workspace(workspace) as quiescent:
        return create_quiescent_backup(
            quiescent,
            output,
            clock=clock,
            bundlewalker_version=bundlewalker_version,
        )


def create_quiescent_backup(
    quiescent: QuiescentWorkspace,
    output: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    bundlewalker_version: str = __version__,
) -> VerifiedBackup:
    workspace = quiescent.workspace
    output_path = output.expanduser().absolute()
    resolved_output = output_path.resolve(strict=False)
    workspace_root = workspace.root.resolve(strict=True)
    if resolved_output == workspace_root or resolved_output.is_relative_to(workspace_root):
        raise BackupError("backup output must be outside the workspace")
    if output_path.exists() or output_path.is_symlink():
        raise BackupError("backup output already exists")
    if not output_path.parent.is_dir() or output_path.parent.is_symlink():
        raise BackupError("backup output parent must be a regular directory")
    temporary: Path | None = None
    try:
        entries = _managed_entries(workspace)
        file_entries = tuple(entry for entry in entries if not entry.is_directory)
        byte_count = sum(entry.absolute.lstat().st_size for entry in file_entries)
        if shutil.disk_usage(output_path.parent).free < byte_count:
            raise BackupError("backup destination has insufficient free space")
        observed_at = clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise BackupError("backup clock must return a timezone-aware timestamp")
        created_at = observed_at.astimezone(UTC)
        descriptor, temporary_name = mkstemp(prefix=".bundlewalker-backup-", dir=output_path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        records: list[BackupFileRecord] = []
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=True,
        ) as archive:
            for entry in entries:
                if entry.is_directory:
                    info = zipfile.ZipInfo(f"{PAYLOAD_PREFIX}{entry.relative}/")
                    info.create_system = 3
                    info.external_attr = (stat.S_IFDIR | 0o700) << 16
                    archive.writestr(info, b"")
            for entry in file_entries:
                records.append(_stream_stable_file(archive, entry))
            manifest = BackupManifest(
                archive_format=ARCHIVE_FORMAT,
                schema_version=ARCHIVE_SCHEMA_VERSION,
                created_at=created_at,
                bundlewalker_version=bundlewalker_version,
                workspace_format_version=workspace.config.version,
                directories=tuple(entry.relative for entry in entries if entry.is_directory),
                files=tuple(records),
            )
            archive.writestr(MANIFEST_NAME, manifest.model_dump_json(indent=2) + "\n")
        verified = verify_backup_archive(temporary)
        with temporary.open("rb") as backup_file:
            os.fsync(backup_file.fileno())
        try:
            os.link(temporary, output_path, follow_symlinks=False)
        except FileExistsError as exc:
            raise BackupError("backup output already exists") from exc
        _sync_parent(output_path.parent)
        return VerifiedBackup(output_path, verified.archive_sha256, verified.manifest)
    except BackupError:
        raise
    except (BundleWalkerError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise BackupError("workspace backup creation failed") from exc
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _sync_parent(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)
```

Do not hide `ReviewPendingError` behind `BackupError`; let it reach the application translator so
the existing review-remediation output remains available. Writing the manifest after streamed
payloads is intentional: ZIP member order is irrelevant, and this avoids buffering managed files
or making a second content pass. Hard-link publication provides create-if-absent atomicity and
cannot overwrite an output introduced by a concurrent actor.

- [ ] **Step 5: Add mutation-race and failure-atomicity tests**

Add tests that monkeypatch `_stream_stable_file`, `verify_backup_archive`, `os.link`, and
`shutil.disk_usage` one at a time. For each injected failure assert:

```python
assert not output.exists()
assert not list(output.parent.glob(".bundlewalker-backup-*"))
assert _managed_tree_bytes(workspace) == before
```

Add symlink, FIFO (skip where unavailable), configured `.bundlewalker` overlap, file replacement,
truncation, append, disappearance, insufficient free space, and existing-output cases. Verify a
pending and a stale durable review remain resolvable after refusal.

- [ ] **Step 6: Prove all released clean fixtures can be backed up**

Extend `tests/test_historical_compatibility.py`:

```python
@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_clean_workspace_creates_a_current_verified_backup(
    tmp_path: Path,
    release: str,
) -> None:
    root = tmp_path / release
    shutil.copytree(FIXTURES / f"{release}-clean", root)
    workspace = discover_workspace(root)

    verified = create_workspace_backup(workspace, tmp_path / f"{release}.zip")

    assert verified.manifest.workspace_format_version == 1
    assert verify_backup_archive(verified.archive_path) == verified
```

- [ ] **Step 7: Run backup, transaction, and historical suites**

Run:

```bash
uv run pytest tests/test_backups.py tests/test_coordination.py tests/test_transactions.py tests/test_historical_compatibility.py -q
uv run ruff format --check src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
uv run ruff check src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
uv run pyright src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
```

Expected: all backups are verified before publication, exact historical workspaces remain usable,
and transaction behavior is unchanged.

- [ ] **Step 8: Commit backup creation**

```bash
git add src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
git commit -m "feat: create verified workspace backups"
```

### Task 6: Restore Verified Backups Without Overwrite

**Files:**
- Modify: `src/bundlewalker/backups.py`
- Modify: `src/bundlewalker/errors.py`
- Modify: `tests/test_backups.py`
- Modify: `tests/test_historical_compatibility.py`

**Interfaces:**
- Consumes: Task 4 `verify_backup_archive(...)`, manifest paths/digests, Task 2 config reader, and
  current workspace discovery.
- Produces: `RestoredWorkspace` and `restore_workspace_backup(archive, target)`; Task 8 exposes
  these through the application and CLI.

- [ ] **Step 1: Write failing absent/empty-target restore tests**

Append to `tests/test_backups.py`:

```python
from bundlewalker.backups import RestoredWorkspace, restore_workspace_backup
from bundlewalker.errors import RestoreTargetError


def test_restore_publishes_verified_bytes_to_absent_target(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source", occurred_at=CREATED_AT)
    archive = tmp_path / "source.zip"
    backup = create_workspace_backup(workspace, archive)
    target = tmp_path / "restored"

    restored = restore_workspace_backup(archive, target)

    assert isinstance(restored, RestoredWorkspace)
    assert restored.workspace.root == target.resolve()
    assert restored.backup.archive_sha256 == backup.archive_sha256
    assert _managed_tree_bytes(restored.workspace) == _managed_tree_bytes(workspace)
    assert discover_workspace(target).root == target.resolve()


def test_restore_replaces_only_an_existing_empty_directory(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "source", occurred_at=CREATED_AT)
    archive = tmp_path / "source.zip"
    create_workspace_backup(workspace, archive)
    target = tmp_path / "empty"
    target.mkdir()

    restored = restore_workspace_backup(archive, target)

    assert restored.workspace.root == target.resolve()
    assert (target / "bundlewalker.toml").is_file()


@pytest.mark.parametrize("kind", ["file", "symlink", "nonempty"])
def test_restore_refuses_occupied_or_linked_target(
    tmp_path: Path,
    kind: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "source", occurred_at=CREATED_AT)
    archive = tmp_path / "source.zip"
    create_workspace_backup(workspace, archive)
    target = tmp_path / "target"
    if kind == "file":
        target.write_text("keep", encoding="utf-8")
    elif kind == "symlink":
        destination = tmp_path / "outside"
        destination.mkdir()
        target.symlink_to(destination, target_is_directory=True)
    else:
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(RestoreTargetError):
        restore_workspace_backup(archive, target)

    if kind == "file":
        assert target.read_text(encoding="utf-8") == "keep"
    elif kind == "symlink":
        assert target.is_symlink()
        assert list((tmp_path / "outside").iterdir()) == []
    else:
        assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
        assert not (target / "bundlewalker.toml").exists()
```

- [ ] **Step 2: Run restore tests and verify the API is absent**

Run:

```bash
uv run pytest tests/test_backups.py -k 'restore' -v
```

Expected: collection fails because the restore interface and error do not exist.

- [ ] **Step 3: Add the typed result, target error, and staged extractor**

Add to `errors.py`:

```python
class RestoreTargetError(UsageError):
    pass
```

Add to `backups.py`:

```python
@dataclass(frozen=True, slots=True)
class RestoredWorkspace:
    workspace: Workspace
    backup: VerifiedBackup


def restore_workspace_backup(archive: Path, target: Path) -> RestoredWorkspace:
    target_path = target.expanduser().absolute()
    target_existed = _validate_restore_target(target_path)
    verified = verify_backup_archive(archive)
    temporary: Path | None = None
    removed_empty_target = False
    try:
        if shutil.disk_usage(target_path.parent).free < verified.byte_count:
            raise BackupError("restore destination has insufficient free space")
        temporary = Path(
            mkdtemp(prefix=f".{target_path.name}-restore-", dir=target_path.parent)
        )
        os.chmod(temporary, 0o700)
        _extract_verified_backup(verified, temporary)
        restored_workspace = discover_workspace(temporary)
        if restored_workspace.config.version != verified.manifest.workspace_format_version:
            raise BackupVerificationError("restored workspace version does not match manifest")
        _verify_extracted_tree(temporary, verified.manifest)
        if target_existed:
            _require_empty_target(target_path)
            target_path.rmdir()
            removed_empty_target = True
        os.rename(temporary, target_path)
        _sync_parent(target_path.parent)
        published = Workspace(root=target_path, config=restored_workspace.config)
        return RestoredWorkspace(published, verified)
    except (BackupError, RestoreTargetError):
        raise
    except (BundleWalkerError, OSError) as exc:
        raise BackupError("workspace restore failed") from exc
    finally:
        if temporary is not None and temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary, ignore_errors=True)
        if removed_empty_target and not target_path.exists():
            with suppress(OSError):
                target_path.mkdir(mode=0o700)


def _validate_restore_target(target: Path) -> bool:
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise RestoreTargetError("restore target parent must be a regular directory")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise RestoreTargetError("restore target must be a new or empty directory")
    if target.is_dir():
        _require_empty_target(target)
        return True
    return False


def _require_empty_target(target: Path) -> None:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RestoreTargetError("restore target must be an empty regular directory")
        if os.listdir(descriptor):
            raise RestoreTargetError("restore target must be empty")
    except OSError as exc:
        raise RestoreTargetError("restore target could not be inspected") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _extract_verified_backup(verified: VerifiedBackup, temporary: Path) -> None:
    with zipfile.ZipFile(verified.archive_path) as archive:
        for relative in verified.manifest.directories:
            destination = temporary.joinpath(*PurePosixPath(relative).parts)
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        for record in verified.manifest.files:
            relative = record.path
            destination = temporary.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(destination, flags, 0o600)
            digest = hashlib.sha256()
            count = 0
            try:
                with archive.open(f"{PAYLOAD_PREFIX}{relative}") as source:
                    while chunk := source.read(1024 * 1024):
                        count += len(chunk)
                        if count > record.size:
                            raise BackupVerificationError(
                                f"backup member exceeds declared size: {relative}"
                            )
                        digest.update(chunk)
                        view = memoryview(chunk)
                        while view:
                            written = os.write(descriptor, view)
                            if written == 0:
                                raise OSError("restore write made no progress")
                            view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if count != record.size or digest.hexdigest() != record.sha256:
                raise BackupVerificationError(f"restored member identity mismatch: {relative}")


def _verify_extracted_tree(root: Path, manifest: BackupManifest) -> None:
    expected_files = {record.path: record for record in manifest.files}
    expected_directories = set(manifest.directories)
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            actual_directories.add(relative)
        elif stat.S_ISREG(metadata.st_mode):
            actual_files.add(relative)
            record = expected_files.get(relative)
            if record is None or _file_sha256(path) != record.sha256:
                raise BackupVerificationError("restored workspace file identity mismatch")
        else:
            raise BackupVerificationError("restored workspace contains a special file")
    if actual_files != set(expected_files) or actual_directories != expected_directories:
        raise BackupVerificationError("restored workspace entries do not match manifest")
```

Change the Task 5 import to `from tempfile import mkdtemp, mkstemp`.

- [ ] **Step 4: Add restore failure-atomicity and concurrent-target tests**

Inject failures from `archive.open`, `os.write`, `_verify_extracted_tree`, `discover_workspace`,
`Path.rmdir`, and `os.rename`. Assert every owned temporary sibling is gone and the target is
absent or remains exactly its original empty/non-empty state. Add a target-race test that writes
`keep.txt` immediately before `_require_empty_target(...)`; the restore must refuse and preserve
that file.

- [ ] **Step 5: Restore every historical clean backup and compare bytes**

Extend `tests/test_historical_compatibility.py`:

```python
@pytest.mark.parametrize("release", ["v1", "v2", "v3"])
def test_released_workspace_round_trips_through_backup_and_restore(
    tmp_path: Path,
    release: str,
) -> None:
    source = tmp_path / f"{release}-source"
    shutil.copytree(FIXTURES / f"{release}-clean", source)
    archive = tmp_path / f"{release}.zip"
    original = discover_workspace(source)
    create_workspace_backup(original, archive)

    restored = restore_workspace_backup(archive, tmp_path / f"{release}-restored")

    assert _workspace_bytes(restored.workspace) == _workspace_bytes(original)
    assert set(OkfRepository(restored.workspace.wiki_dir).scan()) == set(
        OkfRepository(original.wiki_dir).scan()
    )
    assert (restored.workspace.wiki_dir / "index.md").is_file()


def _workspace_bytes(workspace: Workspace) -> dict[str, bytes]:
    roots = (
        workspace.root / "bundlewalker.toml",
        workspace.conventions_file,
        workspace.raw_dir,
        workspace.wiki_dir,
    )
    files: dict[str, bytes] = {}
    for root in roots:
        candidates = (root,) if root.is_file() else tuple(sorted(root.rglob("*")))
        for candidate in candidates:
            if candidate.is_file() and not candidate.is_symlink():
                files[candidate.relative_to(workspace.root).as_posix()] = candidate.read_bytes()
    return files
```

Import `Workspace` in this test module. The helper reads exactly the configured managed files, not
the source `.bundlewalker/` directory created during backup locking.

- [ ] **Step 6: Run restore, historical, lint, and type checks**

Run:

```bash
uv run pytest tests/test_backups.py tests/test_historical_compatibility.py -q
uv run ruff format --check src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
uv run ruff check src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
uv run pyright src/bundlewalker/backups.py tests/test_backups.py tests/test_historical_compatibility.py
```

Expected: exact byte round trips pass and every restore failure leaves no published partial target.

- [ ] **Step 7: Commit non-destructive restore**

```bash
git add src/bundlewalker/backups.py src/bundlewalker/errors.py tests/test_backups.py tests/test_historical_compatibility.py
git commit -m "feat: restore verified workspace backups"
```

### Task 7: Add Explicit Upgrade Orchestration and Rollback Evidence

**Files:**
- Create: `src/bundlewalker/upgrades.py`
- Modify: `src/bundlewalker/compatibility.py`
- Modify: `src/bundlewalker/errors.py`
- Create: `tests/test_upgrades.py`

**Interfaces:**
- Consumes: Task 2 `MigrationStep`, `migration_path(...)`, and
  `read_workspace_format_version(...)`; Task 1 quiescent guard; Task 5
  `create_quiescent_backup(...)`; and Task 6 restore.
- Produces: `UpgradeOutcome`, `upgrade_workspace(...)`, `MigrationUnavailableError`, and
  `MigrationExecutionError` with a typed verified backup. Keeping orchestration in `upgrades.py`
  prevents `compatibility.py -> backups.py -> compatibility.py`.

- [ ] **Step 1: Write failing no-op, backup-before-mutation, and rollback tests**

Create `tests/test_upgrades.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.backups import restore_workspace_backup, verify_backup_archive
from bundlewalker.compatibility import MigrationStep
from bundlewalker.errors import MigrationExecutionError, MigrationUnavailableError
from bundlewalker.transactions import QuiescentWorkspace
from bundlewalker.upgrades import upgrade_workspace
from bundlewalker.workspace import Workspace, initialize_workspace

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_current_upgrade_is_an_exact_noop_without_backup(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    before = _tree_bytes(workspace.root)

    outcome = upgrade_workspace(workspace, backup_dir=tmp_path, clock=lambda: NOW)

    assert outcome.status == "current"
    assert outcome.source_version == 1
    assert outcome.target_version == 1
    assert outcome.backup is None
    assert _tree_bytes(workspace.root) == before
    assert list(tmp_path.glob("*.zip")) == []


def test_synthetic_migration_creates_verified_backup_before_apply(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    events: list[str] = []

    def apply(quiescent: QuiescentWorkspace) -> None:
        archives = list(tmp_path.glob("*.zip"))
        assert len(archives) == 1
        verify_backup_archive(archives[0])
        events.append("apply")
        config = quiescent.workspace.root / "bundlewalker.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace("version = 1", "version = 2"),
            encoding="utf-8",
        )

    def verify(candidate: Workspace) -> None:
        events.append("verify")
        assert "version = 2" in (
            candidate.root / "bundlewalker.toml"
        ).read_text(encoding="utf-8")

    outcome = upgrade_workspace(
        workspace,
        backup_dir=tmp_path,
        target_version=2,
        migrations={1: MigrationStep(1, 2, apply, verify)},
        clock=lambda: NOW,
    )

    assert outcome.status == "upgraded"
    assert outcome.backup is not None
    assert events == ["apply", "verify"]


def test_failed_migration_reports_restorable_preupgrade_backup(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    original = _tree_bytes(workspace.root)

    def fail(quiescent: QuiescentWorkspace) -> None:
        config = quiescent.workspace.root / "bundlewalker.toml"
        config.write_text("version = 2\n", encoding="utf-8")
        raise OSError("simulated migration failure")

    step = MigrationStep(1, 2, fail, lambda _workspace: None)
    with pytest.raises(MigrationExecutionError) as raised:
        upgrade_workspace(
            workspace,
            backup_dir=tmp_path,
            target_version=2,
            migrations={1: step},
            clock=lambda: NOW,
        )

    backup = raised.value.backup
    assert backup is not None
    assert verify_backup_archive(backup.archive_path) == backup
    restored = restore_workspace_backup(backup.archive_path, tmp_path / "rollback")
    assert _tree_bytes(restored.workspace.root) == original


def test_incomplete_path_refuses_before_backup(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    with pytest.raises(MigrationUnavailableError):
        upgrade_workspace(workspace, backup_dir=tmp_path, target_version=2, migrations={})

    assert list(tmp_path.glob("*.zip")) == []


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink() and ".bundlewalker" not in path.parts
    }
```

- [ ] **Step 2: Run upgrade tests and verify orchestration is absent**

Run:

```bash
uv run pytest tests/test_upgrades.py -v
```

Expected: collection fails because `bundlewalker.upgrades` and the typed migration failures do not
exist.

- [ ] **Step 3: Add typed migration errors and the outcome contract**

Add `from __future__ import annotations` and a `TYPE_CHECKING` import to `errors.py`:

```python
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from bundlewalker.backups import VerifiedBackup
```

Then add:

```python
class MigrationUnavailableError(UsageError):
    pass


class MigrationExecutionError(BundleWalkerError):
    def __init__(
        self,
        message: str,
        *,
        backup: VerifiedBackup | None,
    ) -> None:
        self.backup = backup
        super().__init__(message)
```

Create `src/bundlewalker/upgrades.py` with its imports and result:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from bundlewalker.backups import VerifiedBackup, create_quiescent_backup
from bundlewalker.compatibility import (
    CURRENT_WORKSPACE_FORMAT,
    MigrationStep,
    migration_path,
    read_workspace_format_version,
)
from bundlewalker.errors import MigrationExecutionError, MigrationUnavailableError
from bundlewalker.transactions import quiescent_workspace
from bundlewalker.workspace import CONFIG_FILENAME, Workspace


@dataclass(frozen=True, slots=True)
class UpgradeOutcome:
    status: Literal["current", "upgraded"]
    source_version: int
    target_version: int
    backup: VerifiedBackup | None
```

- [ ] **Step 4: Implement backup-first orchestration in the acyclic module**

Add to `upgrades.py`:

```python
def upgrade_workspace(
    workspace: Workspace,
    *,
    backup_dir: Path,
    target_version: int = CURRENT_WORKSPACE_FORMAT,
    migrations: Mapping[int, MigrationStep] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> UpgradeOutcome:
    source_version = workspace.config.version
    path = migration_path(
        source_version,
        target_version=target_version,
        migrations=migrations,
    )
    if source_version == target_version:
        return UpgradeOutcome("current", source_version, target_version, None)
    if path is None or not path:
        raise MigrationUnavailableError("no complete workspace migration path is available")

    observed_at = clock()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise MigrationUnavailableError("migration clock must return a timezone-aware timestamp")
    created_at = observed_at.astimezone(UTC)
    timestamp = created_at.strftime("%Y%m%dT%H%M%S.%fZ")
    suffix = secrets.token_hex(8)
    backup_path = backup_dir.expanduser().absolute() / (
        f"{workspace.root.name}-pre-upgrade-v{source_version}-to-v{target_version}-"
        f"{timestamp}-{suffix}.zip"
    )
    backup: VerifiedBackup | None = None
    with quiescent_workspace(workspace) as quiescent:
        backup = create_quiescent_backup(
            quiescent,
            backup_path,
            clock=lambda: created_at,
        )
        try:
            for step in path:
                step.apply(quiescent)
                declared = read_workspace_format_version(
                    workspace.root / CONFIG_FILENAME
                )
                if declared != step.target_version:
                    raise ValueError("migration did not publish its target workspace version")
                step.verify(workspace)
        except Exception as exc:
            raise MigrationExecutionError(
                "workspace migration failed; restore the verified pre-upgrade backup",
                backup=backup,
            ) from exc
    return UpgradeOutcome("upgraded", source_version, target_version, backup)
```

The broad `Exception` catch is deliberate only around injected migration-step code: it translates
ordinary migration failures while allowing `BaseException`, `KeyboardInterrupt`, and `SystemExit`
to propagate. The already-verified backup survives every path after `step.apply(...)` begins.

- [ ] **Step 5: Run upgrade, backup, and transaction regression suites**

Run:

```bash
uv run pytest tests/test_upgrades.py tests/test_backups.py tests/test_transactions.py -q
uv run ruff format --check src/bundlewalker/upgrades.py src/bundlewalker/compatibility.py src/bundlewalker/errors.py tests/test_upgrades.py
uv run ruff check src/bundlewalker/upgrades.py src/bundlewalker/compatibility.py src/bundlewalker/errors.py tests/test_upgrades.py
uv run pyright src/bundlewalker/upgrades.py src/bundlewalker/compatibility.py src/bundlewalker/errors.py tests/test_upgrades.py
```

Expected: current upgrade is byte-for-byte unchanged, synthetic migration backs up first, and a
failed migration leaves a verified restorable archive.

- [ ] **Step 6: Commit explicit upgrade and rollback orchestration**

```bash
git add src/bundlewalker/upgrades.py src/bundlewalker/compatibility.py src/bundlewalker/errors.py tests/test_upgrades.py
git commit -m "feat: orchestrate backup-first workspace upgrades"
```

### Task 8: Expose Lifecycle Use Cases and the `workspace` CLI Group

**Files:**
- Create: `src/bundlewalker/application/lifecycle.py`
- Modify: `src/bundlewalker/application/contracts.py`
- Modify: `src/bundlewalker/application/errors.py`
- Modify: `src/bundlewalker/application/__init__.py`
- Modify: `src/bundlewalker/interfaces/cli.py`
- Modify: `tests/application/test_contracts.py`
- Create: `tests/application/test_lifecycle.py`
- Create: `tests/cli/test_workspace.py`

**Interfaces:**
- Consumes: Tasks 2, 5, 6, and 7 plus the existing closed application-error boundary and Typer
  adapter.
- Produces: `LifecycleApplication`, `LifecycleDependencies`, `CompatibilityResult`,
  `BackupResult`, `RestoreResult`, `UpgradeResult`, six stable error codes, and the exact CLI
  commands approved in the design.

- [ ] **Step 1: Write failing application-contract and lifecycle tests**

Append model round-trip assertions to `tests/application/test_contracts.py` and create
`tests/application/test_lifecycle.py` with these representative boundaries:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bundlewalker.application import (
    ApplicationError,
    ApplicationErrorCode,
    LifecycleApplication,
    LifecycleDependencies,
)
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def test_lifecycle_status_inspects_future_format_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "future"
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_text("version = 2\nfuture_path = 'future'\n", encoding="utf-8")

    result = LifecycleApplication().status(root)

    assert result.workspace_path == str(root.resolve())
    assert result.workspace_format == 2
    assert result.compatibility == "too_new"
    assert result.readable is False
    assert result.writable is False
    assert list(root.iterdir()) == [config]


def test_lifecycle_backup_and_restore_return_serializable_identity(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    application = LifecycleApplication(
        LifecycleDependencies(clock=lambda: NOW, bundlewalker_version="0.4.0a1")
    )

    backup = application.backup(tmp_path / "knowledge.zip", workspace.root)
    restored = application.restore(Path(backup.archive_path), tmp_path / "restored")

    assert backup.archive_sha256 == restored.archive_sha256
    assert backup.workspace_format == restored.workspace_format == 1
    assert backup.model_dump_json()
    assert restored.model_dump_json()


def test_lifecycle_backup_translates_incompatible_workspace(tmp_path: Path) -> None:
    root = tmp_path / "future"
    root.mkdir()
    (root / "bundlewalker.toml").write_text("version = 2\n", encoding="utf-8")

    with pytest.raises(ApplicationError) as raised:
        LifecycleApplication().backup(tmp_path / "future.zip", root)

    assert raised.value.code is ApplicationErrorCode.WORKSPACE_INCOMPATIBLE
    assert raised.value.safe_message == "workspace format is not supported for this operation"
```

Extend `tests/application/test_contracts.py` so each new core error maps to its exact code and safe
message. Construct migration rollback identity without importing another test module:

```python
manifest = BackupManifest(
    archive_format=ARCHIVE_FORMAT,
    schema_version=ARCHIVE_SCHEMA_VERSION,
    created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    bundlewalker_version="0.4.0a1",
    workspace_format_version=1,
    directories=(),
    files=(),
)
backup = VerifiedBackup(Path("pre-upgrade.zip"), "a" * 64, manifest)
mapped = translate_error(
    MigrationExecutionError("token=private-cause", backup=backup)
)
assert mapped.code is ApplicationErrorCode.MIGRATION_FAILED
assert mapped.backup_archive_path == "pre-upgrade.zip"
assert mapped.backup_archive_sha256 == "a" * 64
assert "private-cause" not in mapped.safe_message
```

Import these backup models/constants plus `UTC`, `datetime`, and `Path` in the contract test.

- [ ] **Step 2: Run the focused application tests and verify contracts are absent**

Run:

```bash
uv run pytest tests/application/test_contracts.py tests/application/test_lifecycle.py -v
```

Expected: collection fails because the lifecycle contracts, facade, and error codes do not exist.

- [ ] **Step 3: Add strict serializable lifecycle result contracts**

Append to `application/contracts.py`:

```python
class CompatibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installed_version: str
    workspace_path: str
    workspace_format: int
    compatibility: CompatibilityStatus
    readable: bool
    writable: bool
    upgrade_available: bool


class BackupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archive_path: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    workspace_format: int
    file_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_path: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_format: int
    file_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)


class UpgradeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["current", "upgraded"]
    workspace_path: str
    source_version: int
    target_version: int
    backup: BackupResult | None
```

Export these records from `application/__init__.py` and add them to `__all__`.
Import `CompatibilityStatus` from `bundlewalker.compatibility` in `application/contracts.py`.

- [ ] **Step 4: Extend the closed public error vocabulary**

Add these members to `ApplicationErrorCode`:

```python
WORKSPACE_INCOMPATIBLE = "workspace_incompatible"
BACKUP_INVALID = "backup_invalid"
BACKUP_FAILED = "backup_failed"
RESTORE_TARGET_INVALID = "restore_target_invalid"
MIGRATION_UNAVAILABLE = "migration_unavailable"
MIGRATION_FAILED = "migration_failed"
```

Add optional rollback identity to `ApplicationError`:

```python
backup_archive_path: str | None = None
backup_archive_sha256: str | None = None
```

Import the new core errors and add these branches to `translate_error(...)` before the existing
`ConfigurationError`, `UsageError`, and generic fallbacks:

```python
if isinstance(error, MigrationExecutionError):
    backup = error.backup
    return ApplicationError(
        ApplicationErrorCode.MIGRATION_FAILED,
        "workspace migration failed; restore the verified pre-upgrade backup",
        backup_archive_path=str(backup.archive_path) if backup is not None else None,
        backup_archive_sha256=backup.archive_sha256 if backup is not None else None,
    )
if isinstance(error, MigrationUnavailableError):
    return ApplicationError(
        ApplicationErrorCode.MIGRATION_UNAVAILABLE,
        "no complete workspace migration path is available",
    )
if isinstance(error, RestoreTargetError):
    return ApplicationError(
        ApplicationErrorCode.RESTORE_TARGET_INVALID,
        "restore target must be a new or empty directory",
    )
if isinstance(error, BackupVerificationError):
    return ApplicationError(
        ApplicationErrorCode.BACKUP_INVALID,
        "backup archive verification failed",
    )
if isinstance(error, BackupError):
    return ApplicationError(
        ApplicationErrorCode.BACKUP_FAILED,
        "workspace backup or restore failed",
    )
if isinstance(error, WorkspaceCompatibilityError):
    return ApplicationError(
        ApplicationErrorCode.WORKSPACE_INCOMPATIBLE,
        "workspace format is not supported for this operation",
    )
```

The branch order is part of the contract because several lifecycle errors subclass existing
configuration or usage errors.

- [ ] **Step 5: Implement the synchronous adapter-neutral lifecycle facade**

Create `src/bundlewalker/application/lifecycle.py`:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bundlewalker import __version__
from bundlewalker.application.contracts import (
    BackupResult,
    CompatibilityResult,
    RestoreResult,
    UpgradeResult,
)
from bundlewalker.application.errors import ApplicationError, translate_error
from bundlewalker.backups import VerifiedBackup, create_workspace_backup, restore_workspace_backup
from bundlewalker.compatibility import (
    CURRENT_WORKSPACE_FORMAT,
    CompatibilityStatus,
    MigrationStep,
    inspect_workspace,
)
from bundlewalker.errors import (
    BundleWalkerError,
    MigrationUnavailableError,
    WorkspaceCompatibilityError,
)
from bundlewalker.upgrades import upgrade_workspace
from bundlewalker.workspace import discover_workspace


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class LifecycleDependencies:
    clock: Callable[[], datetime] = _utc_now
    bundlewalker_version: str = __version__
    target_version: int = CURRENT_WORKSPACE_FORMAT
    migrations: Mapping[int, MigrationStep] = field(default_factory=dict)


class LifecycleApplication:
    def __init__(self, dependencies: LifecycleDependencies | None = None) -> None:
        self.dependencies = dependencies or LifecycleDependencies()

    def status(self, start: Path | None = None) -> CompatibilityResult:
        try:
            inspected = inspect_workspace(
                start,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
            )
            return CompatibilityResult(
                installed_version=self.dependencies.bundlewalker_version,
                workspace_path=str(inspected.root),
                workspace_format=inspected.workspace_format_version,
                compatibility=inspected.status,
                readable=inspected.readable,
                writable=inspected.writable,
                upgrade_available=inspected.upgrade_available,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    def backup(self, output: Path, start: Path | None = None) -> BackupResult:
        try:
            inspected = inspect_workspace(
                start,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
            )
            if inspected.status is not CompatibilityStatus.CURRENT:
                raise WorkspaceCompatibilityError(inspected.status)
            verified = create_workspace_backup(
                discover_workspace(inspected.root),
                output,
                clock=self.dependencies.clock,
                bundlewalker_version=self.dependencies.bundlewalker_version,
            )
            return _backup_result(verified)
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    def restore(self, archive: Path, target: Path) -> RestoreResult:
        try:
            restored = restore_workspace_backup(archive, target)
            backup = restored.backup
            return RestoreResult(
                target_path=str(restored.workspace.root),
                archive_sha256=backup.archive_sha256,
                workspace_format=backup.manifest.workspace_format_version,
                file_count=backup.file_count,
                byte_count=backup.byte_count,
            )
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc

    def upgrade(
        self,
        start: Path | None = None,
        *,
        backup_dir: Path | None = None,
    ) -> UpgradeResult:
        try:
            inspected = inspect_workspace(
                start,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
            )
            if inspected.status in {
                CompatibilityStatus.TOO_NEW,
                CompatibilityStatus.UNSUPPORTED,
            }:
                if inspected.workspace_format_version < self.dependencies.target_version:
                    raise MigrationUnavailableError(
                        "no complete workspace migration path is available"
                    )
                raise WorkspaceCompatibilityError(inspected.status)
            workspace = discover_workspace(inspected.root)
            outcome = upgrade_workspace(
                workspace,
                backup_dir=backup_dir or inspected.root.parent,
                target_version=self.dependencies.target_version,
                migrations=self.dependencies.migrations,
                clock=self.dependencies.clock,
            )
            return UpgradeResult(
                status=outcome.status,
                workspace_path=str(inspected.root),
                source_version=outcome.source_version,
                target_version=outcome.target_version,
                backup=(
                    _backup_result(outcome.backup)
                    if outcome.backup is not None
                    else None
                ),
            )
        except ApplicationError:
            raise
        except BundleWalkerError as exc:
            raise translate_error(exc) from exc


def _backup_result(verified: VerifiedBackup) -> BackupResult:
    return BackupResult(
        archive_path=str(verified.archive_path),
        archive_sha256=verified.archive_sha256,
        created_at=verified.manifest.created_at,
        workspace_format=verified.manifest.workspace_format_version,
        file_count=verified.file_count,
        byte_count=verified.byte_count,
    )
```

Export `LifecycleApplication` and `LifecycleDependencies` from `application/__init__.py`.

- [ ] **Step 6: Write failing CLI tests for all four commands**

Create `tests/cli/test_workspace.py` using `CliRunner` and cover these exact behaviors:

```python
# Copyright (C) 2026 Hendrik Reh
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from bundlewalker.cli import app
from bundlewalker.workspace import initialize_workspace

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
runner = CliRunner()


def test_workspace_status_reports_future_format_without_creating_state(tmp_path: Path) -> None:
    root = tmp_path / "future"
    root.mkdir()
    config = root / "bundlewalker.toml"
    config.write_text("version = 2\nfuture_path = 'future'\n", encoding="utf-8")

    result = runner.invoke(app, ["workspace", "status", str(root)])

    assert result.exit_code == 0, result.output
    assert "Workspace format: 2" in result.output
    assert "Compatibility: too_new" in result.output
    assert not (root / ".bundlewalker").exists()


def test_workspace_backup_and_restore_work_outside_workspace_cwd(tmp_path: Path) -> None:
    source = initialize_workspace(tmp_path / "source", occurred_at=NOW)
    archive = tmp_path / "source.zip"
    target = tmp_path / "restored"

    backed_up = runner.invoke(
        app,
        ["workspace", "backup", str(archive), "--workspace", str(source.root)],
    )
    restored = runner.invoke(app, ["workspace", "restore", str(archive), str(target)])

    assert backed_up.exit_code == 0, backed_up.output
    assert restored.exit_code == 0, restored.output
    assert "SHA-256:" in backed_up.output
    assert "SHA-256:" in restored.output
    assert (target / "bundlewalker.toml").is_file()


def test_workspace_upgrade_current_is_noop(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)

    result = runner.invoke(app, ["workspace", "upgrade", str(workspace.root)])

    assert result.exit_code == 0, result.output
    assert "already current" in result.output
    assert list(tmp_path.glob("*.zip")) == []
```

Also test backup refusal for pending review (including the existing three remediation commands),
invalid archive exit `1`, occupied restore target exit `2`, too-new backup exit `2`, and unavailable
migration exit `2`.

- [ ] **Step 7: Add the Typer group and stable output**

In `interfaces/cli.py`, add and register:

```python
workspace_app = typer.Typer(no_args_is_help=True)
app.add_typer(workspace_app, name="workspace")
```

Change the root callback skip set to `{None, "init", "workspace"}`. Import
`LifecycleApplication`, then add:

```python
@workspace_app.command("status")
def workspace_status(path: Path | None = typer.Argument(None)) -> None:
    try:
        result = LifecycleApplication().status(path)
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    typer.echo(f"BundleWalker version: {result.installed_version}")
    typer.echo(f"Workspace: {result.workspace_path}")
    typer.echo(f"Workspace format: {result.workspace_format}")
    typer.echo(f"Compatibility: {result.compatibility}")
    typer.echo(f"Readable: {'yes' if result.readable else 'no'}")
    typer.echo(f"Writable: {'yes' if result.writable else 'no'}")
    typer.echo(f"Upgrade available: {'yes' if result.upgrade_available else 'no'}")


@workspace_app.command("backup")
def workspace_backup(
    output: Path,
    workspace_path: Path | None = typer.Option(None, "--workspace"),
) -> None:
    try:
        result = LifecycleApplication().backup(output, workspace_path)
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    typer.echo(f"Backup: {result.archive_path}")
    typer.echo(f"SHA-256: {result.archive_sha256}")
    typer.echo(f"Workspace format: {result.workspace_format}")
    typer.echo(f"Files: {result.file_count}")
    typer.echo(f"Bytes: {result.byte_count}")


@workspace_app.command("restore")
def workspace_restore(archive: Path, target: Path) -> None:
    try:
        result = LifecycleApplication().restore(archive, target)
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    typer.echo(f"Restored workspace: {result.target_path}")
    typer.echo(f"SHA-256: {result.archive_sha256}")
    typer.echo(f"Workspace format: {result.workspace_format}")
    typer.echo(f"Files: {result.file_count}")
    typer.echo(f"Bytes: {result.byte_count}")


@workspace_app.command("upgrade")
def workspace_upgrade(
    path: Path | None = typer.Argument(None),
    backup_dir: Path | None = typer.Option(None, "--backup-dir"),
) -> None:
    try:
        result = LifecycleApplication().upgrade(path, backup_dir=backup_dir)
    except ApplicationError as exc:
        _exit_for_application_error(exc)
    if result.status == "current":
        typer.echo(f"Workspace format {result.target_version} is already current.")
        return
    typer.echo(f"Upgraded workspace: {result.workspace_path}")
    if result.backup is not None:
        typer.echo(f"Pre-upgrade backup: {result.backup.archive_path}")
        typer.echo(f"SHA-256: {result.backup.archive_sha256}")
```

Add `WORKSPACE_INCOMPATIBLE`, `RESTORE_TARGET_INVALID`, and `MIGRATION_UNAVAILABLE` to the usage
exit-code set in `_exit_for_application_error(...)`. If a migration failure carries rollback
identity, print `Verified pre-upgrade backup:` and `SHA-256:` to stderr after its safe message.

- [ ] **Step 8: Run application, CLI, and existing adapter regressions**

Run:

```bash
uv run pytest tests/application tests/cli tests/test_backups.py tests/test_upgrades.py -q
uv run ruff format --check src/bundlewalker/application src/bundlewalker/interfaces/cli.py tests/application tests/cli
uv run ruff check src/bundlewalker/application src/bundlewalker/interfaces/cli.py tests/application tests/cli
uv run pyright src/bundlewalker/application src/bundlewalker/interfaces/cli.py tests/application tests/cli
```

Expected: all lifecycle outputs are serializable, restore works without ambient discovery, status
is read-only, and all pre-existing CLI behavior remains unchanged.

- [ ] **Step 9: Commit the lifecycle application and CLI**

```bash
git add src/bundlewalker/application src/bundlewalker/interfaces/cli.py tests/application tests/cli/test_workspace.py
git commit -m "feat: expose workspace lifecycle commands"
```

### Task 9: Prove Authenticated Recovery Across Abrupt Process Exit

**Files:**
- Create: `tests/test_transaction_crash_recovery.py`

**Interfaces:**
- Consumes: the unchanged transaction phase machine, public recovery/review APIs, and a private
  manifest-write hook used only to terminate a child after durable phase publication.
- Produces: subprocess evidence for `prepared`, `accepted`, `raw-persisted`, `swapping`, and
  `new-live`, including idempotent second recovery.

- [ ] **Step 1: Add the deterministic worker and crash harness**

Create `tests/test_transaction_crash_recovery.py` with the standard copyright header, imports, and
this complete deterministic review helper and worker:

```python
from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import bundlewalker.transactions as transactions
from bundlewalker.changes import ChangeValidationContext
from bundlewalker.domain import ChangeOperation, ChangeSet, Citation, ConceptType, DraftConcept
from bundlewalker.okf.repository import OkfRepository
from bundlewalker.transactions import (
    PreparedTransaction,
    ReviewKind,
    ReviewStatus,
    apply_pending_review,
    get_pending_review,
    prepare_transaction,
    recover_transactions,
)
from bundlewalker.workspace import (
    RawSource,
    Workspace,
    discover_workspace,
    initialize_workspace,
    load_raw_source,
)

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
CRASH_EXIT = 86


def _prepare_review(workspace: Workspace) -> tuple[PreparedTransaction, RawSource]:
    source_path = workspace.root.parent / "crash-source.txt"
    source_path.write_bytes(b"first line\r\nsecond line\n")
    source = load_raw_source(source_path, workspace)
    draft = DraftConcept(
        operation=ChangeOperation.CREATE,
        path=source.concept_id,
        type=ConceptType.SOURCE,
        title="Source notes",
        description="Knowledge about Source notes.",
        tags=["test"],
        body="# Source notes\n\nA grounded claim [1].\n",
        citations=[
            Citation(
                number=1,
                concept_id=source.concept_id,
                start_line=1,
                end_line=2,
            )
        ],
        base_digest=None,
    )
    change_set = ChangeSet(
        summary="Integrated source notes.",
        source_sha256=source.sha256,
        drafts=[draft],
    )
    context = ChangeValidationContext(
        mode="ingest",
        repository=OkfRepository(workspace.wiki_dir),
        readable_concepts=frozenset(),
        source=source,
    )
    prepared = prepare_transaction(
        workspace,
        change_set,
        context,
        source,
        NOW,
        kind=ReviewKind.INGESTION,
    )
    return prepared, source


def _child(workspace_root: Path, phase: str, review_id: str | None) -> None:
    original = transactions._write_manifest  # pyright: ignore[reportPrivateUsage]

    def write_then_exit(
        transaction_dir: Path,
        manifest: transactions._Manifest,  # pyright: ignore[reportPrivateUsage]
    ) -> None:
        original(transaction_dir, manifest)
        if manifest.phase == phase:
            os._exit(CRASH_EXIT)

    transactions._write_manifest = write_then_exit  # pyright: ignore[reportPrivateUsage]
    workspace = discover_workspace(workspace_root)
    if phase == "prepared":
        _prepare_review(workspace)
        raise AssertionError("prepared manifest hook did not terminate the child")
    if review_id is None:
        raise AssertionError("accepted-phase worker requires a review ID")
    apply_pending_review(workspace, review_id)
    raise AssertionError(f"{phase} manifest hook did not terminate the child")


def _run_child(workspace: Workspace, phase: str, review_id: str | None) -> None:
    environment = os.environ.copy()
    environment["BUNDLEWALKER_CRASH_WORKER"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            str(workspace.root),
            phase,
            review_id or "-",
        ],
        check=False,
        env=environment,
        timeout=30,
    )
    assert result.returncode == CRASH_EXIT


if __name__ == "__main__" and os.environ.get("BUNDLEWALKER_CRASH_WORKER") == "1":
    root = Path(sys.argv[1])
    selected_phase = sys.argv[2]
    selected_review = None if sys.argv[3] == "-" else sys.argv[3]
    _child(root, selected_phase, selected_review)
```

Never invoke shell signals or kill unrelated processes; the child exits only through its own
`os._exit(86)` hook.

- [ ] **Step 2: Add prepared-decision retention and accepted-decision completion tests**

Add:

```python
def test_abrupt_exit_after_prepared_retains_review_and_live_base(tmp_path: Path) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    base = _tree_bytes(workspace.wiki_dir)

    _run_child(workspace, "prepared", None)
    recover_transactions(workspace)

    pending = get_pending_review(workspace)
    assert pending is not None
    assert pending.status is ReviewStatus.PENDING
    assert _tree_bytes(workspace.wiki_dir) == base
    assert not any(workspace.raw_dir.rglob("*"))
    first = _tree_bytes(workspace.root / ".bundlewalker/transactions")
    recover_transactions(workspace)
    assert _tree_bytes(workspace.root / ".bundlewalker/transactions") == first


@pytest.mark.parametrize("phase", ["accepted", "raw-persisted", "swapping", "new-live"])
def test_abrupt_exit_after_accepted_phase_completes_exact_commit(
    tmp_path: Path,
    phase: str,
) -> None:
    workspace = initialize_workspace(tmp_path / "knowledge", occurred_at=NOW)
    prepared, source = _prepare_review(workspace)
    expected_wiki = _tree_bytes(prepared.prospective_wiki)

    _run_child(workspace, phase, prepared.transaction_id)
    recover_transactions(workspace)

    assert get_pending_review(workspace) is None
    assert _tree_bytes(workspace.wiki_dir) == expected_wiki
    assert (workspace.root / source.stored_relative_path).read_bytes() == source.content
    transactions_root = workspace.root / ".bundlewalker/transactions"
    assert not any(transactions_root.iterdir())
    committed = _tree_bytes(workspace.root)
    recover_transactions(workspace)
    assert _tree_bytes(workspace.root) == committed


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
```

These assertions intentionally observe journal cleanup or retention. Accepted-state expectations
come from authenticated prepared bytes rather than current initialization logic.

- [ ] **Step 3: Run the subprocess crash suite repeatedly**

Run:

```bash
for iteration in 1 2 3; do
  uv run pytest tests/test_transaction_crash_recovery.py -q
done
```

Expected: all five durable phases recover deterministically in every run; prepared state remains
reviewable and every accepted state completes to the same exact raw/wiki bytes.

- [ ] **Step 4: Run transaction and lifecycle regressions plus static checks**

Run:

```bash
uv run pytest tests/test_transaction_crash_recovery.py tests/test_transactions.py tests/test_backups.py tests/test_upgrades.py -q
uv run ruff format --check tests/test_transaction_crash_recovery.py
uv run ruff check tests/test_transaction_crash_recovery.py
uv run pyright tests/test_transaction_crash_recovery.py
```

Expected: abrupt-exit coverage passes without changing normal transaction or lifecycle behavior.

- [ ] **Step 5: Commit abrupt-termination evidence**

```bash
git add tests/test_transaction_crash_recovery.py
git commit -m "test: prove transaction crash recovery"
```

### Task 10: Publish the Policy, Procedures, and Full B1 Evidence

**Files:**
- Create: `docs/workspace-compatibility.md`
- Modify: `README.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/tutorial.md`
- Modify: `docs/maintainers/releases.md`
- Modify: `tests/test_project_automation.py`

**Interfaces:**
- Consumes: the final command/error/archive contracts and supported CI matrix.
- Produces: the authoritative user policy, operational backup/restore/rollback procedures,
  release evidence requirements, and a complete local verification record.

- [ ] **Step 1: Add failing documentation-contract tests**

Append to `tests/test_project_automation.py`:

```python
def test_workspace_lifecycle_policy_and_commands_are_published() -> None:
    policy = (PROJECT_ROOT / "docs/workspace-compatibility.md").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    user_guide = (PROJECT_ROOT / "docs/user-guide.md").read_text(encoding="utf-8")
    tutorial = (PROJECT_ROOT / "docs/tutorial.md").read_text(encoding="utf-8")
    releases = (PROJECT_ROOT / "docs/maintainers/releases.md").read_text(encoding="utf-8")

    for command in (
        "bundlewalker workspace status",
        "bundlewalker workspace backup",
        "bundlewalker workspace restore",
        "bundlewalker workspace upgrade",
    ):
        assert command in policy
        assert command in user_guide
    for warning in (
        "unencrypted",
        "raw source",
        ".bundlewalker",
        "pending review",
        "new or empty",
    ):
        assert warning in policy.lower()
    assert "docs/workspace-compatibility.md" in readme
    assert "workspace backup" in tutorial.lower()
    assert "pre-upgrade backup" in releases.lower()
    assert "sha-256" in releases.lower()
```

- [ ] **Step 2: Run the contract and verify the policy is absent**

Run:

```bash
uv run pytest tests/test_project_automation.py::test_workspace_lifecycle_policy_and_commands_are_published -v
```

Expected: failure because `docs/workspace-compatibility.md` does not exist.

- [ ] **Step 3: Write the authoritative compatibility and archive policy**

Create `docs/workspace-compatibility.md` with these sections and exact facts:

1. **Supported artifacts:** workspace format `1`; transaction manifests `2` with authenticated
   schema-1 recovery; durable reviews `1`; permissive bounded OKF Markdown reads.
2. **Status meanings:** `current`, `upgradeable`, `too_new`, and `unsupported`; malformed TOML is a
   configuration error, not a compatibility status.
3. **No implicit migration:** only `bundlewalker workspace upgrade` may invoke a registered
   migration, and production currently registers none.
4. **Backup scope:** config plus configured conventions/raw/wiki; exclusions include
   `.bundlewalker`, `.git`, unrelated root files, and existing archives.
5. **Privacy warning:** ZIP is unencrypted and may contain exact raw source bytes; recommend an
   encrypted destination or an external encryption tool.
6. **Backup procedure:** resolve pending reviews, stop external writers, run
   `bundlewalker workspace backup OUTPUT --workspace PATH`, and record the printed SHA-256.
7. **Restore procedure:** verify into a new or empty target with
   `bundlewalker workspace restore ARCHIVE TARGET`; it never replaces a non-empty workspace.
8. **Upgrade/rollback:** current format is a no-op; future migrations back up first; rollback
   restores to a separate target, runs status and deterministic lint, and switches consumers only
   after inspection.
9. **Exit codes:** `2` for input/incompatible-target/unavailable-path errors and `1` for archive,
   backup, restore, migration-execution, transaction, or verification failures.
10. **Portability boundary:** exact relative paths and bytes, not modes, ownership, ACLs, xattrs,
    or timestamps.

Use command examples with concrete paths (`./knowledge`, `./backups/knowledge.zip`, and
`./knowledge-restored`) and show the complete four-command CLI contract.

- [ ] **Step 4: Update primary user and maintainer documentation**

Add a concise “Workspace lifecycle” section to `README.md` linking
`docs/workspace-compatibility.md`. Add complete command procedures and the raw-content warning to
`docs/user-guide.md`. Add a tutorial exercise that initializes a workspace, creates a backup,
restores it to `./knowledge-restored`, runs status there, and runs `bundlewalker lint` from that
workspace. Add a release checklist subsection to `docs/maintainers/releases.md` requiring:

- historical fixture compatibility evidence;
- backup and restore SHA-256 output;
- separate-target rollback rehearsal;
- status and deterministic lint on the restored target;
- abrupt-termination recovery results; and
- the supported Ubuntu/macOS Python 3.13/3.14 matrix.

Do not claim Windows support, encryption, production PyPI availability, diagnostics, benchmark
capacity, or a real format migration.

- [ ] **Step 5: Run documentation and command-help checks**

Run:

```bash
uv run pytest tests/test_project_automation.py tests/cli/test_workspace.py -q
uv run bundlewalker workspace --help
uv run bundlewalker workspace status --help
uv run bundlewalker workspace backup --help
uv run bundlewalker workspace restore --help
uv run bundlewalker workspace upgrade --help
git diff --check
```

Expected: documentation contracts pass, every lifecycle command is visible, and no Markdown or
help text contradicts the implemented CLI.

- [ ] **Step 6: Run the complete supported local gate**

Run exactly the same non-evaluation gate required by supported CI:

```bash
uv sync --locked
uv lock --check
uv run pytest -m 'not eval' -q
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv build --clear --no-sources
uv run twine check dist/*
```

Expected: every command exits `0`. Record the pytest pass count and build artifact names in the
implementation handoff. Do not publish, tag, or create a release.

- [ ] **Step 7: Review the implementation against the B1 exit criteria**

Run:

```bash
git diff --check
git status --short
git diff --stat master...HEAD
git log --oneline master..HEAD
```

Confirm all nine B1 exit criteria in the approved design have fresh test or documentation
evidence. Confirm `pyproject.toml` still reports `0.4.0a1` and the unrelated untracked tarball is
the only file outside the intended implementation scope.

- [ ] **Step 8: Commit the policy and final evidence**

```bash
git add README.md docs/workspace-compatibility.md docs/user-guide.md docs/tutorial.md docs/maintainers/releases.md tests/test_project_automation.py
git commit -m "docs: publish workspace lifecycle policy"
```

The implementation branch is then ready for the repository's normal review and merge workflow;
this plan does not authorize pushing, opening a pull request, tagging, or releasing.
